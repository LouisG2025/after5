/**
 * After5 Baileys Bridge
 * =====================
 * Connects WhatsApp (via QR pairing) to the Python FastAPI backend.
 *
 * Inbound flow:
 *   WhatsApp → Baileys socket → POST http://localhost:8000/baileys/incoming
 *
 * Outbound flow:
 *   Python → POST http://localhost:3001/send → Baileys socket → WhatsApp
 *
 * Run:
 *   cd baileys && npm install && npm start
 *
 * First run: a QR code will be printed in the terminal.
 * Scan it from your phone:
 *   WhatsApp → Settings → Linked Devices → Link a Device → scan QR
 *
 * The session is cached in ./auth_info_baileys/ so you only scan once.
 */

import pkg from "@whiskeysockets/baileys";
const {
  makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  makeInMemoryStore,
} = pkg;
import pino from "pino";
import qrcode from "qrcode-terminal";
import QRCode from "qrcode";
import express from "express";
import axios from "axios";
import fs from "fs";

// ---------- Telegram Monitor Config --------------------------------
const TG_BOT_TOKEN = process.env.TG_BOT_TOKEN || "8586385838:AAH13TyUdO0T7A3xqgusR-DiDkQyS08zV5s";
const TG_CHAT_IDS = (process.env.TG_CHAT_IDS || "7368644660").split(",").map(s => s.trim());

async function sendTelegramMessage(text) {
  for (const chatId of TG_CHAT_IDS) {
    try {
      await axios.post(`https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage`, {
        chat_id: chatId, text, parse_mode: "HTML",
      });
    } catch (e) { console.error(`[TG] Failed to send message to ${chatId}: ${e.message}`); }
  }
}

