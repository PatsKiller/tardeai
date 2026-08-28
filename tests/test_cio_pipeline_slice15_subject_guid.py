"""Slice 15: subject_guid from identity registry. No mint. UNRESOLVED stays UNRESOLVED."""
from __future__ import annotations

from scripts.lib.cio_subject_guid import UNRESOLVED, lookup_subject, stamp_row


def test_unknown_symbol_stays_unresolved():
    hit = lookup_subject("ZZZZNOTAREAL")
    assert hit["subject_guid"] is None
    assert hit["identity_status"] == UNRESOLVED
    row = stamp_row({"symbol": "ZZZZNOTAREAL", "action": "WATCH"})
    assert row["subject_guid"] is None
    assert row["identity_status"] == UNRESOLVED
    assert row["action"] == "WATCH"


def test_stamp_does_not_call_register(monkeypatch):
    import scripts.lib.identity_registry as ir
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not mint")

    monkeypatch.setattr(ir, "register", _boom)
    stamp_row({"symbols": ["SCHD"]})
    assert called["n"] == 0
