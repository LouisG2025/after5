"""
Messaging Abstraction
=====================
Routes WhatsApp operations to the configured provider:
  - "baileys"        → local Baileys Node bridge (demo phase, QR-paired)
  - "whatsapp_cloud" → Meta WhatsApp Business Cloud API (production)
  - "messagebird"    → legacy Bird API (deprecated, kept for compat)
"""
import logging

from app.config import settings
from app import baileys_client as baileys
from app import messagebird_client as bird
from app import whatsapp_client as cloud
from typing import Optional

logger = logging.getLogger(__name__)


def _provider() -> str:
    return (settings.MESSAGING_PROVIDER or "baileys").lower()


async def send_message(to: str, body: str) -> Optional[dict]:
    """Send a message using the configured provider."""
    provider = _provider()
    if provider == "baileys":
        return await baileys.send_message(to, body)
    if provider == "whatsapp_cloud":
        return await cloud.send_message(to, body)
    return await bird.send_message(to, body)


async def mark_as_read(conversation_id: str, message_id: str) -> bool:
    """Mark a message as read using the configured provider."""
    provider = _provider()
    if provider == "baileys":
        await baileys.mark_as_read(message_id)
        return True
    if provider == "whatsapp_cloud":
        return await cloud.mark_as_read(message_id)
    return await bird.mark_as_read(conversation_id, message_id)


async def send_chunked_messages(
    to: str,
    chunks: list[str],
    incoming_text: str = "",
    last_message_ts: float = 0,
    message_id: str = "",
    pending_message_ids: Optional[list[str]] = None,
    interruptible: bool = True,
) -> list[str]:
    """Send chunked messages and return the list of chunks that ACTUALLY
    delivered. Callers must use the returned list (not the input chunks)
    when logging to the dashboard so the dashboard stays in sync with
    the mobile WhatsApp conversation.
    """
    provider = _provider()
    if provider == "baileys":
        result = await baileys.send_chunked_messages(
            to, chunks, incoming_text, last_message_ts, message_id,
            pending_message_ids=pending_message_ids,
            interruptible=interruptible,
        )
        return result if isinstance(result, list) else []
    if provider == "whatsapp_cloud":
        result = await cloud.send_chunked_messages(
            to, chunks, incoming_text, last_message_ts, message_id,
            interruptible=interruptible,
        )
        # Cloud client may not yet return a list; fall back to assuming
        # all chunks delivered when the call completed without raising.
        return result if isinstance(result, list) else list(chunks)
    result = await bird.send_chunked_messages(to, chunks, incoming_text, last_message_ts)
    return result if isinstance(result, list) else list(chunks)


async def send_typing_indicator(
    to: str, conversation_id: str = "", message_id: str = ""
) -> bool:
    """Send typing indicator using the configured provider."""
    provider = _provider()
    if provider == "baileys":
        return await baileys.send_typing_indicator(to, message_id)
    if provider == "whatsapp_cloud":
        return await cloud.send_typing_indicator(to, message_id)
    return await bird.send_typing_indicator(to, conversation_id)


async def get_contact_phone(contact_id: str) -> Optional[str]:
    """Contact phone lookup (legacy Bird feature)."""
    if _provider() == "messagebird":
        return await bird.get_contact_phone(contact_id)
    return None