async function sendTelegramQR(qrDataUrl) {
  // Convert QR data URL to buffer
  const base64 = qrDataUrl.replace(/^data:image\/png;base64,/, "");
  const buffer = Buffer.from(base64, "base64");
  const tmpPath = "/tmp/baileys_qr.png";
  fs.writeFileSync(tmpPath, buffer);

  // Send QR image via Telegram's base64 method (no form-data needed)
  for (const chatId of TG_CHAT_IDS) {
    try {
      // Read the file and send as multipart using axios
      const fileData = fs.readFileSync(tmpPath);
      const boundary = "----TelegramQR" + Date.now();
      const caption = "📱 Scan this QR code in WhatsApp → Settings → Linked Devices → Link a Device";

      const body = Buffer.concat([
        Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n${chatId}\r\n`),
        Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n${caption}\r\n`),
        Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="photo"; filename="qr.png"\r\nContent-Type: image/png\r\n\r\n`),
        fileData,
        Buffer.from(`\r\n--${boundary}--\r\n`),
      ]);

      await axios.post(`https://api.telegram.org/bot${TG_BOT_TOKEN}/sendPhoto`, body, {
        headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` },
        maxContentLength: Infinity,
      });
    } catch (e) { console.error(`[TG] Failed to send QR to ${chatId}: ${e.message}`); }
  }
}

// ---------- Failed Message Queue (auto-retry on reconnect) ---------
const FAILED_QUEUE_FILE = "./failed_messages.json";
let failedQueue = [];

function loadFailedQueue() {
  try {
    if (fs.existsSync(FAILED_QUEUE_FILE)) {
      failedQueue = JSON.parse(fs.readFileSync(FAILED_QUEUE_FILE, "utf8"));
    }
  } catch (e) { failedQueue = []; }
}

function saveFailedQueue() {
  try { fs.writeFileSync(FAILED_QUEUE_FILE, JSON.stringify(failedQueue)); } catch (e) {}
}

function queueFailedMessage(phone, text) {
  failedQueue.push({ phone, text, ts: Date.now() });
  saveFailedQueue();
  console.log(`[Queue] Queued failed message for ${phone} (${failedQueue.length} pending)`);
}

async function retryFailedMessages() {
  if (!failedQueue.length || !sock?.user) return;
  const toRetry = [...failedQueue];
  failedQueue = [];
  saveFailedQueue();
  console.log(`[Queue] Retrying ${toRetry.length} failed message(s)...`);

  let sent = 0, failed = 0;
  for (const msg of toRetry) {
    // Skip messages older than 24 hours
    if (Date.now() - msg.ts > 86400000) { failed++; continue; }
    try {
      const jid = toJid(msg.phone);
      await sock.sendMessage(jid, { text: msg.text });
      sent++;
      // Small delay between retries to avoid rate limiting
      await new Promise(r => setTimeout(r, 2000));
    } catch (e) {
      failedQueue.push(msg);
      failed++;
    }
  }
  saveFailedQueue();
  if (sent > 0) {
    console.log(`[Queue] Retried: ${sent} sent, ${failed} failed`);
    await sendTelegramMessage(`✅ Auto-retried ${sent} queued message(s) that failed during downtime.${failed > 0 ? ` ${failed} still failed.` : ""}`);
  }
}

loadFailedQueue();

// ---------- Config -----------------------------------------------
const PORT = Number(process.env.BAILEYS_PORT || 3001);
const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL || "http://127.0.0.1:8000";
const PYTHON_WEBHOOK_PATH = "/baileys/incoming";
const AUTH_FOLDER = "./auth_info_baileys";

const logger = pino({
  level: process.env.LOG_LEVEL || "info",
  transport: {
    target: "pino/file",
    options: { destination: 1 }, // stdout
  },
});

// ---------- Baileys socket ---------------------------------------
let sock = null;

// In-memory store for message retry and session management
const store = makeInMemoryStore({ logger: pino({ level: "silent" }) });
store.readFromFile("./baileys_store.json");
setInterval(() => store.writeToFile("./baileys_store.json"), 30_000);

// Message cache for retry requests (fixes "waiting for this message")
const msgRetryCache = new Map();

// Map: phoneDigits → original JID (e.g. "72666702676122" → "72666702676122@lid")
// We store this on every inbound message so outbound replies go back to the
// same JID, including for anonymised @lid chats where there's no real phone.
const jidByPhone = new Map();

// Bidirectional LID ↔ real phone mapping (persisted to disk)
const LID_MAP_FILE = "./lid_phone_map.json";
const lidToPhone = new Map(); // lidDigits → realPhoneDigits
const phoneToLid = new Map(); // realPhoneDigits → lidDigits

function loadLidMap() {
  try {
    if (fs.existsSync(LID_MAP_FILE)) {
      const data = JSON.parse(fs.readFileSync(LID_MAP_FILE, "utf8"));
      for (const [lid, phone] of Object.entries(data)) {
        lidToPhone.set(lid, phone);
        phoneToLid.set(phone, lid);
      }
      console.log(`📋 Loaded ${lidToPhone.size} LID→phone mappings`);
    }
  } catch (err) {
    console.error(`Failed to load LID map: ${err.message}`);
  }
}

function saveLidMap() {
  try {
    const obj = Object.fromEntries(lidToPhone);
    fs.writeFileSync(LID_MAP_FILE, JSON.stringify(obj, null, 2));
  } catch (err) {
    console.error(`Failed to save LID map: ${err.message}`);
  }
}

loadLidMap();

async function startBaileys() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER);
  const { version } = await fetchLatestBaileysVersion();

  logger.info(`Using Baileys v${version.join(".")}`);

  sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    printQRInTerminal: false,
    logger: pino({ level: "silent" }),
    browser: ["After5 Albert", "Chrome", "1.0.0"],
    markOnlineOnConnect: true,
    syncFullHistory: false,
    msgRetryCounterCache: msgRetryCache,
    getMessage: async (key) => {
      // Provide message content for retry requests
      const msg = await store.loadMessage(key.remoteJid, key.id);
      return msg?.message || undefined;
    },
  });

  // Bind store to socket events for message tracking
  store.bind(sock.ev);

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n╔════════════════════════════════════════════╗");
      console.log("║  Scan this QR with WhatsApp to pair        ║");
      console.log("║  WhatsApp → Settings → Linked Devices →    ║");
      console.log("║  Link a Device → scan below                ║");
      console.log("╚════════════════════════════════════════════╝\n");
      qrcode.generate(qr, { small: true });

      // Send QR to Telegram
      try {
        const qrDataUrl = await QRCode.toDataURL(qr, { width: 400, margin: 2 });
        await sendTelegramMessage("⚠️ <b>Baileys session needs pairing</b>\n\nQR code is ready — scan it from WhatsApp → Settings → Linked Devices → Link a Device");
        await sendTelegramQR(qrDataUrl);
      } catch (e) { console.error(`[TG] QR send failed: ${e.message}`); }
    }

    if (connection === "open") {
      const phone = sock.user?.id?.split(":")[0] || "unknown";
      console.log("\n✅  Connected to WhatsApp");
      console.log(`    Linked number: +${phone}`);
      console.log(`    Bridge URL:    http://localhost:${PORT}`);
      console.log(`    Python URL:    ${PYTHON_BACKEND_URL}\n`);

      // Notify Telegram
      sendTelegramMessage(`✅ <b>Baileys connected</b>\n\nLinked to +${phone}. Albert is online.`);

      // Retry any messages that failed during downtime
      setTimeout(() => retryFailedMessages(), 5000);
    }

    if (connection === "close") {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      logger.warn(
        `Connection closed. Status: ${statusCode}. Reconnect: ${shouldReconnect}`
      );

      // Alert Telegram
      sendTelegramMessage(`🔴 <b>Baileys disconnected</b>\n\nStatus code: ${statusCode}\n${shouldReconnect ? "Attempting reconnect..." : "Logged out — re-scan needed."}`);

      if (shouldReconnect) {
        setTimeout(() => startBaileys(), 2000);
      } else {
        console.log(
          "\n⚠️   Logged out from WhatsApp. Delete ./auth_info_baileys and restart to re-pair.\n"
        );
        process.exit(0);
      }
    }
  });

  // ---------- Presence (typing) → Python backend ----------------
  // Subscribes to typing indicators from leads and forwards to the backend so
  // the interrupt handler in baileys_client.py can pause Albert mid-response.
  sock.ev.on("presence.update", async (update) => {
    const jid = update?.id;
    if (!jid || jid.endsWith("@g.us") || jid === "status@broadcast") return;

    // Pick the most specific presence state reported
    const presences = update.presences || {};
    const presenceForJid = presences[jid] || Object.values(presences)[0];
    if (!presenceForJid) return;

    const state = presenceForJid.lastKnownPresence; // 'composing' | 'paused' | 'available' | 'unavailable'
    const phoneDigits = jid.split("@")[0];

    try {
      await axios.post(
        `${PYTHON_BACKEND_URL}/baileys/presence`,
        { phone: phoneDigits, state: state || "available" },
        { timeout: 3000 }
      );
      logger.debug(`[presence] ${phoneDigits} → ${state}`);
    } catch (err) {
      logger.debug(`[presence] forward failed: ${err.message}`);
    }
  });

  // ---------- Inbound messages → Python backend -----------------
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    for (const msg of messages) {
      if (!msg.message) continue;
      if (msg.key.fromMe) continue; // ignore own messages
      if (msg.key.remoteJid === "status@broadcast") continue;
      if (msg.key.remoteJid?.endsWith("@g.us")) continue; // ignore groups

      // Resolve the REAL phone number.
      // WhatsApp now sends messages from strangers as anonymised @lid JIDs
      // (e.g. "72666702676122@lid"). The real phone number, when available,
      // can be in various fields depending on the Baileys version.
      const remoteJid = msg.key.remoteJid;
      let phoneJid = remoteJid;

      if (remoteJid?.endsWith("@lid")) {
        const lidDigits = remoteJid.split("@")[0];

        // 1. Check our persisted LID→phone map first
        const mappedPhone = lidToPhone.get(lidDigits);
        if (mappedPhone) {
          phoneJid = `${mappedPhone}@s.whatsapp.net`;
          logger.info(`[LID→PN] ${remoteJid} resolved via map to +${mappedPhone}`);
        } else {
          // 2. Try Baileys message fields as fallback
          const candidates = [
            msg.key.senderPn,
            msg.key.senderLid,
            msg.key.participantPn,
            msg.key.participant,
            msg.verifiedBizName,
          ].filter(Boolean);

          const realJid = candidates.find(
            (c) => typeof c === "string" && c.endsWith("@s.whatsapp.net")
          );

          if (realJid) {
            phoneJid = realJid;
            // Store the mapping for future use
            const resolvedDigits = realJid.split("@")[0];
            lidToPhone.set(lidDigits, resolvedDigits);
            phoneToLid.set(resolvedDigits, lidDigits);
            saveLidMap();
            logger.info(`[LID→PN] ${remoteJid} resolved to ${phoneJid} (saved)`);
          } else {
            logger.info(
              `[LID unresolved] ${remoteJid} → keys: ${JSON.stringify(
                Object.keys(msg.key)
              )} | full: ${JSON.stringify(msg.key)}`
            );
          }
        }
      }

      const phoneDigits = phoneJid.split("@")[0];
      const messageText =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        msg.message.imageMessage?.caption ||
        "";
      const senderName = msg.pushName || "";
      const messageId = msg.key.id;
      const timestamp = Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000);

      if (!messageText) {
        logger.debug(`Ignoring non-text message from ${phoneDigits}`);
        continue;
      }

      logger.info(
        `[IN] ${phoneDigits} (${senderName}): ${messageText.slice(0, 200)}`
      );

      // Subscribe to this lead's presence updates so we can detect typing
      // (Baileys requires an explicit presenceSubscribe per contact)
      try {
        await sock.presenceSubscribe(remoteJid);
      } catch (err) {
        logger.debug(`presenceSubscribe failed for ${phoneDigits}: ${err.message}`);
      }

      // Remember the original JID for this phone so we can reply to the same
      // JID later (important for @lid messages where the JID is not a real
      // phone number but an anonymised WhatsApp LID).
      jidByPhone.set(phoneDigits, remoteJid);

      // Forward to Python backend in Baileys-native format
      try {
        await axios.post(
          `${PYTHON_BACKEND_URL}${PYTHON_WEBHOOK_PATH}`,
          {
            phone: phoneDigits,
            name: senderName,
            text: messageText,
            message_id: messageId,
            timestamp,
          },
          { timeout: 5000 }
        );
      } catch (err) {
        logger.error(
          `Failed to forward to Python: ${err.message} - is the backend running at ${PYTHON_BACKEND_URL}?`
        );
      }
    }
  });
}

