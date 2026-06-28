#!/usr/bin/env python3
"""Intraday trading-window parsing must FAIL CLOSED (P0-3).

A missing/malformed/unparsable window for an intraday strategy blocks auto-approval;
it never falls open. Valid windows gate by ET clock with inclusive boundaries.
Runs under pytest and standalone.
"""
import datetime as dt
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
    assert cond, f"{name} {detail}"


def _at(hh, mm):
    return dt.datetime(2026, 6, 27, hh, mm, 0)


def test_parse_valid_window():
    from intraday_window import parse_window
    status, parsed = parse_window({"start": "06:00", "end": "12:00"})
    check("valid window parses", status == "ok" and parsed["start_min"] == 360 and parsed["end_min"] == 720)


def test_parse_malformed_blocks():
    from intraday_window import parse_window
    for bad in [{"start": "6 AM", "end": "noon"}, {"start": "25:00", "end": "26:00"},
                {"start": "06:00"}, {"start": "12:00", "end": "06:00"}, "06:00-12:00", None, {}]:
        status, reason = parse_window(bad)
        check(f"malformed blocks: {bad!r}", status == "invalid", reason)


def test_now_in_window_boundaries():
    from intraday_window import parse_window, now_in_window
    _, w = parse_window({"start": "06:00", "end": "12:00"})
    check("inside 09:00", now_in_window(w, _at(9, 0)) is True)
    check("lower boundary 06:00 inclusive", now_in_window(w, _at(6, 0)) is True)
    check("upper boundary 12:00 inclusive", now_in_window(w, _at(12, 0)) is True)
    check("before 05:59 outside", now_in_window(w, _at(5, 59)) is False)
    check("after 12:01 outside", now_in_window(w, _at(12, 1)) is False)


def test_now_in_window_fail_closed_on_bad_parsed():
    from intraday_window import now_in_window
    # A corrupt parsed dict must fail CLOSED (block), not open.
    check("bad parsed fails closed", now_in_window({"start_min": "x", "end_min": None}, _at(9, 0)) is False)


def test_malformed_window_blocks_auto_approval():
    from intraday_window import evaluate_intraday_window, INVALID_CODE
    r = evaluate_intraday_window("momentum_scalp", intraday=True,
                                 window_raw={"start": "garbage", "end": "12:00"}, now_et=_at(9, 0))
    check("malformed window blocks", r["blocked"] is True and r["code"] == INVALID_CODE, r)


def test_missing_window_blocks_intraday():
    from intraday_window import evaluate_intraday_window, INVALID_CODE
    # window_raw left None + a strategy id with no yaml on disk → load fails → blocked
    r = evaluate_intraday_window("nonexistent_intraday_strat_xyz", intraday=True, now_et=_at(9, 0))
    check("missing window blocks intraday", r["blocked"] is True and r["code"] == INVALID_CODE, r)


def test_valid_window_inside_passes():
    from intraday_window import evaluate_intraday_window
    r = evaluate_intraday_window("momentum_scalp", intraday=True,
                                 window_raw={"start": "06:00", "end": "12:00"}, now_et=_at(9, 30))
    check("inside valid window passes", r["blocked"] is False and r["applicable"] is True, r)


def test_valid_window_outside_blocks():
    from intraday_window import evaluate_intraday_window, OUTSIDE_CODE
    r = evaluate_intraday_window("momentum_scalp", intraday=True,
                                 window_raw={"start": "06:00", "end": "12:00"}, now_et=_at(14, 0))
    check("outside valid window blocks", r["blocked"] is True and r["code"] == OUTSIDE_CODE, r)


def test_non_intraday_unaffected():
    from intraday_window import evaluate_intraday_window
    r = evaluate_intraday_window("swing_value", intraday=False, now_et=_at(3, 0))
    check("non-intraday not applicable", r["applicable"] is False and r["blocked"] is False, r)


def test_real_momentum_scalp_yaml_window():
    """The shipped momentum_scalp.yaml must carry a valid 06:00–12:00 ET window."""
    from intraday_window import _load_window_raw, parse_window
    found, raw = _load_window_raw("momentum_scalp")
    check("momentum_scalp window present", found is True, raw)
    status, parsed = parse_window(raw)
    check("momentum_scalp window valid", status == "ok", parsed)
    check("momentum_scalp window is 06:00-12:00",
          parsed.get("start") == "06:00" and parsed.get("end") == "12:00", parsed)


def test_atm_gate_wrapper_uses_fail_closed():
    """The ATM fast-path wrapper must propagate the fail-closed result."""
    import importlib
    iw = importlib.import_module("intraday_window")
    # Directly exercise the shared evaluator the ATM wrapper calls.
    r = iw.evaluate_intraday_window("momentum_scalp", intraday=True,
                                    window_raw={"start": "bad", "end": "x"}, now_et=_at(9, 0))
    check("atm wrapper path fail-closed", r["blocked"] is True and r["code"] == iw.INVALID_CODE, r)


ALL = [
    test_parse_valid_window,
    test_parse_malformed_blocks,
    test_now_in_window_boundaries,
    test_now_in_window_fail_closed_on_bad_parsed,
    test_malformed_window_blocks_auto_approval,
    test_missing_window_blocks_intraday,
    test_valid_window_inside_passes,
    test_valid_window_outside_blocks,
    test_non_intraday_unaffected,
    test_real_momentum_scalp_yaml_window,
    test_atm_gate_wrapper_uses_fail_closed,
]


if __name__ == "__main__":
    print("\n— intraday window fail-closed —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
