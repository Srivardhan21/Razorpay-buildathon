"""
tests/generate_scenarios.py

Builds tests/scenarios.json: a large, varied set of test cases run against
the validator to produce a real, measured error rate.

Two scenario types:
  - "single":   one proposal, checked against one mandate state.
  - "sequence": multiple proposals in order against the SAME mandate,
                with used_amount_inr updated after each approval — this is
                how we test cumulative spend (an agent trying to "split" a
                purchase into several smaller ones to sneak past the cap).

Run this whenever data/catalog.json changes, so scenarios stay in sync:
    python3 tests/generate_scenarios.py
"""

import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TESTS_DIR = Path(__file__).resolve().parent

random.seed(42)  # reproducible scenario generation

catalog = json.loads((DATA_DIR / "catalog.json").read_text())
active_in_stock = [p for p in catalog if p["active"] and p["stock"] > 0]
out_of_stock = [p for p in catalog if p["active"] and p["stock"] == 0]
delisted = [p for p in catalog if not p["active"]]

scenarios = []
sid = 0


def add(description, category, type_, **kwargs):
    global sid
    sid += 1
    scenarios.append({
        "id": f"S{sid:03d}",
        "description": description,
        "category": category,   # groups results in the harness report
        "type": type_,
        **kwargs,
    })


# ---------------------------------------------------------------------------
# 1. Valid single purchases — one per active, in-stock product
# ---------------------------------------------------------------------------
for p in active_in_stock:
    add(
        f"Valid purchase: 1x {p['name']}",
        category="valid_purchase",
        type_="single",
        proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"]},
        expected_approved=True,
        expected_error_code=None,
    )

