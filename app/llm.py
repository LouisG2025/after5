import os
import time
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from app.config import settings
from app.tracker import AlbertTracker
from app.conversation_library import get_relevant_example
from app.signals import detect_objection_type
from app.redis_client import redis_client

tracker = AlbertTracker()

def _compute_scoring_status(session: dict, current_message: str) -> str:
    """
    V4: Keyword-based qualification gate.
    All three signals must be present before Albert is allowed to push for booking.
    """
    current_state = session.get('state', 'opening')

    if current_state == 'escalation':
        return 'escalate_to_human'

    all_text = ' '.join(
        [m['content'] for m in session.get('history', [])] + [current_message]
    ).lower()

    lead_gen_keywords = [
        'leads', 'enquiries', 'submissions', 'forms', 'ads', 'google', 'meta',
        'facebook', 'instagram', 'referrals', 'organic', 'inbound',
        'calls', 'per month', 'a month', 'a week'
    ]
    has_lead_gen = any(kw in all_text for kw in lead_gen_keywords)

    pain_keywords = [
        'slow', 'missing', 'losing', 'after hours', 'evenings', 'weekends', 'overnight',
        'manual', 'inconsistent', 'going cold', 'cold', 'no one', 'nobody',
        'not following up', 'struggling', 'problem', 'issue', 'gap',
        'nightmare', 'frustrating', 'bottleneck', 'missed', 'taking too long'
    ]
    has_pain = any(kw in all_text for kw in pain_keywords)

    engagement_keywords = [
        'how much', 'cost', 'price', 'how long', 'how does', 'how would', 'what would',
        'integration', 'crm', 'interested', 'looks good', 'sounds good',
        'makes sense', 'want to', 'book', 'call', 'yes', 'yeah', 'exactly'
    ]
    has_engagement = any(kw in all_text for kw in engagement_keywords)

    if has_lead_gen and has_pain and has_engagement:
        return 'push_for_booking'

    return 'continue_discovery'



