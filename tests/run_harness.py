import json
import sys
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.validator import validate_purchase

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TESTS_DIR = Path(__file__).resolve().parent


def build_mandate_for_scenario(base_mandate: dict, scenario: dict) -> tuple[dict, datetime]:
    """Applies a scenario's mandate-related overrides on top of a mandate
    that is freshly issued 'now', so results never depend on what day it is."""
    mandate = deepcopy(base_mandate)
    now = datetime.now(timezone.utc)

    mandate["issued_at"] = now.isoformat()
    mandate["expires_at"] = (now + timedelta(hours=24)).isoformat()
    mandate["status"] = scenario.get("mandate_status_override", "active")
    mandate["used_amount_inr"] = scenario.get("preused_amount_inr", 0)

    effective_now = now + timedelta(hours=scenario.get("now_offset_hours", 0))
    return mandate, effective_now


def run_single(catalog, base_mandate, scenario):
    mandate, effective_now = build_mandate_for_scenario(base_mandate, scenario)
    result = validate_purchase(scenario["proposal"], catalog, mandate, now=effective_now)

    passed = (
        result.approved == scenario["expected_approved"]
        and result.error_code == scenario["expected_error_code"]
    )
    return passed, [{
        "proposal": scenario["proposal"],
        "expected": (scenario["expected_approved"], scenario["expected_error_code"]),
        "actual": (result.approved, result.error_code),
        "actual_reason": result.reason,
    }]


def run_sequence(catalog, base_mandate, scenario):
    mandate, effective_now = build_mandate_for_scenario(base_mandate, scenario)
    step_results = []
    all_passed = True

    for step in scenario["steps"]:
        result = validate_purchase(step["proposal"], catalog, mandate, now=effective_now)
        step_passed = (
            result.approved == step["expected_approved"]
            and result.error_code == step["expected_error_code"]
        )
        all_passed = all_passed and step_passed
        step_results.append({
            "proposal": step["proposal"],
            "expected": (step["expected_approved"], step["expected_error_code"]),
            "actual": (result.approved, result.error_code),
            "actual_reason": result.reason,
        })
        # Mirror what mandate_manager will do in the real system: only a
        # genuinely approved purchase advances the running total.
        if result.approved:
            mandate["used_amount_inr"] = result.details["new_used_amount_inr"]

    return all_passed, step_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    catalog = json.loads((DATA_DIR / "catalog.json").read_text())
    base_mandate = json.loads((DATA_DIR / "mandate.json").read_text())
    scenarios = json.loads((TESTS_DIR / "scenarios.json").read_text())

    total_scenarios = 0
    total_checks = 0
    failed_scenarios = []
    category_stats = defaultdict(lambda: {"total": 0, "passed": 0})

    for scenario in scenarios:
        total_scenarios += 1
        if scenario["type"] == "single":
            passed, checks = run_single(catalog, base_mandate, scenario)
        else:
            passed, checks = run_sequence(catalog, base_mandate, scenario)

        total_checks += len(checks)
        category_stats[scenario["category"]]["total"] += 1
        if passed:
            category_stats[scenario["category"]]["passed"] += 1
        else:
            failed_scenarios.append((scenario, checks))

        if args.verbose:
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {scenario['id']}: {scenario['description']}")

    error_count = len(failed_scenarios)
    error_rate = (error_count / total_scenarios) * 100 if total_scenarios else 0.0

    print("\n" + "=" * 70)
    print("RESULTS BY CATEGORY")
    print("=" * 70)
    for cat, stats in sorted(category_stats.items()):
        rate = (stats["passed"] / stats["total"]) * 100 if stats["total"] else 0
        marker = "OK" if stats["passed"] == stats["total"] else "!!"
        print(f"  [{marker}] {cat:<22} {stats['passed']}/{stats['total']} passed ({rate:.1f}%)")

    if failed_scenarios:
        print("\n" + "=" * 70)
        print("FAILED SCENARIOS (full detail)")
        print("=" * 70)
        for scenario, checks in failed_scenarios:
            print(f"\n  {scenario['id']}: {scenario['description']}")
            for c in checks:
                if c["expected"] != c["actual"]:
                    print(f"    expected={c['expected']}  actual={c['actual']}")
                    print(f"    proposal={c['proposal']}")
                    print(f"    validator said: {c['actual_reason']}")

    print("\n" + "=" * 70)
    print(f"TOTAL SCENARIOS: {total_scenarios}   INDIVIDUAL CHECKS: {total_checks}")
    print(f"FAILED SCENARIOS: {error_count}")
    print(f"MEASURED ERROR RATE: {error_rate:.2f}%")
    print(f"TARGET: < 5.00%   ->   {'PASS' if error_rate < 5.0 else 'FAIL'}")
    print("=" * 70)

    return 0 if error_rate < 5.0 else 1


if __name__ == "__main__":
    sys.exit(main())
