import sys
import json
import argparse
from pathlib import Path
from collections import OrderedDict

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "session_transcript.jsonl"

EVENT_LABELS = {
    "session_start":                 "SESSION STARTED",
    "buyer_message":                 "BUYER",
    "seller_message":                "SELLER",
    "validation_result":             "VALIDATOR",
    "order_created":                 "RAZORPAY ORDER CREATED",
    "order_creation_error":          "ORDER CREATION ERROR",
    "payment_outcome":               "PAYMENT OUTCOME",
    "mandate_updated":               "MANDATE UPDATED",
    "premature_completion_overridden": "SYSTEM GUARD TRIGGERED",
    "session_end":                   "SESSION ENDED",
}


def load_events():
    if not LOG_PATH.exists():
        print(f"No log file found at {LOG_PATH}. Run a conversation first (scripts/test_conversation_loop.py).")
        sys.exit(1)
    events = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def list_transactions(events):
    seen = OrderedDict()
    for e in events:
        tid = e["transaction_id"]
        if tid not in seen:
            seen[tid] = {"first_seen": e["timestamp"], "goal": None, "outcome": None}
        if e["event_type"] == "session_start":
            seen[tid]["goal"] = e["data"].get("goal")
        if e["event_type"] == "session_end":
            seen[tid]["outcome"] = e["data"].get("outcome")

    print(f"\n{len(seen)} transaction(s) found:\n")
    for tid, info in seen.items():
        print(f"  {tid}  |  {info['first_seen']}  |  outcome={info['outcome']}  |  goal={info['goal']}")
    print()


def format_event(e: dict) -> str:
    label = EVENT_LABELS.get(e["event_type"], e["event_type"].upper())
    ts = e["timestamp"]
    data = e["data"]

    if e["event_type"] == "session_start":
        body = f"goal: {data.get('goal')}"
    elif e["event_type"] in ("buyer_message",):
        body = data.get("message", "")
    elif e["event_type"] == "seller_message":
        body = data.get("reply", "")
        if data.get("proposal"):
            body += f"\n            proposal: {json.dumps(data['proposal'])}"
    elif e["event_type"] == "validation_result":
        status = "APPROVED" if data.get("approved") else f"REJECTED ({data.get('error_code')})"
        body = f"{status} — {data.get('reason')}"
    elif e["event_type"] == "order_created":
        body = f"order_id={data.get('order_id')}  amount=Rs.{data.get('total_price_inr')}"
    elif e["event_type"] == "order_creation_error":
        body = f"error: {data.get('error')}"
    elif e["event_type"] == "payment_outcome":
        body = f"status={data.get('status')}  order_id={data.get('order_id')}"
    elif e["event_type"] == "mandate_updated":
        body = f"used_amount_inr now {data.get('used_amount_inr')} / {data.get('max_amount_inr')}  (status: {data.get('status')})"
    elif e["event_type"] == "premature_completion_overridden":
        body = f"buyer tried to end the session early ({data.get('message')!r}) — forced to continue, no payment had succeeded yet"
    elif e["event_type"] == "session_end":
        body = f"outcome={data.get('outcome')}  final mandate used=Rs.{data.get('final_mandate', {}).get('used_amount_inr')}"
    else:
        body = json.dumps(data)

    return f"[{ts}] {label}\n            {body}"


def view_transaction(events, transaction_id: str):
    tx_events = [e for e in events if e["transaction_id"] == transaction_id]
    if not tx_events:
        print(f"No events found for transaction_id={transaction_id!r}")
        return

    print("\n" + "=" * 78)
    print(f"AUDIT TRAIL — transaction_id={transaction_id}")
    print("=" * 78 + "\n")
    for e in tx_events:
        print(format_event(e))
        print()
    print("=" * 78)
    print(f"{len(tx_events)} events total for this transaction.")
    print("=" * 78 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("transaction_id", nargs="?", help="the transaction_id to view")
    parser.add_argument("--list", action="store_true", help="list all transaction_ids in the log")
    parser.add_argument("--latest", action="store_true", help="view the most recently started transaction")
    args = parser.parse_args()

    events = load_events()

    if args.list:
        list_transactions(events)
        return

    if args.latest:
        session_starts = [e for e in events if e["event_type"] == "session_start"]
        if not session_starts:
            print("No sessions logged yet.")
            return
        view_transaction(events, session_starts[-1]["transaction_id"])
        return

    if not args.transaction_id:
        print("Provide a transaction_id, or use --list / --latest. Example:")
        print("  python logging_audit/view_transaction.py --list")
        print("  python logging_audit/view_transaction.py --latest")
        return

    view_transaction(events, args.transaction_id)


if __name__ == "__main__":
    main()
