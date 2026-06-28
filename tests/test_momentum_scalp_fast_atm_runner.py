#!/usr/bin/env python3
"""P0-7: paper-only fast ATM runner — eligibility gates, no weakening, no live broker path."""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_fast_atm_runner import evaluate_fast_atm  # noqa: E402

PASS, FAIL = [], []
# 2026-06-29 09:30 ET == 13:30 UTC (inside 06:00–12:00 ET window).
NOW = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)
FRESH = {"ok": True, "age_minutes": 1}
STALE = {"ok": False, "age_minutes": 1100}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def prop(**kw):
    base = {"id": 1, "symbol": "SCLP", "strategy_id": "momentum_scalp", "target_account": "alpaca_paper",
            "created_at": NOW - timedelta(minutes=5), "expires_at": None,
            "lifecycle_status": "ENTRY_ZONE_VALID", "route": "momentum_scalp",
            "route_actionability": "GO"}
    base.update(kw)
    return base


def main():
    # 1. Fresh in-window micro-cap momentum_scalp → WOULD_APPROVE.
    check("fresh in-window → WOULD_APPROVE",
          evaluate_fast_atm(prop(), now=NOW, quote=FRESH)["decision"] == "WOULD_APPROVE")

    # 2. Stale quote → WOULD_DEFER (never weaken freshness).
    check("stale quote → WOULD_DEFER",
          evaluate_fast_atm(prop(), now=NOW, quote=STALE)["decision"] == "WOULD_DEFER")

    # 3. Expired proposal (45 min old, 30-min TTL) → WOULD_REJECT.
    check("expired proposal → WOULD_REJECT",
          evaluate_fast_atm(prop(created_at=NOW - timedelta(minutes=45)), now=NOW, quote=FRESH)["decision"]
          == "WOULD_REJECT")

    # 4. Out-of-window (16:00 ET = 20:00 UTC) → WOULD_REJECT.
    check("out-of-window → WOULD_REJECT",
          evaluate_fast_atm(prop(), now=NOW.replace(hour=20), quote=FRESH)["decision"] == "WOULD_REJECT")

    # 5. Social-only (watch_only route) → WOULD_REJECT (never fast-path).
    check("social-only route → WOULD_REJECT",
          evaluate_fast_atm(prop(route="watch_only", route_actionability="WAIT"), now=NOW, quote=FRESH)["decision"]
          == "WOULD_REJECT")

    # 6. Large-float scout route → WOULD_REJECT (blocked from momentum_scalp fast-path).
    check("large-float scout → WOULD_REJECT",
          evaluate_fast_atm(prop(route="large_float_social_scout", route_actionability="MANUAL_REVIEW"),
                            now=NOW, quote=FRESH)["decision"] == "WOULD_REJECT")
    check("meme squeeze → WOULD_REJECT",
          evaluate_fast_atm(prop(route="meme_squeeze_momentum", route_actionability="MANUAL_REVIEW"),
                            now=NOW, quote=FRESH)["decision"] == "WOULD_REJECT")

    # 7. Non-paper account → WOULD_REJECT.
    check("non-paper account → WOULD_REJECT",
          evaluate_fast_atm(prop(target_account="schwab_roth_ira"), now=NOW, quote=FRESH)["decision"]
          == "WOULD_REJECT")

    # 8. Non-momentum strategy → WOULD_REJECT.
    check("non-momentum strategy → WOULD_REJECT",
          evaluate_fast_atm(prop(strategy_id="swing_breakout"), now=NOW, quote=FRESH)["decision"]
          == "WOULD_REJECT")

    # 9. momentum_scalp route but actionability WAIT → WOULD_REJECT.
    check("momentum_scalp/WAIT → WOULD_REJECT",
          evaluate_fast_atm(prop(route_actionability="WAIT"), now=NOW, quote=FRESH)["decision"]
          == "WOULD_REJECT")

    # 10. No live broker symbols reachable from this module (read-only/dry-run).
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "momentum_scalp_fast_atm_runner.py")).read()
    check("no live broker write calls in runner",
          "place_order" not in src and "submit_order" not in src and "schwab_transport" not in src)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
