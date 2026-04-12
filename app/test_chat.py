"""
LOCAL TEST CHAT ENDPOINT
Provides a simple chat interface to test Albert in the browser without WhatsApp.

Endpoints:
  GET  /test-chat-ui   → Serves the HTML chat simulator
  POST /test-chat      → Accepts a message, returns Albert's reply
  POST /test-chat/reset → Clears the test session

This is a DEV-ONLY tool. Not used in production.
"""
import logging
import re
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.llm import LLMClient
from app.config import settings
from app.gemini_client import gemini_chat


# ---------- Output sanitizer (enforces brief tone rules) ----------
# Brief says:
#   - Max 3 chunks
#   - No dashes (em, en, hyphen, double hyphen)
#   - No emojis
#   - Drop the full stop on the last sentence
#   - Casual British, no corporate phrases
#   - Never wrap replies in quotes
# Some free LLMs are sloppy with these rules so we enforce them here.

_BANNED_PHRASES = [
    "let me know",
    "i appreciate your interest",
    "great question",
    "i completely understand",
]


_URL_RE = re.compile(r"https?://[^\s\]|<>\"']+", re.IGNORECASE)


def _normalize_urls(text: str) -> str:
    """
    Any URL in Albert's output gets replaced with the canonical Calendly link.
    Albert should only ever send the Calendly link. If the LLM hallucinates a
    different URL, or picks up a stale one from the prompt, force it to the
    value configured in .env.
    """
    canonical = settings.CALENDLY_LINK or "https://calendly.com/after5-louis/15min"
    return _URL_RE.sub(canonical, text)


def clean_llm_output(raw: str) -> List[str]:
    """
    Turn a raw LLM string into up-to-3 clean WhatsApp-style chunks.
    Strips quotes, dashes, trailing marker fragments, placeholders, and enforces the cap.
    Normalises any URL to the canonical Calendly link (safety net against hallucinations).
    """
    if not raw:
        return []

    text = raw.strip()
    text = _normalize_urls(text)

    # Strip any leaked template placeholders (the LLM sometimes echoes them)
    text = re.sub(r"\{\{\s*[a-zA-Z_]+\s*\}\}", "", text)
    # Collapse resulting whitespace + stray commas (", ," or ",  ")
    text = re.sub(r"\s*,\s*,", ",", text)
    text = re.sub(r"\s{2,}", " ", text)

    # Strip internal control markers that leak from the 40KB system prompt
    text = re.sub(r"\[NO_REPLY\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[END\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[CHUNK\]", "|||", text, flags=re.IGNORECASE)
    text = re.sub(r"\[LINK_ALREADY_SENT\]", "", text, flags=re.IGNORECASE)

    # Strip leading/trailing chunk-separator fragments
    text = re.sub(r"^[|>\s]+", "", text)
    text = re.sub(r"[|>\s]+$", "", text)

    # Some models use > as a chunk separator — normalise to |||
    text = text.replace(">|||", "|||").replace("|||>", "|||")
    text = re.sub(r"\s*>\s*", "|||", text)

    # Normalise stray pipe counts → |||
    text = re.sub(r"\|{2,}", "|||", text)

    # Split on the canonical separator
    parts = [p.strip() for p in text.split("|||") if p.strip()]
    if not parts:
        parts = [text]

    cleaned: List[str] = []
    for p in parts:
        # Strip wrapping quotes (straight and curly)
        p = re.sub(r'^["""\'«»]+|["""\'«»]+$', "", p).strip()

        # Remove leaked markers inside the body
        p = p.replace("|||", " ").replace("||", " ")

        # Strip dashes used as punctuation (em, en, spaced hyphen, double hyphen)
        p = p.replace("—", ",").replace("–", ",")
        p = re.sub(r"\s+-+\s+", ", ", p)
        p = p.replace("--", ",")

        # Strip markdown markers
        p = p.replace("**", "").replace("*", "").replace("`", "")

        # Collapse whitespace
        p = re.sub(r"\s+", " ", p).strip()

        # Drop trailing full stop
        if p.endswith("."):
            p = p[:-1].strip()

        # Filter banned corporate phrases
        p_lower = p.lower()
        for banned in _BANNED_PHRASES:
            if banned in p_lower:
                idx = p_lower.find(banned)
                p = (p[:idx] + p[idx + len(banned):]).strip(" ,.")
                p_lower = p.lower()

        # Filter out stray leftover placeholders-as-words
        for ph in ("lead_name", "lead_company", "lead_industry", "calendly_link"):
            p = p.replace(ph, "").replace(f"{{{ph}}}", "")
        p = re.sub(r"\s{2,}", " ", p).strip()

        # HARD LIMIT: max 2 sentences per bubble (brief rule)
        # Preserve URLs: if the chunk is just a URL, keep it whole
        if not _looks_like_url(p):
            sentences = _split_sentences(p)
            if len(sentences) > 2:
                p = " ".join(sentences[:2]).strip()
                if p.endswith("."):
                    p = p[:-1]

        if p:
            cleaned.append(p)

    # Hard cap at 3 chunks
    if len(cleaned) > 3:
        cleaned = cleaned[:2] + [" ".join(cleaned[2:])]

    return cleaned or ["hey, mind saying that again"]


