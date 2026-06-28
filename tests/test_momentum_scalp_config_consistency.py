#!/usr/bin/env python3
"""P0-3: momentum_scalp.yaml lifecycle-config consistency + validator.

Verifies the corrected config passes and that the validator catches each drift class
(float threshold, entry window, lifecycle TTL) on deliberately broken in-memory configs.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from strategy_config_validator import validate_strategy_config  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


# A minimal, internally-consistent intraday config matching the corrected momentum_scalp.
GOOD = {
    "timeframe_class": "INTRADAY",
    "screen_filters": {"max_float_m": 20, "preferred_max_float_m": 10},
    "intraday_execution": {
        "trading_window_et": {"start": "06:00", "end": "12:00"},
        "proposal_ttl_minutes": 30,
        "fast_path_account": "alpaca_paper",
        "fast_path_auto_approve": True,
        "max_price_drift_pct": 3.0,
    },
    "lifecycle": {"proposal_expiry_minutes": 30,
                  "source_of_truth": "intraday_execution.proposal_ttl_minutes"},
    "entry_criteria": [
        {"id": "FLOAT_LOW", "metric": "float_m", "operator": "lte", "value": 20},
        {"id": "ENTRY_WINDOW", "metric": "current_time_et", "operator": "lte", "value": 720},
    ],
}


def main():
    # 1. The real, on-disk momentum_scalp.yaml must be consistent after P0-3.
    real = validate_strategy_config("momentum_scalp")
    check("real momentum_scalp.yaml is consistent (no drift)", real["ok"])
    check("real config: intraday_execution is authoritative", real.get("authoritative") == "intraday_execution")
    check("real config resolves 30-min TTL", real.get("resolved", {}).get("proposal_ttl_minutes") == 30)

    # 2. Good in-memory config passes.
    check("good in-memory config passes", validate_strategy_config("x", copy.deepcopy(GOOD))["ok"])

    # 3. Float conflict is caught.
    bad = copy.deepcopy(GOOD)
    bad["entry_criteria"][0]["value"] = 100  # FLOAT_LOW=100 vs max_float_m=20
    r = validate_strategy_config("x", bad)
    check("float threshold conflict fails", not r["ok"])
    check("float conflict code present", any(e["code"] == "FLOAT_THRESHOLD_CONFLICT" for e in r["errors"]))

    # 4. Entry-window conflict is caught.
    bad = copy.deepcopy(GOOD)
    bad["entry_criteria"][1]["value"] = 810  # 13:30 vs intraday window end 12:00 (720)
    r = validate_strategy_config("x", bad)
    check("entry window conflict fails", not r["ok"])
    check("window conflict code present", any(e["code"] == "ENTRY_WINDOW_CONFLICT" for e in r["errors"]))

    # 5. Lifecycle TTL conflict (legacy hours) is caught.
    bad = copy.deepcopy(GOOD)
    bad["lifecycle"] = {"proposal_expiry_hours": 4}  # 240min vs 30min TTL
    r = validate_strategy_config("x", bad)
    check("lifecycle TTL hours conflict fails", not r["ok"])
    check("TTL conflict code present", any(e["code"] == "TTL_CONFLICT" for e in r["errors"]))

    # 6. Lifecycle minutes mismatch is caught.
    bad = copy.deepcopy(GOOD)
    bad["lifecycle"] = {"proposal_expiry_minutes": 45}
    r = validate_strategy_config("x", bad)
    check("lifecycle TTL minutes mismatch fails", not r["ok"])

    # 7. Non-intraday strategy is unaffected (no intraday_execution).
    r = validate_strategy_config("y", {"timeframe_class": "SHORT_SWING"})
    check("non-intraday strategy passes (not gated)", r["ok"])

    # 8. P0-2: stale human-facing window language (13:30 ET) is caught.
    bad = copy.deepcopy(GOOD)
    bad["prompt_context"] = {"key_questions": ["Are we within the entry window (before 13:30 ET)?"]}
    r = validate_strategy_config("x", bad)
    check("stale 13:30 prompt text fails", not r["ok"])
    check("stale window code present", any(e["code"] == "STALE_WINDOW_TEXT" for e in r["errors"]))

    # 9. The REAL momentum_scalp.yaml prompt_context has no stale 13:30 language.
    real = validate_strategy_config("momentum_scalp")
    check("real momentum_scalp has no stale window text",
          not any(e["code"] == "STALE_WINDOW_TEXT" for e in real["errors"]))

    # 10. Correct in-window prompt language (06:00–12:00) passes.
    ok_cfg = copy.deepcopy(GOOD)
    ok_cfg["prompt_context"] = {"key_questions": ["Are we within 06:00–12:00 ET?"]}
    check("correct window prompt text passes", validate_strategy_config("x", ok_cfg)["ok"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
