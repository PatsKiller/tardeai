#!/usr/bin/env python3
"""P0-6: deterministic pre-submit validation quality gates."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_validation_fast_path import validation_quality_gate as Q  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def good(**kw):
    base = {"spread_pct": 1.0, "halted": False, "reverse_split_recent": False,
            "offering_dilution_risk": False, "same_sector_open": False, "rr": 2.5,
            "liquidity_known": True, "catalyst_still_valid": True, "sector": "Tech"}
    base.update(kw)
    return base


def main():
    cfg = {"max_spread_pct": 5.0}
    check("good candidate PASS", Q(good(), cfg)["decision"] == "PASS")

    # Hard rejects.
    check("wide spread REJECT", Q(good(spread_pct=9.0), cfg)["decision"] == "REJECT")
    check("recent halt REJECT", Q(good(halted=True), cfg)["decision"] == "REJECT")
    check("recent reverse split REJECT", Q(good(reverse_split_recent=True), cfg)["decision"] == "REJECT")
    check("offering/dilution REJECT", Q(good(offering_dilution_risk=True), cfg)["decision"] == "REJECT")
    check("same-sector concentration REJECT", Q(good(same_sector_open=True), cfg)["decision"] == "REJECT")
    check("R:R below min REJECT", Q(good(rr=1.0), cfg)["decision"] == "REJECT")

    # Critical unknowns DEFER.
    r = Q(good(spread_pct=None, liquidity_known=False), cfg)
    check("unknown spread+liquidity DEFER", r["decision"] == "DEFER" and any("DEFER_DATA_UNKNOWN" in c for c in r["reason_codes"]))
    check("stale catalyst DEFER", Q(good(catalyst_still_valid=False), cfg)["decision"] == "DEFER")

    # Non-critical missing → WARN but PASS.
    r = Q(good(sector=None), cfg)
    check("missing sector → PASS with WARN", r["decision"] == "PASS"
          and any("WARN_DATA_MISSING" in w for w in r["warnings"]))
    r = Q(good(rr=1.7), cfg)
    check("R:R 1.7 passes with preferred warning",
          r["decision"] == "PASS" and any("PREFERRED" in w for w in r["warnings"]))

    # Reverse split explicitly allowed → not rejected.
    check("reverse split allowed → not rejected on that ground",
          Q(good(reverse_split_recent=True, reverse_split_allowed=True), cfg)["decision"] == "PASS")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
