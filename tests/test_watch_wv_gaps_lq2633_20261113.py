"""LQ-20261107-2633: the two disclosed LQ-2622 gaps. Synthetic rows, no DB.

1. saved_list filter: a failed membership read is UNKNOWN for the cards (kept + marked), not an empty set that drops all.
2. _screener_finds_candidates: a failed pin read is an explicit UNKNOWN body, not "0 candidates".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import api_v2  # noqa: E402
from lib.data_broker import watch_domains, watch_intelligence as wi  # noqa: E402


def _items(*syms):
    return [{"symbol": s, "card": {"symbol": s}} for s in syms]


Q = {"view": "all", "saved_list": "L1"}


def test_failed_membership_read_keeps_cards_marked_unknown(monkeypatch):
    monkeypatch.setattr(watch_domains, "saved_list_membership_status", lambda lid: (set(), "OperationalError"))
    out = wi._apply_filters(_items("AAA", "BBB"), dict(Q))
    assert [i["symbol"] for i in out] == ["AAA", "BBB"]
    for i in out:
        assert i["saved_list_membership"] == {"state": "UNKNOWN", "list_id": "L1", "cause": "OperationalError"}
        assert i["card"]["saved_list_membership"]["state"] == "UNKNOWN"


def test_readable_membership_still_filters_and_does_not_mark(monkeypatch):
    monkeypatch.setattr(watch_domains, "saved_list_membership_status", lambda lid: ({"AAA"}, None))
    out = wi._apply_filters(_items("AAA", "BBB"), dict(Q))
    assert [i["symbol"] for i in out] == ["AAA"] and "saved_list_membership" not in out[0]


def test_membership_is_read_once_per_filter_pass_not_per_card(monkeypatch):
    calls = []
    monkeypatch.setattr(watch_domains, "saved_list_membership_status",
                        lambda lid: calls.append(lid) or ({"AAA", "BBB", "CCC"}, None))
    wi._apply_filters(_items("AAA", "BBB", "CCC"), dict(Q))
    assert calls == ["L1"]


def test_no_saved_list_never_reads_membership(monkeypatch):
    monkeypatch.setattr(watch_domains, "saved_list_membership_status",
                        lambda lid: pytest.fail("membership read without a saved_list filter"))
    assert len(wi._apply_filters(_items("AAA"), {"view": "all"})) == 1


def _boom(*a, **k):
    raise api_v2._DbReadError("connection refused", unavailable=True)


def test_screener_finds_unreadable_pins_is_explicit_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(api_v2, "_db_required", _boom)
    status, body = api_v2._screener_finds_candidates({})
    assert status == 503 and body["ok"] is False and body["state"] == "UNKNOWN"
    assert body["route"] == "_screener_finds_candidates" and "connection refused" in body["cause"]
    assert "candidates" not in body


def test_screener_finds_readable_empty_is_still_ok_zero(monkeypatch):
    monkeypatch.setattr(api_v2, "_db_required", lambda *a, **k: [])
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(api_v2, "_wide_finds_payload", lambda: {})
    monkeypatch.setattr(api_v2, "_finds_track_record", lambda: {})
    body = api_v2._screener_finds_candidates({})
    assert body["ok"] is True and body["count"] == 0 and body["candidates"] == []
