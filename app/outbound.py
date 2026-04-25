import asyncio
import logging
from fastapi import APIRouter, Body, BackgroundTasks
from app.models import LeadCreate
from app.supabase_client import supabase_client
from app.whatsapp_client import (
    send_message, 
    send_typing_indicator, 
    send_chunked_messages,
    send_template_message
)
from app.redis_client import redis_client
from app.models import ConversationState
from app.tracker import AlbertTracker
from app.chunker import chunk_message, calculate_typing_delay, format_message
from app.templates import OUTREACH_TEMPLATES, FOLLOW_UP_TEMPLATE, RETURNING_LEAD_TEMPLATES
from app.phone_utils import normalize_phone
from app.name_utils import clean_personal_name, clean_company_name
from datetime import datetime, timezone
import random

logger = logging.getLogger(__name__)
router = APIRouter()

async def send_initial_outreach(name_raw: str, phone_raw: str, company_raw: str, form_data: dict = None):
    """Sends the first outbound message after a delay."""
    try:
        tracker = AlbertTracker()
        
        # Normalize name and company for display and storage
        name = clean_personal_name(name_raw)
        company = clean_company_name(company_raw)
        
        # Normalize phone to internal format: whatsapp:+[digits]
        sender_phone = normalize_phone(phone_raw)

        # 1. Save to Supabase via Tracker (or get existing)
        lead = await tracker.get_lead_by_phone(sender_phone)
        if not lead:
            lead = await tracker.create_lead(
                phone=sender_phone, 
                first_name=name, 
                company=company, 
                lead_source=form_data.get("source", "Website Demo Form") if form_data else "Website Demo Form",
                form_message=form_data.get("message", "") if form_data else ""
            )
        
        lead_id = lead.get("id") if lead else "unknown"

        # 2. Start outreach sequence (Wait for lead to settle)
        # Simulation Reliability: Skip delay for testing
        is_sim = form_data and form_data.get("source") == "Interactive Reset Simulation"
        if not is_sim:
            await asyncio.sleep(15)
        
        # 3. Outreach Content
        raw_template = random.choice(OUTREACH_TEMPLATES)
        first_message_content = raw_template.format(name=name, company_name=company)
        
        # 4. Attempt Template Outreach (Highly Recommended for WhatsApp Cloud API)
        template_name = "after5_outreach"
        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": name},
                    {"type": "text", "text": company}
                ]
            }
        ]
        
        if is_sim:
            logger.info("[Outreach] 🧪 Simulation: Skipping template, using raw text fallback.")
            template_res = None
        else:
            logger.info("[Outreach] 🚀 Attempting template outreach for %s (%s)", name, sender_phone)
            template_res = await send_template_message(
                sender_phone, 
                template_name, 
                language_code="en_GB", 
                components=components
            )
        
        # 6. Initialize or Update session with history and correct state
        target_state = ConversationState.DISCOVERY if form_data else ConversationState.OPENING
        
        # Check if a session already exists (e.g. user texted while we were processing)
        session = await redis_client.get_session(sender_phone)
        if not session:
            session = {
                "state": target_state,
                "history": [],
                "turn_count": 0,
                "lead_data": {**(lead or {}), **(form_data or {})}
            }
        
        # Merge history: Add outreach message EARLY to prevent race conditions
        session["history"].append({"role": "assistant", "content": first_message_content})
        session["turn_count"] = session.get("turn_count", 0) + 1
        session["state"] = target_state
        
        await redis_client.save_session(sender_phone, session)
        
        # 7. Update conversation state in Supabase
        state_label = "Discovery" if target_state == ConversationState.DISCOVERY else "Opening"
        await tracker.update_state(lead_id, state_label)

        # 8. Delivery (now happening after session is safe)
        if template_res:
            logger.info("[Outreach] ✅ Template sent successfully via WhatsApp Cloud API")
            # Log to Supabase (already logged to session history)
            await tracker.log_outbound(lead_id, first_message_content)
        else:
            if not is_sim:
                logger.warning("[Outreach] ⚠️ Template send failed. Falling back to raw text.")
            
            # 5. Fallback: Human-like delivery — bypass chunking for template
            chunks = chunk_message(first_message_content, is_template=True)

            # Note: typing indicator and delays are handled INSIDE send_chunked_messages.
            delivered = await send_chunked_messages(sender_phone, chunks, interruptible=False)

            # Only log to Supabase if mobile WhatsApp actually got it.
            for chunk_text in (delivered or []):
                await tracker.log_outbound(lead_id, chunk_text)
            if not delivered:
                logger.error("[Outreach] Initial outreach to %s did NOT deliver — skipping dashboard log to keep it in sync with mobile", sender_phone)

    except Exception as e:
        logger.error("[Outreach] 🚨 Failed to send initial outreach for %s: %s", phone_raw, e, exc_info=True)

@router.post("/send-outbound")
async def send_outbound(lead: LeadCreate, background_tasks: BackgroundTasks = None):
    asyncio.create_task(send_initial_outreach(lead.name, lead.phone, lead.company))
    return {"status": "outreach_scheduled"}

