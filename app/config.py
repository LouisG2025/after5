from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import os

class Settings(BaseSettings):
    # MessageBird / Bird
    MESSAGEBIRD_API_KEY: str = os.getenv("MESSAGEBIRD_API_KEY", "")
    MESSAGEBIRD_WORKSPACE_ID: str = os.getenv("MESSAGEBIRD_WORKSPACE_ID", "")
    MESSAGEBIRD_CHANNEL_ID: str = os.getenv("MESSAGEBIRD_CHANNEL_ID", "")
    MESSAGEBIRD_WHATSAPP_NUMBER: str = ""  # for reference only


    # WhatsApp Cloud API (Meta)
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "after5_verify_token")
    WHATSAPP_API_VERSION: str = os.getenv("WHATSAPP_API_VERSION", "v21.0")
    MESSAGING_PROVIDER: str = os.getenv("MESSAGING_PROVIDER", "baileys")  # "baileys" | "whatsapp_cloud" | "messagebird"

    # Baileys (local Node service for QR-paired WhatsApp)
    BAILEYS_SERVICE_URL: str = os.getenv("BAILEYS_SERVICE_URL", "http://localhost:3001")
    # Comma-separated allowlist of phone numbers. When set, Albert only replies
    # to numbers in this list (safety for testing on a personal WhatsApp).
    # Numbers can be with or without '+', country code, or spaces — we strip to digits.
    # Leave empty to allow everyone (production behaviour).
    BAILEYS_ALLOWED_PHONES: str = os.getenv("BAILEYS_ALLOWED_PHONES", "")
    # Comma-separated allowlist of WhatsApp display names (pushName). Used as a
    # fallback when WhatsApp sends the message via an anonymised @lid that
    # can't be resolved to a real phone. Case-insensitive, partial match
    # against the inbound name. Empty = no name-based check.
    BAILEYS_ALLOWED_NAMES: str = os.getenv("BAILEYS_ALLOWED_NAMES", "")

    # OpenRouter
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_PRIMARY_MODEL: str = "anthropic/claude-sonnet-4-5"
    OPENROUTER_FALLBACK_MODEL: str = "openai/gpt-4o"
    OPENROUTER_BANT_MODEL: str = "openai/gpt-4o-mini"

    # Google Gemini (free tier primary)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openrouter")  # "gemini" | "openrouter"

    # Redis
    REDIS_URL: str

    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: str

    # Helicone (optional)
    HELICONE_API_KEY: Optional[str] = None

    # Calendly
    CALENDLY_LINK: str = "https://calendly.com/after5/free-discovery-call"

    # App
    DEBUG: bool = False
    # Input buffer settings (Brief spec: 5s silence window, 25s hard max)
    INPUT_BUFFER_SECONDS: float = 5.0
    INPUT_BUFFER_MAX_SECONDS: float = 25.0
    MAX_INTERRUPT_RETRIES: int = 2

    # Low content spam threshold (Master Prompt Fix 4)
    LOW_CONTENT_THRESHOLD: int = 3
    TYPING_DELAY_PER_CHAR: float = 0.1  # V4: 0.1s per char (600 CPM)
    CHUNK_DELAY_SECONDS: float = 1.5
    MAX_FOLLOWUPS: int = 3  # V4: up to 3 follow-ups
    MAX_CHUNKS: int = 3

    # OpenAI / Whisper
    OPENAI_API_KEY: str = ""
    VOICE_NOTE_ACKNOWLEDGE: bool = True
    VOICE_NOTE_ACK_MESSAGE: str = "" # "Got your voice note, let me listen..."

    # Human-like Behavior
    MARK_AS_READ_DELAY: float = 2.0
    SHOW_TYPING_INDICATOR: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings():
    s = Settings()
    print(f"[Config] 🛠️ Active Messaging Provider: {s.MESSAGING_PROVIDER}", flush=True)
    return s

settings = get_settings()
