#!/usr/bin/env python3
"""phase6_market_session_policy.py — Market session policy for paper proposal approvals.

Classifies the current market session and determines whether paper
proposal approvals are allowed.

Default policy: only regular session (9:30-16:00 ET Mon-Fri non-holiday).
Pre-market, after-hours, weekends, holidays, and unknown sessions are blocked.

PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/phase6_market_session_policy.py --status --json
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_session import (
    current_market_session,
    is_market_open,
    next_regular_session_open,
    _eastern_now,
    MARKET_CLOSE,
)

log = logging.getLogger("phase6_market_session_policy")

# Session → (allowed, reason)
SESSION_POLICY = {
    "regular":    (True,  "Regular market session is open."),
    "premarket":  (False, "Pre-market approvals are disabled by policy."),
    "afterhours": (False, "After-hours approvals are disabled by policy."),
    "closed":     (False, "Market is closed."),
    "weekend":    (False, "Market is closed for the weekend."),
    "holiday":    (False, "Market is closed for a holiday."),
}


def classify_market_session(now_et=None) -> dict:
    """Classify current market session and return approval policy result.

    Args:
        now_et: Optional datetime for testing. If None, uses current Eastern time.

    Returns:
        dict with ok, session, allowed, reason, timestamp_et, next_regular_open,
        next_regular_close, source.
    """
    result = {
        "ok": False,
        "session": "unknown",
        "allowed": False,
        "reason": "Market session could not be verified; approval blocked fail-closed.",
        "timestamp_et": None,
        "next_regular_open": None,
        "next_regular_close": None,
        "source": "local_time",
    }

    try:
        if now_et is not None:
            et = now_et
            session = current_market_session(now_et)
        else:
            et = _eastern_now()
            session = current_market_session()

        result["timestamp_et"] = et.strftime("%Y-%m-%d %H:%M:%S %Z")
        result["session"] = session
        result["ok"] = True

        if session in SESSION_POLICY:
            allowed, reason = SESSION_POLICY[session]
            result["allowed"] = allowed
            result["reason"] = reason
        else:
            result["allowed"] = False
            result["reason"] = f"Unknown session '{session}'; approval blocked fail-closed."

        # Next open/close
        try:
            nxt = next_regular_session_open(now_et)
            if nxt:
                result["next_regular_open"] = nxt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass

        if session == "regular":
            try:
                close_dt = et.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute,
                                      second=0, microsecond=0)
                result["next_regular_close"] = close_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                pass

    except Exception as e:
        result["ok"] = False
        result["reason"] = f"Session classification error: {e}. Approval blocked fail-closed."
        log.error(f"classify_market_session failed: {e}")

    return result


def main():
    p = argparse.ArgumentParser(description="Market session policy status")
    p.add_argument("--status", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    r = classify_market_session()
    if args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Session: {r['session']}")
        print(f"Allowed: {r['allowed']}")
        print(f"Reason:  {r['reason']}")
        print(f"Time:    {r['timestamp_et']}")
        if r.get('next_regular_open'):
            print(f"Next open: {r['next_regular_open']}")


if __name__ == "__main__":
    main()
