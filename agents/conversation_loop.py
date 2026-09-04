"""
agents/conversation_loop.py

The orchestrator. Runs a full buyer <-> seller conversation, and for every
proposal the seller makes, routes it through the validator before anything
resembling a payment happens. This file is where the "LLM proposes, code
disposes" principle actually gets enforced at runtime.

Flow per turn:
  1. Buyer's message -> seller agent
  2. Seller replies, optionally with a structured proposal
  3. If there's a proposal: validate_purchase() checks it against the real
     catalog + mandate. Approved -> create a real Razorpay order, apply the
     mandate update, simulate a payment outcome. Rejected -> the reason is
     fed back into the conversation, not hidden.
  4. Buyer agent reacts to whatever happened (seller's reply, a rejection,
     or a payment outcome) and either continues or declares task_complete.

Loop is capped at max_turns so a confused conversation can't run forever.
"""

import sys
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.buyer_agent import get_buyer_response
from agents.seller_agent import get_seller_response
from core.validator import validate_purchase
from core.mandate_manager import apply_approved_purchase
from payments.razorpay_client import create_order

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
TRANSCRIPT_LOG = LOG_DIR / "session_transcript.jsonl"


def _log(transaction_id: str, event_type: str, data: dict):
    """Minimal append-only log. Day 8 replaces/extends this with the full
    audit_log.py, but the shape (transaction_id, timestamp, event_type,
    data) is designed to carry over unchanged."""
    with open(TRANSCRIPT_LOG, "a") as f:
        f.write(json.dumps({
            "transaction_id": transaction_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "data": data,
        }) + "\n")


