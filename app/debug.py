"""
Dev-only reset endpoints for controlled test runs.

POST /debug/reset — nukes a phone's lead + Redis state, then (optionally)
re-fires the opening outreach template so a test starts from a real
form-submit state instead of a manual 'hello'.
"""

import asyncio
import logging
from fastapi import APIRouter, Body
from app.supabase_client import supabase_client
from app.redis_client import redis_client
from app.phone_utils import normalize_phone
from app.outbound import send_initial_outreach

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/debug", tags=["debug"])


REDIS_KEY_PATTERNS = [
    "session:{phone}",
    "buffer:{phone}",
    "buffer_first:{phone}",
    "buffer_batch:{phone}",
    "generating:{phone}",
    "generating_ts:{phone}",
    "calendly_sent:{phone}",
    "lead_typing_start:{phone}",
    "lead_typing_last:{phone}",
    "lead_typing_stop:{phone}",
]


async def _wipe_redis(phone: str) -> int:
    keys = [p.format(phone=phone) for p in REDIS_KEY_PATTERNS]
    return await redis_client.redis.delete(*keys)


async def _wipe_supabase(phone: str) -> dict:
    """Delete lead + cascading messages/state/bookings. Safe if nothing exists."""
    client = await supabase_client.get_client()
    lead = await client.table("leads").select("id").eq("phone", phone).execute()
    lead_id = lead.data[0]["id"] if lead.data else None
    if lead_id:
        # ON DELETE CASCADE handles messages, conversation_state, bookings
        await client.table("leads").delete().eq("id", lead_id).execute()
    return {"deleted_lead_id": lead_id}


@router.post("/reset")
async def reset_conversation(payload: dict = Body(...)):
    """
    Body:
      phone         (required) — any format, we normalize
      first_name    (optional, default 'Test') — for outreach template
      company       (optional, default 'your business')
      message       (optional) — form_message stored on the lead
      send_outreach (optional, default true) — fire opening template after reset
    """
    phone_raw = payload.get("phone")
    if not phone_raw:
        return {"error": "phone is required"}

    phone = normalize_phone(phone_raw)
    first_name = payload.get("first_name") or "Test"
    company = payload.get("company") or "your business"
    message = payload.get("message") or ""
    send_outreach = payload.get("send_outreach", True)

    logger.info("[Debug Reset] 🧹 Resetting %s", phone)

    redis_deleted = await _wipe_redis(phone)
    supabase_result = await _wipe_supabase(phone)

    logger.info(
        "[Debug Reset] ✅ Wiped %s — redis keys: %d, supabase: %s",
        phone, redis_deleted, supabase_result,
    )

    scheduled = False
    if send_outreach:
        asyncio.create_task(send_initial_outreach(
            name_raw=first_name,
            phone_raw=phone,
            company_raw=company,
            form_data={
                "source": "Interactive Reset Simulation",
                "message": message,
            },
        ))
        scheduled = True

    return {
        "status": "reset",
        "phone": phone,
        "redis_keys_deleted": redis_deleted,
        "supabase": supabase_result,
        "outreach_scheduled": scheduled,
    }


@router.get("/redis/{phone}")
async def inspect_redis(phone: str):
    """Read-only: show all Redis state for a phone. Useful for debugging."""
    phone = normalize_phone(phone)
    out = {}
    for pattern in REDIS_KEY_PATTERNS:
        key = pattern.format(phone=phone)
        value = await redis_client.redis.get(key)
        if value is not None:
            out[key] = value
    return {"phone": phone, "keys": out}
