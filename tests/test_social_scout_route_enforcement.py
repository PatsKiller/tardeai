#!/usr/bin/env python3
"""P0-6: a Social Scout can never create a strategy signal or a GO, and never leaks into the live
tradeable path. Verified micro-cap GO still flows through the normal path unaffected."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
# continuous_runner / strategy_signal_sync call load_dotenv at import — stub so this is DB-free.
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _d

from strategy_signal_sync import route_enforced_strategy  # noqa: E402
from continuous_runner import classify_social_injection  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # --- route_enforced_strategy: a SOCIAL_SCOUT scan never creates a signal ---
    scout_scan = {"route": "watch_only", "route_actionability": "SCOUT", "source": "social",
                  "catalyst_verified": False, "scout_status": "SOCIAL_SCOUT"}
    sid, reason = route_enforced_strategy(scout_scan, "momentum_scalp")
    check("2/5 Social Scout → no strategy signal", sid is None)
    check("reason names scout awareness", "SOCIAL_SCOUT" in reason or "scout" in reason.lower())

    # Even if some fields look momentum-ish, scout_status blocks the signal.
    scout_scan2 = {"route": "momentum_scalp", "route_actionability": "GO", "source": "social",
                   "catalyst_verified": True, "scout_status": "SOCIAL_SCOUT"}
    sid2, _ = route_enforced_strategy(scout_scan2, "momentum_scalp")
    check("scout_status overrides even GO-looking fields", sid2 is None)

    # --- Verified micro-cap GO (scout suppressed → scout_status NONE) STILL creates the signal ---
    go_scan = {"route": "momentum_scalp", "route_actionability": "GO", "source": "social",
               "catalyst_verified": True, "scout_status": "NONE"}
    sid3, reason3 = route_enforced_strategy(go_scan, "momentum_scalp")
    check("verified micro GO still routes momentum_scalp", sid3 == "momentum_scalp")

    # --- classify_social_injection: scout surfaces but is NEVER tradeable ---
    inj = classify_social_injection({"route": "watch_only", "route_actionability": "SCOUT",
                                     "decision": "WATCH", "scout_status": "SOCIAL_SCOUT",
                                     "catalyst_verified": False})
    check("scout injectable for visibility", inj["injectable"] is True)
    check("scout NEVER tradeable", inj["tradeable"] is False)
    check("scout cannot produce a GO (not tradeable)", inj["tradeable"] is False)

    # A scout row that somehow carries GO-ish fields is still blocked from the tradeable path.
    inj2 = classify_social_injection({"route": "momentum_scalp", "route_actionability": "GO",
                                      "route_strategy_id": "momentum_scalp", "decision": "GO",
                                      "catalyst_verified": True, "rvol": 9, "float_m": 8, "price": 5,
                                      "scout_status": "SOCIAL_SCOUT"})
    check("scout_status blocks the tradeable GO branch", inj2["tradeable"] is False)

    # Normal verified micro-cap GO (no scout) is still tradeable through the normal path.
    inj3 = classify_social_injection({"route": "momentum_scalp", "route_actionability": "GO",
                                      "route_strategy_id": "momentum_scalp", "decision": "GO",
                                      "catalyst_verified": True, "rvol": 9, "float_m": 8, "price": 5,
                                      "scout_status": "NONE"})
    check("verified micro GO still tradeable (normal path intact)", inj3["tradeable"] is True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
