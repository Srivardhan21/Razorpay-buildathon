from datetime import datetime, timezone


def apply_approved_purchase(mandate: dict, validation_details: dict) -> dict:
    """
    Call this ONLY after validate_purchase() has returned approved=True.
    Updates used_amount_inr to the new total, and flips status to
    'exhausted' if this purchase used up the last of the cap.

    validation_details is the ValidationResult.details dict from an
    approved validation call — it already contains the correct
    new_used_amount_inr, so this function doesn't recompute anything,
    it just applies what the validator already calculated.
    """
    mandate["used_amount_inr"] = validation_details["new_used_amount_inr"]

    if mandate["used_amount_inr"] >= mandate["max_amount_inr"]:
        mandate["status"] = "exhausted"

    return mandate


def revoke_mandate(mandate: dict, reason: str = "manually revoked") -> dict:
    """Manually cancels a mandate before it would naturally expire/exhaust.
    Not currently used by the main flow, but useful for a demo showing an
    admin/user pulling the plug mid-session."""
    mandate["status"] = "revoked"
    mandate["revoked_reason"] = reason
    mandate["revoked_at"] = datetime.now(timezone.utc).isoformat()
    return mandate
