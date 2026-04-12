# Baileys Bridge

Tiny Node.js service that connects **WhatsApp** to the **Python FastAPI** backend.

## Why

The Python app is Albert's brain. This service is Albert's mouth/ears on WhatsApp.
We use Baileys because it pairs with WhatsApp via **QR code** (same trick as WhatsApp Web),
which means we don't need Meta approval, a business account, or any fees. Free to test.

## How to Run

```bash
cd baileys
npm install
npm start
```

On first run, a QR code will print in the terminal. Scan it from your phone:

> **WhatsApp → Settings → Linked Devices → Link a Device → scan the QR**

The session is cached in `./auth_info_baileys/` — so you only need to scan once.
If you need to re-pair, delete that folder and restart.

## Ports / URLs

| What | URL |
|---|---|
| This service (HTTP API) | `http://localhost:3001` |
| Python backend (expected) | `http://localhost:8000` |

## Environment Variables (optional)

| Variable | Default | Purpose |
|---|---|---|
| `BAILEYS_PORT` | `3001` | Port this service listens on |
| `PYTHON_BACKEND_URL` | `http://127.0.0.1:8000` | Where to forward incoming messages |
| `LOG_LEVEL` | `info` | `debug` \| `info` \| `warn` \| `error` |

## Endpoints

Used by the Python backend:

- `GET  /health` — Check if WhatsApp is connected
- `POST /send` — Send a text message `{phone, text}`
- `POST /typing` — Show typing indicator `{phone, state}`
- `POST /read` — Mark as read `{phone, message_id}`

Inbound messages are forwarded to:
- `POST http://localhost:8000/baileys/incoming` with `{phone, name, text, message_id, timestamp}`

## Testing

Message the paired number from another WhatsApp account. You should see:
1. The message logged in this terminal
2. Python backend receiving it
3. Albert replying back within the buffer window

## Disconnecting

To unlink and safely shut down, either:
- Delete `./auth_info_baileys/` and restart, OR
- On your phone: WhatsApp → Settings → Linked Devices → tap the bot → Log out