def _looks_like_url(text: str) -> bool:
    return bool(re.match(r"^https?://\S+$", text.strip()))


def _split_sentences(text: str) -> List[str]:
    """Simple sentence split on .?! followed by whitespace or end."""
    # Also split on ";" because LLMs love semicolons
    text = text.replace(";", ".")
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _inject_placeholders(prompt: str) -> str:
    """Replace Louis's {{template_vars}} with sensible defaults for test chat."""
    replacements = {
        "{{lead_name}}": "there",
        "{{lead_company}}": "your business",
        "{{lead_industry}}": "your industry",
        "{{lead_company_summary}}": "",
        "{{current_state}}": "Opening",
        "{{scoring_status}}": "discovering",
        "{{calendly_link}}": settings.CALENDLY_LINK or "https://calendly.com/after5-louis/15min",
        "{{bant_scores}}": "",
        "{{conversation_history}}": "",
        "{{current_datetime}}": "",
    }
    for k, v in replacements.items():
        prompt = prompt.replace(k, v)
    return prompt


# Hard rules block appended to the LLM system prompt every call.
# Using very direct language because free models often ignore subtle guidance.
TONE_HARD_RULES = """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL OUTPUT RULES - YOU MUST FOLLOW THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. NEVER wrap your reply in quotation marks. Output plain text only.
2. ONE question per reply. NEVER stack 2 questions. NEVER ask follow-ups in the same reply.
3. MAXIMUM 2 sentences per reply. Shorter is better.
4. NO dashes of any kind. Not em dash, en dash, hyphen used as punctuation, or double hyphen. Use commas instead.
5. NO full stops on the last sentence. End clean.
6. NO emojis. Ever.
7. NO corporate phrases: never say "let me know", "I appreciate", "great question", "I completely understand".
8. British casual tone only. Contractions always (it's, we're, don't, you're). Natural words (yeah, fair enough, makes sense, nice one, gotcha).
9. Lowercase after commas. Keep it chatty, not formal.
10. To split into multiple bubbles, use ||| between them. Max 3 bubbles total. Only use ||| when you're sending a link or two genuinely separate thoughts.

OUTPUT FORMAT:
- Plain text, no quotes
- 1 to 2 sentences
- 1 question maximum
- No trailing punctuation on final sentence
- No dashes
"""

logger = logging.getLogger(__name__)
router = APIRouter(tags=["test-chat"])

# In-memory session store keyed by phone (no Redis needed for testing)
_test_sessions: Dict[str, List[Dict[str, str]]] = {}

llm_client = LLMClient()


class ChatRequest(BaseModel):
    phone: str = "test-user"
    message: str


class ChatResponse(BaseModel):
    reply: str
    mode: str  # "real" or "demo"
    chunks: List[str]


# ---------- Canned fallback responses (demo mode) -----------------
# The UI shows the opener hardcoded client-side, so the demo flow starts
# from Albert's FIRST reply to the user (not the opener itself).
OPENER = "Hey mate, Albert here from After5 Digital, saw you filled the form, what do you do"

