"""API key authentication dependency for protected endpoints."""
import logging
from fastapi import Header, HTTPException
from app.config import settings

logger = logging.getLogger(__name__)


async def require_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """Validate X-API-Key header. Skips validation if AFTER5_API_KEY is not set (dev mode)."""
    expected = settings.AFTER5_API_KEY
    if not expected:
        return  # No key configured = dev mode, allow all
    if not x_api_key or x_api_key != expected:
        logger.warning("Rejected request with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")
