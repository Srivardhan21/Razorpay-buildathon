import os
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify
from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from payments.razorpay_client import verify_webhook_signature

load_dotenv()

app = Flask(__name__)
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
WEBHOOK_LOG = LOG_DIR / "webhook_events.jsonl"


def log_event(event: dict):
    """Appends the raw event to a simple JSON-lines log, so nothing is lost
    even before the full audit_log.py (Day 8) exists."""
    with open(WEBHOOK_LOG, "a") as f:
        f.write(json.dumps({
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }) + "\n")


@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body = request.get_data()

    if not WEBHOOK_SECRET:
        return jsonify({"error": "server misconfigured: no webhook secret set"}), 500

    if not verify_webhook_signature(raw_body, signature, WEBHOOK_SECRET):
        # This matters: never process a webhook whose signature doesn't check out,
        # since anyone could otherwise POST fake "payment succeeded" events.
        log_event({"status": "REJECTED_BAD_SIGNATURE"})
        return jsonify({"error": "invalid signature"}), 400

    payload = request.get_json()
    event_type = payload.get("event", "unknown")
    log_event(payload)

    print(f"[webhook] verified event: {event_type}")

    if event_type == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        print(f"  -> payment {payment['id']} captured, amount Rs.{payment['amount']/100}")
        # Day 6+: this is where you'd notify the buyer agent that payment succeeded.

    elif event_type == "payment.failed":
        payment = payload["payload"]["payment"]["entity"]
        print(f"  -> payment {payment['id']} FAILED: {payment.get('error_description')}")
        # This is your Day 8 graceful-failure trigger point.

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "webhook server running"}), 200


if __name__ == "__main__":
    print("Webhook server starting on http://localhost:5000")
    print("Expose it publicly with: ngrok http 5000")
    app.run(port=5000, debug=True)
