# After5 WhatsApp AI Agent

This is a complete WhatsApp AI sales agent project for After5 Digital.

## Features
1. Receives incoming WhatsApp messages via Baileys (QR-paired) or WhatsApp Cloud API webhook.
2. Manages conversation state (Opening → Discovery → Qualification → Booking → Escalation).
3. Calls an LLM via OpenRouter to generate natural responses.
4. Sends replies back through Baileys or WhatsApp Cloud API.
5. Extracts BANT scores (Budget, Authority, Need, Timeline) in the background.
6. Tracks everything in Supabase.
7. Uses Redis for session state and conversation memory.
8. Supports message chunking (splitting long replies into multiple WhatsApp messages with delays).
9. Supports input buffering (waits for user to stop typing before replying).
10. Fires typing indicator before every reply.

## Tech Stack
- Python 3.11
- FastAPI (async)
- Baileys (QR-paired WhatsApp via local Node bridge) for demo/development
- WhatsApp Cloud API (official Meta API) for production deployments
- OpenRouter for LLM calls (supports Claude, GPT-4o, Gemini, etc.)
- Redis for session state, conversation history, dedup, and input buffering
- Supabase for persistent storage (leads, messages, status)
- Helicone for LLM observability (optional proxy)
- Deployed on AWS

## Quick Start
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`.
3. Set your environment variables (see `.env.example`).
4. Run the app: `uvicorn main:app --reload`.

## Environment Variables
Check `.env.example` for the full list of required variables.

## API Endpoints
- `GET /`: Health check.
- `POST /baileys/incoming`: Baileys webhook handler for incoming messages.
- `POST /webhook`: WhatsApp Cloud API webhook handler.
- `POST /send-outbound`: Outbound message sender.
- `POST /form-webhook`: For n8n/website form submissions.
- `POST /calendly-webhook`: Calendly booking confirmation webhook.

## Architecture Overview
1.  **Webhook**: Incoming message is received (Baileys or Cloud API).
2.  **Buffering**: Input is buffered in Redis (5s silence window) to handle multiple messages.
3.  **Processing**: Conversation engine is triggered after buffer timeout.
4.  **LLM Call**: Context is built and OpenRouter is called.
5.  **Chunking**: Response is split into multiple messages if needed.
6.  **Delivery**: Messages are sent via Baileys/Cloud API with human-like timing (reading delay, typing indicator, review pause).
7.  **BANT Extraction**: Qualification signals are extracted in the background.
8.  **Logging**: Everything is saved to Supabase for persistent tracking.

## Background Scheduler
A built-in follow-up scheduler runs automatically when the app starts (no external cron needed):
- Checks every hour for leads in Discovery/Qualification/Booking state who went quiet for 24+ hours.
- Sends a single nudge message per lead.
- Tracked in Redis to prevent duplicate follow-ups.
- Code: `app/scheduler.py`, started in `main.py` via `asyncio.create_task(run_scheduler())`.

## Demo Protection
- **Message limit**: After 20 messages with no booking, Albert sends a graceful exit and closes the session.
- **Phone cooldown**: If a phone number has already completed a full conversation (CLOSED/CONFIRMED), repeat form submissions are blocked.