DEMO_FLOW = [
    # Reply 1 — discover
    "Nice one, and how are you getting your leads at the moment",
    # Reply 2 — dig deeper
    "Fair enough, and where's the biggest drop off for you, is it response time or chasing them up",
    # Reply 3 — surface pain
    "Yeah that's the bit that kills most businesses, you're losing hot leads because no one's there at 9pm",
    # Reply 4 — normalise and build rapport
    "Makes sense, most agencies we work with have the same problem, it's why Albert exists",
    # Reply 5 — book (chunked: statement + Calendly link as its own bubble)
    "Quickest way is to jump on a 15 minute call with Louis, he'll walk you through exactly how we'd set it up for you|||https://calendly.com/after5-louis/15min",
    # Reply 6+ — holding pattern after link sent
    "No rush, just hit the link when you've got a sec",
]


def _demo_reply(phone: str, _message: str) -> List[str]:
    """Return next scripted reply based on how many user messages have arrived."""
    session = _test_sessions.setdefault(phone, [])
    user_turns = len([m for m in session if m["role"] == "user"])
    # user_turns includes the current incoming message (we append BEFORE calling this)
    # so index = user_turns - 1
    idx = min(user_turns - 1, len(DEMO_FLOW) - 1)
    reply = DEMO_FLOW[idx] if idx >= 0 else DEMO_FLOW[0]
    # Split on ||| so the Calendly link lands in its own bubble
    return [c.strip() for c in reply.split("|||") if c.strip()]


# ---------- Routes -----------------------------------------------
@router.post("/test-chat", response_model=ChatResponse)
async def test_chat(req: ChatRequest):
    """Accept a user message, return Albert's reply."""
    session = _test_sessions.setdefault(req.phone, [])
    session.append({"role": "user", "content": req.message})

    mode = "demo"
    chunks: List[str] = []

    has_gemini = bool(settings.GEMINI_API_KEY)
    has_openrouter = (
        settings.OPENROUTER_API_KEY
        and not settings.OPENROUTER_API_KEY.lower().startswith("sk-or-dummy")
    )

    system_prompt = _inject_placeholders(_load_system_prompt()) + TONE_HARD_RULES

    # Try Gemini first (best free quality + generous rate limits),
    # fall back to OpenRouter, then finally demo mode.
    raw = None
    if has_gemini and settings.LLM_PROVIDER.lower() == "gemini":
        try:
            raw = await gemini_chat(system_prompt=system_prompt, messages=list(session))
            mode = "real"
            logger.info(f"[test-chat] Gemini reply for {req.phone}")
        except Exception as e:
            logger.warning(f"[test-chat] Gemini failed, trying OpenRouter: {e}")

    if raw is None and has_openrouter:
        try:
            messages = [{"role": "system", "content": system_prompt}] + session
            raw = await llm_client.call_llm(
                messages=messages,
                conversation_state="Opening",
                phone=req.phone,
            )
            mode = "real"
        except Exception as e:
            logger.warning(f"[test-chat] OpenRouter failed, using demo mode: {e}")

    if raw is not None:
        # Run through the sanitizer: strips quotes, enforces tone, caps at 3 chunks
        chunks = clean_llm_output(raw)
    else:
        chunks = _demo_reply(req.phone, req.message)

    # Record assistant reply in session
    session.append({"role": "assistant", "content": " ".join(chunks)})

    return ChatResponse(reply=" ".join(chunks), mode=mode, chunks=chunks)


@router.post("/test-chat/reset")
async def test_chat_reset(phone: str = "test-user"):
    """Clear a test session."""
    _test_sessions.pop(phone, None)
    return {"status": "reset", "phone": phone}


@router.get("/test-chat-ui", response_class=HTMLResponse)
async def test_chat_ui():
    """Serve the HTML chat simulator."""
    html_path = Path(__file__).parent / "test_chat_ui.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


def _load_system_prompt() -> str:
    """Load Albert's system prompt for real LLM calls."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "You are Albert, a British AI sales rep for After5 Digital. Be casual, sharp, confident. Short messages, contractions, no emojis, no dashes, no corporate speak."
