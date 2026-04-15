/**
 * WhatsApp Bot — приймає POST /send і пересилає повідомлення в WhatsApp
 * Бібліотека: whatsapp-web.js  (QR-код авторизація)
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
const express    = require("express");
const qrcode     = require("qrcode-terminal");
const bodyParser = require("body-parser");

// Load .env if present
try { require("dotenv").config(); } catch (_) {}

// ─── CONFIG ──────────────────────────────────────────────────────────────────
const TARGET_PHONE = process.env.TARGET_PHONE || "380XXXXXXXXX";
const BOT_PORT     = process.env.BOT_PORT     || 3000;

// ─── WHATSAPP CLIENT ─────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ clientId: "grafana-bot" }),
  puppeteer: {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
    ],
  },
});

let isReady = false;

client.on("qr", (qr) => {
  console.log("\n📱 Відскануй QR-код у WhatsApp (Linked Devices → Link a Device):\n");
  qrcode.generate(qr, { small: true });
});

client.on("authenticated", () => {
  console.log("✅ WhatsApp: аутентифікація успішна");
});

client.on("ready", () => {
  isReady = true;
  console.log(`✅ WhatsApp бот готовий! Надсилатиме на: ${TARGET_PHONE}`);
});

client.on("disconnected", (reason) => {
  isReady = false;
  console.warn("⚠️  WhatsApp відключився:", reason);
  console.log("🔄 Перепідключення через 5 сек...");
  setTimeout(() => client.initialize(), 5000);
});

client.on("auth_failure", (msg) => {
  console.error("❌ Помилка аутентифікації:", msg);
});

// Черга повідомлень (якщо бот ще не готовий)
const messageQueue = [];

async function sendMessage(phone, text) {
  const chatId = phone.includes("@c.us") ? phone : `${phone}@c.us`;
  await client.sendMessage(chatId, text);
  console.log(`📤 Надіслано на ${chatId}`);
}

// ─── HTTP SERVER ─────────────────────────────────────────────────────────────
const app = express();
app.use(bodyParser.json());

app.get("/health", (req, res) => {
  res.json({ status: isReady ? "ready" : "connecting", phone: TARGET_PHONE });
});

app.post("/send", async (req, res) => {
  const { message, phone } = req.body;

  if (!message) {
    return res.status(400).json({ error: "message is required" });
  }

  const target = phone || TARGET_PHONE;

  if (!isReady) {
    messageQueue.push({ phone: target, message });
    console.log(`📥 Повідомлення додано в чергу (бот не готовий). Черга: ${messageQueue.length}`);
    return res.json({ status: "queued", queue_length: messageQueue.length });
  }

  try {
    await sendMessage(target, message);
    return res.json({ status: "sent", phone: target });
  } catch (err) {
    console.error("❌ Помилка відправки:", err.message);
    return res.status(500).json({ error: err.message });
  }
});

// Відправка черги після підключення
client.on("ready", async () => {
  if (messageQueue.length > 0) {
    console.log(`📤 Відправляємо ${messageQueue.length} повідомлень з черги...`);
    while (messageQueue.length > 0) {
      const { phone, message } = messageQueue.shift();
      try {
        await sendMessage(phone, message);
        await new Promise((r) => setTimeout(r, 500)); // throttle
      } catch (e) {
        console.error("Queue send error:", e.message);
      }
    }
  }
});

app.listen(BOT_PORT, () => {
  console.log(`🚀 WhatsApp HTTP API слухає на порту ${BOT_PORT}`);
  console.log(`   POST http://localhost:${BOT_PORT}/send  { "message": "..." }`);
});

// ─── START ────────────────────────────────────────────────────────────────────
console.log("🔄 Ініціалізація WhatsApp клієнта...");
client.initialize();
