#!/usr/bin/env python3
"""P0-2: old paper alias and new validation module produce EQUIVALENT gate decisions."""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import momentum_scalp_paper_fast_path as legacy  # noqa: E402
import momentum_scalp_validation_fast_path as canonical  # noqa: E402

PASS, FAIL = [], []
NOW = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)
FRESH = {"ok": True, "age_minutes": 1, "last_price": 5.0}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def prop(**kw):
    base = {"id": 1, "symbol": "SCLP", "strategy_id": "momentum_scalp", "target_account": "alpaca_paper",
            "created_at": NOW - timedelta(minutes=5), "proposed_entry": 5.0, "proposed_stop": 4.6,
            "proposed_target1": 5.8, "rvol": 7, "float_m": 8, "price": 5.0, "route": "momentum_scalp",
            "route_actionability": "GO", "route_strategy_id": "momentum_scalp", "catalyst_verified": True}
    base.update(kw)
    return base


def main():
    # 1. The canonical evaluator IS the legacy evaluator (single source of truth — no divergence).
    check("canonical evaluate == legacy evaluate",
          canonical.evaluate_validation_fast_path is legacy.evaluate_paper_fast_path)

    # 2. Old and new produce identical decisions across a scenario sweep.
    scenarios = [prop(), prop(float_m=50), prop(route="watch_only", route_actionability="WAIT"),
                 prop(created_at=NOW - timedelta(minutes=45)), prop(catalyst_verified=False),
                 prop(target_account="schwab_roth_ira")]
    equiv = all(
        legacy.evaluate_paper_fast_path(p, now=NOW, quote=FRESH)["decision"]
        == canonical.evaluate_validation_fast_path(p, now=NOW, quote=FRESH)["decision"]
        for p in scenarios)
    check("old/new equivalent decisions across scenarios", equiv)

    # 3. Legacy submitter/logger wrappers map to canonical validation names (same functions).
    import validation_submitter as vs
    import validation_trade_logger as vl
    import proposal_paper_submitter as pps
    import paper_trade_logger as ptl
    check("submit_validation == legacy submit_paper", vs.submit_validation is pps.submit_paper)
    check("open_validation_trade == legacy open_paper_trade", vl.open_validation_trade is ptl.open_paper_trade)
    check("legacy table documented", vl.LEGACY_TABLE == "paper_trades")
    check("sandbox account identifier preserved", vs.SANDBOX_ACCOUNT == "alpaca_paper")

    # 4. Legacy paper CLI prints a deprecation note to stderr but still runs.
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "momentum_scalp_paper_fast_path.py"), "--dry-run"],
                       capture_output=True, text=True, timeout=60)
    check("legacy CLI prints deprecation note", "Deprecated alias" in r.stderr)
    check("legacy CLI still works (exit 0)", r.returncode == 0)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
