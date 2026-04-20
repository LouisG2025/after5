import json
import os
from typing import List, Dict, Any
from app.config import settings
from app.llm import llm_client
from app.redis_client import redis_client

from app.tracker import AlbertTracker

tracker = AlbertTracker()

async def extract_bant(phone: str, history: List[Dict[str, str]]):
    """Background BANT extraction using a cheap LLM model."""
    prompt_path = os.path.join(os.getcwd(), "prompts", "bant_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        bant_prompt = f.read()

    # Format history for prompt
    history_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history])
    system_prompt = bant_prompt.replace("{{conversation_history}}", history_text)

    messages = [{"role": "system", "content": system_prompt}]

    try:
        # Load current session
        session = await redis_client.get_session(phone)
        if not session:
            return

        lead_data = session.get("lead_data", {})
        lead_id = lead_data.get("id", "unknown")

        response_text = await llm_client.call_llm(
            messages, 
            model=settings.OPENROUTER_BANT_MODEL,
            lead_id=lead_id,
            conversation_state=session["state"],
            phone=phone,
            company=lead_data.get("company", "")
        )
        # Clean response text in case LLM added markdown backticks
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        bant_data = json.loads(response_text)
        
        # Update session
        session["bant_scores"] = bant_data
        
        # Additional flags
        if bant_data.get("overall_score", 0) >= 7:
            session["push_booking"] = True
        if bant_data.get("overall_score", 0) >= 9:
            session["escalate"] = True
            
        await redis_client.save_session(phone, session)
        
        # ── Update Tracker ─────────────────
        # Map new scoring categories to existing BANT DB columns
        await tracker.update_state(
            lead_id=lead_id,
            current_state=session["state"],
            bant_budget=bant_data.get("lead_gen", {}).get("evidence"),
            bant_authority=bant_data.get("engagement", {}).get("evidence"),
            bant_need=bant_data.get("pain", {}).get("evidence"),
            bant_timeline=bant_data.get("intent", {}).get("evidence")
        )
        
        await tracker.update_signal_score(lead_id, bant_data.get("overall_score", 0))
        
        # Logic for temperature
        score = bant_data.get("overall_score", 0)
        temp = "Cold"
        if score >= 8: temp = "Hot"
        elif score >= 5: temp = "Warm"
        await tracker.update_temperature(lead_id, temp)
            
    except Exception as e:
        print(f"Error extracting BANT for {phone}: {e}")
