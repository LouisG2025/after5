"""
Baileys Messaging Client
========================
Drop-in replacement for whatsapp_client.py that routes all WhatsApp operations
through a local Baileys Node.js service (see /baileys folder).

Communicates via HTTP to BAILEYS_SERVICE_URL (default http://localhost:3001).
"""
import asyncio
import logging

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
    """Send a plain text message via the Baileys bridge."""
    url = f"{settings.BAILEYS_SERVICE_URL}/send"
    digits = _normalize_phone(to)
    resolved = await _resolve_to_lid(digits)
    payload = {"phone": resolved, "text": body}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info(f"[Baileys] Sent to {to}: {body[:50]}...")
                return resp.json()
            logger.error(f"[Baileys] Send failed {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"[Baileys] Send error: {e}")
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
    """
    Mark a message as read (blue ticks).
    Note: Baileys requires both phone and message_id. The caller must have
    stored the phone separately (see webhook.py) — we accept only message_id
    to match the whatsapp_client.mark_as_read signature, and look up the phone
    from Redis.
    """
    if not message_id:
        return
    try:
        # Look up phone for this message_id
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
    step: float = 0.5,
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


async def _handle_pause(to: str, max_wait: float = 20.0) -> str:
    """
    Lead started typing while Albert was mid-response.
    1) Drop the typing indicator immediately.
    2) Wait up to max_wait seconds for them to send or stop.
    3) Return action:
        "reprocess" → a new message arrived, restart
        "resume"    → they stopped typing or timed out, carry on
    Per brief: "Pause if lead types mid-response. Wait 20s.
                If they send, restart. If not, continue."
    """
    from app.redis_client import redis_client

    await _clear_typing(to)
    logger.info(f"[Baileys] Paused for {to} — lead is typing, waiting up to {max_wait}s")

    waited = 0.0
    step = 0.5
    silence_threshold = 5.0  # resume if they go quiet for 5s

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
) -> None:
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

    if not interruptible:
        # Fast path with no interrupt checks (used for hardcoded templates)
        for chunk in chunks:
            await send_message(to, format_message(chunk))
        return

    current_time = _time.time()
    sequences = calculate_chunk_sequence(incoming_text, chunks, last_message_ts, current_time)

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

        # 1. Blue tick delay
        if seq["blue_tick_delay"] > 0:
            if await _interruptible_sleep(seq["blue_tick_delay"]):
                return
            if message_id:
                await mark_as_read(message_id)

        # 2. Reading delay
        if await _interruptible_sleep(seq["reading_delay"]):
            return

        # 3. Think pause
        if await _interruptible_sleep(seq["think_pause"]):
            return

        # 4. Typing delay (show indicator, poll for interrupts)
        if seq["typing_delay"] > 0:
            await send_typing_indicator(to, message_id)
            if await _interruptible_sleep(seq["typing_delay"]):
                await _clear_typing(to)
                return

        # 5. Review pause
        if await _interruptible_sleep(seq["review_pause"]):
            return

        # 6. Send the bubble (pass incoming_text for context-aware AI disclosure filter)
        formatted = format_message(chunk, last_user_message=incoming_text)
        await send_message(to, formatted)


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
