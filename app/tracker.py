"""
AlbertTracker — writes all Albert activity to Supabase
so the After5 dashboard can display it in real time.
"""

import os
from datetime import datetime, timezone
from typing import Optional
from app.supabase_client import supabase_client

# Shortcut to the underlying supabase-py client
supabase = supabase_client.client


class AlbertTracker:

    # ─── LEADS ───────────────────────────────────────────────

    def create_lead(
        self,
        phone: str,
        first_name: str = "",
        last_name: str = "",
        email: str = "",
        company: str = "",
        industry: str = "",
        lead_source: str = "Other",
        form_message: str = "",
    ) -> dict:
        """Call when a new lead submits the form or contacts Albert for the first time."""
        try:
            # Check if lead already exists (duplicate phone)
            existing = self.get_lead_by_phone(phone)
            if existing:
                return existing

            result = supabase.table("leads").insert({
                "phone": phone,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "company": company,
                "industry": industry,
                "lead_source": lead_source,
                "form_message": form_message,
                "temperature": "Cold",
                "outcome": "In Progress",
                "signal_score": 0,
            }).execute()

            if result.data:
                lead = result.data[0]
                self._init_conversation_state(lead["id"])
                print(f"[Albert Tracker] ✅ Lead created: {first_name} {last_name} ({phone})")
                return lead

        except Exception as e:
            print(f"[Albert Tracker Error] create_lead: {e}")
        return {}

    def get_lead_by_phone(self, phone: str) -> Optional[dict]:
        """Call on every incoming WhatsApp message to find the lead."""
        try:
            result = supabase.table("leads").select("*").eq("phone", phone).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"[Albert Tracker Error] get_lead_by_phone: {e}")
            return None

    def update_signal_score(self, lead_id: str, score: int) -> None:
        """Call whenever Albert recalculates lead quality. Score: 0–10."""
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("leads").update({
                "signal_score": max(0, min(10, score)),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", lead_id).execute()
        except Exception as e:
            print(f"[Albert Tracker Error] update_signal_score: {e}")

    def update_temperature(self, lead_id: str, temperature: str) -> None:
        """temperature: 'Cold' | 'Warm' | 'Hot'"""
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("leads").update({
                "temperature": temperature,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", lead_id).execute()
        except Exception as e:
            print(f"[Albert Tracker Error] update_temperature: {e}")

    def update_outcome(self, lead_id: str, outcome: str) -> None:
        """outcome: 'In Progress' | 'Not Interested' | 'Disqualified' | 'Meeting Booked'"""
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("leads").update({
                "outcome": outcome,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", lead_id).execute()
        except Exception as e:
            print(f"[Albert Tracker Error] update_outcome: {e}")

    # ─── MESSAGES ────────────────────────────────────────────

    def log_inbound(self, lead_id: str, content: str) -> dict:
        """Call every time a lead sends Albert a WhatsApp message."""
        if not lead_id or lead_id == "unknown":
            return {}
        try:
            result = supabase.table("messages").insert({
                "lead_id": lead_id,
                "direction": "inbound",
                "content": content,
            }).execute()
            self._increment_message_count(lead_id)
            self._update_last_active(lead_id)
            return result.data[0] if result.data else {}
        except Exception as e:
            print(f"[Albert Tracker Error] log_inbound: {e}")
            return {}

    def log_outbound(self, lead_id: str, content: str) -> dict:
        """Call every time Albert sends a WhatsApp reply."""
        if not lead_id or lead_id == "unknown":
            return {}
        try:
            result = supabase.table("messages").insert({
                "lead_id": lead_id,
                "direction": "outbound",
                "content": content,
            }).execute()
            self._increment_message_count(lead_id)
            self._update_last_active(lead_id)
            return result.data[0] if result.data else {}
        except Exception as e:
            print(f"[Albert Tracker Error] log_outbound: {e}")
            return {}

    # ─── CONVERSATION STATE ───────────────────────────────────

    def update_state(
        self,
        lead_id: str,
        current_state: str,
        bant_budget: Optional[str] = None,
        bant_authority: Optional[str] = None,
        bant_need: Optional[str] = None,
        bant_timeline: Optional[str] = None,
    ) -> None:
        if not lead_id or lead_id == "unknown":
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                "lead_id": lead_id,
                "current_state": current_state,
                "last_active_at": now,
                "updated_at": now,
            }
            # Only include BANT fields that were explicitly passed
            if bant_budget is not None:
                payload["bant_budget"] = bant_budget
            if bant_authority is not None:
                payload["bant_authority"] = bant_authority
            if bant_need is not None:
                payload["bant_need"] = bant_need
            if bant_timeline is not None:
                payload["bant_timeline"] = bant_timeline

            supabase.table("conversation_state").upsert(payload, on_conflict="lead_id").execute()
        except Exception as e:
            print(f"[Albert Tracker Error] update_state: {e}")

    # ─── BOOKINGS ─────────────────────────────────────────────

    def confirm_booking(
        self,
        lead_id: str,
        calendly_event_id: str,
        scheduled_at: str,
    ) -> dict:
        """Call when Calendly confirms a meeting. Automatically updates outcome + state."""
        if not lead_id or lead_id == "unknown":
            return {}
        try:
            result = supabase.table("bookings").insert({
                "lead_id": lead_id,
                "calendly_event_id": calendly_event_id,
                "scheduled_at": scheduled_at,
                "status": "confirmed",
            }).execute()
            # Auto-update lead outcome and conversation state
            self.update_outcome(lead_id, "Meeting Booked")
            self.update_state(lead_id, "Confirmed")
            print(f"[Albert Tracker] ✅ Booking confirmed for lead {lead_id}")
            return result.data[0] if result.data else {}
        except Exception as e:
            print(f"[Albert Tracker Error] confirm_booking: {e}")
            return {}

    def cancel_booking(self, lead_id: str, calendly_event_id: str) -> None:
        """Call when Calendly cancels a meeting. Puts lead back to In Progress."""
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("bookings").update({
                "status": "cancelled"
            }).eq("calendly_event_id", calendly_event_id).execute()
            self.update_outcome(lead_id, "In Progress")
            self.update_state(lead_id, "Awaiting")
        except Exception as e:
            print(f"[Albert Tracker Error] cancel_booking: {e}")

    # ─── LLM TRACKING ─────────────────────────────────────────

    def log_llm_call(
        self,
        lead_id: str,
        response_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: int,
        conversation_state: str,
    ) -> None:
        """Called automatically by llm.py — do not call manually."""
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("llm_sessions").insert({
                "lead_id": lead_id,
                "helicone_id": response_id,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "conversation_state": conversation_state,
            }).execute()
        except Exception as e:
            print(f"[Albert Tracker Error] log_llm_call: {e}")

    # ─── PRIVATE HELPERS ──────────────────────────────────────

    def _init_conversation_state(self, lead_id: str) -> None:
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("conversation_state").upsert({
                "lead_id": lead_id,
                "current_state": "Opening",
                "message_count": 0,
                "last_active_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="lead_id").execute()
        except Exception as e:
            print(f"[Albert Tracker Error] _init_conversation_state: {e}")

    def _increment_message_count(self, lead_id: str) -> None:
        if not lead_id or lead_id == "unknown":
            return
        try:
            result = supabase.table("conversation_state").select("message_count").eq("lead_id", lead_id).execute()
            if result.data:
                count = (result.data[0].get("message_count") or 0) + 1
                supabase.table("conversation_state").update({
                    "message_count": count
                }).eq("lead_id", lead_id).execute()
        except Exception as e:
            print(f"[Albert Tracker Error] _increment_message_count: {e}")

    def _update_last_active(self, lead_id: str) -> None:
        if not lead_id or lead_id == "unknown":
            return
        try:
            supabase.table("conversation_state").update({
                "last_active_at": datetime.now(timezone.utc).isoformat()
            }).eq("lead_id", lead_id).execute()
        except Exception as e:
            print(f"[Albert Tracker Error] _update_last_active: {e}")
