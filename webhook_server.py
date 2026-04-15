#!/usr/bin/env python3
"""
Grafana → WhatsApp Alert Bridge
Receives Grafana webhooks and forwards them to a WhatsApp bot via HTTP
"""

import json
import logging
import os
from datetime import datetime
from flask import Flask, request, jsonify
import requests

# Load .env if present (pip install python-dotenv  — optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── CONFIG ──────────────────────────────────────────────────────────────────
WHATSAPP_BOT_URL = os.getenv("WHATSAPP_BOT_URL", "http://localhost:3000/send")
SECRET_TOKEN     = os.getenv("SECRET_TOKEN",     "my_secret_token_123")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("alerts.log"),
    ],
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── FORMATTERS ──────────────────────────────────────────────────────────────

STATUS_EMOJI = {
    "firing":   "🔴",
    "resolved": "✅",
    "pending":  "🟡",
    "no_data":  "⚪",
    "unknown":  "❓",
}

SEVERITY_EMOJI = {
    "critical": "🚨",
    "high":     "🔥",
    "warning":  "⚠️",
    "info":     "ℹ️",
}


def format_grafana_alert(payload: dict) -> str:
    """Converts raw Grafana webhook payload to a readable WhatsApp message."""
    title    = payload.get("title", "Grafana Alert")
    state    = payload.get("state", payload.get("status", "unknown")).lower()
    message  = payload.get("message", payload.get("body", ""))
    rule_url = payload.get("ruleUrl", payload.get("orgId", ""))

    status_e  = STATUS_EMOJI.get(state, "❓")
    now_str   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    lines = [
        f"{status_e} *GRAFANA ALERT*",
        f"📋 *{title}*",
        f"🕒 {now_str}",
        f"📊 Стан: `{state.upper()}`",
    ]

    # ── Grafana Unified Alerting (newer format) ──────────────────────────────
    if "alerts" in payload:
        for i, alert in enumerate(payload["alerts"], 1):
            a_status   = alert.get("status", "unknown").lower()
            a_name     = alert.get("labels", {}).get("alertname", f"Alert {i}")
            severity   = alert.get("labels", {}).get("severity", "")
            a_summary  = alert.get("annotations", {}).get("summary", "")
            a_desc     = alert.get("annotations", {}).get("description", "")
            starts_at  = alert.get("startsAt", "")
            ends_at    = alert.get("endsAt", "")

            sev_e = SEVERITY_EMOJI.get(severity.lower(), "")
            s_e   = STATUS_EMOJI.get(a_status, "❓")

            lines.append(f"\n{'─'*30}")
            lines.append(f"{s_e} {sev_e} Alert #{i}: *{a_name}*")

            if severity:
                lines.append(f"   Severity: `{severity.upper()}`")
            if a_summary:
                lines.append(f"   📝 {a_summary}")
            if a_desc:
                lines.append(f"   {a_desc}")

            # Labels (without alertname/severity to avoid duplication)
            labels = {k: v for k, v in alert.get("labels", {}).items()
                      if k not in ("alertname", "severity")}
            if labels:
                label_str = ", ".join(f"{k}={v}" for k, v in labels.items())
                lines.append(f"   🏷 {label_str}")

            if starts_at and not starts_at.startswith("0001"):
                lines.append(f"   ⏱ Початок: {starts_at[:19].replace('T', ' ')}")
            if ends_at and not ends_at.startswith("0001"):
                lines.append(f"   ⏹ Кінець:  {ends_at[:19].replace('T', ' ')}")

    # ── Legacy Grafana format ────────────────────────────────────────────────
    else:
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


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/grafana-webhook", methods=["POST"])
def grafana_webhook():
    # Optional token check
    token = request.headers.get("X-Grafana-Token") or request.args.get("token", "")
    if token != SECRET_TOKEN:
        log.warning("Unauthorized request (bad token): %s", token)
        return jsonify({"error": "Unauthorized"}), 401

    try:
        payload = request.get_json(force=True)
    except Exception as exc:
        log.error("JSON parse error: %s", exc)
        return jsonify({"error": "Invalid JSON"}), 400

    log.info("Alert received: %s", json.dumps(payload, ensure_ascii=False)[:300])

    text = format_grafana_alert(payload)
    log.info("Formatted message:\n%s", text)

    try:
        resp = requests.post(
            WHATSAPP_BOT_URL,
            json={"message": text},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("WhatsApp bot responded: %s", resp.json())
        return jsonify({"status": "sent", "whatsapp_response": resp.json()})
    except requests.RequestException as exc:
        log.error("Failed to send to WhatsApp bot: %s", exc)
        return jsonify({"status": "queued", "warning": str(exc)}), 202


# ─── TEST ENDPOINT ───────────────────────────────────────────────────────────

@app.route("/test", methods=["POST"])
def test_alert():
    """Send a fake Grafana alert — useful for local testing."""
    fake = {
        "title": "Test Alert from PC",
        "state": "firing",
        "message": "CPU usage above 90% on test-server",
        "ruleUrl": "http://localhost:3000/alerting",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighCPU",
                    "severity":  "warning",
                    "instance":  "localhost:9100",
                },
                "annotations": {
                    "summary":     "CPU usage is critically high",
                    "description": "CPU load has been above 90% for 5 minutes",
                },
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt":   "0001-01-01T00:00:00Z",
            }
        ],
    }

    # Inject token automatically for the test
    try:
        resp = requests.post(
            f"http://localhost:5000/grafana-webhook?token={SECRET_TOKEN}",
            json=fake,
            timeout=10,
        )
        return jsonify({"test_payload": fake, "webhook_response": resp.json()}), resp.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    log.info("Starting Grafana→WhatsApp webhook server on :5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
