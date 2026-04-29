import asyncio
import logging
import random
import time
from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends
from app.auth import require_api_key
from pydantic import BaseModel
from app.config import settings
from app.redis_client import redis_client
from app.messaging import mark_as_read, send_message, send_chunked_messages, send_typing_indicator
from app.models import ConversationState
from app.stt import process_voice_note_from_media_id

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_INTERRUPT_RETRIES = 2


class BaileysIncoming(BaseModel):
    """Payload shape emitted by the Baileys Node bridge."""
    phone: str           # digits only, e.g. "447700900000"
    name: str = ""
    text: str
    message_id: str = ""
    timestamp: int = 0


def _is_phone_allowed(phone_digits: str) -> bool:
    """Phone-only allowlist check. Empty list → allow everyone."""
    raw = (settings.BAILEYS_ALLOWED_PHONES or "").strip()
    if not raw:
        return True

    import re as _re
    incoming = _re.sub(r"\D", "", phone_digits or "")
    allowed = {_re.sub(r"\D", "", p) for p in raw.split(",") if p.strip()}
    if incoming in allowed:
        return True
    for a in allowed:
        if a and (incoming.endswith(a) or a.endswith(incoming)):
            return True
    return False


def _is_name_allowed(name: str) -> bool:
    """Name-based fallback for WhatsApp accounts that arrive via @lid and
    can't be resolved to a real phone number. Case-insensitive substring
    match — 'shashank' allows 'shashank', 'Shashank Sharma', 'shashank j'.
    Empty allowlist returns False (won't accidentally allow everyone here)."""
    raw = (settings.BAILEYS_ALLOWED_NAMES or "").strip()
    if not raw or not name:
        return False
    n = name.strip().lower()
    return any(token.strip().lower() in n for token in raw.split(",") if token.strip())


def _is_lead_allowed(phone_digits: str, name: str) -> bool:
    """Combined allowlist gate. Passes if EITHER:
      1. BAILEYS_ALLOWED_PHONES is empty (open-door production mode), OR
      2. The resolved phone matches BAILEYS_ALLOWED_PHONES, OR
      3. WhatsApp pushName matches BAILEYS_ALLOWED_NAMES — the fallback for
         @lid messages that can't be resolved to a real phone.
    The name fallback only kicks in when phones are configured (i.e. you're
    in lockdown mode) — otherwise step 1 short-circuits."""
    raw_phones = (settings.BAILEYS_ALLOWED_PHONES or "").strip()
    if not raw_phones:
        return True  # phone list empty → allow everyone (production)

    if _is_phone_allowed(phone_digits):
        return True
    return _is_name_allowed(name)


class BaileysPresence(BaseModel):
    """Presence update from the Baileys bridge (lead typing / stopped)."""
    phone: str
    state: str           # "composing" | "paused" | "available" | "unavailable"


@router.post("/baileys/map-phone")
async def baileys_map_phone(data: dict):
    """Map a WhatsApp LID to a real phone number."""
    lid = data.get("lid", "")
    real = data.get("real_phone", "")
    if lid and real:
        await redis_client.redis.set(f"lid_map:{lid}", real, ex=86400 * 30)
        logger.info(f"[Baileys] Mapped LID {lid} → {real}")
        return {"status": "mapped"}
    return {"status": "ignored"}


@router.post("/baileys/presence")
async def baileys_presence(p: BaileysPresence):
    """
    Called by the Baileys Node service when the lead's typing state changes.
    Updates Redis so the interrupt logic in send_chunked_messages can react.
    """
    resolved = await redis_client.redis.get(f"lid_map:{p.phone}")
    phone = f"whatsapp:+{resolved.decode('utf-8') if isinstance(resolved, bytes) else resolved}" if resolved else f"whatsapp:+{p.phone}"
    state = (p.state or "").lower()
    if state == "composing":
        await redis_client.set_lead_typing(phone)
    elif state in ("paused", "available", "unavailable"):
        await redis_client.clear_lead_typing(phone)
    return {"status": "ok", "state": state}


