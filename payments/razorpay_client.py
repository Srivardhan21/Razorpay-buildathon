import os
import razorpay
from dotenv import load_dotenv

load_dotenv()

KEY_ID = os.getenv("RAZORPAY_KEY_ID")
KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

if not KEY_ID or not KEY_SECRET:
    raise RuntimeError(
        "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not found in environment. "
        "Check that .env exists in the project root and contains your test-mode keys."
    )

client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))


def create_order(amount_inr: float, receipt_id: str, notes: dict | None = None) -> dict:
    """
    Creates a Razorpay Order — the first step before any payment can happen.
    Amount must be sent in paise (smallest currency unit), so Rs.499 becomes 49900.

    Returns the raw Razorpay order object, which includes the order 'id'
    you'll need for the next step (payment link or checkout).
    """
    order = client.order.create({
        "amount": int(round(amount_inr * 100)),
        "currency": "INR",
        "receipt": receipt_id,
        "notes": notes or {},
    })
    return order


def create_payment_link(amount_inr: float, description: str, reference_id: str,
                         customer_name: str = "Test Buyer",
                         customer_email: str = "test@example.com",
                         customer_contact: str = "9123456780") -> dict:
    """
    Creates a Payment Link — a hosted Razorpay page you can open in a browser
    to actually complete a test payment using Razorpay's published test card
    numbers. This is the easiest way to manually verify Day 5 before any
    agent code exists.

    Returns the raw Razorpay payment link object; the 'short_url' field is
    what you open in a browser to pay.
    """
    link = client.payment_link.create({
        "amount": int(round(amount_inr * 100)),
        "currency": "INR",
        "description": description,
        "reference_id": reference_id,
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "contact": customer_contact,
        },
        "notify": {"sms": False, "email": False},
    })
    return link


def fetch_payment(payment_id: str) -> dict:
    """Fetches the current status of a payment by its ID — used after a
    webhook tells you something happened, to confirm details."""
    return client.payment.fetch(payment_id)


def verify_webhook_signature(payload_body: bytes, received_signature: str, webhook_secret: str) -> bool:
    """
    Verifies that a webhook actually came from Razorpay and wasn't spoofed.
    This is NOT optional in a real system — never trust an unverified webhook.
    """
    try:
        client.utility.verify_webhook_signature(
            payload_body.decode("utf-8"), received_signature, webhook_secret
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
