# 📡 Grafana → WhatsApp Alert Bridge

Пересилає алерти з Grafana у WhatsApp через webhook.

```
Grafana ──POST──► webhook_server.py :5000 ──► whatsapp_bot/index.js :3000 ──► 📱 WhatsApp
```

## Вимоги

- Python 3.8+
- Node.js 18+


# 📦 Grafana → WhatsApp Alert Bridge — Інструкція встановлення

## Архітектура

```
Grafana  →  POST :5000/grafana-webhook  →  webhook_server.py  →  POST :5055/send  →  index.js  →  WhatsApp
```

---

## 1. Системні залежності (Ubuntu/Debian)

```bash
# Node.js 18+
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Python 3.10+
sudo apt-get install -y python3 python3-pip python3-venv

# Chromium (потрібен для whatsapp-web.js)
sudo apt-get install -y \
    chromium-browser \
    libgbm-dev \
    libxshmfence-dev \
    libasound2t64 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libnss3 \
    libx11-xcb1 \
    fonts-liberation \
    xdg-utils
```

> **VPS без GUI (headless)?** Chromium встановиться і так — puppeteer в headless режимі.

---

## 2. Структура файлів

```
/opt/grafana-whatsapp/
├── index.js              ← WhatsApp бот (Node.js)
├── webhook_server.py     ← Webhook приймач (Python/Flask)
├── .env                  ← Конфігурація (номер телефону, порти)
├── package.json          ← (автоматично після npm install)
└── requirements.txt      ← (автоматично після pip install)
```

```bash
sudo mkdir -p /opt/grafana-whatsapp
sudo chown $USER:$USER /opt/grafana-whatsapp
cd /opt/grafana-whatsapp
```

Скопіюй файли:
```bash
cp /шлях/до/index.js          /opt/grafana-whatsapp/
cp /шлях/до/webhook_server.py /opt/grafana-whatsapp/
cp /шлях/до/.env              /opt/grafana-whatsapp/
cp /шлях/до/requirements.txt  /opt/grafana-whatsapp/
```

---

## 3. Налаштування .env

```bash
nano /opt/grafana-whatsapp/.env
```

Встав свій номер телефону (одержувача алертів):
```env
TARGET_PHONE=380671234567      # Твій номер БЕЗ + (міжнародний формат)
TARGET_GROUP=123XXXXXXXXXXXXXX    # ID без @g.us твоєї группи
BOT_PORT=5055
WHATSAPP_BOT_URL=http://localhost:5055/send
SECRET_TOKEN=                  # Залиш порожнім (або встав секрет)
```

---

## 4. Встановлення Node.js залежностей

```bash
cd /opt/grafana-whatsapp

cat > package.json << 'EOF'
{
  "name": "grafana-whatsapp-bot",
  "version": "1.0.0",
  "main": "index.js",
  "dependencies": {
    "whatsapp-web.js": "^1.23.0",
    "express": "^4.18.2",
    "qrcode-terminal": "^0.12.0",
    "body-parser": "^1.20.2",
    "dotenv": "^16.3.1"
  }
}
EOF

npm install
```

---

## 5. Встановлення Python залежностей

```bash
cd /opt/grafana-whatsapp
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

---

## 6. Перший запуск — авторизація WhatsApp

Перший раз ОБОВ'ЯЗКОВО запускати вручну (потрібен QR-код):

```bash
cd /opt/grafana-whatsapp
node index.js
```

У терміналі з'явиться QR-код. Відскануй його через WhatsApp:
**Налаштування → Пов'язані пристрої → Прив'язати пристрій**

Після успішного сканування побачиш:
```
✅ WhatsApp: аутентифікація успішна
✅ WhatsApp бот готовий! Надсилатиме на: 380671234567
```

Зупини (`Ctrl+C`). Сесія збережена в `.wwebjs_auth/` — більше QR не потрібен.

---

## 7. Systemd сервіси (автозапуск)

### 7.1 WhatsApp бот

```bash
sudo nano /etc/systemd/system/whatsapp-bot.service
```

```ini
[Unit]
Description=WhatsApp Bot for Grafana Alerts
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/grafana-whatsapp
ExecStart=/usr/bin/node /opt/grafana-whatsapp/index.js
Restart=always
RestartSec=10
EnvironmentFile=/opt/grafana-whatsapp/.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> Замість `YOUR_USER` встав своє ім'я користувача: `echo $USER`