// ---------- HTTP API for Python backend to call -----------------
const app = express();
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    connected: !!sock?.user,
    phone: sock?.user?.id?.split(":")[0] || null,
  });
});

/** POST /send  — Python sends a text message out via WhatsApp */
app.post("/send", async (req, res) => {
  const { phone, text } = req.body || {};
  if (!phone || !text) {
    return res.status(400).json({ error: "phone and text are required" });
  }
  if (!sock?.user) {
    // Queue for retry when connection comes back
    queueFailedMessage(phone, text);
    return res.status(503).json({ error: "WhatsApp not connected", queued: true });
  }
  try {
    const jid = toJid(phone);
    const sent = await sock.sendMessage(jid, { text });
    logger.info(`[OUT] ${phone}: ${String(text).slice(0, 200)}`);

    // Capture LID mapping: if we sent to a real phone but Baileys used a LID
    const sentJid = sent?.key?.remoteJid;
    const realDigits = String(phone).replace("whatsapp:", "").replace("+", "");
    if (sentJid && sentJid.endsWith("@lid")) {
      const lidDigits = sentJid.split("@")[0];
      if (lidDigits !== realDigits) {
        lidToPhone.set(lidDigits, realDigits);
        phoneToLid.set(realDigits, lidDigits);
        jidByPhone.set(realDigits, sentJid);
        saveLidMap();
        logger.info(`[LID MAP] ${lidDigits} → +${realDigits}`);
      }
    }

    res.json({ status: "sent" });
  } catch (err) {
    logger.error(`Send failed: ${err.message}`);
    // Queue for retry on reconnect
    queueFailedMessage(phone, text);
    res.status(500).json({ error: err.message, queued: true });
  }
});