@router.post("/baileys/incoming")
async def baileys_incoming(msg: BaileysIncoming, background_tasks: BackgroundTasks):
    """
    Receive a message from the local Baileys bridge and run it through the
    same buffering + processing pipeline as the Cloud API webhook.
    Returns 200 immediately; processing happens async.
    """
    if not msg.text or not msg.text.strip():
        return {"status": "ignored", "reason": "empty"}

    # Resolve LID → real phone via Redis mapping BEFORE allowlist check
    resolved = await redis_client.redis.get(f"lid_map:{msg.phone}")
    if resolved:
        real_phone = resolved.decode('utf-8') if isinstance(resolved, bytes) else resolved
        logger.info(f"[Baileys] LID {msg.phone} resolved to {real_phone}")
        # Store reverse mapping so outbound messages route back through LID
        await redis_client.redis.set(f"phone_to_lid:{real_phone}", msg.phone, ex=86400 * 30)
    else:
        real_phone = msg.phone

    # Allowlist check — phone OR pushName must match (name covers @lid
    # accounts that can't be resolved to a real phone number).
    if not _is_lead_allowed(real_phone, msg.name):
        logger.info(
            f"[Baileys] Ignored phone={real_phone} name='{msg.name}' — not on allowlist"
        )
        return {"status": "ignored", "reason": "not_on_allowlist"}

    sender_phone = f"whatsapp:+{real_phone}"
    message_id = msg.message_id or f"baileys-{int(time.time() * 1000)}"
    message_ts = msg.timestamp or int(time.time())

    # 1. Dedup
    dedup_key = f"dedup:{message_id}"
    if await redis_client.redis.get(dedup_key):
        return {"status": "duplicate"}
    await redis_client.redis.set(dedup_key, "1", ex=86400)

    # 2. Map message_id → phone so baileys_client.mark_as_read can look it up
    await redis_client.redis.set(f"msgid_phone:{message_id}", sender_phone, ex=3600)

    # 3. Staleness
    age = int(time.time()) - message_ts
    if message_ts and age > 300:
        return {"status": "ignored", "reason": "stale"}

    # 4. Stale-generation cleanup
    await redis_client.check_and_clear_stale_generation(sender_phone)

    # 5. CLOSED-state handling (same logic as /webhook)
    session = await redis_client.get_session(sender_phone)
    cmd_check = msg.text.strip().lower()
    if session and session.get("state") == ConversationState.CLOSED and not cmd_check.startswith(("/reset", "#reset")):
        last_updated = session.get("last_updated")
        if last_updated:
            from datetime import datetime
            try:
                lu_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                diff = (datetime.utcnow().replace(tzinfo=None) - lu_dt.replace(tzinfo=None)).total_seconds()
                if diff < 86400:
                    return {"status": "ignored", "reason": "closed_state"}
                lead_name = session.get("lead_data", {}).get("first_name", "there")
                returning_template = f"Hey {lead_name}, Albert here again from After5. Glad you came back — what changed?"
                await send_message(sender_phone, returning_template)
                new_session = {
                    "state": ConversationState.OPENING,
                    "history": [{"role": "assistant", "content": returning_template}],
                    "turn_count": 1,
                    "lead_data": session.get("lead_data", {}),
                }
                await redis_client.save_session(sender_phone, new_session)
                return {"status": "reopened"}
            except Exception as e:
                logger.warning(f"[Baileys] CLOSED cooldown check failed: {e}")

    logger.info(f"[Baileys IN] {sender_phone} ({msg.name}): {msg.text[:80]}")

    # 6. Buffer + schedule processing — identical flow to /webhook
    batch_id = await redis_client.buffer_message(sender_phone, msg.text)
    await redis_client.redis.set(f"last_msg_id:{sender_phone}", message_id, ex=300)
    # Track every msg_id in the burst so we can blue-tick them all at once
    await redis_client.redis.rpush(f"pending_msg_ids:{sender_phone}", message_id)
    await redis_client.redis.expire(f"pending_msg_ids:{sender_phone}", 300)
    await redis_client.redis.set(f"last_name:{sender_phone}", msg.name, ex=300)
    # Track last lead message text so the typing-pause budget can scale with
    # how substantive their messages have been
    await redis_client.redis.set(f"last_lead_msg:{sender_phone}", msg.text[:500], ex=600)

    # SNAPPY GLANCE: if Albert is currently generating/sending another reply,
    # fire a fast blue-tick after a short pause. Mimics a real human who
    # finishes their current message, glances at the incoming new one
    # (instant blue tick), THEN takes time to compose the next reply.
    # Without this, the new message stays grey for 10-20s while the next
    # process cycle runs.
    if await redis_client.is_generating(sender_phone):
        background_tasks.add_task(_snappy_blue_tick, sender_phone, message_id)

    background_tasks.add_task(_delayed_buffer_process, sender_phone, batch_id, message_ts)
    if not await redis_client.redis.get(f"buffer_first:{sender_phone}"):
        background_tasks.add_task(_hard_max_check, sender_phone, message_ts)
    # Inbound logging fires CONCURRENTLY (asyncio.create_task) instead of
    # being queued in BackgroundTasks. The latter runs sequentially after
    # the buffer tasks (20+ seconds), so dashboard wouldn't show the user's
    # message until then — and if uvicorn reloaded mid-flow, it'd never log.
    asyncio.create_task(_background_tracker_log(sender_phone, msg.name, msg.text))

    return {"status": "ok"}

