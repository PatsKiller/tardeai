#!/usr/bin/env python3
import sys
from pathlib import Path
from unittest import mock

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


def test_db_unavailable_fail_closed():
    from brokers.kill_switches import is_blocked
    with mock.patch("brokers.kill_switches._conn", return_value=None):
        blocked, reasons = is_blocked(live_submit=True)
    check("db unavailable blocks", blocked)
    check("fail closed reason", any("fail_closed" in r or "unavailable" in r for r in reasons))


def test_global_blocks_readiness():
    from brokers.kill_switches import list_active
    with mock.patch("brokers.kill_switches._conn", return_value=None):
        active = list_active()
    check("global fail_closed in list", any(a.get("fail_closed") for a in active))


def test_disable_requires_confirm():
    from brokers.kill_switches import disable
    r = disable("global", confirm="wrong")
    check("disable needs exact confirm", not r.get("ok"))


def test_levels_defined():
    from brokers.kill_switches import LEVELS
    check("global level", "global" in LEVELS)
    check("live_submit level", "live_submit" in LEVELS)
    check("options_only level", "options_only" in LEVELS)


if __name__ == "__main__":
    print("\n— kill switches —")
    test_db_unavailable_fail_closed()
    test_global_blocks_readiness()
    test_disable_requires_confirm()
    test_levels_defined()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)