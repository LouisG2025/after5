import asyncio
from fastapi import APIRouter, Body, BackgroundTasks
from app.models import LeadCreate
from app.supabase_client import supabase_client
from app.messagebird_client import send_message
from app.redis_client import redis_client
from app.models import ConversationState

router = APIRouter()

async def send_initial_outreach(name: str, phone: str, company: str, form_data: dict = None):
    """Sends the first outbound message after a delay."""
    from app.tracker import AlbertTracker
    tracker = AlbertTracker()

    # 1. Save to Supabase via Tracker
    lead = tracker.get_lead_by_phone(phone)
    if not lead:
        lead = tracker.create_lead(phone=phone, first_name=name, company=company)
    
    lead_id = lead.get("id")

    # 2. Start outreach sequence
    await asyncio.sleep(30)
    
    # 3. Initialize session with full form data if available
    # Form leads bypass OPENING and go straight to DISCOVERY
    session = {
        "state": ConversationState.DISCOVERY if form_data else ConversationState.OPENING,
        "history": [],
        "turn_count": 0,
        "lead_data": {**(lead or {}), **(form_data or {})}
    }
    await redis_client.save_session(phone, session)
    
    # 4. Send first message
    first_message = f"Hey {name}, this is Albert from After5 Digital. I saw your inquiry about {company} — wanted to reach out and see how we can help!"
    await send_message(phone, first_message)
    
    # 5. Log and update via Tracker
    tracker.log_outbound(lead_id, first_message)
    tracker.update_state(lead_id, "Opening")
    
    # Initial history
    await redis_client.add_to_history(phone, "assistant", first_message)

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
