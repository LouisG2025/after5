import logging
import io
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"


async def download_audio(audio_url: str) -> bytes | None:
    """
    Download audio file from MessageBird media URL.
    
    MessageBird media URLs that start with media.messagebird.com 
    do NOT require authentication. Other MessageBird-hosted media
    may need the AccessKey header.
    
    Args:
        audio_url: URL of the audio file from MessageBird webhook
    
    Returns:
        Audio file bytes or None on error
    """
    try:
        headers = {}
        # Add MessageBird auth for non-public media URLs
        if "media.messagebird.com" not in audio_url:
            headers["Authorization"] = f"AccessKey {settings.MESSAGEBIRD_API_KEY}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(audio_url, headers=headers)
            
            if response.status_code == 200:
                logger.info(f"Audio downloaded: {len(response.content)} bytes")
                return response.content
            else:
                logger.error(f"Audio download failed: {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"Audio download error: {e}")
        return None


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """
    Transcribe audio using OpenAI Whisper API.
    
    Args:
        audio_bytes: Raw audio file bytes (OGG Opus from WhatsApp)
        filename: Filename hint for Whisper (helps with format detection)
    
    Returns:
        Transcribed text or None on error
    """
    if not settings.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set — cannot transcribe voice notes")
        return None
    
    try:
        # Whisper API expects multipart/form-data with file upload
        files = {
            "file": (filename, io.BytesIO(audio_bytes), "audio/ogg"),
        }
        data = {
            "model": "whisper-1",
            "language": "en",  # Optimize for English. Remove for auto-detect.
        }
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                WHISPER_URL,
                headers=headers,
                files=files,
                data=data,
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "").strip()
                logger.info(f"Transcription result: {text[:100]}...")
                return text if text else None
            else:
                logger.error(f"Whisper API error: {response.status_code} — {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return None


async def process_voice_note(audio_url: str) -> str | None:
    """
    Full pipeline: download audio → transcribe → return text.
    
    This is the main function to call from webhook.py.
    
    Args:
        audio_url: URL of the audio file from MessageBird webhook
    
    Returns:
        Transcribed text or None if transcription failed
    """
    # Step 1: Download audio
    audio_bytes = await download_audio(audio_url)
    if not audio_bytes:
        logger.error("Failed to download voice note audio")
        return None
    
    # Step 2: Transcribe
    text = await transcribe_audio(audio_bytes)
    if not text:
        logger.error("Failed to transcribe voice note")
        return None
    
    logger.info(f"Voice note transcribed successfully: {text[:50]}...")
    return text
