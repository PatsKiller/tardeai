#!/usr/bin/env python3
"""Hardcoded canary gate test suite (Stage 2a Part D). Self-runnable (no pytest dependency):
    .venv/bin/python tests/test_canary_gate.py

Proves, in isolation AND through the guard:
  1. The committed envelope blocks everything outside symbol-allowlist / price<=$4 / qty<=10 /
     notional<=$40 / US-equity / long-only — and the shipped EMPTY allowlist blocks everything.
  2. The gate module is pure: no env, no DB, no config reads (commit-only by construction).
  3. HYPOTHETICAL LIFT: even with BROKER_DISABLED lifted (mode forced to LIVE_ENABLED_FUTURE, all
     standing locks mocked open, 2FA mocked approved) an out-of-envelope submit is denied BY THE
     GATE, and an in-envelope submit is STILL denied end-to-end (execution out of scope).
  4. Alpaca paper-training path is untouched (Hard Rule 7).
"""
import sys
import re
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity,
                                  ExitPolicy, StopSpec, TargetSpec, LadderConfig, LadderLeg, AssetType)
from brokers import canary_gate
from brokers import execution_guard

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def mk(symbol="TST", direction=Direction.LONG, qty=2.0, limit=3.50, method=EntryMethod.LIMIT,
       broker="schwab", **over):
    kw = dict(
        instrument=Instrument(symbol), direction=direction,
        entry=EntrySpec(method=method, limit_price=limit),
        quantity=Quantity(qty=qty), broker=broker,
        exit_policy=ExitPolicy(stop=StopSpec(price=3.20), targets=[TargetSpec(price=3.80)]))
    kw.update(over)
    return OrderIntent(**kw)


print("\n— 1. committed-allowlist state: fail-closed shape holds —")
d = canary_gate.evaluate(mk())   # mk() uses TST — never in any committed allowlist
check("non-allowlisted symbol blocked in shipped state", not d.allowed)
AL = canary_gate.CANARY_SYMBOL_ALLOWLIST
check("allowlist is resting-empty OR a session commit of ≤2 uppercase tickers",
      AL == () or (len(AL) <= 2 and all(s.isupper() and s.isalpha() and len(s) <= 5 for s in AL)), str(AL))
with mock.patch.object(canary_gate, "CANARY_SYMBOL_ALLOWLIST", ()):
    d0 = canary_gate.evaluate(mk())
    check("empty allowlist blocks even an in-envelope order (resting-state contract)",
          not d0.allowed and any("allowlist EMPTY" in r for r in d0.reasons))

print("\n— 2. envelope logic (allowlist patched to ('TST',) for isolation) —")
with mock.patch.object(canary_gate, "CANARY_SYMBOL_ALLOWLIST", ("TST",)):
    check("in-envelope LIMIT buy passes the gate in isolation", canary_gate.evaluate(mk()).allowed)
    check("non-allowlisted symbol blocked", not canary_gate.evaluate(mk(symbol="AAPL")).allowed)
    check("price > $4 blocked", not canary_gate.evaluate(mk(limit=4.01)).allowed)
    check("qty > 10 blocked", not canary_gate.evaluate(mk(qty=11)).allowed)
    check("boundary 10 sh @ $4.00 = $40 notional passes", canary_gate.evaluate(mk(qty=10, limit=4.00)).allowed)
    check("SHORT blocked (long-only)", not canary_gate.evaluate(mk(direction=Direction.SHORT)).allowed)
    check("MARKET (no committed price cap) blocked",
          not canary_gate.evaluate(mk(method=EntryMethod.MARKET, limit=None)).allowed)
    check("notional-based quantity blocked (shares only)",
          not canary_gate.evaluate(mk(quantity=Quantity(notional=30.0), qty=None)).allowed)
    check("option intent blocked (US equities only)",
          not canary_gate.evaluate(mk(instrument=Instrument("TST", asset_type=AssetType.OPTION))).allowed)
    lad = mk(ladder=LadderConfig(legs=[LadderLeg(3.50, 50), LadderLeg(4.20, 50)]))
    check("ladder with any leg > $4 blocked", not canary_gate.evaluate(lad).allowed)
    lad_ok = mk(qty=10, ladder=LadderConfig(legs=[LadderLeg(3.50, 50), LadderLeg(3.40, 50)]))
    check("in-envelope ladder passes", canary_gate.evaluate(lad_ok).allowed)
    check("malformed intent fails closed", not canary_gate.evaluate(object()).allowed)

print("\n— 3. purity: commit-only by construction —")
src = (ROOT / "scripts" / "brokers" / "canary_gate.py").read_text()
check("gate module never imports os (no env access possible)",
      not re.search(r"^\s*(import os\b|from os\b)", src, re.M) and not re.search(r"os\.getenv\s*\(|os\.environ\[", src))
check("no DB access in gate module", not re.search(r"db_adapter|_get_conn|psycopg|cursor\(", src))
check("no config/json/yaml loads in gate module", not re.search(r"json\.load|yaml|configparser|open\(", src))

print("\n— 4. guard integration: gate sits IN FRONT of any allow path —")
out_env = mk(symbol="AAPL", limit=180.0, qty=100)            # flagrantly outside the envelope
d = execution_guard.authorize(out_env, "submit")
check("guard denies out-of-envelope submit with CANARY_GATE reason",
      not d.allowed and d.reason.startswith("CANARY_GATE BLOCK"))
d = execution_guard.authorize(mk(), "preview")
check("preview/translate actions are NOT gated (drafting must keep working)",
      "CANARY_GATE" not in d.reason)

print("\n— 5. HYPOTHETICAL LIFT: BROKER_DISABLED lifted, all locks open, 2FA approved —")
with mock.patch.object(execution_guard, "mode_for",
                       return_value=execution_guard.BrokerExecutionMode.LIVE_ENABLED_FUTURE), \
     mock.patch.object(execution_guard, "_live_future_unlocked", return_value=True):
    sys.modules.setdefault("brokers.approval_service", __import__("brokers.approval_service", fromlist=["x"]))
    with mock.patch("brokers.approval_service.is_fully_approved", return_value=True):
        d_out = execution_guard.authorize(out_env, "submit")
        check("even fully unlocked+approved, out-of-envelope submit is denied BY THE GATE",
              not d_out.allowed and d_out.reason.startswith("CANARY_GATE BLOCK"))
        with mock.patch.object(canary_gate, "CANARY_SYMBOL_ALLOWLIST", ("TST",)):
            d_in = execution_guard.authorize(mk(), "submit")
            check("in-envelope submit STILL denied end-to-end (execution out of scope this phase)",
                  not d_in.allowed)

print("\n— 6. alpaca paper-training path untouched (Hard Rule 7) —")
alp = mk(broker="alpaca", symbol="AAPL", limit=180.0, qty=100)
d = execution_guard.authorize(alp, "submit")
check("alpaca decision carries no CANARY_GATE reason", "CANARY_GATE" not in d.reason)

print(f"\n  {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
