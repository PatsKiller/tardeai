"""A half-written FINAL JSONL record (disk full mid-write) is skipped, archived on the next write and alerted once.

2026-10-30: ``anthropic_credit.jsonl`` row 12410 and ``persistent_wake/state/wakes.jsonl`` row 3514 were left
half-written. The credit book then refused every Anthropic call (CREDIT_UNAVAILABLE) with no log and no alert for
30+ hours, and the hourly persistent wake died on JSONDecodeError. Corruption anywhere else still fails loudly.
Fixtures only: synthetic policy, temp dirs, Telegram stubbed.

The storage/credit helpers carry no sender (planner-lane reach); this suite injects the notification owner and a
fake transport so both delivery failure classes are exercised without a real send.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone

import pytest

from scripts.lib import anthropic_routing as routing
from scripts.lib import jsonl_tail
from scripts.lib import ops_diagnostics, ops_notify_owner
from scripts.lib.anthropic_credit import CreditBook, CreditDenied
from scripts.lib.persistent_wake_store import JsonlStore

COVERS = [
    "scripts/lib/jsonl_tail.py",
    "scripts/lib/anthropic_routing.py",
    "scripts/lib/ops_notify_owner.py",
]

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
    ops_notify_owner.install()  # the already-authorised owner registers lazily-resolved delivery
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


# ── F2: every damaged fragment survives, even at one frozen second ──────────────────────────────────


def test_two_repairs_in_one_frozen_second_retain_both_fragments(tmp_path, monkeypatch, sent):
    monkeypatch.setattr(jsonl_tail, "time", types.SimpleNamespace(time=lambda: 1_700_000_000))
    store = JsonlStore(tmp_path)
    store.append_unique("wakes", "wake_id", {"wake_id": "w0"})

    with open(store.path("wakes"), "ab") as fh:
        fh.write(b'{"wake_id": "damage-one"')
    assert store.count("wakes") == 1
    store.append_unique("wakes", "wake_id", {"wake_id": "w1"})  # repair archives fragment one

    with open(store.path("wakes"), "ab") as fh:
        fh.write(b'{"wake_id": "damage-two"')
    store.append_unique("wakes", "wake_id", {"wake_id": "w2"})  # same frozen second; must not overwrite

    archives = sorted(tmp_path.glob("wakes.jsonl.corrupt-tail-*"))
    assert len(archives) == 2, [p.name for p in archives]
    assert len({p.name for p in archives}) == 2
    fragments = b"".join(p.read_bytes() for p in archives)
    assert b"damage-one" in fragments and b"damage-two" in fragments
    assert store.count("wakes") == 3


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


# ── F4: an unavailable diagnostic transport never blocks wake recovery ───────────────────────────────


def test_unavailable_sender_transport_never_blocks_wake_recovery(tmp_path, monkeypatch):
    store = JsonlStore(tmp_path)
    with open(store.path("wakes"), "ab") as fh:
        fh.write(b'{"wake_id": "w0"}\n{"agent_id": "cio", "corr')  # valid prefix + truncated tail
    ops_notify_owner.install()
    jsonl_tail._alerted.clear()
    # Both historical sender layouts unavailable: the diagnostic must fail visibly, not raise.
    monkeypatch.setitem(sys.modules, "telegram_alert", None)
    monkeypatch.setitem(sys.modules, "scripts.telegram_alert", None)
    assert store.count("wakes") == 1
    assert store.get("wakes", "wake_id", "w0")["wake_id"] == "w0"


# ── F3: dedupe binds to CONFIRMED delivery; a failure stays retryable ────────────────────────────────


def test_tail_rejected_delivery_stays_retryable_then_dedupes(tmp_path):
    path = tmp_path / "wakes.jsonl"
    calls = []

    def reject(diag):
        calls.append("reject")
        return False

    def accept(diag):
        calls.append("accept")
        return True

    jsonl_tail._alerted.clear()
    assert jsonl_tail.report(path, 4, action="skipped", notify=reject) is False
    assert jsonl_tail.report(path, 4, action="skipped", notify=accept) is True
    assert calls == ["reject", "accept"]  # the rejection did not suppress the retry
    assert jsonl_tail.report(path, 4, action="skipped", notify=accept) is False  # now deduped
    assert calls == ["reject", "accept"]


def test_tail_raising_delivery_stays_retryable_then_dedupes(tmp_path):
    path = tmp_path / "wakes.jsonl"
    calls = []

    def boom(diag):
        calls.append("raise")
        raise RuntimeError("transport down")

    def accept(diag):
        calls.append("accept")
        return True

    jsonl_tail._alerted.clear()
    assert jsonl_tail.report(path, 4, action="skipped", notify=boom) is False
    assert jsonl_tail.report(path, 4, action="skipped", notify=accept) is True
    assert calls == ["raise", "accept"]
    assert jsonl_tail.report(path, 4, action="skipped", notify=accept) is False


def test_routing_rejected_delivery_stays_retryable_then_dedupes():
    calls = []

    def reject(diag):
        calls.append("reject")
        return False

    def accept(diag):
        calls.append("accept")
        return True

    routing._refusal_alerted.clear()
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route", notify=reject) is False
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route", notify=accept) is True
    assert calls == ["reject", "accept"]
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route", notify=accept) is False
    assert calls == ["reject", "accept"]


def test_routing_raising_delivery_stays_retryable_then_dedupes():
    calls = []

    def boom(diag):
        calls.append("raise")
        raise RuntimeError("transport down")

    def accept(diag):
        calls.append("accept")
        return True

    routing._refusal_alerted.clear()
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route", notify=boom) is False
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route", notify=accept) is True
    assert calls == ["raise", "accept"]
    assert routing._report_credit_refusal("CREDIT_UNAVAILABLE", where="route", notify=accept) is False


def test_absent_owner_is_not_delivered_and_remains_retryable(tmp_path):
    path = tmp_path / "wakes.jsonl"
    jsonl_tail._alerted.clear()
    ops_diagnostics.unregister("store_damage")
    try:
        assert jsonl_tail.report(path, 3, action="skipped") is False
        assert jsonl_tail.report(path, 3, action="skipped") is False  # absence is not success
    finally:
        calls = []
        ops_diagnostics.register("store_damage", lambda diag: calls.append(diag) or True)
        try:
            assert jsonl_tail.report(path, 3, action="skipped") is True
        finally:
            ops_notify_owner.install()
    assert len(calls) == 1


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


# ── an owner-less process retains the event; the owner drains it ────────────────────────────────────
# The governed bridge and the provider-health check make Anthropic calls but hold no sender (§23.20), so
# `deliver` had no notifier and nothing was kept. The outage was reported to nobody, which is exactly the
# 2026-10-30 silence this PR exists to end.


def _spool_env(monkeypatch, tmp_path):
    path = tmp_path / "spool.jsonl"
    monkeypatch.setenv(ops_diagnostics.SPOOL_ENV, str(path))
    return path


def test_a_process_without_an_owner_spools_the_diagnostic_instead_of_dropping_it(monkeypatch, tmp_path):
    spool = _spool_env(monkeypatch, tmp_path)
    jsonl_tail._alerted.clear()
    ops_diagnostics.unregister("store_damage")
    try:
        assert jsonl_tail.report(tmp_path / "wakes.jsonl", 3, action="skipped") is False
        assert jsonl_tail.report(tmp_path / "wakes.jsonl", 3, action="skipped") is False
    finally:
        ops_notify_owner.install()
    rows = ops_diagnostics.spooled()
    assert len(rows) == 1, rows  # retried on every call, retained ONCE
    assert rows[0]["channel"] == "store_damage" and "STORE DAMAGE" in rows[0]["message"]
    assert spool.exists()


def test_the_owner_drains_the_spool_and_keeps_what_it_could_not_deliver(monkeypatch, tmp_path):
    _spool_env(monkeypatch, tmp_path)
    jsonl_tail._alerted.clear()
    ops_diagnostics.unregister("store_damage")
    try:
        jsonl_tail.report(tmp_path / "one.jsonl", 3, action="skipped")
        jsonl_tail.report(tmp_path / "two.jsonl", 4, action="skipped")
    finally:
        ops_notify_owner.install()
    assert len(ops_diagnostics.spooled()) == 2

    accepted: list[str] = []

    def only_the_second(row):
        if row["path"].endswith("two.jsonl"):
            accepted.append(row["path"])
            return True
        return False

    assert ops_diagnostics.drain(only_the_second) == 1
    remaining = ops_diagnostics.spooled()
    assert [r["path"] for r in remaining] == [str(tmp_path / "one.jsonl")], remaining
    assert accepted == [str(tmp_path / "two.jsonl")]


def test_a_dry_run_sends_nothing_and_reports_what_it_would_have_sent(tmp_path, sent):
    """The reviewer's reproduction: reading a damaged store during --dry-run paged the operator."""
    jsonl_tail._alerted.clear()
    path = tmp_path / "wakes.jsonl"
    ops_diagnostics.suppress("run_persistent_wake --dry-run")
    try:
        assert jsonl_tail.report(path, 3, action="skipped") is False
        assert jsonl_tail.report(path, 3, action="skipped") is False
        would_have_sent = ops_diagnostics.suppressed_events()
    finally:
        ops_diagnostics.resume()
    assert sent == [], sent  # nothing reached the transport
    assert len(would_have_sent) == 2  # every call is recorded; dedupe belongs to the caller's key
    assert "STORE DAMAGE" in would_have_sent[0]["diagnostic"]["message"]
    assert would_have_sent[0]["reason"] == "run_persistent_wake --dry-run"
    # and the suppression did not leave the dedupe key set: the next real read still alerts
    assert jsonl_tail.report(path, 3, action="skipped") is True
    assert len(sent) == 1


