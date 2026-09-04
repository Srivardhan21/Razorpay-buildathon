"""
scripts/test_conversation_loop.py

Day 7 sanity check: run one complete buyer<->seller conversation end to end,
including real Razorpay order creation and a simulated payment outcome.

Run:
    python scripts/test_conversation_loop.py                 # normal success path
    python scripts/test_conversation_loop.py --fail-payment  # trigger the graceful-failure demo
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.conversation_loop import run_conversation

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fresh_mandate():
    """A clean, currently-valid mandate for this test run — doesn't depend
    on what day mandate.json's hardcoded sample dates happen to be."""
    m = json.loads((DATA_DIR / "mandate.json").read_text())
    now = datetime.now(timezone.utc)
    m["issued_at"] = now.isoformat()
    m["expires_at"] = (now + timedelta(hours=24)).isoformat()
    m["status"] = "active"
    m["used_amount_inr"] = 0
    return m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-payment", action="store_true")
    parser.add_argument("--goal", default="Buy one cotton crew-neck t-shirt.")
    args = parser.parse_args()

    catalog = json.loads((DATA_DIR / "catalog.json").read_text())
    mandate = fresh_mandate()

    print("=" * 70)
    print(f"GOAL: {args.goal}")
    print(f"MANDATE: max Rs.{mandate['max_amount_inr']}, expires in 24h")
    print(f"SIMULATE PAYMENT FAILURE: {args.fail_payment}")
    print("=" * 70 + "\n")

    result = run_conversation(
        goal=args.goal,
        mandate=mandate,
        catalog=catalog,
        force_payment_failure=args.fail_payment,
    )

    print("\n" + "=" * 70)
    print(f"OUTCOME: {result['outcome']}")
    print(f"TRANSACTION ID: {result['transaction_id']}")
    print(f"FINAL MANDATE STATE: used Rs.{result['final_mandate']['used_amount_inr']} "
          f"of Rs.{result['final_mandate']['max_amount_inr']} "
          f"(status: {result['final_mandate']['status']})")
    print("=" * 70)
    print("\nFull transcript logged to logs/session_transcript.jsonl")
    print(f"Filter by transaction_id={result['transaction_id']!r} to see just this run.")


if __name__ == "__main__":
    main()
