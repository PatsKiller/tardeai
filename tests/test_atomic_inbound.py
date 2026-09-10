"""Atomic inbound — one coherent intake; checkpoint advances only after all artifacts.

Phase 3 (Grok-closure). Hermetic: all five pipeline steps are injected so the
ordering invariant is asserted directly (checkpoint is LAST; a failure before it
never advances the offset).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.lib.comms.inbound as inbound_mod  # noqa: E402
from scripts.lib.atomic_inbound import (  # noqa: E402
    FEATURE_FLAG,
    process_update_atomically,
)


def _update(uid=100):
    return {"update_id": uid, "message": {"message_id": 7, "chat": {"id": "42"}, "text": "V analyst target"}}


class _Event:
    event_id = "evt-100"
    thread_id = "thr-1"
    correlation_id = "corr-1"
    direction = "INBOUND"
    sanitized_body = "V analyst target"


def _ok_event():
    return {"ok": True, "event_id": "evt-100", "event": _Event()}


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setenv(FEATURE_FLAG, "1")
    monkeypatch.setattr(
        inbound_mod,
        "claim_update",
        lambda uid: type("C", (), {"already_processed": False, "checkpoint_offset": uid - 1})(),
    )
    monkeypatch.setattr(inbound_mod, "commit_checkpoint", lambda uid: uid)
    yield


def test_feature_flag_off_refuses(monkeypatch):
    monkeypatch.setenv(FEATURE_FLAG, "0")
    r = process_update_atomically(_update())
    assert not r.ok and r.outcome == "refused" and r.reason == "feature_flag_off"


def test_already_processed_short_circuits(monkeypatch):
    calls = []
    monkeypatch.setattr(
        inbound_mod, "claim_update", lambda uid: type("C", (), {"already_processed": True, "checkpoint_offset": 200})()
    )
    steps = {"normalize": lambda u, **k: calls.append("normalize")}
    r = process_update_atomically(_update(100), steps=steps)
    assert r.outcome == "already_processed" and r.ok
    assert calls == []  # no further steps ran


def test_full_success_orders_checkpoint_last():
    order = []

    def norm(u, **k):
        order.append("normalize")
        return _ok_event()

    def tag(text):
        order.append("tag")
        return {"resolved": [], "topics": [], "unresolved_mentions": []}

    def turn(u, t, text, ev):
        order.append("turn")
        return 1

    def receipt(**k):
        order.append("receipt")
        return {"ok": True, "receipt_id": "rcpt-1"}

    def commit(uid):
        order.append("checkpoint")
        return uid

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(inbound_mod, "commit_checkpoint", commit)
    r = process_update_atomically(
        _update(),
        steps={
            "normalize": norm,
            "tag": tag,
            "turn": turn,
            "receipt": receipt,
        },
    )
    monkeypatch.undo()
    assert r.ok and r.outcome == "processed"
    assert r.event_id == "evt-100" and r.receipt_id == "rcpt-1" and r.turn_written == 1
    assert order == ["normalize", "tag", "turn", "receipt", "checkpoint"]


def test_normalize_failure_never_advances_checkpoint():
    order = []

    def norm(u, **k):
        order.append("normalize")
        return {"ok": False, "reason": "bad"}

    r = process_update_atomically(_update(), steps={"normalize": norm})
    assert not r.ok and r.outcome == "error"
    assert order == ["normalize"]


def test_turn_failure_never_advances_checkpoint():
    order = []

    def norm(u, **k):
        order.append("normalize")
        return _ok_event()

    def tag(text):
        return {"resolved": [], "topics": [], "unresolved_mentions": []}

    def turn(u, t, text, ev):
        order.append("turn")
        raise RuntimeError("db down")

    def receipt(**k):
        order.append("receipt")

    r = process_update_atomically(_update(), steps={"normalize": norm, "tag": tag, "turn": turn, "receipt": receipt})
    assert not r.ok and "turn_failed" in r.reason
    assert order == ["normalize", "turn"]  # receipt + checkpoint never ran


def test_receipt_failure_never_advances_checkpoint():
    order = []

    def norm(u, **k):
        return _ok_event()

    def tag(text):
        return {"resolved": [], "topics": [], "unresolved_mentions": []}

    def turn(u, t, text, ev):
        return 1

    def receipt(**k):
        order.append("receipt")
        return {"ok": False}

    r = process_update_atomically(_update(), steps={"normalize": norm, "tag": tag, "turn": turn, "receipt": receipt})
    assert not r.ok and r.reason == "receipt_rejected"
    assert order == ["receipt"]


def test_implausible_checkpoint_is_incident(monkeypatch):
    monkeypatch.setattr(
        inbound_mod,
        "claim_update",
        lambda uid: type("C", (), {"already_processed": False, "checkpoint_offset": uid + 2_000_000})(),
    )
    r = process_update_atomically(_update(100), steps={"normalize": lambda u, **k: _ok_event()})
    assert r.plausibility["incident"] is True


def test_update_id_required():
    r = process_update_atomically({"message": {"message_id": 1, "chat": {"id": "1"}, "text": "x"}})
    assert not r.ok and r.outcome == "error" and "update_id" in r.reason
