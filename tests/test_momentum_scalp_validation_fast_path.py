#!/usr/bin/env python3
"""P0-2/P0-5/P0-7: canonical validation fast path — same gates, validation taxonomy, cadence-safe."""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_validation_fast_path import (evaluate_validation_fast_path, run, heartbeat,
                                                 submission_allowed, SOURCE_TAG)  # noqa: E402

PASS, FAIL = [], []
NOW = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)
FRESH = {"ok": True, "age_minutes": 1, "last_price": 5.0}
STALE = {"ok": False, "reason": "stale", "age_minutes": 1100}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def prop(**kw):
    base = {"id": 1, "symbol": "SCLP", "strategy_id": "momentum_scalp", "target_account": "alpaca_paper",
            "created_at": NOW - timedelta(minutes=5), "expires_at": None,
            "proposed_entry": 5.0, "proposed_stop": 4.6, "proposed_target1": 5.8,
            "rvol": 7, "float_m": 8, "price": 5.0, "route": "momentum_scalp",
            "route_actionability": "GO", "route_strategy_id": "momentum_scalp",
            "catalyst_verified": True, "social_only": False}
    base.update(kw)
    return base


def D(p, **kw):
    return evaluate_validation_fast_path(p, now=kw.get("now", NOW), quote=kw.get("quote", FRESH))["decision"]


def main():
    # 1. Valid candidate → WOULD_SUBMIT_PAPER (canonical gate decision, no approval).
    check("valid → submit decision", D(prop()) == "WOULD_SUBMIT_PAPER")
    # 2. Boundaries (P0-7) preserved through the canonical alias.
    check("stale quote → DEFER", D(prop(), quote=STALE) == "DEFER")
    check("expired → REJECT", D(prop(created_at=NOW - timedelta(minutes=45))) == "REJECT")
    check("out-of-window → REJECT", D(prop(), now=NOW.replace(hour=20)) == "REJECT")
    check("social_only → REJECT", D(prop(social_only=True)) == "REJECT")
    check("large_float_social_scout → REJECT",
          D(prop(route="large_float_social_scout", route_actionability="MANUAL_REVIEW")) == "REJECT")
    check("watch_only → REJECT", D(prop(route="watch_only", route_actionability="WAIT")) == "REJECT")
    check("float>20 → REJECT", D(prop(float_m=50)) == "REJECT")
    check("non-paper account → REJECT", D(prop(target_account="schwab_roth_ira")) == "REJECT")

    # 3. run() emits validation taxonomy with legacy aliases.
    rep = run(dry_run=True)
    if rep.get("ok"):
        check("run emits validation_fast_path", rep.get("validation_fast_path") is True)
        check("run emits would_submit_validation", "would_submit_validation" in rep)
        check("run emits sandbox_account=alpaca_paper", rep.get("sandbox_account") == "alpaca_paper")
        check("run keeps legacy_aliases", "paper_fast_path" in (rep.get("legacy_aliases") or {}))
        check("source tag canonical", rep.get("source_tag") == SOURCE_TAG)
        check("default mode is dry_run", rep.get("mode") == "dry_run")
        check("heartbeat renders", "validation fast-path" in heartbeat(rep))
    else:
        check("run degrades safely (WARN)", rep.get("status") == "WARN")

    # 4. Cadence dedup/limits (P0-5).
    check("open trade blocks duplicate", submission_allowed(1, 0)[0] is False)
    check("max daily blocks", submission_allowed(0, 3, {"max_daily_trades": 3})[0] is False)

    # 5. No live broker symbols in the canonical module.
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "momentum_scalp_validation_fast_path.py")).read()
    check("no live broker symbols", all(s not in src for s in ("schwab_transport", "place_order(", "submit_order(")))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
