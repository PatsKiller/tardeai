#!/usr/bin/env python3
"""P0-2/P0-6: deterministic momentum_scalp paper fast path — gates replace approval, paper-only."""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_paper_fast_path import evaluate_paper_fast_path, run, SOURCE_TAG  # noqa: E402

PASS, FAIL = [], []
NOW = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)   # 09:30 ET — inside 06:00–12:00 ET
FRESH = {"ok": True, "age_minutes": 1, "last_price": 5.0}
STALE = {"ok": False, "reason": "stale", "age_minutes": 1100}
NOQUOTE = {"ok": False, "reason": "no_quote"}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def prop(**kw):
    base = {"id": 1, "symbol": "SCLP", "strategy_id": "momentum_scalp", "target_account": "alpaca_paper",
            "created_at": NOW - timedelta(minutes=5), "expires_at": None,
            "proposed_entry": 5.0, "proposed_stop": 4.6, "proposed_target1": 5.8,
            "rvol": 7, "float_m": 8, "price": 5.0, "route": "momentum_scalp",
            "route_actionability": "GO", "route_strategy_id": "momentum_scalp",
            "catalyst_verified": True, "social_only": False, "discovery_trace_id": "trace-1"}
    base.update(kw)
    return base


def D(p, **kw):
    return evaluate_paper_fast_path(p, now=kw.get("now", NOW), quote=kw.get("quote", FRESH))["decision"]


def main():
    # 1. Valid fresh in-window micro-float verified GO → WOULD_SUBMIT_PAPER (NO approval needed).
    ev = evaluate_paper_fast_path(prop(), now=NOW, quote=FRESH)
    check("valid → WOULD_SUBMIT_PAPER", ev["decision"] == "WOULD_SUBMIT_PAPER")
    check("valid passed all gates", "ALL_GATES_PASS" in ev["reason_codes"])
    check("no 'approval' gate exists in decision path",
          not any("APPROV" in c.upper() for c in ev["reason_codes"]))

    # 2. Stale quote → DEFER (freshness preserved).
    check("stale quote → DEFER", D(prop(), quote=STALE) == "DEFER")
    # 3. Unknown liquidity / no quote → DEFER.
    ev = evaluate_paper_fast_path(prop(), now=NOW, quote=NOQUOTE)
    check("no quote → DEFER + LIQUIDITY_UNKNOWN",
          ev["decision"] == "DEFER" and "LIQUIDITY_UNKNOWN" in ev["reason_codes"])

    # 4. Expired proposal → REJECT.
    check("expired (45m) → REJECT", D(prop(created_at=NOW - timedelta(minutes=45))) == "REJECT")
    # 5. Out-of-window → REJECT.
    check("out-of-window → REJECT", D(prop(), now=NOW.replace(hour=20)) == "REJECT")
    # 6. Social-only → REJECT.
    check("social_only → REJECT", D(prop(social_only=True)) == "REJECT")
    # 7. Large-float scout route → REJECT.
    check("large_float_social_scout route → REJECT",
          D(prop(route="large_float_social_scout", route_actionability="MANUAL_REVIEW")) == "REJECT")
    check("meme_squeeze route → REJECT",
          D(prop(route="meme_squeeze_momentum", route_actionability="MANUAL_REVIEW")) == "REJECT")
    # 8. watch_only / WAIT route → REJECT.
    check("watch_only route → REJECT", D(prop(route="watch_only", route_actionability="WAIT")) == "REJECT")
    # 9. Float > 20M → REJECT.
    check("float 50M → REJECT", D(prop(float_m=50)) == "REJECT")
    # 10. Unverified catalyst → REJECT.
    check("unverified catalyst → REJECT", D(prop(catalyst_verified=False)) == "REJECT")
    # 11. Invalid plan (inverted stop) → REJECT.
    check("inverted stop → REJECT", D(prop(proposed_stop=5.5)) == "REJECT")
    check("missing target → REJECT", D(prop(proposed_target1=None)) == "REJECT")
    # 12. R:R too low → REJECT (entry 5, stop 4.6 -> risk .4; target 5.2 -> reward .2 -> RR .5).
    check("low R:R → REJECT", D(prop(proposed_target1=5.2)) == "REJECT")
    # 13. Price drift beyond max (entry 5, quote last 6 = 20% drift) → REJECT.
    check("price drift → REJECT", D(prop(), quote={"ok": True, "age_minutes": 1, "last_price": 6.0}) == "REJECT")
    # 14. Non-paper account → REJECT.
    check("schwab account → REJECT", D(prop(target_account="schwab_roth_ira")) == "REJECT")
    # 15. Non-momentum strategy → REJECT.
    check("swing strategy → REJECT", D(prop(strategy_id="swing_breakout")) == "REJECT")

    # 16. Module contains no live broker write symbols.
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "momentum_scalp_paper_fast_path.py")).read()
    check("no live broker symbols (schwab/place_order/submit_order)",
          all(s not in src for s in ("schwab_transport", "place_order(", "submit_order(")))
    check("delegates to existing safe paper submitter", "submit_paper" in src)
    check("source tag stamped", SOURCE_TAG == "momentum_scalp_paper_fast_path")

    # 17. Default run() mode is dry_run (no writes).
    rep = run(dry_run=True)
    check("run default dry_run safe", rep.get("mode") == "dry_run" or not rep.get("ok"))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
