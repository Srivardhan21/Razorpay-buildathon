"""
core/validator.py

The single gatekeeper between an agent's proposed purchase and any real
payment action. Every check here is plain, deterministic Python — no LLM
calls, no "judgment calls". A proposal either satisfies every rule or it
doesn't. This is the piece the whole project's trust claim rests on, so
keep it boring on purpose.

A "proposal" is what the buyer/seller agents agree on, expressed as a
plain dict — never trust an agent's own claim about whether something is
valid; always re-derive the truth from catalog.json and mandate.json.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Result object — every validation call returns exactly one of these.
# Kept simple and serializable so it can be written straight to the audit log.
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    approved: bool
    reason: str                       # human-readable, goes straight into the audit log
    error_code: Optional[str] = None  # machine-readable, used by tests/harness
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "error_code": self.error_code,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_iso(ts: str) -> datetime:
    """Parses an ISO 8601 timestamp (with or without trailing 'Z') into an
    aware UTC datetime, so it can be safely compared to datetime.now(timezone.utc)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _find_product(catalog: list[dict], sku: str) -> Optional[dict]:
    return next((p for p in catalog if p["sku"] == sku), None)


# ---------------------------------------------------------------------------
# The main entry point
# ---------------------------------------------------------------------------
def validate_purchase(
    proposal: dict,
    catalog: list[dict],
    mandate: dict,
    now: Optional[datetime] = None,
) -> ValidationResult:
    """
    Checks a proposed purchase against the real catalog and the active mandate.

    proposal is expected to look like:
        {
            "sku": "SHOE-001",
            "quantity": 1,
            "proposed_price_inr": 2499   # what the agents agreed on — must match catalog
        }

    Returns a ValidationResult. Approval requires ALL of the following:
      1. sku exists in the catalog
      2. product is active (not delisted)
      3. stock is sufficient for the requested quantity
      4. proposed_price_inr exactly matches the catalog price for that sku
      5. mandate.status == "active"
      6. mandate has not expired (now < expires_at)
      7. mandate.scope allows this purchase (currently: any_active_catalog_sku)
      8. used_amount_inr + total price <= max_amount_inr

    Each failure returns immediately with a specific error_code, so the
    audit log always records exactly which rule stopped the purchase —
    never a generic "rejected".
    """
    now = now or datetime.now(timezone.utc)

    sku = proposal.get("sku")
    quantity = proposal.get("quantity", 1)
    proposed_price = proposal.get("proposed_price_inr")

    # --- 1. SKU must exist -------------------------------------------------
    product = _find_product(catalog, sku)
    if product is None:
        return ValidationResult(
            approved=False,
            reason=f"SKU '{sku}' does not exist in the catalog.",
            error_code="SKU_NOT_FOUND",
            details={"sku": sku},
        )

    # --- 2. Product must be active (not delisted) --------------------------
    if not product["active"]:
        return ValidationResult(
            approved=False,
            reason=f"'{product['name']}' ({sku}) is delisted and cannot be sold.",
            error_code="PRODUCT_INACTIVE",
            details={"sku": sku},
        )

    # --- 3. Stock must be sufficient ---------------------------------------
    if product["stock"] < quantity:
        return ValidationResult(
            approved=False,
            reason=(
                f"Requested quantity ({quantity}) exceeds available stock "
                f"({product['stock']}) for '{product['name']}'."
            ),
            error_code="INSUFFICIENT_STOCK",
            details={"sku": sku, "requested": quantity, "available": product["stock"]},
        )

    # --- 4. Price must match the catalog exactly ----------------------------
    # This is the check that stops an agent (or a manipulated conversation)
    # from agreeing to a different price than what the seller actually sells at.
    if proposed_price != product["price_inr"]:
        return ValidationResult(
            approved=False,
            reason=(
                f"Proposed price (Rs.{proposed_price}) does not match the "
                f"catalog price (Rs.{product['price_inr']}) for '{product['name']}'."
            ),
            error_code="PRICE_MISMATCH",
            details={
                "sku": sku,
                "proposed_price_inr": proposed_price,
                "catalog_price_inr": product["price_inr"],
            },
        )

    total_price = product["price_inr"] * quantity

    # --- 5. Mandate must be active ------------------------------------------
    if mandate["status"] != "active":
        return ValidationResult(
            approved=False,
            reason=f"Mandate '{mandate['mandate_id']}' is not active (status: {mandate['status']}).",
            error_code="MANDATE_NOT_ACTIVE",
            details={"mandate_id": mandate["mandate_id"], "status": mandate["status"]},
        )

    # --- 6. Mandate must not have expired ------------------------------------
    expires_at = _parse_iso(mandate["expires_at"])
    if now >= expires_at:
        return ValidationResult(
            approved=False,
            reason=f"Mandate '{mandate['mandate_id']}' expired at {mandate['expires_at']}.",
            error_code="MANDATE_EXPIRED",
            details={"mandate_id": mandate["mandate_id"], "expires_at": mandate["expires_at"]},
        )

    # --- 7. Scope check --------------------------------------------------------
    # Currently the only supported scope means "any active catalog SKU is fine",
    # which we've already confirmed above (checks 1-2). This step exists so that
    # adding a narrower scope later (e.g. "footwear only") is a one-line change
    # here, not a redesign.
    if mandate["scope"] != "any_active_catalog_sku":
        return ValidationResult(
            approved=False,
            reason=f"Unrecognized mandate scope '{mandate['scope']}'.",
            error_code="UNKNOWN_SCOPE",
            details={"scope": mandate["scope"]},
        )

    # --- 8. Spending cap check ---------------------------------------------
    projected_total = mandate["used_amount_inr"] + total_price
    if projected_total > mandate["max_amount_inr"]:
        return ValidationResult(
            approved=False,
            reason=(
                f"This purchase (Rs.{total_price}) would bring total spend to "
                f"Rs.{projected_total}, exceeding the mandate cap of "
                f"Rs.{mandate['max_amount_inr']}."
            ),
            error_code="MANDATE_CAP_EXCEEDED",
            details={
                "mandate_id": mandate["mandate_id"],
                "used_amount_inr": mandate["used_amount_inr"],
                "attempted_total_inr": total_price,
                "max_amount_inr": mandate["max_amount_inr"],
            },
        )

    # --- All checks passed ---------------------------------------------------
    return ValidationResult(
        approved=True,
        reason=f"Approved: {quantity} x '{product['name']}' ({sku}) for Rs.{total_price}.",
        error_code=None,
        details={
            "sku": sku,
            "quantity": quantity,
            "total_price_inr": total_price,
            "mandate_id": mandate["mandate_id"],
            "new_used_amount_inr": projected_total,  # caller applies this via mandate_manager
        },
    )
