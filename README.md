# Agentic Commerce Demo — Razorpay AI Buildathon 2026

**Track 01: AI Growth & Agentic Commerce.** A merchant made transactable by an AI buyer, built on Razorpay's test-mode APIs, with every money action explainable, bounded, and gated.

## What this is

Two AI agents — a buyer and a seller — negotiate a purchase in natural language. Every proposed purchase is checked by a deterministic validator (no LLM involved) against a real product catalog and a spending mandate before any payment is attempted. Every decision, approval, rejection, and payment outcome is written to a queryable audit trail.

**The core principle: the LLM proposes, the code disposes.** Neither agent can move money on its own — a proposal only becomes a real Razorpay order after passing a fixed set of deterministic checks.

## Locked spec

We built a two-agent agentic commerce demo on Razorpay's test-mode APIs: a buyer agent that interprets natural-language purchase requests and a seller agent that manages a fixed catalog of 12 products (a small apparel/footwear store), with every proposed purchase passing through a deterministic validator that checks price accuracy, stock availability, and a pre-set spending mandate (max ₹3,000, valid for 24 hours, restricted to catalog SKUs) before any Razorpay Order is created; every agent decision, validation result, and payment outcome is written to an audit log queryable by transaction; and the system explicitly handles one failure scenario end-to-end — a payment that fails after order creation — by having the buyer agent detect the failure, ask to retry, and complete successfully on the second attempt, all logged, instead of crashing or falsely reporting success.

## Architecture

```
Buyer Agent  <---->  Seller Agent
     |                    |
     |            (reads real catalog)
     |                    |
     +----> proposal ----->
                           |
                           v
                  ┌─────────────────┐
                  │    VALIDATOR     │   <-- deterministic, no LLM
                  │  (core/validator.py)
                  └─────────────────┘
                   checks: SKU exists, not delisted, stock sufficient,
                   price matches catalog exactly, mandate active & not
                   expired, spend stays under cap
                           |
                    approved? ---- no ----> rejection reason fed back
                           |                 into the conversation
                          yes
                           |
                           v
                  Razorpay Order created (test mode)
                           |
                           v
                  Payment outcome (captured / failed)
                           |
                           v
                  Mandate updated -- ONLY on confirmed capture,
                  never on a failed attempt
                           |
                           v
                  Every step logged to the audit trail
```

Layers, and where each lives in this repo:

| Layer | File | What it does |
|---|---|---|
| Catalog | `data/catalog.json` | 12 real products, source of truth for name/price/stock |
| Mandate | `data/mandate.json` | The spending permission slip: ₹3,000 cap, 24h validity |
| Validator | `core/validator.py` | Deterministic gate — the only thing that can approve a purchase |
| Mandate manager | `core/mandate_manager.py` | The only place mandate state is mutated, and only on confirmed payment |
| Seller agent | `agents/seller_agent.py` | Reads the catalog, proposes purchases in structured JSON |
| Buyer agent | `agents/buyer_agent.py` | Pursues a shopping goal, reacts to rejections/failures |
| Orchestrator | `agents/conversation_loop.py` | Wires everything together, enforces "propose, don't execute" |
| Payments | `payments/razorpay_client.py`, `payments/webhook_server.py` | Real Razorpay test-mode orders + signed webhook verification |
| Audit trail | `logging_audit/view_transaction.py` | Pretty-prints one transaction's complete history |
| Tests | `tests/` | 84 scenarios, 98 individual checks against the validator |

