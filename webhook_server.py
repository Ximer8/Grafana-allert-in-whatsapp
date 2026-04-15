#!/usr/bin/env python3
"""
Grafana → WhatsApp Alert Bridge
Приймає webhook від Grafana на порті 5000 і пересилає в WhatsApp-бот на порті 5055.
Підтримує: Unified Alerting (нові версії), Legacy alerting, і будь-який невідомий формат.
"""

import json
import logging
import os
import traceback
from datetime import datetime
from flask import Flask, request, jsonify
import requests

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── CONFIG ──────────────────────────────────────────────────────────────────
WHATSAPP_BOT_URL = os.getenv("WHATSAPP_BOT_URL", "http://localhost:5055/send")
TARGET_PHONE     = os.getenv("TARGET_PHONE", "")          # напр. 380671234567
SECRET_TOKEN     = os.getenv("SECRET_TOKEN", "")           # залиш порожнім — без перевірки
# Якщо SECRET_TOKEN порожній — перевірка токена вимкнена (зручно для prod без токенів)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("alerts.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

STATUS_EMOJI = {
    "firing":   "🔴",
    "resolved": "✅",
    "pending":  "🟡",
    "no_data":  "⚪",
    "nodata":   "⚪",
    "unknown":  "❓",
    "ok":       "✅",
    "alerting": "🔴",
    "error":    "💥",
}

SEVERITY_EMOJI = {
    "critical": "🚨",
    "high":     "🔥",
    "warning":  "⚠️",
    "info":     "ℹ️",
    "low":      "🔵",
}


def _ts(iso: str) -> str:
    """Converts ISO timestamp to readable format, skips zero-time."""
    if not iso or iso.startswith("0001"):
        return ""
    return iso[:19].replace("T", " ")


def format_unified_alert(payload: dict) -> str:
    """
    Grafana Unified Alerting format (Grafana 8+).
    Payload contains: title, status, orgId, alerts[], externalURL, etc.
    """
    title      = payload.get("title", "Grafana Alert")
    status     = payload.get("status", "unknown").lower()
    ext_url    = payload.get("externalURL", "")
    group_key  = payload.get("groupKey", "")
    now_str    = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    s_e        = STATUS_EMOJI.get(status, "❓")
    alerts     = payload.get("alerts", [])

    lines = [
        f"{s_e} *GRAFANA ALERT*",
        f"📋 *{title}*",
        f"🕒 {now_str}",
        f"📊 Стан: `{status.upper()}`",
    ]

    if group_key:
        lines.append(f"🔑 Group: `{group_key}`")

    for i, alert in enumerate(alerts, 1):
        a_status  = alert.get("status", "unknown").lower()
        labels    = alert.get("labels", {})
        annots    = alert.get("annotations", {})
        a_name    = labels.get("alertname", f"Alert #{i}")
        severity  = labels.get("severity", "")
        summary   = annots.get("summary", "")
        desc      = annots.get("description", annots.get("message", ""))
        starts_at = _ts(alert.get("startsAt", ""))
        ends_at   = _ts(alert.get("endsAt", ""))
        panel_url = alert.get("panelURL", alert.get("generatorURL", ""))

        s_e2  = STATUS_EMOJI.get(a_status, "❓")
        sev_e = SEVERITY_EMOJI.get(severity.lower(), "")

        lines.append(f"\n{'─'*28}")
        lines.append(f"{s_e2} {sev_e} *{a_name}*")

        if severity:
            lines.append(f"   Severity: `{severity.upper()}`")
        if summary:
            lines.append(f"   📝 {summary}")
        if desc:
            lines.append(f"   {desc}")

        # Extra labels (skip common ones already shown)
        skip = {"alertname", "severity", "__name__"}
        extra = {k: v for k, v in labels.items() if k not in skip}
        if extra:
            label_str = ", ".join(f"{k}={v}" for k, v in list(extra.items())[:6])
            lines.append(f"   🏷 {label_str}")

        if starts_at:
            lines.append(f"   ⏱ Початок: {starts_at}")
        if ends_at:
            lines.append(f"   ⏹ Кінець:  {ends_at}")
        if panel_url and panel_url.startswith("http"):
            lines.append(f"   🔗 {panel_url}")

    if ext_url and ext_url.startswith("http"):
        lines.append(f"\n🌐 Grafana: {ext_url}")

    return "\n".join(lines)


def format_legacy_alert(payload: dict) -> str:
    """
    Grafana Legacy alerting format (pre-Grafana 8 or old notification channels).
    Fields: title, state, message, ruleUrl, evalMatches[], imageUrl
    """
    title    = payload.get("title", "Grafana Alert")
    state    = payload.get("state", "unknown").lower()
    message  = payload.get("message", "")
    rule_url = payload.get("ruleUrl", "")
    now_str  = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    s_e      = STATUS_EMOJI.get(state, "❓")

    lines = [
        f"{s_e} *GRAFANA ALERT (Legacy)*",
        f"📋 *{title}*",
        f"🕒 {now_str}",
        f"📊 Стан: `{state.upper()}`",
    ]

    if message:
        lines.append(f"\n📝 {message}")

    eval_matches = payload.get("evalMatches", [])
    if eval_matches:
        lines.append("\n📈 *Метрики:*")
        for m in eval_matches:
            metric = m.get("metric", "N/A")
            value  = m.get("value")
            lines.append(f"   • {metric}: `{value}`")

    if rule_url and rule_url.startswith("http"):
        lines.append(f"\n🔗 {rule_url}")

    return "\n".join(lines)


