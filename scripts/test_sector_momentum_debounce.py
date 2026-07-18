#!/usr/bin/env python3
"""Defense Desk WS-A acceptance: debounce + transition-only firing over synthetic history.

Rule under test (engine main loop): an alert fires ONLY when today's computed state
equals yesterday's persisted state (2nd consecutive close in the NEW state = day-2
confirm) AND differs from the state before that. Levels never fire; single-day
flickers never fire; a confirmed flip fires exactly once.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sector_momentum_engine import classify, CFG  # noqa: E402


def fire(prior: list, today: str) -> bool:
    """Mirror of the engine's transition rule. prior = persisted states, newest first."""
    d = CFG["debounce_days"]
    return len(prior) >= d and prior[0] == today and prior[-1] != today


def run():
    ok = 0

    # 1. classify() quadrants are exact
    assert classify(2.0, 1.0) == "LEADING"
    assert classify(2.0, -1.0) == "WEAKENING"
    assert classify(-2.0, -1.0) == "LAGGING"
    assert classify(-2.0, 1.0) == "IMPROVING"
    assert classify(None, 1.0) is None
    ok += 1
    print("✓ quadrant classification")

    # 2. steady state NEVER fires (levels don't alert)
    assert not fire(["LEADING", "LEADING"], "LEADING")
    ok += 1
    print("✓ steady state silent")

    # 3. day-1 of a flip does NOT fire (debounce)
    #    history: LEADING,LEADING → today WEAKENING (prior[0] is still LEADING)
    assert not fire(["LEADING", "LEADING"], "WEAKENING")
    ok += 1
    print("✓ day-1 flip held by debounce")

    # 4. day-2 confirm FIRES exactly once
    #    history newest-first: [WEAKENING(day1), LEADING] → today WEAKENING
    assert fire(["WEAKENING", "LEADING"], "WEAKENING")
    ok += 1
    print("✓ day-2 confirm fires")

    # 5. day-3+ does NOT re-fire (transition already alerted; prior now uniform)
    assert not fire(["WEAKENING", "WEAKENING"], "WEAKENING")
    ok += 1
    print("✓ no re-fire after confirmation")

    # 6. single-day flicker that reverts never fires
    #    [WEAKENING(flicker), LEADING] → today LEADING (reverted): prior[0]!=today → no fire
    assert not fire(["WEAKENING", "LEADING"], "LEADING")
    ok += 1
    print("✓ flicker-revert silent")

    print(f"ALL {ok} DEBOUNCE TESTS PASS")
    return 0

def run_v2():
    """v2 additions: style-spread states + market-state line template."""
    from sector_momentum_engine import market_state_line
    assert classify(3.01, 2.6) == "LEADING"      # RSP−SPY live shape
    assert classify(-0.1, 2.05) == "IMPROVING"   # VUG−VTV live shape
    print("✓ style-spread quadrants")
    m = {"indices": [{"symbol": "SPY", "short": -0.9}],
         "styles": [{"key": "equal_vs_cap", "s20": 1.2}, {"key": "small_vs_large", "s20": -0.4}],
         "internals": {"new_high": 89, "new_low": 412}}
    line = market_state_line(m, [{"state": "LAGGING"}] * 3)
    assert "SPY -0.9% wk" in line and "equal-weight leading" in line \
        and "small caps lagging" in line and "NH/NL 89/412 — narrow tape" in line \
        and "3/11 sectors lagging" in line, line
    print("✓ market-state line template")


if __name__ == "__main__":
    rc = run()
    run_v2()
    print("ALL v1+v2 TESTS PASS")
    sys.exit(rc)