/** POST /typing  — Python shows/hides typing indicator */
app.post("/typing", async (req, res) => {
  const { phone, state = "composing" } = req.body || {};
  if (!phone) return res.status(400).json({ error: "phone required" });
  if (!sock?.user) return res.status(503).json({ error: "not connected" });
  try {
    const jid = toJid(phone);
    await sock.sendPresenceUpdate(state, jid);
    res.json({ status: "ok" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/** POST /read  — Python marks one or many messages as read (blue ticks).
 * Body: { phone, message_id }  OR  { phone, message_ids: [...] }
 * Sending all IDs in one call lets Baileys flip them blue atomically,
 * which matters for back-to-back message bursts (3 messages → 3 ticks
 * at the same instant, not a staggered drip). */
app.post("/read", async (req, res) => {
  const { phone, message_id, message_ids } = req.body || {};
  if (!phone || (!message_id && !(message_ids && message_ids.length))) {
    return res.status(400).json({ error: "phone and message_id(s) required" });
  }
  if (!sock?.user) return res.status(503).json({ error: "not connected" });
  try {
    const jid = toJid(phone);
    const ids = (message_ids && message_ids.length) ? message_ids : [message_id];
    // 1-on-1 chats (both @s.whatsapp.net and @lid) don't need participant.
    // Pass all IDs to Baileys in a single readMessages call so they flip
    // blue together rather than racing across multiple HTTP calls.
    const readables = ids
      .filter(Boolean)
      .map((id) => ({ remoteJid: jid, id }));
    await sock.readMessages(readables);
    logger.info(`[OUT/read] ${phone}: marked ${readables.length} message(s) read`);
    res.json({ status: "read", count: readables.length });
  } catch (err) {
    logger.error(`Read failed: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

// ---------- Helpers ---------------------------------------------
function toJid(phone) {
  // Accepts "whatsapp:+447700900000", "447700900000", "+447700900000"
  // ALWAYS use the standard phone JID format - never use stored LIDs.
  // Using LIDs for sending causes replies to appear as a separate chat.
  const digits = String(phone).replace("whatsapp:", "").replace("+", "");
  return `${digits}@s.whatsapp.net`;
}

// ---------- Start -----------------------------------------------
app.listen(PORT, () => {
  console.log(`\n🚀 Baileys bridge HTTP API on http://localhost:${PORT}`);
  console.log("   Endpoints: GET /health, POST /send, POST /typing, POST /read\n");
});

startBaileys().catch((err) => {
  logger.error(`Fatal: ${err.message}`);
  process.exit(1);
});