This mirrors, at small scale, the layering the industry is converging on for agentic commerce: a catalog/discovery layer (similar in spirit to ACP's product feeds), a bounded authorization layer (conceptually close to AP2's mandates and NPCI's proposed UAP / the already-live UPI Reserve Pay pattern), and a settlement layer (Razorpay).

## Measured results

**Validator error rate: 0.00%** across 84 scenarios (98 individual checks), covering:

- Valid purchases across all in-stock products
- Unknown SKUs, delisted products, out-of-stock items
- Price mismatches (both under- and over-quoted) — the key adversarial case
- Invalid/malformed quantities
- Expired and revoked mandates
- Spending cap exceeded, including exact-boundary cases (spending exactly at the cap is approved, one rupee over is rejected)
- **Split-purchase sequences** — an agent attempting to break a purchase into several smaller ones to dodge the ₹3,000 cap

Reproduce it yourself:
```
python tests/generate_scenarios.py
python tests/run_harness.py
```

The full agent-to-agent pipeline (buyer ↔ seller ↔ validator ↔ Razorpay) was verified through multiple real, manually-run conversations rather than a large automated batch, since conversational LLM behavior is non-deterministic — this surfaced three real bugs during development (see `docs/what_broke.md`), which is arguably stronger evidence of rigor than a clean automated number would have been.

## The audit trail, for real

Every event in every conversation is logged to `logs/session_transcript.jsonl` and can be viewed per-transaction:

```
python logging_audit/view_transaction.py --list
python logging_audit/view_transaction.py <transaction_id>
```

Real example from this repo — a purchase where the payment failed, the buyer asked to retry, and the retry succeeded, with the mandate correctly charged only once:

```
[SESSION STARTED]     goal: Buy one cotton crew-neck t-shirt.
[BUYER]                Hello, I'm interested in purchasing a cotton crew-neck t-shirt...
[SELLER]               The Cotton crew-neck t-shirt (SKU APP-001) is priced at Rs.499...
[BUYER]                I would like to order 1 unit in size M. Please send the proposal.
[SELLER]               proposal: {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499}
[VALIDATOR]            APPROVED — 1 x 'Cotton crew-neck t-shirt' (APP-001) for Rs.499.
[RAZORPAY ORDER]       order_TXvT8BkXqoGcET  amount=Rs.499
[PAYMENT OUTCOME]      status=failed
[BUYER]                I see the payment failed. Could we please try the payment again?
[SELLER]               proposal: {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499}
[VALIDATOR]            APPROVED — 1 x 'Cotton crew-neck t-shirt' (APP-001) for Rs.499.
[RAZORPAY ORDER]       order_TXvTAJMv7S6PSf  amount=Rs.499
[MANDATE UPDATED]      used_amount_inr now 499 / 3000   <-- only charged once, not twice
[PAYMENT OUTCOME]      status=captured
[BUYER]                Thank you, the payment succeeded...
[SESSION ENDED]        outcome=completed
```

## Known limitations

- **Live checkout is blocked by Razorpay account activation**, not by anything in this code — order creation and payment-link generation both work against the real test-mode API (confirmed with real order IDs), but the hosted checkout page rejects test cards as "international" and UPI isn't enabled pending KYC, which isn't required for Test Mode functionality otherwise. Worked around by testing the webhook handler against a correctly HMAC-signed simulated payload (`scripts/simulate_webhook.py`), exercising the identical verification and event-handling code a real webhook would trigger.
- Single merchant, 12 products, no multi-merchant support — intentionally out of scope per the locked spec.
- No UI beyond terminal output — intentional, to prioritize the trust architecture over polish given the timeline.

## How to run it

```
pip install -r requirements.txt
# copy .env.example to .env and fill in your own Razorpay test-mode keys and Groq API key

python scripts/test_manual_payment.py        # confirms Razorpay integration works
python scripts/test_seller_agent.py          # seller agent sanity check
python scripts/test_conversation_loop.py     # full end-to-end run
python scripts/test_conversation_loop.py --fail-payment   # the graceful-failure demo

python tests/run_harness.py                  # validator error-rate measurement
python logging_audit/view_transaction.py --latest   # view the audit trail of your last run
```

## Stack

- **Agents:** Groq API, `openai/gpt-oss-120b`
- **Payments:** Razorpay test-mode (Orders, Payment Links, Webhooks)
- **Language:** Python