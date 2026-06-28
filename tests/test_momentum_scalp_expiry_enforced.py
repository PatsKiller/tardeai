#!/usr/bin/env python3
"""P0-1: ATM enforces intraday proposal-TTL expiry BEFORE approval.

Exercises the deterministic, DB-free expiry resolver `resolve_atm_expiry` that the ATM
approval cycle consults before any approval decision. The 30-minute momentum_scalp TTL
(intraday_execution.proposal_ttl_minutes, the single source of truth) must expire stale
scalps; the legacy 4-hour rule must NOT keep them alive.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from atm_auto_approver import resolve_atm_expiry  # noqa: E402

PASS, FAIL = [], []
NOW = datetime(2026, 6, 27, 15, 0, 0, tzinfo=timezone.utc)


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # 1. 31-min-old momentum_scalp (30-min TTL) → EXPIRE before approval.
    r = resolve_atm_expiry("momentum_scalp", NOW - timedelta(minutes=31), None, now=NOW)
    check("31-min-old momentum_scalp expires", r["action"] == "expire")
    check("expiry reason is intraday_ttl_expired", r.get("reason") == "intraday_ttl_expired")
    check("expiry lifecycle is EXPIRED_INTRADAY", r.get("lifecycle_status") == "EXPIRED_INTRADAY")
    check("expiry message cites age + TTL", "30min TTL" in r.get("message", ""))

    # 2. 29-min-old momentum_scalp → OK, continues to other gates.
    r = resolve_atm_expiry("momentum_scalp", NOW - timedelta(minutes=29), None, now=NOW)
    check("29-min-old momentum_scalp continues (ok)", r["action"] == "ok")
    check("29-min resolves 30-min TTL", r.get("ttl_minutes") == 30)

    # 3. Exactly at TTL boundary (30 min) → expired (>=).
    r = resolve_atm_expiry("momentum_scalp", NOW - timedelta(minutes=30, seconds=1), None, now=NOW)
    check("just-past-30-min momentum_scalp expires", r["action"] == "expire")

    # 4. The OLD 4-hour rule must NOT apply to intraday: a 31-min scalp is already dead at 31min,
    #    proving expiry is the 30-min TTL, not 4h. (3.9h-old would NOT have expired under 4h rule
    #    but DOES expire here.)
    r = resolve_atm_expiry("momentum_scalp", NOW - timedelta(hours=3, minutes=54), None, now=NOW)
    check("3.9h-old momentum_scalp expires on TTL (not 4h rule)", r["action"] == "expire")

    # 5. Non-intraday strategy → resolver returns ok/intraday=False (caller applies legacy fallback).
    r = resolve_atm_expiry("swing_breakout", NOW - timedelta(hours=10), None, now=NOW)
    check("non-intraday returns ok (handled by fallback)", r["action"] == "ok")
    check("non-intraday flagged intraday=False", r.get("intraday") is False)

    # 6. Fail-safe: intraday proposal with NO created_at and NO expires_at → BLOCK (never approve).
    r = resolve_atm_expiry("momentum_scalp", None, None, now=NOW)
    check("intraday missing created_at+expires_at blocks (fail-safe)", r["action"] == "block")
    check("block reason is intraday_ttl_unknown", r.get("reason") == "intraday_ttl_unknown")

    # 7. Stored expires_at earlier than TTL is honored (expire even if age < TTL).
    r = resolve_atm_expiry("momentum_scalp", NOW - timedelta(minutes=5),
                           NOW - timedelta(minutes=1), now=NOW)
    check("earlier stored expires_at is honored (expire)", r["action"] == "expire")

    # 8. Fresh intraday with future expires_at → ok.
    r = resolve_atm_expiry("momentum_scalp", NOW - timedelta(minutes=5),
                           NOW + timedelta(minutes=20), now=NOW)
    check("fresh intraday with future expires_at continues", r["action"] == "ok")

    # 9. momentum_scalp is the canonical (and only) intraday strategy after gap_and_go was
    #    absorbed; a now-defunct gap_and_go id is treated as non-intraday (ok → legacy fallback).
    import proposal_lifecycle as pl
    check("momentum_scalp is in INTRADAY_STRATEGIES", "momentum_scalp" in pl.INTRADAY_STRATEGIES)
    r = resolve_atm_expiry("gap_and_go", NOW - timedelta(hours=2), None, now=NOW)
    check("defunct gap_and_go treated as non-intraday (ok)", r["action"] == "ok" and r.get("intraday") is False)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