ANCHOR = 'JSONL_TRUNCATED_TAIL_20261031'  # config/ci_gates/jsonl_truncated_tail_20261031.json names this file


def test_one_truncated_spool_record_does_not_lose_the_intact_ones(monkeypatch, tmp_path):
    """A disk-full write leaves a partial final record; the intact ones must still be delivered."""
    spool = _spool_env(monkeypatch, tmp_path)
    spool.parent.mkdir(parents=True, exist_ok=True)
    good_one = {"channel": "store_damage", "path": "/a", "day": "2026-11-05", "message": "STORE DAMAGE a"}
    good_two = {"channel": "credit_refusal", "code": "CREDIT_UNAVAILABLE", "day": "2026-11-05", "message": "LANE OFF"}
    spool.write_text(json.dumps(good_one) + "\n" + json.dumps(good_two) + "\n" + '{"channel": "store_dam')
    delivered = []
    assert ops_diagnostics.drain(lambda row: delivered.append(row["message"]) or True) == 2
    assert delivered == ["STORE DAMAGE a", "LANE OFF"]
    assert ops_diagnostics.spooled() == []


def test_a_write_after_an_interrupted_record_restores_drainability(monkeypatch, tmp_path):
    spool = _spool_env(monkeypatch, tmp_path)
    spool.parent.mkdir(parents=True, exist_ok=True)
    spool.write_text('{"channel": "store_dam')  # interrupted mid-record
    ops_diagnostics.unregister("store_damage")
    try:
        assert jsonl_tail.report(tmp_path / "wakes.jsonl", 3, action="skipped") is False
    finally:
        ops_notify_owner.install()
    rows = ops_diagnostics.spooled()
    assert len(rows) == 1 and rows[0]["channel"] == "store_damage", rows