@router.get("/webhook")
async def verify_webhook(request: Request):
    """WhatsApp Cloud API webhook verification (GET request)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Reachable", status_code=200 if not mode else 403)


@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive incoming WhatsApp messages via Cloud API webhook.
    NEVER process immediately. Always buffer first.
    Return 200 instantly — process async.
    """
    try:
        payload = await request.json()
        
        # Ignore non-WhatsApp events
        if payload.get("object") != "whatsapp_business_account":
            return {"status": "ignored"}
        
        # Extract data from nested structure
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        # Check for status updates (delivered, read, failed)
        if "statuses" in value:
            status_obj = value["statuses"][0]
            status = status_obj.get("status")
            recipient = status_obj.get("recipient_id")
            logger.info(f"[Webhook Status] {recipient}: {status}")
            if status == "failed":
                errors = status_obj.get("errors")
                logger.error(f"[Webhook Status Error] {recipient} failed with errors: {errors}")
            return {"status": "ignored"}
        
        message = value["messages"][0]
        contact = value.get("contacts", [{}])[0]
        metadata = value.get("metadata", {})
        
        # Extract fields
        sender_wa_id = message.get("from", "")       # "447700900000"
        sender_name = contact.get("profile", {}).get("name", "")
        message_id = message.get("id", "")            # "wamid.xxx"
        message_type = message.get("type", "")        # "text" | "audio" | etc.
        message_ts = int(message.get("timestamp", 0))
        
        # Convert to internal phone format
        sender_phone = f"whatsapp:+{sender_wa_id}"    # "whatsapp:+447700900000"
        
        # 1. Dedup Check (Safeguard 2)
        dedup_key = f"dedup:{message_id}"
        if await redis_client.redis.get(dedup_key):
            logger.info(f"Duplicate message {message_id}, ignoring")
            return {"status": "duplicate"}
        await redis_client.redis.set(dedup_key, "1", ex=86400)

        # 2. Staleness check (Safeguard 1)
        import time
        message_age = int(time.time()) - message_ts
        if message_ts > 0 and message_age > 300:
            logger.info(f"Stale message ignored from {sender_phone}, age: {message_age}s")
            return {"status": "ignored", "reason": "stale"}

        # 3. Generation Cleanup (Safeguard 3)
        await redis_client.check_and_clear_stale_generation(sender_phone)

        # 4. CLOSED State Check — V4: re-open returning leads after 24h (bypassed for /reset commands)
        session = await redis_client.get_session(sender_phone)
        
        # Extract text early just for the command check
        cmd_check = ""
        if message_type == "text":
            cmd_check = message.get("text", {}).get("body", "").strip().lower()

        if session and session.get("state") == ConversationState.CLOSED and not cmd_check.startswith(("/reset", "#reset")):
            last_updated = session.get("last_updated")
            if last_updated:
                from datetime import datetime
                try:
                    lu_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    diff = (datetime.utcnow().replace(tzinfo=None) - lu_dt.replace(tzinfo=None)).total_seconds()
                    if diff < 86400:  # Still within 24h cooldown — ignore
                        logger.info(f"[Webhook] {sender_phone} is CLOSED within 24h. Ignoring message.")
                        return {"status": "ignored", "reason": "closed_state"}
                    else:
                        # 24h+ since close — re-open as returning lead
                        logger.info(f"[Webhook] {sender_phone} returning after 24h+ — reopening session.")
                        lead_name = session.get("lead_data", {}).get("first_name", "there")
                        returning_template = f"Hey {lead_name}, Albert here again from After5. Glad you came back — what changed?"
                        # Send template as single message
                        await send_message(sender_phone, returning_template)
                        # Re-initialise session
                        new_session = {
                            "state": ConversationState.OPENING,
                            "history": [{"role": "assistant", "content": returning_template}],
                            "turn_count": 1,
                            "lead_data": session.get("lead_data", {}),
                        }
                        await redis_client.save_session(sender_phone, new_session)
                        return {"status": "reopened"}
                except Exception as e:
                    logger.warning(f"[Webhook] CLOSED cooldown check failed: {e}")
        
        # 3. Dedup check
        
        # === EXTRACT MESSAGE TEXT (text or voice note) ===
        message_text = ""
        
        if message_type == "text":
            message_text = message.get("text", {}).get("body", "")
            
        elif message_type == "audio":
            # Voice note — optional acknowledgment
            if settings.VOICE_NOTE_ACKNOWLEDGE and settings.VOICE_NOTE_ACK_MESSAGE:
                await send_message(sender_phone, settings.VOICE_NOTE_ACK_MESSAGE)
                
            # Download and transcribe
            audio_media_id = message.get("audio", {}).get("id", "")
            if audio_media_id:
                message_text = await process_voice_note_from_media_id(audio_media_id)
                if not message_text:
                    # Transcription failed fallback
                    if settings.VOICE_NOTE_ACKNOWLEDGE:
                        await send_message(sender_phone, 
                            "Sorry, I had trouble hearing that voice note. Mind typing it out for me?")
                    return {"status": "error", "reason": "transcription failed"}
            else:
                return {"status": "error", "reason": "missing audio media id"}
                
        elif message_type == "document" or message_type == "image":
            # Check for audio files sent as documents (Bird new API or direct uploads)
            doc_mime = message.get(message_type, {}).get("mime_type", "")
            if doc_mime.startswith("audio/"):
                doc_media_id = message.get(message_type, {}).get("id", "")
                if doc_media_id:
                    message_text = await process_voice_note_from_media_id(doc_media_id)
                    if not message_text:
                        if settings.VOICE_NOTE_ACKNOWLEDGE:
                           await send_message(sender_phone, 
                                "Sorry, I had trouble hearing that voice note. Mind typing it out for me?")
                        return {"status": "error", "reason": "transcription failed"}
            else:
                logger.info(f"Ignored non-audio file: {message_type}")
                return {"status": "ignored", "reason": f"unsupported type: {message_type}"}
        else:
            # Unsupported type (image, sticker, location, etc.)
            logger.info(f"Unsupported message type: {message_type}")
            return {"status": "ignored", "reason": f"unsupported type: {message_type}"}
        
        if not message_text:
            return {"status": "ignored", "reason": "empty message"}
        
        logger.info(f"Message from {sender_phone} ({sender_name}): {message_text[:80]}...")
        
        # === BUFFER THE MESSAGE — DON'T PROCESS YET ===
        batch_id = await redis_client.buffer_message(sender_phone, message_text)
        # Store last message_id and sender_name for processing
        await redis_client.redis.set(f"last_msg_id:{sender_phone}", message_id, ex=300)
        # Track every msg_id in the burst so we can blue-tick them all at once
        await redis_client.redis.rpush(f"pending_msg_ids:{sender_phone}", message_id)
        await redis_client.redis.expire(f"pending_msg_ids:{sender_phone}", 300)
        await redis_client.redis.set(f"last_name:{sender_phone}", sender_name, ex=300)
        # Track last lead message text so the typing-pause budget can scale with
        # how substantive their messages have been
        await redis_client.redis.set(f"last_lead_msg:{sender_phone}", message_text[:500], ex=600)

        # SNAPPY GLANCE — if Albert is mid-reply, blue-tick the new message
        # within ~1.5s instead of making it wait through the next reply cycle.
        if await redis_client.is_generating(sender_phone):
            background_tasks.add_task(_snappy_blue_tick, sender_phone, message_id)

        # 5. Instant Blue Tick & Typing (REMOVED: Handled by advanced timing sequence)
        # background_tasks.add_task(mark_as_read, "", message_id)
        # background_tasks.add_task(send_typing_indicator, sender_phone, message_id)
        
        # Fire delayed processor (3s rolling timer)
        background_tasks.add_task(_delayed_buffer_process, sender_phone, batch_id, message_ts)
        
        # Fire hard-max safety check (8s fixed timer from first message in batch)
        # We only start this if it's the first message of a potentially new batch
        if await redis_client.redis.get(f"buffer_first:{sender_phone}"):
            # Already running for this batch
            pass
        else:
            # This shouldn't happen because buffer_message sets it, but for safety:
            background_tasks.add_task(_hard_max_check, sender_phone, message_ts)
        
        # Tracker Log fires concurrently (not via BackgroundTasks) so it
        # doesn't queue behind the buffer/process tasks. Otherwise inbound
        # would only log after the full reply cycle finishes ~20s later.
        asyncio.create_task(_background_tracker_log(sender_phone, sender_name, message_text))

        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"status": "error"}


