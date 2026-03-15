import asyncio
import logging
from fastapi import APIRouter, Body, BackgroundTasks
from app.models import LeadCreate
from app.supabase_client import supabase_client
from app.messaging import send_message, send_typing_indicator, send_chunked_messages
from app.redis_client import redis_client
from app.models import ConversationState
from app.tracker import AlbertTracker
from app.chunker import chunk_message, calculate_typing_delay

logger = logging.getLogger(__name__)
router = APIRouter()

async def send_initial_outreach(name: str, phone: str, company: str, form_data: dict = None):
    """Sends the first outbound message after a delay."""
    tracker = AlbertTracker()

    # 1. Save to Supabase via Tracker with source
    lead = await tracker.get_lead_by_phone(phone)
    if not lead:
        lead = await tracker.create_lead(
            phone=phone, 
            first_name=name, 
            company=company, 
            lead_source=form_data.get("source", "Website Demo Form") if form_data else "Website Demo Form",
            form_message=form_data.get("message", "") if form_data else ""
        )
    
    lead_id = lead.get("id")

    # 2. Start outreach sequence (Radio silence first)
    await asyncio.sleep(20)
    
    # 3. Message Prep (London Guy tone: lowercase, tbh, |||)
    first_message = f"hey {name}, Albert here|||just saw you checked out the demo for {company} and wanted to say hi|||any questions on how it all works tbh"
    
    # 4. Human-like outreach: Typing indicator and character-based delay
    chunks = chunk_message(first_message)
    outreach_delay = calculate_typing_delay(chunks[0])
    
    logger.info("[Outreach] Showing typing indicator for %.1fs for %s", outreach_delay, phone)
    await send_typing_indicator(phone)
    await asyncio.sleep(outreach_delay)

    # 5. Send the message(s)
    await send_chunked_messages(phone, chunks)
    
    # 6. Initialize session with history and correct state
    target_state = ConversationState.DISCOVERY if form_data else ConversationState.OPENING
    session = {
        "state": target_state,
        "history": [{"role": "assistant", "content": first_message}],
        "turn_count": 1,
        "lead_data": {**(lead or {}), **(form_data or {})}
    }
    await redis_client.save_session(phone, session)
    
    # 7. Log and update via Tracker
    await tracker.log_outbound(lead_id, first_message)
    
    # State synchronization with Supabase
    state_label = "Discovery" if target_state == ConversationState.DISCOVERY else "Opening"
    await tracker.update_state(lead_id, state_label)

@router.post("/send-outbound")
async def send_outbound(lead: LeadCreate, background_tasks: BackgroundTasks = None):
    asyncio.create_task(send_initial_outreach(lead.name, lead.phone, lead.company))
    return {"status": "outreach_scheduled"}

@router.post("/form-webhook")
async def form_webhook(payload: dict):
    """Endpoint for n8n/website form submissions."""
    name = payload.get("first_name") or payload.get("name")
    phone = payload.get("phone")
    company = payload.get("company", "your business")
    
    if not name or not phone:
        return {"error": "name and phone required"}
        
    asyncio.create_task(send_initial_outreach(name, phone, company, payload))
    return {"status": "outreach_scheduled"}
