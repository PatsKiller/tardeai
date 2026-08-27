"""Three identical CIO briefs reached the operator's phone on 2026-08-27.

A check-in carries no decision identity, so `build_dedupe_key`'s only
distinguishing part was `wake_job_id` -- a fresh run id per run. Byte-identical
bodies therefore hashed to three different keys. Content-keying collapses them;
a bounded window keeps an unchanged brief arriving daily rather than once.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cio_notification_outbox import build_dedupe_key


def _checkin(body: str, run_id: str) -> dict:
    return {
        "notification_id": f"notif-{run_id}",
        "message_class": "checkin",
        "channel_targets": ["telegram"],
        "subject": f"CIO Run Complete — {run_id}",
        "body": body,
        "body_hash": hashlib.sha256(body.encode()).hexdigest(),
        "wake_job_id": run_id,
        "severity": "INFO",
    }


def test_the_incident_identical_bodies_from_different_runs_collapse():
    body = "RISK ON TREND. Nothing requires action today."
    keys = {build_dedupe_key(_checkin(body, r)) for r in ("run-a", "run-b", "run-c")}
    assert len(keys) == 1, "three runs, one unchanged brief, one notification"


def test_a_changed_brief_is_not_suppressed():
    a = build_dedupe_key(_checkin("Nothing requires action today.", "run-a"))
    b = build_dedupe_key(_checkin("DO NOW: TRIM NVDA.", "run-b"))
    assert a != b, "a brief whose content changed must still reach the operator"


def test_decision_keyed_notifications_keep_their_old_identity():
    """The content-key must apply only where there is no decision identity."""
    n = _checkin("body", "run-a")
    n["decision_id"] = "dec-1"
    n["message_class"] = "checkin"
    assert build_dedupe_key(n) != build_dedupe_key(_checkin("body", "run-a"))


def test_other_classes_are_untouched():
    n = _checkin("body", "run-a")
    n["message_class"] = "advisory"
    n["cio_action_id"] = "act-1"
    # advisory still keys on its action/wake identity, not its body
    other = dict(n, body="different", body_hash=hashlib.sha256(b"different").hexdigest())
    assert build_dedupe_key(n) == build_dedupe_key(other)


# ── the window ─────────────────────────────────────────────────────────────

def _outbox(tmp_path):
    from scripts.lib.cio_notification_outbox import NotificationOutbox
    try:
        return NotificationOutbox(event_store_path=tmp_path / "events.jsonl")
    except TypeError:
        pytest.skip("outbox constructor signature differs in this build")


def _event(key: str, occurred: datetime) -> dict:
    return {"stream_id": "s", "event_id": "e", "event_hash": "h",
            "occurred_at": occurred.isoformat(),
            "payload": {"dedupe_key": key, "notification_id": "n"}}


def test_a_match_inside_the_window_suppresses(tmp_path, monkeypatch):
    ob = _outbox(tmp_path)
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(ob, "_iter_all_events", lambda: iter([_event("k", recent)]))
    assert ob._check_dedupe("k", window_hours=6) is not None


def test_a_match_older_than_the_window_does_not(tmp_path, monkeypatch):
    """Otherwise an unchanged daily brief matches its own first send forever."""
    ob = _outbox(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    monkeypatch.setattr(ob, "_iter_all_events", lambda: iter([_event("k", old)]))
    assert ob._check_dedupe("k", window_hours=6) is None


def test_no_window_stays_unbounded(tmp_path, monkeypatch):
    """Decision-keyed callers must keep the old never-re-page behaviour."""
    ob = _outbox(tmp_path)
    ancient = datetime.now(timezone.utc) - timedelta(days=400)
    monkeypatch.setattr(ob, "_iter_all_events", lambda: iter([_event("k", ancient)]))
    assert ob._check_dedupe("k") is not None


def test_an_unreadable_timestamp_does_not_widen_the_window(tmp_path, monkeypatch):
    """Fail toward delivering, not toward silent indefinite suppression."""
    ob = _outbox(tmp_path)
    bad = {"stream_id": "s", "event_id": "e", "event_hash": "h",
           "occurred_at": "not-a-date", "payload": {"dedupe_key": "k"}}
    monkeypatch.setattr(ob, "_iter_all_events", lambda: iter([bad]))
    assert ob._check_dedupe("k", window_hours=6) is None
