import logging
import asyncio
import httpx
from fastapi import APIRouter, Request, BackgroundTasks
from app.config import settings
from app.redis_client import redis_client
from app.conversation import process_conversation
from app.messagebird_client import get_contact_phone, send_message

logger = logging.getLogger(__name__)
router = APIRouter()

# Bird API base
_BIRD_BASE = "https://api.bird.com"


def _headers() -> dict:
    return {
        "Authorization": f"AccessKey {settings.MESSAGEBIRD_API_KEY}",
        "Accept": "application/json",
    }


async def _buffer_timeout_handler(phone: str):
    """Waits for input buffer to expire, then processes combined message."""
    await asyncio.sleep(settings.INPUT_BUFFER_SECONDS)

    while await redis_client.is_timer_active(phone):
        await asyncio.sleep(0.5)

    messages = await redis_client.get_and_clear_buffer(phone)
    if messages:
        combined_message = " ".join(messages)
        await process_conversation(phone, combined_message)


@router.post("/webhook")
async def bird_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives Bird (MessageBird v2) Conversations webhook (JSON).

    Bird fires webhooks for both inbound AND outbound messages.
    We filter on direction to avoid infinite loops.
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Webhook: non-JSON body received")
        return {"status": "error", "reason": "invalid_json"}

    # ── Bird v2 webhook payload structure ──────────────────────────────────
    # {
    #   "event": "message.created" | "message.updated" | ...
    #   "workspace": {"id": "..."},
    #   "contact":   {"id": "...", "identifierValue": "+447700900000"},
    #   "channel":   {"id": "..."},
    #   "message": {
    #       "id": "...",
    #       "direction": "incoming" | "outgoing",
    #       "body": {"type": "text", "text": {"text": "..."}}
    #   }
    # }

    event = payload.get("event", payload.get("type", ""))

    # Only handle new inbound messages
    if "message" not in event:
        return {"status": "ignored", "reason": f"event:{event}"}

    message = payload.get("message", {})
    contact  = payload.get("contact", {})

    # Filter outbound echoes — CRITICAL to prevent infinite loops
    direction = message.get("direction", "")
    if direction not in ("incoming", "received"):
        return {"status": "ignored", "reason": "outbound_echo"}

    message_id   = message.get("id", "")
    contact_id   = contact.get("id", "")

    # Extract text — Bird v2 body structure
    body_obj   = message.get("body", {})
    msg_type   = body_obj.get("type", "")
    if msg_type == "text":
        message_text = body_obj.get("text", {}).get("text", "")
    else:
        # Non-text message (image, audio, etc.) — skip for now
        return {"status": "ignored", "reason": f"unsupported_type:{msg_type}"}

    if not message_text:
        return {"status": "ignored", "reason": "empty_body"}

    # Dedup on message ID
    if message_id and await redis_client.check_dedup(message_id):
        logger.info("Duplicate message %s, ignoring", message_id)
        return {"status": "ignored", "reason": "duplicate"}

    # Resolve sender phone
    # Bird may include identifierValue directly in the contact object
    sender_phone = None
    identifier = contact.get("identifierValue", "")
    if identifier:
        from app.messagebird_client import _to_internal_phone
        sender_phone = _to_internal_phone(identifier)
    elif contact_id:
        sender_phone = await get_contact_phone(contact_id)

    if not sender_phone:
        logger.error("Could not resolve phone for contact %s", contact_id)
        return {"status": "error", "reason": "phone_resolution_failed"}

    logger.info("Bird message from %s: %.60s…", sender_phone, message_text)

    # Buffer message + set/reset timer
    await redis_client.buffer_message(sender_phone, message_text)
    await redis_client.set_buffer_timer(sender_phone)

    # Schedule processing — return 200 immediately
    background_tasks.add_task(_buffer_timeout_handler, sender_phone)

    return {"status": "ok"}
