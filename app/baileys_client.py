"""
Baileys Messaging Client
========================
Drop-in replacement for whatsapp_client.py that routes all WhatsApp operations
through a local Baileys Node.js service (see /baileys folder).

Communicates via HTTP to BAILEYS_SERVICE_URL (default http://localhost:3001).
"""
import asyncio
import logging
import time

import httpx

from app.config import settings
from typing import Optional

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    """'whatsapp:+447700900000' → '447700900000'"""
    return phone.replace("whatsapp:", "").replace("+", "")


async def _resolve_to_lid(phone_digits: str) -> str:
    """Check if this real phone has a LID mapping and use that instead."""
    from app.redis_client import redis_client
    lid = await redis_client.redis.get(f"phone_to_lid:{phone_digits}")
    if lid:
        resolved = lid.decode('utf-8') if isinstance(lid, bytes) else lid
        logger.info(f"[Baileys] Routing {phone_digits} via LID {resolved}")
        return resolved
    return phone_digits


async def send_message(to: str, body: str) -> Optional[dict]:
    """Send a plain text message via the Baileys bridge.
    One automatic retry on transient failures (network blip, brief 503).
    Returns the response dict on success, None on hard failure — callers
    MUST check the return value before logging to the dashboard, otherwise
    the dashboard will show messages that the mobile WhatsApp never got.
    """
    url = f"{settings.BAILEYS_SERVICE_URL}/send"
    digits = _normalize_phone(to)
    resolved = await _resolve_to_lid(digits)
    payload = {"phone": resolved, "text": body}

    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"[Baileys] Sent to {to}: {body[:50]}...")
                    return resp.json()
                logger.error(
                    f"[Baileys] Send failed (attempt {attempt}) {resp.status_code}: {resp.text}"
                )
        except Exception as e:
            logger.error(f"[Baileys] Send error (attempt {attempt}): {e}")
        if attempt == 1:
            await asyncio.sleep(1.5)
    return None


