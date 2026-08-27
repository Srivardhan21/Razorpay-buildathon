"""
tests/test_validator.py

Unit tests for core/validator.py, using the real data/catalog.json and
data/mandate.json so these tests exercise the actual data your demo will run
against, not synthetic stand-ins.

Run with:  pytest tests/test_validator.py -v
"""

import json
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.validator import validate_purchase

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_catalog():
    return json.loads((DATA_DIR / "catalog.json").read_text())


def load_mandate():
    return json.loads((DATA_DIR / "mandate.json").read_text())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_valid_purchase_is_approved():
    catalog = load_catalog()
    mandate = load_mandate()
    proposal = {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499}

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is True
    assert result.error_code is None
    assert result.details["total_price_inr"] == 499


# ---------------------------------------------------------------------------
# Rejection paths — one test per validator rule
# ---------------------------------------------------------------------------
def test_unknown_sku_is_rejected():
    catalog = load_catalog()
    mandate = load_mandate()
    proposal = {"sku": "SHOE-999", "quantity": 1, "proposed_price_inr": 999}

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is False
    assert result.error_code == "SKU_NOT_FOUND"


def test_delisted_product_is_rejected():
    catalog = load_catalog()
    mandate = load_mandate()
    # SHOE-006 is active: false in the sample catalog
    proposal = {"sku": "SHOE-006", "quantity": 1, "proposed_price_inr": 3999}

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is False
    assert result.error_code == "PRODUCT_INACTIVE"


def test_out_of_stock_is_rejected():
    catalog = load_catalog()
    mandate = load_mandate()
    # SHOE-003 has stock: 0 in the sample catalog
    proposal = {"sku": "SHOE-003", "quantity": 1, "proposed_price_inr": 3499}

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is False
    assert result.error_code == "INSUFFICIENT_STOCK"


def test_price_mismatch_is_rejected():
    """The core adversarial case: an agent (or a manipulated conversation)
    agrees to a price that doesn't match the real catalog."""
    catalog = load_catalog()
    mandate = load_mandate()
    proposal = {"sku": "APP-002", "quantity": 1, "proposed_price_inr": 999}  # real price is 1799

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is False
    assert result.error_code == "PRICE_MISMATCH"


def test_expired_mandate_is_rejected():
    catalog = load_catalog()
    mandate = load_mandate()
    proposal = {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499}

    # simulate checking the proposal after the mandate's expiry
    future = datetime.now(timezone.utc) + timedelta(days=2)

    result = validate_purchase(proposal, catalog, mandate, now=future)

    assert result.approved is False
    assert result.error_code == "MANDATE_EXPIRED"


def test_inactive_mandate_status_is_rejected():
    catalog = load_catalog()
    mandate = load_mandate()
    mandate["status"] = "revoked"
    proposal = {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499}

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is False
    assert result.error_code == "MANDATE_NOT_ACTIVE"


def test_spend_cap_exceeded_is_rejected():
    """The core adversarial case for the money limit: a single purchase or a
    cumulative sequence of them tries to exceed the mandate's max_amount_inr."""
    catalog = load_catalog()
    mandate = load_mandate()
    mandate["used_amount_inr"] = 2800  # only Rs.200 of headroom left
    proposal = {"sku": "APP-006", "quantity": 1, "proposed_price_inr": 2299}  # would push total to 5099

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is False
    assert result.error_code == "MANDATE_CAP_EXCEEDED"


def test_purchase_exactly_at_cap_is_approved():
    """Boundary case: spending exactly up to the cap should be allowed,
    not rejected off-by-one."""
    catalog = load_catalog()
    mandate = load_mandate()
    mandate["used_amount_inr"] = 2501
    proposal = {"sku": "APP-001", "quantity": 1, "proposed_price_inr": 499}  # totals exactly 3000

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is True
    assert result.details["new_used_amount_inr"] == 3000


def test_multi_quantity_price_is_checked_against_total():
    catalog = load_catalog()
    mandate = load_mandate()
    # buying 2 at the correct unit price of 699 -> total should be 1398
    proposal = {"sku": "SHOE-005", "quantity": 2, "proposed_price_inr": 699}

    result = validate_purchase(proposal, catalog, mandate)

    assert result.approved is True
    assert result.details["total_price_inr"] == 1398
