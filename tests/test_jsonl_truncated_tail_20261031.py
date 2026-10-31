"""A half-written FINAL JSONL record (disk full mid-write) is skipped, archived on the next write and alerted once.

2026-10-30: ``anthropic_credit.jsonl`` row 12410 and ``persistent_wake/state/wakes.jsonl`` row 3514 were left
half-written. The credit book then refused every Anthropic call (CREDIT_UNAVAILABLE) with no log and no alert for
30+ hours, and the hourly persistent wake died on JSONDecodeError. Corruption anywhere else still fails loudly.
Fixtures only: synthetic policy, temp dirs, Telegram stubbed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts.lib import anthropic_routing as routing
from scripts.lib import jsonl_tail
from scripts.lib.anthropic_credit import CreditBook, CreditDenied
from scripts.lib.persistent_wake_store import JsonlStore

COVERS = ["scripts/lib/jsonl_tail.py", "scripts/lib/anthropic_routing.py"]

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"


def _policy():
    price = {
        "input": "0.10",
        "output": "0.50",
        "cache_read": "0.01",
        "cache_write_5m": "0.125",
        "cache_write_1h": "0.20",
        "batch_multiplier": "0.5",
    }
    return {
        "enabled": True,
        "promotion_id": "fixture-promotion",
        "credit_usd": "200",
        "total_cap_usd": "190",
        "daily_cap_usd": "10",
        "starts_at": "2026-10-25T00:00:00Z",
        "expires_at": "2026-11-16T00:00:00Z",
        "per_call_caps_usd": {"bulk": "0.10", "standard": "0.25", "high": "0.50", "highest": "0.50"},
        "models": {"bulk": HAIKU, "standard": OPUS, "high": OPUS, "highest": OPUS},
        "retry": {"max_attempts": 2, "max_delay_seconds": 0},
        "input_framing_margin_tokens": 4096,
        "pricing": {HAIKU: price, OPUS: price},
    }


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    def fake_send(message, **kw):
        calls.append({"message": message, **kw})
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", fake_send)
    jsonl_tail._alerted.clear()
    routing._refusal_alerted.clear()
    return calls


# ── the detector ────────────────────────────────────────────────────────────────────────────────────


def test_truncated_tail_detection_is_narrow():
    assert jsonl_tail.truncated_tail(b'{"a":1}\n{"b":') == (8, b'{"b":')
    assert jsonl_tail.truncated_tail(b'{"a":1}\n') is None  # clean
    assert jsonl_tail.truncated_tail(b'{"a":1}\n{"b":2}') is None  # complete record, newline missing
    assert jsonl_tail.truncated_tail(b'{"a":\n{"b":2}\n') is None  # interior damage is not a tail
    assert jsonl_tail.truncated_tail(b"") is None
    assert jsonl_tail.truncated_tail(b"broken") is None  # whole-file garbage is not a tail


# ── the Anthropic credit book ───────────────────────────────────────────────────────────────────────


def _book_with_rows(tmp_path, n=3):
    book = CreditBook(tmp_path, _policy())
    for i in range(n):
        book.record_failure("timeout", now=NOW)
    return book


def test_credit_book_truncated_tail_stays_closed_but_alerts_once(tmp_path, sent):
    book = _book_with_rows(tmp_path)
    with open(book.path, "ab") as fh:
        fh.write(b'{"schema":"x","event":"reserve","sequ')  # disk full mid-write
    for _ in range(3):
        with pytest.raises(CreditDenied, match="CREDIT_UNAVAILABLE"):
            book._read()  # an unreadable spend journal is never read as zero spend
    assert len(sent) == 1 and sent[0]["priority"] == "P1" and "STORE DAMAGE" in sent[0]["message"]
    assert "Anthropic lane OFF" in sent[0]["message"]


def test_credit_book_interior_corruption_still_fails_closed(tmp_path, sent):
    book = _book_with_rows(tmp_path)
    lines = book.path.read_bytes().split(b"\n")
    lines[1] = lines[1][:20]
    book.path.write_bytes(b"\n".join(lines))
    with pytest.raises(CreditDenied):
        book._read()


# ── the persistent wake store ───────────────────────────────────────────────────────────────────────


def test_wake_store_reads_past_truncated_tail_and_repairs_on_write(tmp_path, sent):
    store = JsonlStore(tmp_path)
    for i in range(3):
        store.append_unique("wakes", "wake_id", {"wake_id": f"w{i}", "agent_id": "cio"})
    with open(store.path("wakes"), "ab") as fh:
        fh.write(b'{"agent_id": "cio", "authority": "READ_ONLY_ADVISORY", "corr')
    assert store.count("wakes") == 3
    assert store.get("wakes", "wake_id", "w1")["agent_id"] == "cio"
    inserted, _ = store.append_unique("wakes", "wake_id", {"wake_id": "w3", "agent_id": "cio"})
    assert inserted and store.count("wakes") == 4
    assert [json.loads(x)["wake_id"] for x in store.path("wakes").read_text().splitlines()] == ["w0", "w1", "w2", "w3"]
    assert list(tmp_path.glob("wakes.jsonl.corrupt-tail-*"))
    assert len(sent) == 1  # one alert per file per day


def test_wake_store_interior_corruption_still_raises(tmp_path, sent):
    store = JsonlStore(tmp_path)
    store.path("wakes").write_text('{"wake_id": "w0"}\n{"wake_id": \n{"wake_id": "w2"}\n')
    with pytest.raises(json.JSONDecodeError):
        store.count("wakes")


# ── routing no longer swallows a broken credit book ─────────────────────────────────────────────────


def test_broken_book_refusal_is_logged_and_alerted_once_per_day(sent, caplog):
    caplog.set_level("WARNING")
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route") is True
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route") is False
    assert len(sent) == 1 and sent[0]["priority"] == "P2" and "ANTHROPIC LANE OFF" in sent[0]["message"]
    assert "anthropic credit book unavailable: CREDIT_UNAVAILABLE" in caplog.text


def test_ordinary_cap_refusal_is_logged_not_alerted(sent):
    assert routing._report_credit_refusal("PAUSED_TODAY", where="route") is False
    assert sent == []


def test_record_fallback_failure_is_reported(monkeypatch, sent):
    class Boom:
        def __init__(self, *a, **k):
            raise CreditDenied("CREDIT_UNAVAILABLE")

    monkeypatch.setattr(routing, "CreditBook", Boom)
    monkeypatch.setattr(routing, "state_root", lambda: "/nonexistent")
    monkeypatch.setattr(routing, "load_policy", lambda: {})
    routing.FundingContext.record_fallback("TIMEOUT")  # must not raise
    assert len(sent) == 1 and "CREDIT_UNAVAILABLE" in sent[0]["message"]
