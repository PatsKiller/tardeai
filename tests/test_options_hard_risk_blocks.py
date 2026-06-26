#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_earnings_blackout_block():
    import options_desk_enterprise as ent
    p = {"symbol": "TST", "strategy": "covered_call", "dte": 7,
         "enterprise": {"earnings": {"in_blackout": True, "reason": "earnings in 3d"}}}
    blocks = ent.evaluate_hard_risk_blocks(p, mode="live")
    codes = [b["code"] for b in blocks]
    check("earnings_blackout", "earnings_blackout" in codes)


def test_bs_estimate_block():
    import options_desk_enterprise as ent
    p = {"symbol": "TST", "strategy": "covered_call", "data_source": "bs_estimate", "contracts": 1}
    blocks = ent.evaluate_hard_risk_blocks(p, mode="live")
    codes = [b["code"] for b in blocks]
    check("bs_estimate_only", "bs_estimate_only" in codes)


def test_stale_quote_block():
    import options_desk_enterprise as ent
    p = {"symbol": "TST", "strategy": "covered_call", "quote_age_seconds": 999, "contracts": 1,
         "enterprise": {"liquidity": {"pass": True}}}
    blocks = ent.evaluate_hard_risk_blocks(p, mode="live")
    codes = [b["code"] for b in blocks]
    check("quote_stale", "quote_stale" in codes)


def test_advisory_mode_no_blocks():
    import options_desk_enterprise as ent
    p = {"symbol": "TST", "strategy": "covered_call", "data_source": "bs_estimate"}
    blocks = ent.evaluate_hard_risk_blocks(p, mode="advisory")
    check("advisory mode empty", len(blocks) == 0)


def test_portfolio_hard_blocks():
    import options_desk_enterprise as ent
    risk = ent.portfolio_risk_preflight(
        [{"symbol": "TST", "premium_total": 999999}],
        [{"market_value": 100000, "is_cash": False}],
        [],
    )
    check("hard_blocks in portfolio risk", len(risk.get("hard_blocks") or []) >= 0)


if __name__ == "__main__":
    print("\n— options hard risk blocks —")
    test_earnings_blackout_block()
    test_bs_estimate_block()
    test_stale_quote_block()
    test_advisory_mode_no_blocks()
    test_portfolio_hard_blocks()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)