@router.post("/form-webhook")
async def form_webhook(payload: dict):
    """Endpoint for n8n/website form submissions.

    If the lead is new → normal outreach.
    If the lead already exists (same phone) → welcome-back flow that
    preserves awareness of the previous conversation.
    """
    name = payload.get("first_name") or payload.get("name")
    phone = payload.get("phone")
    company = payload.get("company", "your business")

    if not name or not phone:
        return {"error": "name and phone required"}

    normalized = normalize_phone(phone)
    tracker = AlbertTracker()
    existing_lead = await tracker.get_lead_by_phone(normalized)

    if existing_lead:
        # --- Returning lead: welcome-back flow ---
        logger.info("[Form Webhook] 🔁 Returning lead detected: %s (%s)", name, normalized)
        asyncio.create_task(
            send_returning_outreach(name, normalized, company, payload, existing_lead)
        )
        return {"status": "returning_outreach_scheduled", "returning": True}
    else:
        # --- Brand new lead: normal outreach ---
        asyncio.create_task(send_initial_outreach(name, phone, company, payload))
        return {"status": "outreach_scheduled", "returning": False}

async def send_returning_outreach(name_raw: str, phone: str, company_raw: str, form_data: dict, existing_lead: dict):
    """Handles a returning lead who re-submitted the form.

    Instead of wiping everything, we reset the session but keep the lead
    record and inject a summary of the previous conversation so Albert
    picks up where they left off with a cheeky welcome-back opener.
    """
    try:
        tracker = AlbertTracker()
        name = clean_personal_name(name_raw)
        company = clean_company_name(company_raw)
        lead_id = existing_lead.get("id")

        # 1. Grab previous session history before we reset it
        old_session = await redis_client.get_session(phone)
        previous_summary = ""
        if old_session and old_session.get("history"):
            # Build a short context note for the LLM about the prior conversation
            old_history = old_session["history"]
            user_msgs = [m["content"] for m in old_history if m["role"] == "user"]
            if user_msgs:
                previous_summary = (
                    "RETURNING LEAD CONTEXT: This person spoke to Albert before. "
                    f"They sent {len(user_msgs)} messages last time. "
                    f"Previous state was '{old_session.get('state', 'unknown')}'. "
                    "Do NOT repeat discovery questions they already answered. "
                    "Pick up naturally from where things left off."
                )

        # 2. Update the lead record with any new form data (company may have changed etc)
        if lead_id:
            client = await supabase_client.get_client()
            update_payload = {"updated_at": datetime.now(timezone.utc).isoformat()}
            if name:
                update_payload["first_name"] = name
            if company:
                update_payload["company"] = company
            if form_data.get("message"):
                update_payload["form_message"] = form_data["message"]
            await client.table("leads").update(update_payload).eq("id", lead_id).execute()

        # 3. Pick a welcome-back template
        welcome_msg = random.choice(RETURNING_LEAD_TEMPLATES).format(
            name=name, company_name=company
        )

        # 4. Wait a natural delay
        await asyncio.sleep(10)

        # 5. Build new session with the welcome-back message and previous context
        new_session = {
            "state": ConversationState.DISCOVERY,
            "history": [{"role": "assistant", "content": welcome_msg}],
            "turn_count": 1,
            "lead_data": {**existing_lead, **(form_data or {})},
            "low_content_count": 0,
            "returning_lead": True,
        }
        if previous_summary:
            new_session["previous_context"] = previous_summary

        await redis_client.save_session(phone, new_session)

        # 6. Update conversation state in Supabase
        if lead_id:
            await tracker.update_state(lead_id, "Discovery")

        # 7. Send the welcome-back message
        chunks = chunk_message(welcome_msg, is_template=True)
        delivered = await send_chunked_messages(phone, chunks, interruptible=False)
        if lead_id:
            for chunk_text in (delivered or []):
                await tracker.log_outbound(lead_id, chunk_text)
            if not delivered:
                logger.error("[Returning Outreach] Welcome-back to %s did NOT deliver — skipping dashboard log", phone)

        logger.info("[Returning Outreach] ✅ Welcome-back sent to %s (%s)", name, phone)

    except Exception as e:
        logger.error("[Returning Outreach] 🚨 Failed for %s: %s", phone, e, exc_info=True)


async def send_follow_up_message(lead_id: str, name: str, phone: str):
    """Sends the 24-hour follow-up message."""
    try:
        tracker = AlbertTracker()
        
        # 1. Formatting the follow-up content
        follow_up_content = FOLLOW_UP_TEMPLATE.format(name=name)
        
        logger.info("[Follow-up] 🚀 Sending follow-up to %s (%s)", name, phone)
        
        # 2. Human-like delivery — bypass chunking for follow-up template
        from app.chunker import chunk_message
        chunks = chunk_message(follow_up_content, is_template=True)
        delivered = await send_chunked_messages(phone, chunks, interruptible=False)

        # 3. Log to Supabase only what actually delivered to mobile WhatsApp
        for chunk_text in (delivered or []):
            await tracker.log_outbound(lead_id, chunk_text)
        if not delivered:
            logger.error("[Follow-up] Follow-up to %s did NOT deliver — skipping dashboard log", phone)
        
        # 4. Initialize or Update session state
        session = await redis_client.get_session(phone)
        if session:
            session["history"].append({"role": "assistant", "content": follow_up_content})
            session["turn_count"] = session.get("turn_count", 1) + 1
            await redis_client.save_session(phone, session)
        
        logger.info("[Follow-up] ✅ Follow-up sent to %s", name)

    except Exception as e:
        logger.error("[Follow-up] 🚨 Failed to send follow-up for %s: %s", name, e, exc_info=True)

@router.post("/follow-up")
async def trigger_follow_up(payload: dict = Body(...)):
    """Admin endpoint to manually trigger a follow-up for a lead."""
    lead_id = payload.get("lead_id")
    name = payload.get("name")
    phone = payload.get("phone")
    
    if not all([lead_id, name, phone]):
        return {"error": "lead_id, name, and phone are required"}
        
    asyncio.create_task(send_follow_up_message(lead_id, name, phone))
    return {"status": "follow_up_scheduled"}