# ---------------------------------------------------------------------------
# 2. Valid multi-quantity purchases (still within the Rs.3000 cap)
# ---------------------------------------------------------------------------
cheap_items = [p for p in active_in_stock if p["price_inr"] <= 1000]
for p in cheap_items:
    max_qty = min(p["stock"], 3000 // p["price_inr"])
    if max_qty >= 2:
        add(
            f"Valid multi-quantity purchase: {max_qty}x {p['name']}",
            category="valid_purchase",
            type_="single",
            proposal={"sku": p["sku"], "quantity": max_qty, "proposed_price_inr": p["price_inr"]},
            expected_approved=(p["price_inr"] * max_qty <= 3000),
            expected_error_code=None if (p["price_inr"] * max_qty <= 3000) else "MANDATE_CAP_EXCEEDED",
        )

# ---------------------------------------------------------------------------
# 3. Unknown SKU (typos, hallucinated SKUs, fake items)
# ---------------------------------------------------------------------------
fake_skus = ["SHOE-999", "APP-999", "SKU-0000", "SHOE-01", "shoe-001", "APP-1", "XYZ-001"]
for fake in fake_skus:
    add(
        f"Unknown SKU: {fake}",
        category="unknown_sku",
        type_="single",
        proposal={"sku": fake, "quantity": 1, "proposed_price_inr": 999},
        expected_approved=False,
        expected_error_code="SKU_NOT_FOUND",
    )

# ---------------------------------------------------------------------------
# 4. Delisted products — must never be sold even though they're "in the catalog"
# ---------------------------------------------------------------------------
for p in delisted:
    for qty in (1, 2):
        add(
            f"Delisted product: {qty}x {p['name']}",
            category="delisted_product",
            type_="single",
            proposal={"sku": p["sku"], "quantity": qty, "proposed_price_inr": p["price_inr"]},
            expected_approved=False,
            expected_error_code="PRODUCT_INACTIVE",
        )

# ---------------------------------------------------------------------------
# 5. Out-of-stock products
# ---------------------------------------------------------------------------
for p in out_of_stock:
    for qty in (1, 5):
        add(
            f"Out-of-stock product: {qty}x {p['name']}",
            category="out_of_stock",
            type_="single",
            proposal={"sku": p["sku"], "quantity": qty, "proposed_price_inr": p["price_inr"]},
            expected_approved=False,
            expected_error_code="INSUFFICIENT_STOCK",
        )

# ---------------------------------------------------------------------------
# 6. Insufficient stock (item exists and is active, but not enough units)
# ---------------------------------------------------------------------------
for p in active_in_stock:
    over_qty = p["stock"] + random.randint(1, 5)
    add(
        f"Request exceeds stock: {over_qty}x {p['name']} (only {p['stock']} available)",
        category="insufficient_stock",
        type_="single",
        proposal={"sku": p["sku"], "quantity": over_qty, "proposed_price_inr": p["price_inr"]},
        expected_approved=False,
        expected_error_code="INSUFFICIENT_STOCK",
    )

# ---------------------------------------------------------------------------
# 7. Price mismatch — the key adversarial case: agent agrees to a wrong price
# ---------------------------------------------------------------------------
for p in active_in_stock:
    # Under-priced (agent lowballing/being tricked into a discount that doesn't exist)
    add(
        f"Price mismatch (underquoted): {p['name']} proposed at Rs.{p['price_inr'] - 100} vs real Rs.{p['price_inr']}",
        category="price_mismatch",
        type_="single",
        proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": max(p["price_inr"] - 100, 1)},
        expected_approved=False,
        expected_error_code="PRICE_MISMATCH",
    )
    # Over-priced (agent overcharging, or hallucinated price)
    add(
        f"Price mismatch (overquoted): {p['name']} proposed at Rs.{p['price_inr'] + 250} vs real Rs.{p['price_inr']}",
        category="price_mismatch",
        type_="single",
        proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"] + 250},
        expected_approved=False,
        expected_error_code="PRICE_MISMATCH",
    )

# ---------------------------------------------------------------------------
# 8. Malformed / adversarial quantity values
# ---------------------------------------------------------------------------
bad_quantities = [0, -1, -5]
for i, qty in enumerate(bad_quantities):
    p = active_in_stock[i % len(active_in_stock)]
    add(
        f"Invalid quantity ({qty}) for {p['name']}",
        category="invalid_quantity",
        type_="single",
        proposal={"sku": p["sku"], "quantity": qty, "proposed_price_inr": p["price_inr"]},
        expected_approved=False,
        expected_error_code="INVALID_QUANTITY",
    )

# ---------------------------------------------------------------------------
# 9. Expired mandate — valid purchase, but the permission slip has lapsed
# ---------------------------------------------------------------------------
for p in random.sample(active_in_stock, k=min(5, len(active_in_stock))):
    add(
        f"Expired mandate attempting: {p['name']}",
        category="expired_mandate",
        type_="single",
        proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"]},
        now_offset_hours=30,  # mandate is only valid for 24h
        expected_approved=False,
        expected_error_code="MANDATE_EXPIRED",
    )

# ---------------------------------------------------------------------------
# 10. Revoked / exhausted mandate status
# ---------------------------------------------------------------------------
for status in ("revoked", "exhausted"):
    for p in random.sample(active_in_stock, k=min(3, len(active_in_stock))):
        add(
            f"Mandate status '{status}' attempting: {p['name']}",
            category="mandate_not_active",
            type_="single",
            proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"]},
            mandate_status_override=status,
            expected_approved=False,
            expected_error_code="MANDATE_NOT_ACTIVE",
        )

# ---------------------------------------------------------------------------
# 11. Spend cap exceeded — single purchase that alone blows the budget
# ---------------------------------------------------------------------------
expensive_items = [p for p in active_in_stock if p["price_inr"] > 3000]
if not expensive_items:
    # none in catalog by design (cap is 3000) — simulate via pre-used balance instead
    for p in random.sample(active_in_stock, k=min(6, len(active_in_stock))):
        preused = 3000 - p["price_inr"] + random.randint(1, 300)
        preused = max(preused, 0)
        add(
            f"Cap exceeded: {p['name']} with Rs.{preused} already used on the mandate",
            category="cap_exceeded",
            type_="single",
            proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"]},
            preused_amount_inr=preused,
            expected_approved=False,
            expected_error_code="MANDATE_CAP_EXCEEDED",
        )

# ---------------------------------------------------------------------------
# 12. Boundary cases — spending exactly at the cap should be approved,
#     not off-by-one rejected
# ---------------------------------------------------------------------------
for p in active_in_stock[:4]:
    preused = max(3000 - p["price_inr"], 0)
    add(
        f"Exactly at cap boundary: {p['name']} with Rs.{preused} already used",
        category="boundary_at_cap",
        type_="single",
        proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"]},
        preused_amount_inr=preused,
        expected_approved=True,
        expected_error_code=None,
    )
    add(
        f"One rupee over cap boundary: {p['name']} with Rs.{preused + 1} already used",
        category="boundary_over_cap",
        type_="single",
        proposal={"sku": p["sku"], "quantity": 1, "proposed_price_inr": p["price_inr"]},
        preused_amount_inr=preused + 1,
        expected_approved=False,
        expected_error_code="MANDATE_CAP_EXCEEDED",
    )

# ---------------------------------------------------------------------------
# 13. Adversarial sequences — the "split the purchase to dodge the cap" attack.
#     Each step alone looks fine; the cumulative total should eventually be
#     rejected once it would cross Rs.3000.
# ---------------------------------------------------------------------------
sequence_templates = [
    ["SHOE-002", "APP-004", "APP-003"],   # 1299 + 999 + 1599 = 3897 -> 3rd step rejected
    ["APP-001", "APP-001", "APP-001", "APP-001", "APP-001", "APP-001", "APP-001"],  # 7x499=3493 -> 7th rejected
    ["SHOE-005", "SHOE-005", "SHOE-005", "SHOE-005", "SHOE-005"],  # 5x699=3495 -> 5th rejected
]
for i, sku_sequence in enumerate(sequence_templates):
    steps = []
    running_total = 0
    for sku in sku_sequence:
        product = next(p for p in catalog if p["sku"] == sku)
        running_total += product["price_inr"]
        steps.append({
            "proposal": {"sku": sku, "quantity": 1, "proposed_price_inr": product["price_inr"]},
            "expected_approved": running_total <= 3000,
            "expected_error_code": None if running_total <= 3000 else "MANDATE_CAP_EXCEEDED",
        })
    add(
        f"Split-purchase sequence attempting to dodge the cap ({' -> '.join(sku_sequence)})",
        category="adversarial_sequence",
        type_="sequence",
        steps=steps,
    )

# ---------------------------------------------------------------------------
# 14. Mixed adversarial sequence: valid purchase, then a price-mismatch attempt
#     mid-session, then another valid purchase — checks the validator doesn't
#     get confused by session state after a rejection.
# ---------------------------------------------------------------------------
add(
    "Valid purchase, then price-mismatch attempt, then another valid purchase",
    category="adversarial_sequence",
    type_="sequence",
    steps=[
        {"proposal": {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499},
         "expected_approved": True, "expected_error_code": None},
        {"proposal": {"sku": "APP-004", "quantity": 1, "proposed_price_inr": 1},  # lowball attempt
         "expected_approved": False, "expected_error_code": "PRICE_MISMATCH"},
        {"proposal": {"sku": "APP-004", "quantity": 1, "proposed_price_inr": 999},  # correct price, retried
         "expected_approved": True, "expected_error_code": None},
    ],
)

TESTS_DIR.joinpath("scenarios.json").write_text(json.dumps(scenarios, indent=2))
print(f"Generated {len(scenarios)} scenarios -> tests/scenarios.json")

from collections import Counter
counts = Counter(s["category"] for s in scenarios)
for cat, n in sorted(counts.items()):
    print(f"  {cat}: {n}")
