import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from payments.razorpay_client import create_order, create_payment_link

TEST_PRODUCT_NAME = "Cotton crew-neck t-shirt"
TEST_PRICE_INR = 499


def main():
    print(f"Creating order for '{TEST_PRODUCT_NAME}' at Rs.{TEST_PRICE_INR}...")
    order = create_order(
        amount_inr=TEST_PRICE_INR,
        receipt_id="manual-test-001",
        notes={"product": TEST_PRODUCT_NAME, "purpose": "Day 5 manual sanity check"},
    )
    print(f"Order created: {order['id']}  status={order['status']}")

    print("\nCreating payment link...")
    link = create_payment_link(
        amount_inr=TEST_PRICE_INR,
        description=f"Test purchase: {TEST_PRODUCT_NAME}",
        reference_id="manual-test-001",
    )
    print(f"Payment link created: {link['short_url']}")

    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print(f"1. Open this URL in your browser:\n   {link['short_url']}")
    print("2. Pay using a Razorpay TEST card — do NOT use a real card, this is test mode.")
    print("   Test card number: 4111 1111 1111 1111")
    print("   Any future expiry date, any 3-digit CVV, any name.")
    print("   For a FAILED payment test instead, use: 4000 0000 0000 0002")
    print("3. If your webhook_server.py + ngrok are running, watch that terminal —")
    print("   you should see 'payment.captured' (or 'payment.failed') logged there")
    print("   within a few seconds of completing the payment.")
    print("4. Confirm the event landed in logs/webhook_events.jsonl")
    print("=" * 70)


if __name__ == "__main__":
    main()