async def _snappy_blue_tick(phone: str, message_id: str):
    """Quick blue-tick when a new message arrives while Albert is mid-reply."""
    try:
        import asyncio as _asyncio
        await _asyncio.sleep(0.5)
        from app.baileys_client import mark_batch_as_read
        await mark_batch_as_read(phone, [message_id])
        logger.info(f"[Snappy glance] Blue-ticked {message_id} for {phone} mid-reply")
    except Exception as e:
        logger.debug(f"[Snappy glance] failed for {phone}: {e}")


async def _background_tracker_log(phone: str, name: str, message: str):
    """Logs incoming message to Supabase in the background."""
    try:
        from app.tracker import AlbertTracker
        tracker = AlbertTracker()
        lead = await tracker.get_lead_by_phone(phone)
        if not lead:
            lead = await tracker.create_lead(phone=phone, first_name=name)
        if not lead:
            # Final fallback — retry lookup once more
            lead = await tracker.get_lead_by_phone(phone)
        if lead and lead.get("id"):
            await tracker.log_inbound(lead["id"], message)
        else:
            logger.warning("[Webhook] Could not find/create lead for %s — inbound message not logged", phone)
    except Exception as e:
        logger.error("[Webhook] Background Tracker failed: %s", e)


async def _delayed_buffer_process(phone: str, batch_id: str, last_message_ts: float = 0):
    """
    Wait. If no new messages arrived (batch_id still current),
    process the buffer. If new message arrived, this timer dies silently.
    """
    await asyncio.sleep(settings.INPUT_BUFFER_SECONDS)
    
    # Is this still the current batch?
    if not await redis_client.is_batch_current(phone, batch_id):
        return  # Newer message arrived, a newer timer will handle it
    
    # Clean up any stuck generation flags
    await redis_client.check_and_clear_stale_generation(phone)
    
    # If LLM generation already in progress, don't start another
    if await redis_client.is_generating(phone):
        return  # The interrupt handler will pick up new messages
    
    combined = await redis_client.get_and_clear_buffer(phone)
    if combined:
        logger.info(f"Buffer ready for {phone}: {combined[:80]}...")
        asyncio.create_task(_process_with_interrupt_protection(phone, combined, last_message_ts=last_message_ts))


