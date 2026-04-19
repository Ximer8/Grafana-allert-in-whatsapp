/**
 * WhatsApp Bot — приймає POST /send і пересилає повідомлення в WhatsApp
 * Порт: 5055  |  Бібліотека: whatsapp-web.js (QR-код авторизація)
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
const express    = require("express");
const qrcode     = require("qrcode-terminal");
const bodyParser = require("body-parser");

// Load .env if present
try { require("dotenv").config(); } catch (_) {}

// ─── CONFIG ──────────────────────────────────────────────────────────────────
const TARGET_PHONE = process.env.TARGET_PHONE || "";   // напр. 380671234567
const TARGET_GROUP = (process.env.TARGET_GROUP || "").trim();  // напр. 120111422228333170
const BOT_PORT     = parseInt(process.env.BOT_PORT) || 5055;

if (!TARGET_PHONE) {
  console.warn("⚠️  TARGET_PHONE не вказано! Встанови в .env або передай при запуску.");
}


if (!TARGET_GROUP) {
  console.warn("⚠️  TARGET_GROUP не вказано! Встанови в .env або передай при запуску.");
}

// ─── WHATSAPP CLIENT ─────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ clientId: "grafana-bot" }),
  puppeteer: {
    executablePath: '/usr/bin/chromium-browser',
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-extensions",
      "--single-process",         // допомагає на серверах з малою RAM
    ],
  },
  // Таймаут на ініціалізацію (мс) — збільшено для повільних серверів
  authTimeoutMs: 60000,
  qrMaxRetries: 5,
});

let isReady     = false;
let clientError = null;

// ─── EVENTS ──────────────────────────────────────────────────────────────────

client.on("qr", (qr) => {
  console.log("\n📱 Відскануй QR-код у WhatsApp (Linked Devices → Link a Device):\n");
  qrcode.generate(qr, { small: true });
  console.log("\n(або скопіюй рядок вище і встав на https://www.qr-code-generator.com/)\n");
});

client.on("authenticated", () => {
  console.log("✅ WhatsApp: аутентифікація успішна");
  clientError = null;
});

client.on("ready", () => {
  isReady     = true;
  clientError = null;
  const phone = TARGET_PHONE || "(не вказано)";
  console.log(`✅ WhatsApp бот готовий! Надсилатиме на: ${phone}`);
  flushQueue();
});

client.on("disconnected", (reason) => {
  isReady = false;
  console.warn("⚠️  WhatsApp відключився:", reason);
  console.log("🔄 Перепідключення через 10 сек...");
  setTimeout(() => {
    client.initialize().catch((e) => console.error("Reinit error:", e.message));
  }, 10000);
});

client.on("auth_failure", (msg) => {
  clientError = msg;
  console.error("❌ Помилка аутентифікації:", msg);
  console.error("   Видали папку .wwebjs_auth/ і перезапусти бота для нового QR-коду.");
});

// ─── MESSAGE QUEUE ───────────────────────────────────────────────────────────
const messageQueue = [];

async function sendWhatsApp(phone, text) {
  // Відправка на телефон
  if (phone) {
    const chatId = phone.includes("@c.us") ? phone : `${phone}@c.us`;
    await client.sendMessage(chatId, text);
    console.log(`📤 Надіслано → ${chatId}`);
  }
  // Відправка в групу
  if (TARGET_GROUP) {
    const groupId = TARGET_GROUP.endsWith("@g.us") ? TARGET_GROUP : `${TARGET_GROUP}@g.us`;
    await client.sendMessage(groupId, text);
    console.log(`📤 Надіслано в групу → ${groupId}`);
  }
}

async function flushQueue() {
  if (messageQueue.length === 0) return;
  console.log(`📤 Відправляємо ${messageQueue.length} повідомлень з черги...`);
  while (messageQueue.length > 0) {
    const { phone, message } = messageQueue.shift();
    try {
      await sendWhatsApp(phone, message);
      await new Promise((r) => setTimeout(r, 700)); // throttle між повідомленнями
    } catch (e) {
      console.error("Queue flush error:", e.message);
    }
  }
}

// ─── HTTP SERVER ─────────────────────────────────────────────────────────────
const app = express();
app.use(bodyParser.json({ limit: "1mb" }));
app.use(bodyParser.text({ limit: "1mb" }));   // fallback для не-JSON тіл

// Health check
app.get("/health", (req, res) => {
  res.json({
    status  : isReady ? "ready" : "connecting",
    phone   : TARGET_PHONE || "not set",
    queued  : messageQueue.length,
    error   : clientError || null,
  });
});

// Send endpoint
app.post("/send", async (req, res) => {
  // Якщо тіло прийшло як рядок (content-type: text/plain) — пробуємо розпарсити
  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch (_) { body = { message: body }; }
  }

  const message = body?.message;
  const phone   = body?.phone || TARGET_PHONE;

  if (!message) {
    return res.status(400).json({ error: "message is required" });
  }
  if (!phone) {
    return res.status(400).json({ error: "phone not specified and TARGET_PHONE not set" });
  }

  // Якщо бот ще не готовий — ставимо в чергу
  if (!isReady) {
    messageQueue.push({ phone, message });
    console.log(`📥 Повідомлення в черзі (бот не готовий). Черга: ${messageQueue.length}`);
    return res.json({ status: "queued", queue_length: messageQueue.length });
  }

  try {
    await sendWhatsApp(phone, message);
    return res.json({ status: "sent", phone });
  } catch (err) {
    console.error("❌ Помилка відправки:", err.message);
    // Додаємо в чергу замість одразу повертати помилку
    messageQueue.push({ phone, message });
    return res.status(500).json({
      error       : err.message,
      status      : "queued_on_error",
      queue_length: messageQueue.length,
    });
  }
});

app.listen(BOT_PORT, "0.0.0.0", () => {
  console.log(`\n🚀 WhatsApp HTTP API слухає на порту ${BOT_PORT}`);
  console.log(`   POST http://localhost:${BOT_PORT}/send  { "message": "...", "phone": "380..." }`);
  console.log(`   GET  http://localhost:${BOT_PORT}/health\n`);
});

// ─── START ───────────────────────────────────────────────────────────────────
console.log("🔄 Ініціалізація WhatsApp клієнта...");
client.initialize().catch((e) => {
  console.error("Fatal init error:", e.message);
  process.exit(1);
});

// Graceful shutdown
process.on("SIGTERM", async () => {
  console.log("Shutting down...");
  await client.destroy().catch(() => {});
  process.exit(0);
});