### 7.2 Webhook сервер

```bash
sudo nano /etc/systemd/system/grafana-webhook.service
```

```ini
[Unit]
Description=Grafana Webhook to WhatsApp Bridge
After=network.target whatsapp-bot.service

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/grafana-whatsapp
ExecStart=/opt/grafana-whatsapp/venv/bin/python /opt/grafana-whatsapp/webhook_server.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/grafana-whatsapp/.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> Також замість `YOUR_USER` встав своє ім'я користувача: `echo $USER`

### 7.3 Увімкнення сервісів

```bash
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-bot grafana-webhook
sudo systemctl start whatsapp-bot grafana-webhook
```

Перевірка статусу:
```bash
sudo systemctl status whatsapp-bot
sudo systemctl status grafana-webhook
```

Перегляд логів в реальному часі:
```bash
sudo journalctl -fu whatsapp-bot
sudo journalctl -fu grafana-webhook
```

---

## 8. Налаштування Grafana

### Contact point (Grafana 8+, Unified Alerting)

1. **Alerting → Contact points → New contact point**
2. Тип: **Webhook**
3. URL: `http://localhost:5000/grafana-webhook`
   - Якщо Grafana на іншому сервері: `http://IP_СЕРВЕРА:5000/grafana-webhook`
4. **HTTP Method**: POST
5. Якщо SECRET_TOKEN встановлено:
   - Authorization headers → `X-Grafana-Token: твій_токен`
6. Save → Test

### Legacy alerting (Grafana 7 і старше)

1. **Alerting → Notification channels → New channel**
2. Тип: **webhook**
3. URL: `http://localhost:5000/grafana-webhook`
4. Save → Send test

---

## 9. Тест без Grafana

```bash
# Перевірка що webhook сервер живий
curl http://localhost:5000/health

# Перевірка що WhatsApp бот живий
curl http://localhost:5055/health

# Надіслати тестовий алерт (GET або POST)
curl http://localhost:5000/test

# Надіслати вручну
curl -X POST http://localhost:5055/send \
  -H "Content-Type: application/json" \
  -d '{"message": "Привіт! Це тест 🚀", "phone": "380671234567"}'
```

---

## 10. Порти — налаштування firewall

Webhook сервер `:5000` НЕ ПОВИНЕН бути відкритий назовні (тільки Grafana → localhost).
WhatsApp бот `:5055` — теж тільки localhost.

Якщо Grafana на окремому сервері:
```bash
# Дозволити тільки з IP Grafana
sudo ufw allow from GRAFANA_IP to any port 5000
```

---

## 11. Усунення проблем

| Проблема | Рішення |
|---|---|
| 500 від webhook | Дивись `alerts.log` або `journalctl -fu grafana-webhook` |
| QR не з'являється | Перевір що chromium встановлено: `which chromium-browser` |
| WhatsApp відключається | Нормально — бот перепідключиться автоматично через 10 сек |
| `auth_failure` | Видали `.wwebjs_auth/` і знову відскануй QR |
| Повідомлення не доходять | Перевір `curl http://localhost:5055/health` — чи `"status":"ready"` |
| Grafana не може достукатись | Перевір що webhook слухає: `ss -tlnp | grep 5000` |

---

## 12. Файлова структура після встановлення

```
/opt/grafana-whatsapp/
├── .env
├── index.js
├── webhook_server.py
├── package.json
├── node_modules/
├── venv/
├── alerts.log              ← Лог усіх отриманих алертів
└── .wwebjs_auth/           ← WhatsApp сесія (НЕ ВИДАЛЯЙ!)
```


## Приклад повідомлення

```
🔴 GRAFANA ALERT
📋 High CPU Usage
🕒 15.01.2024 10:35:22
📊 Стан: FIRING

──────────────────────────────
🔴 🚨 Alert #1: HighCPU
   Severity: CRITICAL
   📝 CPU usage > 95% on prod-server-01
   🏷 instance=prod-server-01:9100, job=node_exporter
   ⏱ Початок: 2024-01-15 10:35:20
```

## ⚠️ Безпека

- Ніколи не комітьте `.env` і `.wwebjs_auth/` — вони в `.gitignore`
- Використовуйте складний `SECRET_TOKEN`
- Для публічного доступу використовуйте HTTPS (nginx + certbot або ngrok)
