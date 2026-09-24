#!/usr/bin/env python3
"""Scoring must not overwrite Momentum Scalp GO with warrior awareness lanes.

Mirrors the gate in scripts/scoring.py score_all(): squeeze always MANUAL_REVIEW;
low_price / micro_float preserve GO (same as qualifies_*); high_rvol only WAIT.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from high_rvol_manual_review import apply_high_rvol_manual_fields, qualifies_high_rvol_manual  # noqa: E402
from low_price_manual_review import apply_low_price_manual_fields  # noqa: E402
from micro_float_manual_review import apply_micro_float_manual_fields  # noqa: E402
from squeeze_manual_review import apply_squeeze_manual_fields  # noqa: E402


def check(name: str, cond: bool) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def apply_scoring_warrior_gate(scored: dict, *, squeeze_manual=False, micro_float_manual=False, low_price_manual=False) -> dict:
    """Copy of scoring.py warrior branch — keep in sync when that gate changes."""
    row = dict(scored)
    _dec = (row.get("decision") or "").upper()
    if squeeze_manual:
        apply_squeeze_manual_fields(row, rs_reason="REVERSE_SPLIT: test")
    elif micro_float_manual and _dec != "GO":
        apply_micro_float_manual_fields(row, mf_reason="MICRO_FLOAT_RVOL: test")
    elif low_price_manual and _dec != "GO":
        apply_low_price_manual_fields(row, lp_reason="LOW_PRICE_SPIKE: test")
    elif qualifies_high_rvol_manual(row):
        apply_high_rvol_manual_fields(row)
    return row


def main() -> None:
    ok = True

    hcti = {
        "symbol": "HCTI",
        "decision": "GO",
        "score": 46,
        "grade": "B",
        "price": 1.23,
        "change_pct": 42,
        "rvol": 123.0,
        "float_m": 14.85,
    }
    out = apply_scoring_warrior_gate(hcti, low_price_manual=True)
    ok &= check("HCTI GO preserved under low_price_manual", out["decision"] == "GO")
    ok &= check("HCTI no LOW_PRICE awareness when GO", out.get("awareness_status") != "LOW_PRICE")

    wait_low = {
        "symbol": "WAIT1",
        "decision": "WAIT",
        "score": 32,
        "price": 1.10,
        "change_pct": 55,
        "rvol": 20.0,
        "float_m": 8.0,
    }
    out_w = apply_scoring_warrior_gate(wait_low, low_price_manual=True)
    ok &= check("WAIT still upgrades to MANUAL_REVIEW", out_w["decision"] == "MANUAL_REVIEW")
    ok &= check("WAIT gets LOW_PRICE awareness", out_w.get("awareness_status") == "LOW_PRICE")

    go_micro = {
        "symbol": "MICROGO",
        "decision": "GO",
        "score": 44,
        "price": 5.0,
        "rvol": 12.0,
        "float_m": 0.8,
    }
    out_m = apply_scoring_warrior_gate(go_micro, micro_float_manual=True)
    ok &= check("GO preserved under micro_float_manual", out_m["decision"] == "GO")

    go_sq = {
        "symbol": "VBIO",
        "decision": "GO",
        "score": 45,
        "price": 2.5,
        "rvol": 268.0,
        "float_m": 0.89,
    }
    out_s = apply_scoring_warrior_gate(go_sq, squeeze_manual=True)
    ok &= check("squeeze still forces MANUAL_REVIEW (Ross)", out_s["decision"] == "MANUAL_REVIEW")
    ok &= check("squeeze awareness SQUEEZE", out_s.get("awareness_status") == "SQUEEZE")

    go_rvol = {"symbol": "GO1", "decision": "GO", "rvol": 40.0, "score": 50}
    out_r = apply_scoring_warrior_gate(go_rvol)
    ok &= check("high_rvol does not touch GO", out_r["decision"] == "GO")

    if not ok:
        sys.exit(1)
    print("All scoring warrior GO-preserve checks passed.")


if __name__ == "__main__":
    main()