async def send_typing_indicator(to: str, message_id: str = "") -> bool:
    """Show 'typing…' presence to the lead."""
    url = f"{settings.BAILEYS_SERVICE_URL}/typing"
    digits = _normalize_phone(to)
    resolved = await _resolve_to_lid(digits)
    payload = {"phone": resolved, "state": "composing"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.debug(f"[Baileys] Typing error: {e}")
        return False


async def mark_as_read(message_id: str) -> None:
    """Mark a single message as read (blue ticks)."""
    if not message_id:
        return
    try:
        from app.redis_client import redis_client
        phone_val = await redis_client.redis.get(f"msgid_phone:{message_id}")
        if not phone_val:
            logger.debug(f"[Baileys] No phone mapping for message_id {message_id}")
            return
        phone = phone_val.decode() if isinstance(phone_val, bytes) else phone_val
        url = f"{settings.BAILEYS_SERVICE_URL}/read"
        payload = {"phone": _normalize_phone(phone), "message_id": message_id}
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        logger.debug(f"[Baileys] Mark-as-read error: {e}")


async def mark_batch_as_read(phone: str, message_ids: list[str]) -> None:
    """Blue-tick a burst of messages all at once — exactly how real WhatsApp
    behaves when you open a chat with unread messages.

    Sends ALL message_ids in a single HTTP call, which Baileys passes to
    sock.readMessages in one batch. WhatsApp then sends batched read
    receipts to the sender's client, so all bubbles flip blue together
    rather than ticking one at a time.
    """
    ids = [m for m in (message_ids or []) if m]
    if not ids:
        return
    digits = _normalize_phone(phone)
    resolved = await _resolve_to_lid(digits)
    url = f"{settings.BAILEYS_SERVICE_URL}/read"
    payload = {"phone": resolved, "message_ids": ids}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error(f"[Baileys] Batch read failed {resp.status_code}: {resp.text}")
            else:
                logger.info(f"[Baileys] Marked {len(ids)} msg(s) read in one batch for {phone}")
    except Exception as e:
        logger.debug(f"[Baileys] Mark-as-read error: {e}")


async def _clear_typing(to: str) -> None:
    """Fire-and-forget helper: tell Baileys to drop the typing indicator."""
    url = f"{settings.BAILEYS_SERVICE_URL}/typing"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(url, json={"phone": _normalize_phone(to), "state": "paused"})
    except Exception:
        pass


async def _poll_interruptible(
    to: str,
    total_seconds: float,
    step: float = 0.3,
    expect_typing_indicator_on: bool = True,
    message_id: str = "",
) -> str:
    """
    Sleep for up to `total_seconds` but poll every `step` seconds for:
      - a new inbound message  → returns "reprocess"
      - lead typing in progress → returns "pause"
    Returns "continue" if the full duration elapses without interruption.
    """
    from app.redis_client import redis_client

    elapsed = 0.0
    while elapsed < total_seconds:
        await asyncio.sleep(step)
        elapsed += step

        if await redis_client.has_new_messages(to):
            return "reprocess"

        typing = await redis_client.get_lead_typing_state(to)
        if typing.get("is_typing"):
            return "pause"

    return "continue"


async def _compute_pause_budget(to: str) -> float:
    """How long to wait for the lead to finish typing. Minimal waits for fast responses."""
    return 3.0  # Quick 3 second max wait


async def _handle_pause(to: str, max_wait: float | None = None) -> str:
    """Lead started typing while Albert was mid-response. Drop the typing
    indicator and wait up to max_wait seconds for them to send or stop.
    If max_wait is None (default), it's computed dynamically from the lead's
    last message length so we don't stall on quick chats or cut off long ones.

    Returns:
        "reprocess" → new message arrived, restart from scratch
        "resume"    → they went silent or timed out, carry on
    """
    from app.redis_client import redis_client

    if max_wait is None:
        max_wait = await _compute_pause_budget(to)

    await _clear_typing(to)
    logger.info(f"[Baileys] Paused for {to} — lead is typing, waiting up to {max_wait:.1f}s")

    waited = 0.0
    step = 0.3
    silence_threshold = 1.5  # resume quickly when they stop typing

    while waited < max_wait:
        await asyncio.sleep(step)
        waited += step

        # New message means they sent what they were typing → restart
        if await redis_client.has_new_messages(to):
            logger.info(f"[Baileys] Resume as reprocess for {to} — new message arrived")
            return "reprocess"

        typing = await redis_client.get_lead_typing_state(to)
        if not typing.get("is_typing"):
            # They stopped typing without sending. Give them 5s of silence to be sure.
            stopped_at = typing.get("stopped_at") or 0.0
            if stopped_at > 0 and (time.time() - stopped_at) >= silence_threshold:
                logger.info(f"[Baileys] Resume for {to} — typing stopped for {silence_threshold}s")
                return "resume"

    logger.info(f"[Baileys] Resume for {to} — pause timed out after {max_wait}s")
    return "resume"


async def send_chunked_messages(
    to: str,
    chunks: list[str],
    incoming_text: str = "",
    last_message_ts: float = 0,
    message_id: str = "",
    interruptible: bool = True,
    pending_message_ids: Optional[list[str]] = None,
) -> list[str]:
    """
    Send multiple messages with realistic human-like timing sequence.
    Mirrors whatsapp_client.send_chunked_messages but uses the Baileys bridge.

    Interrupt handling (brief spec):
    - If a new message arrives during any delay → abort (caller reprocesses)
    - If lead starts typing during any delay → pause, clear typing indicator,
      wait up to 20s, then either reprocess (if they sent) or resume
    """
    from app.chunker import calculate_chunk_sequence, format_message
    from app.redis_client import redis_client
    import time as _time

    sent: list[str] = []  # chunks that actually got HTTP 200 from Baileys

    if not interruptible:
        # Fast path with no interrupt checks (used for hardcoded templates)
        for chunk in chunks:
            # Templates already have formatting, send as-is
            result = await send_message(to, chunk)
            if result is not None:
                sent.append(chunk)
        return sent

    current_time = _time.time()
    sequences = calculate_chunk_sequence(incoming_text, chunks, last_message_ts, current_time)

    # Build the batch of message_ids we'll blue-tick at once. Falls back to
    # the single message_id if the caller didn't pass a list.
    ids_to_read = list(pending_message_ids) if pending_message_ids else (
        [message_id] if message_id else []
    )

    t_start = _time.time()
    logger.info(
        f"[timing] {to} sequences={[{k: round(v, 2) for k, v in s.items()} for s in sequences]}"
    )

    async def _interruptible_sleep(duration: float) -> bool:
        """Sleep, checking for interrupts. Returns True if interrupted to abort."""
        if duration <= 0:
            return False
        action = await _poll_interruptible(to, duration)
        if action == "reprocess":
            logger.info(f"[Baileys] Aborting send to {to} — reprocess triggered")
            return True
        if action == "pause":
            result = await _handle_pause(to)
            if result == "reprocess":
                return True
            # resume — carry on with remainder of the sequence
        return False

    for i, chunk in enumerate(chunks):
        seq = sequences[i]

        # 1. Blue tick delay (only fires for first chunk; batch-tick all
        # buffered messages so the burst flips read together)
        if seq["blue_tick_delay"] > 0:
            if await _interruptible_sleep(seq["blue_tick_delay"]):
                return sent
            if ids_to_read:
                await mark_batch_as_read(to, ids_to_read)
                logger.info(f"[timing] {to} blue-ticked {len(ids_to_read)} msg(s) at +{round(_time.time() - t_start, 2)}s")

        # 2. Reading delay
        if await _interruptible_sleep(seq["reading_delay"]):
            return sent

        # 3. Think pause
        if await _interruptible_sleep(seq["think_pause"]):
            return sent

        # 4. Typing delay (show indicator, poll for interrupts)
        if seq["typing_delay"] > 0:
            await send_typing_indicator(to, message_id)
            if await _interruptible_sleep(seq["typing_delay"]):
                await _clear_typing(to)
                return sent

        # 5. Review pause
        if await _interruptible_sleep(seq["review_pause"]):
            return sent

        # 6. Send the bubble. Only mark as 'sent' if Baileys returns 200,
        # so the dashboard log stays in sync with what mobile WhatsApp got.
        formatted = format_message(chunk, last_user_message=incoming_text)
        result = await send_message(to, formatted)
        if result is not None:
            sent.append(formatted)
            logger.info(f"[timing] {to} chunk {i+1}/{len(chunks)} sent at +{round(_time.time() - t_start, 2)}s")
        else:
            # Send failed even after retry. Stop the chain — sending later
            # chunks when an earlier one failed leaves WhatsApp out of order.
            logger.error(f"[Baileys] Hard fail on chunk {i+1}/{len(chunks)} for {to}, aborting remaining chunks")
            return sent

    return sent


async def is_connected() -> bool:
    """Check whether the Baileys service is currently paired with WhatsApp."""
    url = f"{settings.BAILEYS_SERVICE_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return bool(resp.json().get("connected"))
            return False
    except Exception:
        return False
