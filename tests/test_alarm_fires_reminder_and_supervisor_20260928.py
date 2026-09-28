"""C1 firing tests (2026-09-28) for the two send_telegram sites #1328 added without one.

`approval_package_reminder.py` and `supervisor_breach_detector.py` each gained a Telegram send
that the alarm-coverage gate (`tests/test_alarm_coverage.py`) counted as untested, so `main`
failed `alarm_fires`. Each test injects the condition and asserts the message reaches the
transport (telegram_alert.send_telegram), and asserts the failure path is recorded durably.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import approval_package as ap  # noqa: E402
import approval_package_reminder as rem  # noqa: E402
import supervisor_breach_detector as sbd  # noqa: E402
import telegram_alert as TA  # noqa: E402

COVERS = ["scripts/approval_package_reminder.py", "scripts/supervisor_breach_detector.py"]

ITEMS = [{"item_id": "O-1", "category": "OPERATOR", "title": "t1", "why": "w", "rule": "r", "rollback": "x"}]


def _due_ledger(tmp_path):
    created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)   # REMINDER_4H is due
    led = ap.Ledger(tmp_path / "led.jsonl")
    pkg = ap.new_package("c", "w1", "s", ITEMS, package_id="pkg-test-fire-0001", now=created)
    led.append({"event": "PACKAGE_CREATED", "package_id": pkg["package_id"], "package": pkg})
    led.append({"event": "SUBMITTED", "package_id": pkg["package_id"], "telegram": {}, "ts": created.isoformat()})
    return led


def test_reminder_reaches_the_transport(tmp_path, monkeypatch):
    led = _due_ledger(tmp_path)
    assert rem.plan(led, now=dt.datetime.now(dt.timezone.utc)), "fixture must produce a due reminder"
    sent = []
    monkeypatch.setattr(TA, "send_telegram", lambda text, **kw: sent.append((text, kw)) or True)
    monkeypatch.setattr(sys, "argv", ["rem", "--ledger", str(tmp_path / "led.jsonl"), "--send"])
    assert rem.main() == 0
    assert sent and "pkg-test-fire-0001".replace("_", "-") in sent[0][0] and sent[0][1].get("bypass_router") is True
    rows = [json.loads(l) for l in (tmp_path / "led.jsonl").read_text().splitlines() if l.strip()]
    assert any(r.get("event") == "NOTE" and r.get("sent") is True for r in rows)


def test_reminder_send_failure_is_recorded_on_the_ledger(tmp_path, monkeypatch):
    _due_ledger(tmp_path)

    def _boom(text, **kw):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(TA, "send_telegram", _boom)
    monkeypatch.setattr(sys, "argv", ["rem", "--ledger", str(tmp_path / "led.jsonl"), "--send"])
    assert rem.main() == 0
    rows = [json.loads(l) for l in (tmp_path / "led.jsonl").read_text().splitlines() if l.strip()]
    failed = [r for r in rows if r.get("event") == "SEND_FAILED"]
    assert failed and "RuntimeError" in failed[0]["error"]
    assert any(r.get("event") == "NOTE" and r.get("sent") is False for r in rows)


def test_supervisor_l4_page_reaches_the_transport(tmp_path, monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    rows = [{"breach_id": "b-fire-1", "lane_id": "lane-x", "kind": "MISSED_RUN",
             "detected_at": (now - dt.timedelta(seconds=sbd.L4_AFTER_S + 600)).isoformat()}]
    sent = []
    monkeypatch.setattr(TA, "send_telegram", lambda text, **kw: sent.append((text, kw)) or True)
    out = sbd._ladder_l4_l5(rows, {"lane-x": {"ladder_max": 4}}, now, tmp_path, live=True)
    assert out["l4_candidates"] == 1 and out["l4_paged"] == 1, out
    assert sent and "supervisor L4" in sent[0][0] and "lane-x" in sent[0][0] and sent[0][1].get("bypass_router") is True
    receipts = [json.loads(l) for l in (tmp_path / "supervisor_ladder_receipts.jsonl").read_text().splitlines() if l.strip()]
    assert any(r.get("level") == 4 and r.get("paged") is True for r in receipts)


def test_supervisor_shadow_mode_never_pages(tmp_path, monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    rows = [{"breach_id": "b-fire-2", "lane_id": "lane-x", "kind": "MISSED_RUN",
             "detected_at": (now - dt.timedelta(seconds=sbd.L4_AFTER_S + 600)).isoformat()}]
    sent = []
    monkeypatch.setattr(TA, "send_telegram", lambda text, **kw: sent.append(text) or True)
    out = sbd._ladder_l4_l5(rows, {"lane-x": {"ladder_max": 4}}, now, tmp_path, live=False)
    assert out["l4_candidates"] == 1 and out["l4_paged"] == 0 and not sent
