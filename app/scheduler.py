"""
Follow-up scheduler — runs in the background and sends nudge messages
to leads who haven't replied after 24 hours.

Checks every hour for:
1. Leads in DISCOVERY/QUALIFICATION state with no reply in 24h → sends nudge
2. Max 1 follow-up per lead (tracked via Redis flag)
"""

import asyncio
import logging
from datetime import datetime, timezone
from app.supabase_client import supabase_client
from app.redis_client import redis_client
from app.messaging import send_message
from app.tracker import AlbertTracker

logger = logging.getLogger(__name__)

FOLLOWUP_CHECK_INTERVAL = 3600  # Check every hour
FOLLOWUP_AFTER_SECONDS = 86400  # 24 hours since last activity
FOLLOWUP_MESSAGE = "Hey {name}, just following up from yesterday. No stress if the timing's off, just didn't want you to miss the message. Let me know if it's worth chatting"

# States where a follow-up makes sense
FOLLOWUP_STATES = ["Discovery", "Qualification", "Booking Push"]


async def check_and_send_followups():
    """Scan for leads that need a 24h follow-up nudge."""
    try:
        tracker = AlbertTracker()
        client = await supabase_client.get_client()

        # Find leads in active states that haven't been updated in 24h+
        now = datetime.now(timezone.utc)

        result = await client.table("leads").select(
            "id, phone, first_name, current_state, updated_at"
        ).in_("current_state", FOLLOWUP_STATES).execute()

        if not result.data:
            return

        sent_count = 0
        for lead in result.data:
            lead_id = lead.get("id")
            phone = lead.get("phone", "")
            name = lead.get("first_name", "there")
            updated_at = lead.get("updated_at", "")

            if not phone or not updated_at:
                continue

            # Check if 24h has passed since last activity
            try:
                last_update = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                idle_seconds = (now - last_update).total_seconds()
            except Exception:
                continue

            if idle_seconds < FOLLOWUP_AFTER_SECONDS:
                continue

            # Check if we already sent a follow-up (max 1 per lead)
            followup_key = f"followup_sent:{phone}"
            if await redis_client.redis.get(followup_key):
                continue

            # Send the follow-up
            msg = FOLLOWUP_MESSAGE.format(name=name or "there")
            try:
                await send_message(phone, msg)
                await redis_client.redis.set(followup_key, "1", ex=86400 * 7)  # 7 day TTL
                await tracker.log_outbound(lead_id, msg)
                sent_count += 1
                logger.info("[Scheduler] Sent 24h follow-up to %s (%s)", name, phone)
            except Exception as e:
                logger.error("[Scheduler] Failed to send follow-up to %s: %s", phone, e)

        if sent_count:
            logger.info("[Scheduler] Sent %d follow-up(s) this cycle", sent_count)

    except Exception as e:
        logger.error("[Scheduler] Follow-up check failed: %s", e, exc_info=True)


async def run_scheduler():
    """Background loop that runs follow-up checks every hour."""
    logger.info("[Scheduler] Follow-up scheduler started (checks every %ds)", FOLLOWUP_CHECK_INTERVAL)
    # Wait 60s after startup before first check (let everything initialise)
    await asyncio.sleep(60)
    while True:
        try:
            await check_and_send_followups()
        except Exception as e:
            logger.error("[Scheduler] Unexpected error: %s", e, exc_info=True)
        await asyncio.sleep(FOLLOWUP_CHECK_INTERVAL)