def format_unknown_payload(payload: dict) -> str:
    """
    Fallback: невідомий формат — просто копіюємо весь payload у читабельному вигляді.
    """
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    lines = [
        "❓ *GRAFANA ALERT (unknown format)*",
        f"🕒 {now_str}",
        "\n📦 Raw payload:\n```",
    ]
    try:
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2)[:3000])
    except Exception:
        lines.append(str(payload)[:3000])
    lines.append("```")
    return "\n".join(lines)


def parse_and_format(payload) -> str:
    """
    Детектує формат payload і викликає відповідний форматтер.
    Ніколи не кидає виняток — у гіршому разі повертає raw dump.
    """
    if not isinstance(payload, dict):
        return f"❓ *Grafana Alert*\n\nНеочікуваний тип даних: {type(payload).__name__}\n\n{str(payload)[:2000]}"

    try:
        # Unified Alerting: є поле "alerts" (список) або "status" + "receiver"
        if "alerts" in payload and isinstance(payload["alerts"], list):
            return format_unified_alert(payload)

        # Legacy: є "state" або "evalMatches"
        if "state" in payload or "evalMatches" in payload:
            return format_legacy_alert(payload)

        # Має "status" і "title" — теж Unified-подібний
        if "status" in payload and "title" in payload:
            return format_unified_alert(payload)

        # Невідомий формат — відправляємо як є
        return format_unknown_payload(payload)

    except Exception as exc:
        log.error("Formatter crashed: %s\n%s", exc, traceback.format_exc())
        return format_unknown_payload(payload)


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/grafana-webhook", methods=["POST"])
def grafana_webhook():
    # ── Опціональна перевірка токена ─────────────────────────────────────────
    if SECRET_TOKEN:
        token = (
            request.headers.get("X-Grafana-Token")
            or request.headers.get("Authorization", "").removeprefix("Bearer ")
            or request.args.get("token", "")
        )
        if token != SECRET_TOKEN:
            log.warning("Unauthorized request. Token: '%s'", token)
            return jsonify({"error": "Unauthorized"}), 401

    # ── Парсинг тіла ─────────────────────────────────────────────────────────
    payload = None
    raw_body = request.get_data(as_text=True)

    # Спочатку пробуємо JSON
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        pass

    # Якщо JSON не вийшов — логуємо raw і ліпимо текстове повідомлення
    if payload is None:
        log.warning("Could not parse JSON. Raw body: %s", raw_body[:500])
        payload = {"_raw": raw_body, "title": "Grafana Alert (raw body)"}

    log.info("Alert received:\n%s", json.dumps(payload, ensure_ascii=False, default=str)[:600])

    # ── Форматування ─────────────────────────────────────────────────────────
    text = parse_and_format(payload)
    log.info("Formatted message:\n%s", text)

    # ── Надсилання в WhatsApp бот ─────────────────────────────────────────────
    body = {"message": text}
    if TARGET_PHONE:
        body["phone"] = TARGET_PHONE

    try:
        resp = requests.post(WHATSAPP_BOT_URL, json=body, timeout=10)
        resp.raise_for_status()
        log.info("WhatsApp response: %s", resp.text[:200])
        return jsonify({"status": "sent", "whatsapp_response": resp.json()})
    except requests.RequestException as exc:
        log.error("Failed to send to WhatsApp bot: %s", exc)
        # Повертаємо 202 а не 500 — щоб Grafana не вважала webhook зламаним
        return jsonify({"status": "queued", "warning": str(exc)}), 202


# ─── TEST ENDPOINT ───────────────────────────────────────────────────────────

@app.route("/test", methods=["GET", "POST"])
def test_alert():
    """Надсилає тестовий алерт через сам webhook."""
    fake = {
        "receiver": "whatsapp",
        "status": "firing",
        "title": "[FIRING:1] Test Alert",
        "orgId": 1,
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighCPU",
                    "severity":  "warning",
                    "instance":  "server01:9100",
                    "job":       "node_exporter",
                },
                "annotations": {
                    "summary":     "CPU usage is critically high",
                    "description": "CPU load > 90% for 5 minutes on server01",
                },
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt":   "0001-01-01T00:00:00Z",
                "generatorURL": "http://localhost:3000/alerting",
                "panelURL": "",
            }
        ],
        "externalURL": "http://localhost:3000",
    }

    params = {}
    if SECRET_TOKEN:
        params["token"] = SECRET_TOKEN

    try:
        resp = requests.post(
            "http://localhost:5000/grafana-webhook",
            json=fake,
            params=params,
            timeout=10,
        )
        return jsonify({"test_payload": fake, "webhook_response": resp.json()}), resp.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    log.info("🚀 Starting Grafana→WhatsApp webhook bridge on :5000")
    log.info("   Webhook URL  : http://0.0.0.0:5000/grafana-webhook")
    log.info("   Health check : http://0.0.0.0:5000/health")
    log.info("   Test alert   : http://0.0.0.0:5000/test")
    log.info("   WhatsApp bot : %s", WHATSAPP_BOT_URL)
    if not SECRET_TOKEN:
        log.warning("   SECRET_TOKEN is empty — token check DISABLED")
    app.run(host="0.0.0.0", port=5000, debug=False)
