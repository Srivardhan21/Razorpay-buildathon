# What broke, and how we fixed it

Seven real issues came up during development, in roughly the order we hit them. None were hidden or smoothed over — each one changed the actual code, and most of them exposed something we wouldn't have caught by only testing the happy path.

## 1. Missing quantity validation (caught before agents even existed)

**What happened:** while writing `tests/test_validator.py`, we needed a test for "what if quantity is 0 or negative," and realized the validator had no check for this at all — `total_price = price * quantity` would silently produce a negative or zero total, which could have interacted unpredictably with the spending cap check.

**Fix:** added an explicit `INVALID_QUANTITY` check as the first rule the validator runs, rejecting anything that isn't a positive integer.

**Why it matters:** this was caught purely by writing tests before the agents existed, and before any real conversation could have triggered it — a direct payoff of testing the boring deterministic layer first, in isolation, rather than only testing it indirectly through agent behavior later.

## 2. Razorpay rejected our placeholder phone number

**What happened:** the first live call to `create_payment_link` failed with `"Recurring digits in customer contact are disallowed"` — we'd used `9999999999` as a placeholder.

**Fix:** switched to a non-repeating placeholder number (`9123456780`).

**Why it matters:** a small thing, but a good example of a real API's validation rules not matching what looks like a reasonable placeholder — worth knowing before it happens on stage during a demo.

## 3. Live checkout blocked by account activation, not by our code

**What happened:** test payments failed at the checkout page — first with `"International cards are not supported"` on a widely-documented generic test card, then UPI wasn't offered as a payment method at all. Trying a second, different domestic test card also failed.

**Root cause:** Razorpay's Test Mode doesn't require KYC/GST for API access (order creation and payment link generation both worked immediately), but certain checkout-page payment methods are gated behind account activation status regardless of Test Mode.

**Fix:** rather than blocking on KYC (which we don't need for this project and didn't want to pursue given the timeline), we verified the webhook-handling logic independently — `scripts/simulate_webhook.py` sends a payload shaped exactly like a real Razorpay event, signed with the same HMAC-SHA256 method Razorpay actually uses, exercising the identical signature-verification and event-handling code a real webhook would trigger.

**Why it matters:** this let us separate "is our integration correct" from "is our account fully activated" — the former was provably yes, independent of the latter.

## 4. Groq deprecated our model mid-build

**What happened:** `agents/seller_agent.py` failed on its first real call with `model_not_found` for `llama-3.3-70b-versatile`.

**Root cause:** Groq deprecated that model in favor of `openai/gpt-oss-120b` for general-purpose workloads, and it was fully removed from the API by the time we ran this.

**Fix:** switched both agents to `openai/gpt-oss-120b`.

**Why it matters:** a reminder that the fast-moving model landscape is itself a dependency risk worth designing for — the model name lives in one place (`.env` / a single default constant), not hardcoded in multiple files, specifically so this kind of swap is a one-line change.

## 5. The buyer agent declared victory too early

**What happened:** in the first full end-to-end run, the buyer said "I'll take one, please proceed with the order" and immediately reported `task_complete: true` — before the seller had even turned that into a structured proposal, before the validator ran, before any order existed. The loop stopped there. Confirmed by checking the mandate's `used_amount_inr`, which was still 0 after a session that appeared to "complete."

**Root cause:** the buyer's prompt conflated *stating intent* to buy with the *purchase actually being done*.

**Fix, in two layers:**
- Rewrote the buyer's system prompt to explicitly state that confirming intent is not completion — only an actual payment success (or a legitimate give-up after rejection) counts.
- Added a deterministic code-level guard in `conversation_loop.py` that refuses to honor `task_complete: true` unless a payment has actually succeeded or a real rejection occurred — the same "don't trust the agent's own claim, verify against real state" principle the validator itself is built on.

**Why it matters:** this is the clearest example in the whole project of why the validator pattern needs to extend beyond just the payment step — anywhere an agent self-reports a state, that claim needs an independent check.

## 6. Failed payments were incorrectly consuming the spending cap

**What happened:** running the `--fail-payment` test (payment fails, buyer retries, retry succeeds) produced a final `used_amount_inr` of 998 for a single ₹499 t-shirt — double what it should have been.

**Root cause:** the mandate was being updated immediately after validator *approval*, before the payment outcome was known. Both the failed attempt and the successful retry each independently deducted ₹499, even though real money only moved once.

**Fix:** moved the mandate update (`apply_approved_purchase`) to only fire after a payment is confirmed *captured*, never on approval alone. A failed payment now correctly costs nothing against the cap.

**Why it matters:** this is a real-world-relevant bug — without this fix, a buyer with a flaky payment method could get artificially locked out by their own spending limit despite never successfully spending that much, which is exactly the kind of subtle correctness issue the ₹3,000/24-hour mandate design is supposed to prevent, not cause.

## 7. Retries sometimes stalled instead of re-proposing

**What happened:** in one run of the same failure/retry test, after the payment failed and the buyer asked to retry, the seller responded with reassurance text ("we'll notify you once it's confirmed") but never re-emitted a structured `proposal`. With nothing for the validator to check, no second order was created, and the conversation looped until `max_turns_reached` without ever completing.

**Root cause:** the seller's prompt told it to propose "when the buyer has clearly agreed to purchase," but didn't explicitly cover the retry case — the model apparently treated the original proposal as already having been made and didn't consider a retry request as needing a fresh one.

**Fix:** added an explicit rule to the seller's prompt: any retry request must produce a fresh proposal with the same SKU/quantity/price, every time, not just on the first attempt.

**Why it matters:** a good concrete example of structured-output reliability being genuinely harder than it looks — the model wasn't "wrong" in a way that broke JSON parsing, it just made a reasonable-sounding but incorrect judgment call about when action was needed, which only surfaced by actually testing the adversarial retry path rather than the happy path.

---

**Pattern across all seven:** the deterministic layers (validator, mandate manager) were solid from day one and caught issues in themselves early via unit tests. Nearly every bug that made it further than that lived in the *seams* between the LLM agents and the deterministic code — exactly where "trust the agent's output, act on it directly" would have been dangerous, and exactly why the project is built around never doing that.
