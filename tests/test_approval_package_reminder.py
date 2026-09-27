"""Reminder/expiry lane over the approval ledger — hermetic (13 §6)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import approval_package as ap  # noqa: E402
import approval_package_reminder as rem  # noqa: E402

ITEMS = [{"item_id": "O-1", "category": "OPERATOR", "title": "t1", "why": "w", "rule": "r", "rollback": "x"},
         {"item_id": "O-2", "category": "OPERATOR", "title": "t2", "why": "w", "rule": "r", "rollback": "x"}]


def _submitted(tmp_path, created):
    led = ap.Ledger(tmp_path / "led.jsonl")
    pkg = ap.new_package("c", "w1", "s", ITEMS, package_id="pkg-test-rem-0001", now=created)
    led.append({"event": "PACKAGE_CREATED", "package_id": pkg["package_id"], "package": pkg})
    led.append({"event": "SUBMITTED", "package_id": pkg["package_id"], "telegram": {}, "ts": created.isoformat()})
    return led


def test_reminders_fire_once_each_and_expiry_marks_items(tmp_path):
    t0 = dt.datetime(2026, 9, 27, 18, 0, tzinfo=dt.timezone.utc)
    led = _submitted(tmp_path, t0)
    assert rem.plan(led, now=t0 + dt.timedelta(hours=1)) == []
    acts = rem.plan(led, now=t0 + dt.timedelta(hours=5))
    assert [a["kind"] for a in acts] == ["REMINDER_4H"] and "expires in 19h" in acts[0]["text"]
    rem.record(led, acts, sent=False)
    assert rem.plan(led, now=t0 + dt.timedelta(hours=6)) == []           # not repeated
    acts = rem.plan(led, now=t0 + dt.timedelta(hours=13))
    assert [a["kind"] for a in acts] == ["REMINDER_12H"]
    rem.record(led, acts, sent=True)
    # decide one item, then expire the rest
    ap.apply_reply(led, ap.parse_reply("APPROVE pkg-test-rem-0001 1"), decided_by={"who": "op"})
    acts = rem.plan(led, now=t0 + dt.timedelta(hours=25))
    assert acts[0]["kind"] == "EXPIRE" and acts[0]["items"] == [2]
    rem.record(led, acts, sent=False)
    pkg = led.package("pkg-test-rem-0001")
    assert pkg["items"][0]["state"] == "APPROVED" and pkg["items"][1]["state"] == "EXPIRED"
    assert pkg["state"] in ("PARTIAL", "APPROVED", "EXPIRED") and rem.plan(led, now=t0 + dt.timedelta(hours=30)) == []
    assert led.verify_chain()[0]
