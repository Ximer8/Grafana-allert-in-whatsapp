# 📡 Grafana → WhatsApp Alert Bridge

Пересилає алерти з Grafana у WhatsApp через webhook.

```
Grafana ──POST──► webhook_server.py :5000 ──► whatsapp_bot/index.js :3000 ──► 📱 WhatsApp
```

## Вимоги

- Python 3.8+
- Node.js 18+

## Швидкий старт

### 1. Клонуй репозиторій
```bash
git clone https://github.com/YOUR_USERNAME/grafana-whatsapp.git
cd grafana-whatsapp
```

### 2. Налаштуй змінні середовища
```bash
cp .env.example .env
# Відкрий .env і вкажи TARGET_PHONE та SECRET_TOKEN
```

### 3. Встанови залежності
```bash
# Python
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Node.js
cd whatsapp_bot && npm install && cd ..
```

### 4. Запусти WhatsApp бот (Термінал 1)
```bash
cd whatsapp_bot && node index.js
```
Відскануй QR-код: WhatsApp → **Linked Devices → Link a Device**

### 5. Запусти webhook сервер (Термінал 2)
```bash
source venv/bin/activate
python webhook_server.py
```

### 6. Протестуй з ПК (Термінал 3)
```bash
python test_alert.py
```

## Підключення до Grafana

**Grafana 9+ (Unified Alerting):**
`Alerting → Contact points → Add → Webhook`
URL: `http://YOUR_IP:5000/grafana-webhook?token=YOUR_SECRET_TOKEN`

**Grafana 8 і старше:**
`Alerting → Notification channels → Add → Webhook`

## Структура проекту

```
grafana-whatsapp/
├── webhook_server.py   ← Flask сервер, приймає POST від Grafana
├── test_alert.py       ← Скрипт для тестування без Grafana
├── requirements.txt
└── whatsapp_bot/
    ├── index.js        ← Node.js WhatsApp бот
    └── package.json
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