def test_the_wake_runner_drains_the_spool_even_when_nothing_is_due(monkeypatch, tmp_path, sent):
    """An hourly run that selects no subject is still a run: a credit outage must not wait for a busy hour."""
    _spool_env(monkeypatch, tmp_path)
    jsonl_tail._alerted.clear()
    ops_diagnostics.unregister("store_damage")
    try:
        jsonl_tail.report(tmp_path / "damaged.jsonl", 3, action="skipped")
    finally:
        ops_notify_owner.install()
    assert len(ops_diagnostics.spooled()) == 1
    sent.clear()

    import run_persistent_wake as rpw

    rpw.run_once(
        agent_id="cio",
        dry_run=False,
        env={"PERSISTENT_WAKE_ENABLED": "1", "PERSISTENT_WAKE_SCHEDULE_ENABLED": "1"},
        state_root=tmp_path / "state",
        research_objects=[], receipts=[], material_changes=[], operator_turns=[],
    )
    assert sent and "STORE DAMAGE" in sent[0]["message"], sent
    assert ops_diagnostics.spooled() == []


def test_a_select_only_run_sends_nothing_and_keeps_the_spool(monkeypatch, tmp_path, sent):
    """`--select-only` is documented as "selection only; no writes" — draining there sent real alerts."""
    _spool_env(monkeypatch, tmp_path)
    jsonl_tail._alerted.clear()
    ops_diagnostics.unregister("store_damage")
    try:
        jsonl_tail.report(tmp_path / "damaged.jsonl", 3, action="skipped")
    finally:
        ops_notify_owner.install()
    assert len(ops_diagnostics.spooled()) == 1
    sent.clear()

    import run_persistent_wake as rpw

    rpw.run_once(
        agent_id="cio",
        dry_run=False,
        select_only=True,
        env={"PERSISTENT_WAKE_ENABLED": "1", "PERSISTENT_WAKE_SCHEDULE_ENABLED": "1"},
        state_root=tmp_path / "state",
        research_objects=[], receipts=[], material_changes=[], operator_turns=[],
    )
    assert sent == [], sent
    assert len(ops_diagnostics.spooled()) == 1, "a select-only run consumed the outbox"
