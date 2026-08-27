"""
scripts/simulate_webhook.py

Sends a correctly-signed, realistic Razorpay webhook payload to your local
webhook_server.py, so you can verify the signature-checking and event
handling logic work correctly WITHOUT depending on a live checkout page
succeeding (which is currently blocked by account activation on Razorpay's
side, not by anything in your code).

This exercises the exact same code path (verify_webhook_signature +
event handling in webhook_server.py) that a real webhook would hit. It does
NOT create a real payment or order — it's a payload shaped exactly like one,
signed the same way Razorpay signs its real webhooks.

Usage:
    python scripts/simulate_webhook.py                  # simulates payment.captured
    python scripts/simulate_webhook.py --event failed    # simulates payment.failed
"""

import os
import sys
import json
import hmac
import hashlib
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
WEBHOOK_URL = "http://localhost:5000/webhook/razorpay"  # local; ngrok not needed for this test


def build_payload(event: str) -> dict:
    if event == "captured":
        return {
            "entity": "event",
            "account_id": "acc_test000000000",
            "event": "payment.captured",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_simulated00000001",
                        "amount": 49900,
                        "currency": "INR",
                        "status": "captured",
                        "order_id": "order_TUlqquPl9QVTe1",
                        "method": "upi",
                        "email": "test@example.com",
                        "contact": "+919123456780",
                    }
                }
            },
        }
    elif event == "failed":
        return {
            "entity": "event",
            "account_id": "acc_test000000000",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_simulated00000002",
                        "amount": 49900,
                        "currency": "INR",
                        "status": "failed",
                        "order_id": "order_TUlqquPl9QVTe1",
                        "method": "card",
                        "error_code": "GATEWAY_ERROR",
                        "error_description": "Payment failed simulated for testing.",
                    }
                }
            },
        }
    else:
        raise ValueError(f"Unknown event type: {event}")


def sign_payload(body_bytes: bytes, secret: str) -> str:
    """Reproduces exactly how Razorpay signs real webhooks: HMAC-SHA256 of
    the raw request body using the webhook secret."""
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", choices=["captured", "failed"], default="captured")
    args = parser.parse_args()

    if not WEBHOOK_SECRET:
        print("ERROR: RAZORPAY_WEBHOOK_SECRET not set in .env")
        print("This must match the secret you configured on Razorpay's dashboard,")
        print("even though we're simulating rather than using a real webhook right now.")
        sys.exit(1)

    payload = build_payload(args.event)
    body_bytes = json.dumps(payload).encode()
    signature = sign_payload(body_bytes, WEBHOOK_SECRET)

    print(f"Sending simulated '{args.event}' event to {WEBHOOK_URL}")
    print(f"Signature: {signature[:16]}... (truncated)")

    response = requests.post(
        WEBHOOK_URL,
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
        },
    )

    print(f"\nResponse status: {response.status_code}")
    print(f"Response body: {response.json()}")

    if response.status_code == 200:
        print("\nSUCCESS: webhook_server.py correctly verified and processed the event.")
        print("Check logs/webhook_events.jsonl to confirm it was logged.")
    else:
        print("\nSomething is off in the webhook handler or the secret doesn't match.")


if __name__ == "__main__":
    main()
