#!/usr/bin/env python3
"""P0-6: a Social Scout can NEVER enter the validation fast path (sandbox/simulated submit). Verified
micro-cap GO still passes the route/scout gates (and proceeds to the normal validation gates)."""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_paper_fast_path import evaluate_paper_fast_path  # noqa: E402

PASS, FAIL = [], []
NOW = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)   # 09:30 ET, in-window
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
    # 1. scout_status=SOCIAL_SCOUT is rejected even if every other field looks momentum-ready.
    r = evaluate_paper_fast_path(prop(scout_status="SOCIAL_SCOUT"), now=NOW, quote=FRESH)
    check("scout_status SOCIAL_SCOUT → REJECT", r["decision"] == "REJECT")
    check("reject reason is scout-specific",
          "SOCIAL_SCOUT_NOT_VALIDATION_ELIGIBLE" in r["reason_codes"])

    # 2. SCOUT actionability is rejected (the operator-awareness actionability).
    r = evaluate_paper_fast_path(prop(route="watch_only", route_actionability="SCOUT"), now=NOW, quote=FRESH)
    check("SCOUT actionability → REJECT", r["decision"] == "REJECT")

    # 3. A realistic 2/5 social-only scout shape (watch_only/SCOUT/unverified) → REJECT.
    r = evaluate_paper_fast_path(
        prop(route="watch_only", route_actionability="SCOUT", route_strategy_id=None,
             catalyst_verified=False, scout_status="SOCIAL_SCOUT", social_only=True),
        now=NOW, quote=FRESH)
    check("2/5 social scout → REJECT (not validation-eligible)", r["decision"] == "REJECT")

    # 4. A 4/5 scout missing catalyst (large-float scout shape) → REJECT.
    r = evaluate_paper_fast_path(
        prop(route="large_float_social_scout", route_actionability="MANUAL_REVIEW",
             route_strategy_id="large_float_social_scout", float_m=80,
             scout_status="SOCIAL_SCOUT"),
        now=NOW, quote=FRESH)
    check("4/5 large-float scout → REJECT", r["decision"] == "REJECT")

    # 5. Verified micro-cap GO (NO scout) passes the route/scout gates — not blocked by scout logic.
    r = evaluate_paper_fast_path(prop(scout_status="NONE"), now=NOW, quote=FRESH)
    check("verified micro GO not blocked by scout gate (proceeds)",
          "SOCIAL_SCOUT_NOT_VALIDATION_ELIGIBLE" not in r["reason_codes"])
    check("verified micro GO would submit (normal path intact)",
          r["decision"] in ("WOULD_SUBMIT_PAPER", "DEFER"))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