def run_conversation(
    goal: str,
    mandate: dict,
    catalog: list[dict],
    max_turns: int = 8,
    force_payment_failure: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Runs one full buyer<->seller session.

    force_payment_failure: if True, the FIRST approved purchase in this
    session will be told its payment failed (a real Razorpay order is still
    created, but the payment outcome is simulated as failed) — this is how
    you deliberately trigger the graceful-failure demo on command.

    Returns {"transcript": [...], "final_mandate": {...}, "outcome": str}
    """
    transaction_id = str(uuid.uuid4())[:8]
    _log(transaction_id, "session_start", {"goal": goal})

    buyer_history: list[dict] = []
    seller_history: list[dict] = []
    transcript: list[dict] = []
    failure_already_triggered = False
    payment_succeeded = False
    had_rejection = False

    def record(speaker: str, text: str):
        transcript.append({"speaker": speaker, "text": text})
        if verbose:
            print(f"[{speaker}] {text}")

    # Buyer opens the conversation based on its goal.
    buyer_turn = get_buyer_response(goal, buyer_history, "Start the conversation with the seller.")
    buyer_history.append({"role": "assistant", "content": json.dumps(buyer_turn)})
    record("buyer", buyer_turn["message"])
    _log(transaction_id, "buyer_message", buyer_turn)

    current_buyer_message = buyer_turn["message"]

    for turn in range(max_turns):
        # --- Seller responds ---
        seller_turn = get_seller_response(current_buyer_message, seller_history, catalog)
        seller_history.append({"role": "user", "content": current_buyer_message})
        seller_history.append({"role": "assistant", "content": json.dumps(seller_turn)})
        record("seller", seller_turn["reply"])
        _log(transaction_id, "seller_message", seller_turn)

        incoming_for_buyer = seller_turn["reply"]

        # --- If the seller proposed something, validate it for real ---
        if seller_turn.get("proposal"):
            proposal = seller_turn["proposal"]
            result = validate_purchase(proposal, catalog, mandate)
            _log(transaction_id, "validation_result", result.to_dict())

            if result.approved:
                # Real order, real API call.
                try:
                    order = create_order(
                        amount_inr=result.details["total_price_inr"],
                        receipt_id=f"{transaction_id}-{turn}",
                        notes={"sku": proposal["sku"], "transaction_id": transaction_id},
                    )
                    _log(transaction_id, "order_created", {"order_id": order["id"], **result.details})
                except Exception as e:
                    # A real API failure (e.g. network) is itself a graceful-failure
                    # case worth surfacing to the buyer rather than crashing the loop.
                    _log(transaction_id, "order_creation_error", {"error": str(e)})
                    incoming_for_buyer = f"Order could not be created due to a system error: {e}"
                    buyer_turn = get_buyer_response(goal, buyer_history, incoming_for_buyer)
                    buyer_history.append({"role": "user", "content": incoming_for_buyer})
                    buyer_history.append({"role": "assistant", "content": json.dumps(buyer_turn)})
                    record("buyer", buyer_turn["message"])
                    if buyer_turn["task_complete"]:
                        break
                    current_buyer_message = buyer_turn["message"]
                    continue

                mandate_details_for_this_attempt = result.details  # keep for later, don't apply yet

                # Simulate the payment outcome (real checkout is blocked by
                # account activation — see Day 5 notes). This is the deliberate
                # trigger point for the one graceful-failure scenario.
                simulate_failure = force_payment_failure and not failure_already_triggered
                if simulate_failure:
                    failure_already_triggered = True
                    _log(transaction_id, "payment_outcome", {"status": "failed", "order_id": order["id"]})
                    incoming_for_buyer = (
                        f"Payment for order {order['id']} FAILED (simulated gateway error). "
                        f"The order was created but payment did not go through. "
                        f"No amount was deducted from your spending limit for this failed attempt."
                    )
                    # Deliberately NOT calling apply_approved_purchase here — a
                    # payment that never actually captured must not consume any
                    # of the mandate's spending cap. Only a confirmed success does.
                else:
                    mandate = apply_approved_purchase(mandate, mandate_details_for_this_attempt)
                    _log(transaction_id, "mandate_updated", mandate)
                    payment_succeeded = True
                    _log(transaction_id, "payment_outcome", {"status": "captured", "order_id": order["id"]})
                    incoming_for_buyer = (
                        f"Payment for order {order['id']} succeeded. "
                        f"{result.details['quantity']}x item purchased for Rs.{result.details['total_price_inr']}."
                    )
            else:
                # Rejected — the reason goes straight into the conversation, not hidden.
                had_rejection = True
                incoming_for_buyer = f"The seller's proposal was rejected: {result.reason}"

        # --- Buyer reacts to whatever just happened ---
        buyer_turn = get_buyer_response(goal, buyer_history, incoming_for_buyer)
        buyer_history.append({"role": "user", "content": incoming_for_buyer})
        buyer_history.append({"role": "assistant", "content": json.dumps(buyer_turn)})
        record("buyer", buyer_turn["message"])
        _log(transaction_id, "buyer_message", buyer_turn)

        # Defensive guard: don't trust a premature "task_complete" that fires
        # right after the buyer merely STATES intent to buy, before any
        # payment has actually succeeded or any rejection has legitimately
        # ended the session. This is the same "don't trust the LLM's own
        # claim, verify against real state" principle as the validator.
        if buyer_turn["task_complete"] and not payment_succeeded and not had_rejection:
            _log(transaction_id, "premature_completion_overridden", buyer_turn)
            if verbose:
                print("  [system] Ignoring premature task_complete — no payment has succeeded yet.")
            buyer_turn["task_complete"] = False
            current_buyer_message = buyer_turn["message"]
            continue

        if buyer_turn["task_complete"]:
            break

        current_buyer_message = buyer_turn["message"]

    outcome = "completed" if buyer_turn.get("task_complete") else "max_turns_reached"
    _log(transaction_id, "session_end", {"outcome": outcome, "final_mandate": mandate})

    return {"transcript": transcript, "final_mandate": mandate, "outcome": outcome, "transaction_id": transaction_id}