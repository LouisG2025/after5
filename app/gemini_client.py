"""
Google Gemini Client
====================
Thin async wrapper around google-generativeai for Albert's dev testing.
Uses the generous Gemini free tier (1500 req/day) which is much more
reliable than OpenRouter free tier during development.

Usage:
    from app.gemini_client import gemini_chat
    reply = await gemini_chat(
        system_prompt="You are Albert, a British sales rep...",
        history=[
            {"role": "user", "content": "hey"},
            {"role": "assistant", "content": "nice one, what's your business"},
        ],
        user_message="we run a law firm",
    )
"""
import logging
from typing import List, Dict

import google.generativeai as genai

from app.config import settings

logger = logging.getLogger(__name__)

# Configure the SDK once at import time. Safe to call repeatedly.
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)


def _to_gemini_history(messages: List[Dict[str, str]]) -> List[Dict]:
    """
    Convert OpenAI-style messages into Gemini's history format.

    OpenAI: [{"role": "user"/"assistant", "content": "..."}]
    Gemini: [{"role": "user"/"model", "parts": ["..."]}]

    Gemini requires alternating user/model turns. We skip any "system" roles
    (those should go into system_instruction separately).
    """
    history = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if not content:
            continue
        if role == "system":
            continue  # handled separately as system_instruction
        gemini_role = "model" if role == "assistant" else "user"
        history.append({"role": gemini_role, "parts": [content]})
    return history


async def gemini_chat(
    system_prompt: str,
    messages: List[Dict[str, str]],
    model: str | None = None,
    temperature: float = 0.8,
    max_output_tokens: int = 500,
) -> str:
    """
    Send an OpenAI-style conversation to Gemini and return the reply text.

    Parameters:
        system_prompt: Albert's system instructions (the 40KB prompt).
        messages: Full message history including the latest user turn.
                  Format: [{"role": "user"/"assistant", "content": "..."}]
        model: Optional override for the Gemini model name.
        temperature: Sampling temperature (higher = more varied replies).
        max_output_tokens: Hard cap on reply length.

    Returns:
        The raw text of Gemini's reply.

    Raises:
        Exception on API error. Caller decides whether to fall back.
    """
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")

    model_name = model or settings.GEMINI_MODEL or "gemini-flash-lite-latest"

    # Pull the last user message off the end — that's what we "send",
    # the rest becomes the chat history.
    history_msgs = list(messages)
    if not history_msgs or history_msgs[-1].get("role") != "user":
        raise ValueError("Last message must be from the user")

    last_user_message = history_msgs.pop()["content"]
    gemini_history = _to_gemini_history(history_msgs)

    # Gemma models don't support system_instruction — they need it prepended
    # to the first user message instead.
    is_gemma = "gemma" in model_name.lower()

    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    if is_gemma:
        model_obj = genai.GenerativeModel(
            model_name=model_name,
            generation_config=generation_config,
        )
        # Prepend the system prompt to the last user message
        combined_user_message = f"{system_prompt}\n\n---\nUser: {last_user_message}"
        chat = model_obj.start_chat(history=gemini_history)
        response = await chat.send_message_async(combined_user_message)
    else:
        model_obj = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            generation_config=generation_config,
        )
        chat = model_obj.start_chat(history=gemini_history)
        response = await chat.send_message_async(last_user_message)

    text = (response.text or "").strip()
    logger.info(f"[Gemini] {model_name} → {len(text)} chars")
    return text
