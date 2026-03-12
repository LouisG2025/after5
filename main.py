import logging
import sys
from fastapi import FastAPI
from app.webhook import router as webhook_router
from app.outbound import router as outbound_router
from app.calendly import router as calendly_router
from app.config import settings

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
logger.info("Application starting...")

app = FastAPI(title="After5 WhatsApp AI Agent", version="1.0.0")

app.include_router(webhook_router)
app.include_router(outbound_router)
app.include_router(calendly_router)

@app.get("/")
async def health():
    return {"status": "After5 Agent is running", "version": "1.0.1"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}
