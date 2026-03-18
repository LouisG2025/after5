import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.webhook import router as webhook_router
from app.outbound import router as outbound_router
from app.calendly import router as calendly_router
from app.training_api import router as training_router
from app.config import settings

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stdout
)
from app.conversation_library import load_conversation_library
from app.redis_client import redis_client

logger = logging.getLogger(__name__)
logger.info("Application starting...")

app = FastAPI(title="After5 WhatsApp AI Agent", version="1.0.0")

@app.on_event("startup")
async def startup():
    logger.info("Running startup tasks...")
    await load_conversation_library(redis_client.redis)

# Allow CORS for the frontend dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (standard for development/admin dashboard)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(outbound_router)
app.include_router(calendly_router)
app.include_router(training_router)

@app.get("/")
async def health():
    return {"status": "After5 Agent is running", "version": "1.0.1"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}
