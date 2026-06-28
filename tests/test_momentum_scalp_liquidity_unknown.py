#!/usr/bin/env python3
"""P0-4: momentum_scalp liquidity-unknown DEFERS (no proposal), never fails open.

For the intraday, liquidity-sensitive momentum_scalp, a quote/provider error, a missing
quote, or a stale quote must return a structured DEFER_LIQUIDITY_UNKNOWN (the generator
then skips proposal creation). A fresh quote proceeds. Non-intraday strategies keep their
prior fail-open behavior.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import market_quote_provider as mqp  # noqa: E402
from auto_proposal_generator import _liquidity_prescreen, _is_intraday_strategy  # noqa: E402

PASS, FAIL = [], []
RULES = {"liquidity_prescreen": {"enabled": True, "max_spread_pct": 5.0,
                                 "min_day_volume_shares": 25000, "min_dollar_day_volume": 100000}}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def _patch(fresh=None, best=None, fresh_raises=False, best_raises=False):
    def _cf(symbol, strategy_id=None):
        if fresh_raises:
            raise RuntimeError("provider down")
        return fresh
    def _bq(symbol):
        if best_raises:
            raise RuntimeError("provider down")
        return best
    mqp.check_fresh_quote = _cf
    mqp.get_best_quote = _bq


def main():
    _orig = (getattr(mqp, "check_fresh_quote", None), getattr(mqp, "get_best_quote", None))
    try:
        check("momentum_scalp is intraday", _is_intraday_strategy("momentum_scalp"))
        check("swing_breakout is not intraday", not _is_intraday_strategy("swing_breakout"))

        # 1. Provider exception → DEFER.
        _patch(fresh_raises=True)
        ok, reason = _liquidity_prescreen("AAAA", RULES, "momentum_scalp")
        check("provider exception defers", (not ok) and reason.startswith("DEFER_LIQUIDITY_UNKNOWN"))

        # 2. No quote (check_fresh_quote not ok) → DEFER.
        _patch(fresh={"ok": False, "reason": "no_quote"})
        ok, reason = _liquidity_prescreen("BBBB", RULES, "momentum_scalp")
        check("no quote defers", (not ok) and "DEFER_LIQUIDITY_UNKNOWN" in reason)

        # 3. Stale quote → DEFER.
        _patch(fresh={"ok": False, "reason": "stale (22min)"})
        ok, reason = _liquidity_prescreen("CCCC", RULES, "momentum_scalp")
        check("stale quote defers", (not ok) and "stale" in reason)

        # 4. Fresh quote + good liquidity → proceeds.
        _patch(fresh={"ok": True}, best={"spread_pct": 1.0, "last_price": 5.0, "day_volume": 2_000_000})
        ok, reason = _liquidity_prescreen("DDDD", RULES, "momentum_scalp")
        check("fresh + liquid proceeds", ok and reason == "")

        # 5. Fresh quote but wide spread → blocked (normal liquidity reject, not a defer).
        _patch(fresh={"ok": True}, best={"spread_pct": 9.0, "last_price": 5.0, "day_volume": 2_000_000})
        ok, reason = _liquidity_prescreen("EEEE", RULES, "momentum_scalp")
        check("fresh but wide spread blocked", (not ok) and "spread" in reason)

        # 6. get_best_quote raises after fresh ok → DEFER (fail-closed).
        _patch(fresh={"ok": True}, best_raises=True)
        ok, reason = _liquidity_prescreen("FFFF", RULES, "momentum_scalp")
        check("best-quote error defers", (not ok) and reason.startswith("DEFER_LIQUIDITY_UNKNOWN"))

        # 7. Non-intraday gated strategy (earnings_catalyst) keeps fail-open on provider error.
        _patch(fresh_raises=True, best_raises=True)
        # earnings_catalyst is in the gated set but NOT intraday → non-intraday branch.
        # market_session import will run; force a benign path by patching get_best_quote to raise →
        # non-intraday branch returns True (fail-open).
        ok, reason = _liquidity_prescreen("GGGG", RULES, "earnings_catalyst")
        check("non-intraday provider error fails open (True)", ok)

        # 8. Strategy outside the gated set is never blocked.
        ok, reason = _liquidity_prescreen("HHHH", RULES, "swing_breakout")
        check("non-gated strategy passes", ok and reason == "")

        print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
        return 1 if FAIL else 0
    finally:
        if _orig[0]:
            mqp.check_fresh_quote = _orig[0]
        if _orig[1]:
            mqp.get_best_quote = _orig[1]


if __name__ == "__main__":
    raise SystemExit(main())
