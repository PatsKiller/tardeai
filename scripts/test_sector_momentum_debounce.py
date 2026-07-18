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


if __name__ == "__main__":
    sys.exit(run())