class LLMClient:
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.helicone_key = settings.HELICONE_API_KEY

    def _get_client(self, lead_id: Optional[str], conversation_state: str, phone: str = "", company: str = "") -> AsyncOpenAI:
        """Helper to create a Helicone-instrumented OpenAI client."""
        # Coerce None values to empty strings — HTTP headers cannot be None
        safe_lead_id = lead_id or ""
        safe_phone = phone or ""
        safe_company = company or ""
        safe_state = conversation_state or "Opening"

        headers = {
            "HTTP-Referer": "https://after5.digital",
            "X-Title": "Albert by After5",
        }
        
        if self.helicone_key:
            headers.update({
                "Helicone-Auth": f"Bearer {self.helicone_key}",
                "Helicone-User-Id": safe_lead_id,
                "Helicone-Session-Id": f"conv_{safe_lead_id}",
                "Helicone-Property-Lead-Id": safe_lead_id,
                "Helicone-Property-Phone": safe_phone,
                "Helicone-Property-Company": safe_company,
                "Helicone-Property-State": safe_state,
                "Helicone-Property-Agent": "Albert",
                "Helicone-Property-Platform": "After5",
            })
            base_url = "https://openrouter.helicone.ai/api/v1"
        else:
            base_url = "https://openrouter.ai/api/v1"

        return AsyncOpenAI(
            base_url=base_url,
            api_key=self.api_key,
            default_headers=headers
        )

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimates USD cost based on token usage."""
        pricing = {
            "openai/gpt-4o":               {"prompt": 2.50,  "completion": 10.00},
            "openai/gpt-4o-mini":          {"prompt": 0.15,  "completion": 0.60},
            "anthropic/claude-3.5-sonnet": {"prompt": 3.00,  "completion": 15.00},
            "anthropic/claude-3-haiku":    {"prompt": 0.25,  "completion": 1.25},
        }
        # Default to gpt-4o rates if model not found
        rates = pricing.get(model, {"prompt": 2.50, "completion": 10.00})
        total = (prompt_tokens * rates["prompt"] + completion_tokens * rates["completion"]) / 1_000_000
        return round(total, 6)

    async def call_llm(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        lead_id: Optional[str] = None,
        conversation_state: str = "Opening",
        phone: str = "",
        company: str = "",
        **kwargs
    ) -> str:
        """Calls the configured LLM provider. Supports Gemini (free tier) and OpenRouter."""
        # Route to Gemini when configured — used for local dev because Gemini's
        # free tier is much more generous than OpenRouter's.
        if (settings.LLM_PROVIDER or "").lower() == "gemini" and settings.GEMINI_API_KEY:
            from app.gemini_client import gemini_chat
            system_prompt = ""
            conversation = []
            for m in messages:
                if m.get("role") == "system":
                    system_prompt += (m.get("content") or "") + "\n"
                else:
                    conversation.append(m)
            if not conversation or conversation[-1].get("role") != "user":
                # Gemini requires the last message to be from the user
                conversation.append({"role": "user", "content": "..."})
            try:
                reply = await gemini_chat(
                    system_prompt=system_prompt.strip() or "You are Albert, a British AI sales rep.",
                    messages=conversation,
                )
                print(f"[LLM] Gemini reply for {phone or 'unknown'} ({len(reply)} chars)")
                return reply
            except Exception as e:
                print(f"[LLM] Gemini failed, falling back to OpenRouter: {e}")

        model = model or settings.OPENROUTER_PRIMARY_MODEL
        client = self._get_client(lead_id, conversation_state, phone, company)
        
        start_time = time.time()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            latency_ms = int((time.time() - start_time) * 1000)
            
            content = response.choices[0].message.content
            usage = response.usage
            cost = self._estimate_cost(model, usage.prompt_tokens, usage.completion_tokens)

            # Log to Supabase Tracker
            await tracker.log_llm_call(
                lead_id=lead_id,
                response_id=response.id,
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                conversation_state=conversation_state,
            )
            
            return content

        except Exception as e:
            print(f"[LLM Error] {model} call failed: {e}")
            # Simple fallback if primary fails
            if model != settings.OPENROUTER_FALLBACK_MODEL:
                print(f"[LLM] Falling back to {settings.OPENROUTER_FALLBACK_MODEL}")
                return await self.call_llm(
                    messages, 
                    model=settings.OPENROUTER_FALLBACK_MODEL,
                    lead_id=lead_id,
                    conversation_state=conversation_state,
                    phone=phone,
                    company=company,
                    **kwargs
                )
            raise e

    async def build_context(self, session: Dict[str, Any], lead_data: Dict[str, Any], message: str, knowledge_context: str = "") -> List[Dict[str, str]]:
        """Builds the full LLM context using V4 system prompt + RAG."""
        # Always load static system prompt from file
        prompt_path = os.path.join(os.getcwd(), "prompts", "system_prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            core_prompt = f.read()
        industry_context = ""

        # 2. Dynamic Objection Injection
        objection_context = ""
        objection_map = {
            "price": "price.txt",
            "cost": "price.txt",
            "avoiding": "price_pressure.txt",
            "bad": "bad_experience.txt",
            "awful": "bad_experience.txt",
            "chatgpt": "tools_comparison.txt",
            "zapier": "tools_comparison.txt",
            "manychat": "tools_comparison.txt",
            "budget": "no_budget.txt",
            "work": "ai_failure_fear.txt",
            "sales team": "sales_team.txt",
            "business hours": "business_hours.txt",
            "weekends": "business_hours.txt",
            "case study": "proof.txt",
            "proof": "proof.txt",
            "setup": "setup_time.txt",
            "how long": "setup_time.txt",
            "crm": "crm.txt",
            "hubspot": "crm.txt",
            "ready": "ai_readiness.txt",
            "ai isn't": "ai_readiness.txt",
            "few months": "delayed_action.txt",
            "small business": "small_business.txt",
            "too good": "skepticism.txt",
            "wrong": "ai_errors.txt",
            "error": "ai_errors.txt",
            "not interested": "not_interested.txt",
            "manually": "manual_process.txt",
            "more information": "send_info.txt"
        }

        found_objections = []
        msg_lower = message.lower()
        for key, filename in objection_map.items():
            if key in msg_lower:
                path = os.path.join(os.getcwd(), "prompts", "objections", filename)
                if os.path.exists(path) and filename not in found_objections:
                    with open(path, "r", encoding="utf-8") as f:
                        objection_context += f.read() + "\n"
                    found_objections.append(filename)

        if objection_context:
            objection_context = "\n═══ OBJECTION HANDLING (DIAGNOSTIC) ═══\n" + objection_context

        # 3. Dynamic Example Injection (Phase 2)
        example_context = ""
        try:
            objection = detect_objection_type(message)

            example = await get_relevant_example(
                redis_client.redis,
                stage=session.get("state", "opening"),
                objection=objection,
            )
            
            if example:
                example_context = f"\n═══ REFERENCE CONVERSATION (LEARN FROM THIS TONE) ═══\n{example}\n"
        except Exception as e:
            print(f"[LLM] ❌ Error getting relevant example: {e}", flush=True)

        # Combine Core + Addons (Industry, Objections, Examples)
        system_prompt = core_prompt
        
        # Industry Injection
        if "{{DYNAMIC_KNOWLEDGE}}" in system_prompt:
            system_prompt = system_prompt.replace("{{DYNAMIC_KNOWLEDGE}}", industry_context)
        elif industry_context:
            system_prompt += f"\n\n{industry_context}"
            
        # Objection Injection
        if "{{DYNAMIC_OBJECTIONS}}" in system_prompt:
            system_prompt = system_prompt.replace("{{DYNAMIC_OBJECTIONS}}", objection_context)
        elif objection_context:
            system_prompt += f"\n\n{objection_context}"
            
        # Example Injection
        if "{{DYNAMIC_EXAMPLES}}" in system_prompt:
            system_prompt = system_prompt.replace("{{DYNAMIC_EXAMPLES}}", example_context)
        elif example_context:
            system_prompt += f"\n\n{example_context}"

        # Inject RAG context if available (Standard RAG)
        if knowledge_context:
            rag_block = f"\n\n### KNOWLEDGE BASE CONTEXT (USE THIS TO ANSWER DISCOVERY QUESTIONS):\n{knowledge_context}\n\n"
            system_prompt = rag_block + system_prompt

        # Replace placeholders
        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Format conversation history
        history = session.get("history", [])
        if history:
            history_lines = []
            for msg in history:
                role_label = "Lead" if msg["role"] == "user" else "Albert"
                history_lines.append(f"{role_label}: {msg['content']}")
            formatted_history = "\n".join(history_lines)
        else:
            formatted_history = "(no conversation yet)"

        # V4: keyword-based scoring_status — inspects conversation history for qualification signals
        current_state_val = session.get("state", "opening")
        scoring_status = _compute_scoring_status(session, message)

        replacements = {
            "{{lead_name}}": lead_data.get("name", lead_data.get("first_name", "there")),
            "{{lead_company}}": lead_data.get("company", "your company"),
            "{{lead_company_summary}}": lead_data.get("form_message", ""),
            "{{current_state}}": current_state_val,
            "{{scoring_status}}": scoring_status,
            "{{calendly_link}}": settings.CALENDLY_LINK,
            "{{bant_scores}}": str(session.get("bant_scores", {})),
            "{{current_datetime}}": current_datetime,
            "{{conversation_history}}": formatted_history,
        }
        
        for key, value in replacements.items():
            system_prompt = system_prompt.replace(key, str(value))

        messages = [{"role": "system", "content": system_prompt}]
        history = session.get("history", [])

        # Token budget guard: estimate total tokens and trim oldest history
        # if we're approaching the limit. 1 token ≈ 4 chars is a safe estimate.
        MAX_TOKENS = 100_000  # safe limit for Claude Sonnet / GPT-4o
        system_tokens = len(system_prompt) // 4
        message_tokens = len(message) // 4
        available_for_history = MAX_TOKENS - system_tokens - message_tokens - 500  # 500 buffer

        # Trim from the oldest if history is too large
        history_tokens = sum(len(m.get("content", "")) // 4 for m in history)
        if history_tokens > available_for_history:
            trimmed = 0
            while history and history_tokens > available_for_history:
                removed = history.pop(0)
                history_tokens -= len(removed.get("content", "")) // 4
                trimmed += 1
            if trimmed:
                print(f"[LLM] ⚠️ Trimmed {trimmed} oldest messages from history (token budget)", flush=True)

        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": message})

        return messages

llm_client = LLMClient()
