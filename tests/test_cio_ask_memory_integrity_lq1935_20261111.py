"""LQ-20261107-1935 (EPIC-A part 2). Synthetic fixtures only; nothing reads or writes production state.

F6 retry bound: a dead memory service is retried on a back-off, not every five minutes forever.
F5: "memory unreadable" is distinguishable from "nothing remembered", in the answer payload and the ledger.
F7: a failed / unconfirmed Telegram mirror leaves a ledger receipt and is reported to the caller.
"""

from __future__ import annotations

from datetime import timedelta

from scripts.lib import cio_ask_core as core
from scripts.lib import cio_ask_lifecycle as life
from scripts.lib.cio_ask_contract import EntityRef
from scripts.lib.cio_ask_memory import SpineAskMemory
from scripts.lib.cio_ask_store import AskEventStore
from tests.test_cio_ask_20261023 import (  # noqa: F401  (fixtures + helpers; _offline is autouse)
    _offline,
    cc_ask,
    make_deps,
)
from tests.test_cio_ask_hourly_20261026 import ASK, NOW, TID, fixture


def _memory_events(d):
    return [e for e in d.store.events(thread_id=TID) if e.get("kind") == "ask.memory_synced"]


def _tick(d, when):
    life._retry_publication(d, d.store.thread(TID), d.store.events(thread_id=TID), now=when)


# ── F6: bounded retry / back-off ──────────────────────────────────────────────────────────────────────────────────


def test_dead_memory_service_is_retried_on_a_backoff_not_every_tick(tmp_path):
    d = fixture(tmp_path)
    d.memory.ok = False  # connection refused: every write is unacknowledged
    for i in range(288):  # one day of 5-minute ticks
        _tick(d, NOW + timedelta(minutes=5 * i))
    attempts = len(_memory_events(d))
    assert 1 <= attempts <= 14, attempts  # the old rule wrote one attempt per 5-minute slot: 288
    last = _memory_events(d)[-1]["memory_sync"]
    assert last["state"] == "pending" and last["attempts"] == attempts and last["next_retry_after_s"] >= 300


def test_backoff_never_gives_up_and_recovers_when_the_service_returns(tmp_path):
    d = fixture(tmp_path)
    d.memory.ok = False
    for i in range(40):
        _tick(d, NOW + timedelta(minutes=5 * i))
    d.memory.ok = True
    when = NOW + timedelta(days=2)  # beyond the 6 h cap: the next tick must retry
    _tick(d, when)
    assert _memory_events(d)[-1]["memory_sync"]["state"] == "synced"
    n = len(_memory_events(d))
    _tick(d, when + timedelta(minutes=5))
    assert len(_memory_events(d)) == n  # synced: no further writes


def test_backoff_schedule_is_monotonic_and_capped():
    waits = [life.memory_retry_wait(n).total_seconds() for n in range(0, 20)]
    assert waits[0] == waits[1] == 0 and waits[2] == 300 and waits[3] == 600
    assert waits == sorted(waits) and max(waits) == 6 * 3600


# ── F5: unreadable != empty ───────────────────────────────────────────────────────────────────────────────────────


def _exmp():
    return EntityRef(name="Example Robotics", symbol="EXMP", kind="security", security_guid="fixture-security-1935",
                     resolution="CONFIRMED")


def test_spine_recall_error_is_reported_not_flattened_to_empty(tmp_path):
    # Force the failure deterministically: the spine reader raises.
    mem = SpineAskMemory(spine_path=tmp_path / "missing_dir" / "x.jsonl")
    import scripts.lib.cross_asset.security_research_spine as sp

    orig = sp.load_latest
    sp.load_latest = lambda *a, **k: (_ for _ in ()).throw(OSError("unreadable"))
    try:
        items, errors = mem.recall_checked(entity=_exmp(), limit=4)
        assert mem.recall(entity=_exmp(), limit=4) == []  # the old API is unchanged
    finally:
        sp.load_latest = orig
    assert items == [] and errors == [{"store": "security_research_spine", "error": "OSError"}]


def test_answer_payload_and_ledger_carry_recall_health(tmp_path, _offline):
    class Broken:
        def append(self, **kw):
            return {"ok": True}

        def recall(self, **kw):
            raise OSError("spine unreadable")

    d = make_deps(tmp_path, memory=Broken())
    out = cc_ask(d, _offline, "What is the view on TSLA?")
    answers = [e for e in d.store.events() if e.get("kind") == "ask.answer_version"]
    health = answers[-1]["answer"]["provenance"]["recall_health"]
    assert health["state"] == "unreadable" and health["errors"][0]["error"] == "OSError"
    assert out["ok"]


def test_healthy_empty_recall_is_marked_empty_not_unreadable(tmp_path, _offline):
    d = make_deps(tmp_path)  # FakeMemory: readable, nothing stored
    cc_ask(d, _offline, "What is the view on TSLA?")
    answers = [e for e in d.store.events() if e.get("kind") == "ask.answer_version"]
    assert answers[-1]["answer"]["provenance"]["recall_health"]["state"] == "empty"


# ── F7: mirror failure leaves a receipt ───────────────────────────────────────────────────────────────────────────


def test_failed_telegram_mirror_leaves_a_ledger_receipt(tmp_path, _offline):
    d = make_deps(tmp_path)

    def boom(text):
        raise ConnectionError("telegram down")

    d.telegram_send = boom
    out = cc_ask(d, _offline, "What is the view on TSLA?")
    assert out["ok"] and out["mirror"] == {"state": "failed", "reason": "ConnectionError"}
    rows = [e for e in d.store.events() if e.get("kind") == "ask.mirror_status"]
    assert len(rows) == 1 and rows[0]["mirror"]["state"] == "failed" and rows[0]["ask_id"] == out["ask_id"]


def test_unconfirmed_mirror_is_recorded_and_sent_mirror_is_not_noise(tmp_path, _offline):
    d = make_deps(tmp_path)
    d.telegram_send = lambda text: {"ok": False}
    out = cc_ask(d, _offline, "What is the view on TSLA?")
    assert out["mirror"]["state"] == "unconfirmed"
    assert [e["mirror"]["state"] for e in d.store.events() if e.get("kind") == "ask.mirror_status"] == ["unconfirmed"]
    d2 = make_deps(tmp_path / "ok") if (tmp_path / "ok").mkdir() is None else None
    out2 = cc_ask(d2, _offline, "What is the view on TSLA?")
    assert out2["mirror"]["state"] == "sent"
    assert not [e for e in d2.store.events() if e.get("kind") == "ask.mirror_status"]
