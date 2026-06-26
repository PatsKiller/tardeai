#!/usr/bin/env python3
import datetime as dt
import sys
import uuid
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


def test_revalidate_quote_moved():
    from brokers import evidence_approval as ea
    iid = str(uuid.uuid4())
    rec = {
        "id": 1, "evidence_hash": "abc", "expires_at": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10),
        "used_at": None, "quote_snapshot": {"mid": 1.0},
    }
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        r = ea.revalidate_before_submit(iid, current_quote={"mid": 1.05})
    check("quote move blocks", not r["ok"] and "quote_moved" in r.get("reason", ""))


def test_revalidate_used_approval():
    from brokers import evidence_approval as ea
    rec = {"id": 1, "evidence_hash": "abc", "used_at": dt.datetime.now(dt.timezone.utc),
           "expires_at": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)}
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        r = ea.revalidate_before_submit("x")
    check("single use blocks replay", not r["ok"] and "used" in r.get("reason", ""))


def test_revalidate_expired():
    from brokers import evidence_approval as ea
    rec = {"id": 1, "evidence_hash": "abc", "used_at": None,
           "expires_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)}
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        r = ea.revalidate_before_submit("x")
    check("expired blocks", not r["ok"] and "expired" in r.get("reason", ""))


def test_kill_switch_after_approval():
    from brokers import evidence_approval as ea
    rec = {"id": 1, "evidence_hash": "abc", "used_at": None,
           "expires_at": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10),
           "quote_snapshot": {"mid": 1.0}}
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(True, ["kill_switch:global"])):
            r = ea.revalidate_before_submit("x", current_quote={"mid": 1.0})
    check("kill switch after approval", not r["ok"])


if __name__ == "__main__":
    print("\n— evidence bound approval —")
    test_revalidate_quote_moved()
    test_revalidate_used_approval()
    test_revalidate_expired()
    test_kill_switch_after_approval()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)