async def _hard_max_check(phone: str, last_message_ts: float = 0):
    """Hard max safety — force process even if messages still arriving."""
    await asyncio.sleep(settings.INPUT_BUFFER_MAX_SECONDS)
    
    # Only if buffer still has unprocessed content
    if await redis_client.has_hit_hard_max(phone):
        if await redis_client.is_generating(phone):
            return  # Already processing, interrupt handler will catch it
        
        combined = await redis_client.get_and_clear_buffer(phone)
        if combined:
            logger.info(f"Hard max hit for {phone}, force-processing")
            asyncio.create_task(_process_with_interrupt_protection(phone, combined, last_message_ts=last_message_ts))


async def _process_with_interrupt_protection(
    phone: str, 
    combined_text: str, 
    retry_count: int = 0,
    last_message_ts: float = 0
):
    """
    Generate reply with interrupt protection.
    If new messages arrive during LLM generation, discard stale response
    and re-generate with full combined context.
    """
    from app.conversation import process_conversation
    
    try:
        # 1. State check (CLOSED state handler)
        session = await redis_client.get_session(phone)
        if session and session.get("state") == ConversationState.CLOSED:
            # Handled in webhook for instant rejection, but here for safety
            # But wait, we want to allow re-opening if cooldown passed.
            # We'll skip complex cooldown check here and let conversation engine handle or just reject.
            pass

        # 2. Mark as read (Handled in advanced timing now)
        last_msg_id_val = await redis_client.redis.get(f"last_msg_id:{phone}")
        last_msg_id = last_msg_id_val.decode('utf-8') if isinstance(last_msg_id_val, bytes) else (last_msg_id_val or "")

        # Pull the full burst of pending msg_ids so we can batch-blue-tick them
        pending_key = f"pending_msg_ids:{phone}"
        raw_ids = await redis_client.redis.lrange(pending_key, 0, -1)
        pending_ids = [
            (m.decode('utf-8') if isinstance(m, bytes) else m) for m in raw_ids
        ]
        if pending_ids:
            await redis_client.redis.delete(pending_key)

        # 3. Mark generation in progress
        await redis_client.set_generating(phone)

        # 4. Process via conversation engine
        await process_conversation(
            phone,
            combined_text,
            message_id=last_msg_id or "",
            last_message_ts=last_message_ts,
            pending_message_ids=pending_ids,
        )
        
        # 5. Interrupt Check (Layer 3)
        # Note: Step 9 in conversation.py already does this:
        # "If new messages arrived during processing for ..., re-generating"
        # It recursively calls itself.
        
        await redis_client.clear_generating(phone)
        
    except Exception as e:
        logger.error(f"Processing error for {phone}: {e}", exc_info=True)
        await redis_client.clear_generating(phone)

# Admin endpoints... (Keeping them)
@router.post("/admin/reset-session")
async def admin_reset_session(request: Request, _: None = Depends(require_api_key)):
    try:
        body = await request.json()
        phone = body.get("phone", "").strip()
        if not phone: return {"status": "error"}
        await redis_client.redis.delete(f"session:{phone}")
        await redis_client.redis.delete(f"buffer:{phone}")
        await redis_client.redis.delete(f"buffer_batch:{phone}")
        await redis_client.redis.delete(f"generating:{phone}")
        return {"status": "ok"}
    except: return {"status": "error"}
