"""Synthetic Ask lifecycle proofs: clocks, durable retries and bounded accounting."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.lib import cio_ask_core as core
from scripts.lib import cio_ask_lifecycle as life
from scripts.lib.cio_ask_contract import AskAnswer, EntityRef
from scripts.lib.cio_ask_store import AskEventStore

NOW = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
TID, ASK = "thr_fixture", "ask_fixture"
ENTITY = EntityRef(
    name="Example Robotics", symbol="EXMP", kind="security", security_guid="fixture-security", resolution="CONFIRMED"
)


class Memory:
    def __init__(self):
        self.ok = True
        self.calls = 0

    def recall(self, **kw):
        return []

    def append(self, **kw):
        self.calls += 1
        return {"ok": self.ok}


def fixture(tmp_path, *, answer=True, partial=False, provider=None):
    store = AskEventStore(tmp_path / "asks.jsonl")
    cfg = {
        "enabled": True,
        "mirror_cc_to_telegram": True,
        "cost": {
            "approval": {"status": "APPROVED"},
            "process_id": "cio_ask_deep_research",
            "daily_cap_usd": 5,
            "per_question_cap_usd": 0.5,
            "projected_usd_deep": 0.25,
        },
        "lifecycle": {"enabled": True, "memory_apply": False, "daily_request_cap": 30, "max_attempts_per_evidence": 2},
        "reanswer": {"min_hours_between_per_thread": 6, "max_per_day": 10},
    }
    d = core.AskDeps(
        store=store,
        memory=Memory(),
        tracker=None,
        resolver=lambda _: [],
        sizing=None,
        cost=core.CostGate(cfg, store, lambda *_: {"allow": True}),
        config=cfg,
        deep_provider=provider,
        telegram_send=lambda _: {"ok": True, "queued": "fixture-outbox"},
        run_async=False,
    )
    life.append(
        store,
        "ask.asked",
        {"thread_id": TID, "ask_id": ASK, "question": "What changed at Example Robotics?", "channel": "cc"},
        key=("seed",),
        now=NOW - timedelta(days=2),
    )
    life.append(
        store,
        "ask.entity_resolved",
        {"thread_id": TID, "ask_id": ASK, "entity": ENTITY.to_dict()},
        key=("entity",),
        now=NOW - timedelta(days=2),
    )
    life.append(
        store,
        "ask.tracking_changed",
        {"thread_id": TID, "entity_key": ENTITY.memory_key, "state": "tracked"},
        key=("track",),
        now=NOW - timedelta(days=2),
    )
    if answer:
        core.record_answer(
            AskAnswer(
                version=1,
                ask_id=ASK,
                thread_id=TID,
                depth="deep",
                status="deep",
                summary="Stored evidence",
                entities=[ENTITY],
                produced_at=life.stamp(NOW - timedelta(hours=43)),
                provenance={"evidence_fingerprint": "same", "partial": partial},
            ),
            deps=d,
        )
    return d


def evidence(_request, fingerprint="same", **kw):
    return {
        "fingerprint": fingerprint,
        "facts": [],
        "source_runs": [{"source": "fixture", "status": "ok", "observed_at": life.stamp(NOW)}],
    }


def provider(calls, *, known=True, partial=False):
    def call(ctx, **kw):
        calls.append({"context": ctx, **kw})
        return AskAnswer(
            version=1,
            ask_id=ctx.request.ask_id,
            thread_id=ctx.thread_id,
            depth="deep",
            status="deep",
            summary="New evidence answer",
            produced_at=life.stamp(NOW),
            entities=[ENTITY],
            cost_usd=0.04,
            provenance={
                "cost_usage_known": known,
                "evidence_fingerprint": "changed",
                "partial": partial,
                "native_request_count_known": True,
                "native_request_count": 1,
            },
        )

    return call


def run(d, **kw):
    return life.run_once(
        deps=d,
        now=kw.pop("now", NOW),
        collect=kw.pop("collect", evidence),
        event_sources=kw.pop("event_sources", []),
        run_id="fixture-run",
        **kw,
    )


def test_hourly_unchanged_updates_check_not_answer_and_makes_no_model_call(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    old = life.latest_answer(d.store.thread(TID))
    result = run(d)
    assert result["checked_count"] == result["no_change_count"] == 1
    assert calls == []
    current = d.store.thread(TID)
    assert life.latest_answer(current) == old
    projected = life.project_lifecycle(current, d.store.events(thread_id=TID), now=NOW)
    assert projected["last_checked_at"] == life.stamp(NOW)
    assert projected["last_answer_at"] == old["produced_at"]
    assert projected["next_check_at"] == life.stamp(NOW + timedelta(hours=1))
    assert projected["reason"] is None
    assert run(d)["checked_count"] == 0


def test_changed_evidence_uses_automated_process_with_real_receipts(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    result = run(d, collect=lambda req: evidence(req, "changed"))
    assert result["research_count"] == 1
    assert calls[0]["manual_trigger"] is False
    assert calls[0]["process_id"] == life.AUTO_PROCESS
    assert result["threads"][0]["consumer_readback"]["state"] == "verified"
    assert d.store.cost_today(day="2026-10-26") == 0.04
    assert result["threads"][0]["lifecycle"]["memory_sync"]["state"] == "synced"
    assert result["threads"][0]["lifecycle"]["delivery"]["state"] == "queued"


def test_manual_refresh_propagates_intent_and_is_idempotent(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    a = life.request_deep(TID, ASK, deps=d, request_id="operator-click", now=NOW)
    b = life.request_deep(TID, ASK, deps=d, request_id="operator-click", now=NOW)
    assert a["status"] == b["status"] == "deep_done"
    assert len(calls) == 1 and calls[0]["manual_trigger"] is True
    assert calls[0]["process_id"] == "cio_ask_deep_research"


def test_queued_manual_intent_drains_under_native_process_binding(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    life.append(
        d.store,
        "ask.check_requested",
        {"thread_id": TID, "ask_id": ASK, "request_id": "queued-manual", "manual_trigger": True},
        key=("queued-manual",),
        now=NOW,
    )
    result = run(d, events_only=True)
    assert result["research_count"] == 1
    assert calls[0]["manual_trigger"] is False and calls[0]["process_id"] == life.AUTO_PROCESS
    assert life.request_deep(TID, ASK, deps=d, request_id="queued-manual", now=NOW)["status"] == "deep_done"
    assert len(calls) == 1


def test_unknown_usage_retains_hold(tmp_path):
    d = fixture(tmp_path, provider=provider([], known=False))
    life.request_deep(TID, ASK, deps=d, request_id="unknown-cost", now=NOW)
    assert d.store.cost_today(day="2026-10-26") == 0.25
    assert not [e for e in d.store.events() if e["kind"] == "ask.cost"]


def test_absent_usage_evidence_never_becomes_known_zero(tmp_path):
    def missing(ctx, **kw):
        return AskAnswer(
            version=1,
            ask_id=ctx.request.ask_id,
            thread_id=TID,
            depth="deep",
            status="deep",
            summary="Unknown usage",
            entities=[ENTITY],
        )

    d = fixture(tmp_path, provider=missing)
    life.request_deep(TID, ASK, deps=d, request_id="absent-cost", now=NOW)
    assert d.store.cost_today(day="2026-10-26") == 0.25


def test_atomic_daily_admission_under_competing_requests(tmp_path):
    d = fixture(tmp_path)
    d.config["cost"]["daily_cap_usd"] = 0.5

    def attempt(i):
        return life.reserve(
            d.store,
            thread_id=TID,
            ask_id=ASK,
            request_id=f"r{i}",
            job_id=f"j{i}",
            projected=0.25,
            config=d.config,
            now=NOW,
            process_id=life.AUTO_PROCESS,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(row is not None for row, _ in results) == 2
    assert d.store.cost_today(day="2026-10-26") == 0.5


def test_aggregate_request_cap_and_per_question_actuals(tmp_path):
    d = fixture(tmp_path)
    d.config["lifecycle"]["daily_request_cap"] = 4
    row, _ = life.reserve(
        d.store,
        thread_id=TID,
        ask_id=ASK,
        request_id="one",
        job_id="job",
        projected=0.25,
        config=d.config,
        now=NOW,
        process_id=life.AUTO_PROCESS,
    )
    assert row
    assert (
        life.reserve(
            d.store,
            thread_id=TID,
            ask_id=ASK,
            request_id="two",
            job_id="other",
            projected=0.25,
            config=d.config,
            now=NOW,
            process_id=life.AUTO_PROCESS,
        )[1]
        == "DAILY_REQUEST_CAP"
    )
    life.settle(
        d.store, thread_id=TID, ask_id=ASK, request_id="one", job_id="job", actual=0.1, native_requests=1, now=NOW
    )
    d.config["lifecycle"]["daily_request_cap"] = 30
    assert (
        life.reserve(
            d.store,
            thread_id=TID,
            ask_id=ASK,
            request_id="three",
            job_id="job",
            projected=0.45,
            config=d.config,
            now=NOW,
            process_id=life.AUTO_PROCESS,
        )[1]
        == "PER_QUESTION_CAP"
    )


def test_deferred_material_check_retries_after_cooldown_without_new_event(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    life.append(
        d.store,
        "ask.research_finished",
        {
            "thread_id": TID,
            "request_id": "earlier",
            "published": True,
            "automated": True,
            "usage_known": True,
            "fingerprint": "same",
        },
        key=("earlier",),
        now=NOW - timedelta(hours=1),
    )
    event = {"thread_id": TID, "ask_id": ASK, "request_id": "material-one", "manual_trigger": False}
    life.append(d.store, "ask.check_requested", event, key=("material-one",), now=NOW)
    first = run(d, collect=lambda req: evidence(req, "changed"), events_only=True)
    assert first["deferred_count"] == 1 and not calls
    second = run(d, now=NOW + timedelta(hours=5), collect=lambda req: evidence(req, "changed"), events_only=True)
    assert second["research_count"] == 1 and len(calls) == 1
    assert life.latest_answer(d.store.thread(TID))["provenance"]["evidence_fingerprint"] == "changed"


def test_interrupted_paid_job_is_not_redispatched(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    life.append(
        d.store,
        "ask.check_requested",
        {"thread_id": TID, "ask_id": ASK, "request_id": "crashed", "manual_trigger": True},
        key=("crashed",),
        now=NOW,
    )
    life.reserve(
        d.store,
        thread_id=TID,
        ask_id=ASK,
        request_id="crashed",
        job_id="crashed",
        projected=0.25,
        config=d.config,
        now=NOW,
        process_id=life.AUTO_PROCESS,
    )
    result = run(d, events_only=True)
    assert result["blocked_count"] == 1 and not calls
    assert d.store.cost_today(day="2026-10-26") == 0.25


def test_memory_retry_and_delivery_retry_do_not_repeat_models(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    aid = life.latest_answer(d.store.thread(TID))["answer_id"]
    life.append(
        d.store,
        "ask.memory_synced",
        {"thread_id": TID, "answer_id": aid, "memory_sync": {"state": "pending"}},
        key=("memory-fail",),
        now=NOW,
    )
    life.append(
        d.store,
        "ask.delivery_status",
        {"thread_id": TID, "answer_id": aid, "delivery": {"state": "failed"}},
        key=("send-fail",),
        now=NOW,
    )
    before = d.memory.calls
    run(d, events_only=True)
    assert not calls and d.memory.calls > before
    life_now = life.project_lifecycle(d.store.thread(TID), d.store.events(thread_id=TID), now=NOW)
    assert life_now["memory_sync"]["state"] == "synced"
    assert life_now["delivery"]["state"] == "queued"
    count = len(d.store.events())
    run(d, events_only=True)
    assert len(d.store.events()) == count


def test_partial_answer_remains_partial_even_when_a_call_returns(tmp_path):
    d = fixture(tmp_path, provider=provider([], partial=True))
    result = run(d, collect=lambda req: evidence(req, "changed"))
    assert result["threads"][0]["lifecycle"]["state"] == "partial"


def test_source_failure_does_not_advance_observation_clock(tmp_path):
    d = fixture(tmp_path)
    result = run(d, collect=lambda _: {"source_runs": [{"source": "web", "status": "refused", "reason": "SEARCH_CAP"}]})
    assert not result["ok"] and result["failed_count"] == 1
    assert result["threads"][0]["lifecycle"]["last_checked_at"] is None


def test_dry_run_never_reads_sources_locks_or_writes(tmp_path, monkeypatch):
    d = fixture(tmp_path)
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.iterdir()}

    def forbidden(*a, **kw):
        raise AssertionError("dry run attempted work")

    monkeypatch.setattr(d.store, "thread_lock", forbidden)
    result = run(d, dry_run=True, collect=forbidden, event_sources=[SimpleNamespace(name="forbidden", fetch=forbidden)])
    assert result["dry_run"] and result["would_check"] == [TID]
    assert before == {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.iterdir()}


def test_corrupt_accounting_is_closed(tmp_path):
    d = fixture(tmp_path)
    with d.store.path.open("a") as fh:
        fh.write("{bad-json\n")
    result = run(d)
    assert not result["ok"] and result["reason"] == "ASK_LEDGER_UNAVAILABLE"
    with pytest.raises(ValueError, match="CORRUPT"):
        life.reserve(
            d.store,
            thread_id=TID,
            ask_id=ASK,
            request_id="x",
            job_id="x",
            projected=0.25,
            config=d.config,
            now=NOW,
            process_id=life.AUTO_PROCESS,
        )


def test_slot_clock_handles_dst_and_seven_day_schedule():
    before = life.clock("2026-11-01T01:30:00-04:00")
    after = life.clock("2026-11-01T01:30:00-05:00")
    assert life.next_hour(after) - life.next_hour(before) == timedelta(hours=1)
    assert life.next_hour("2026-10-25T13:01:00Z").isoformat() == "2026-10-25T14:00:00+00:00"


def test_overdue_and_interrupted_are_visible(tmp_path):
    d = fixture(tmp_path)
    run(d)
    out = life.project_lifecycle(d.store.thread(TID), d.store.events(thread_id=TID), now=NOW + timedelta(hours=2))
    assert out["state"] == "overdue" and out["monitoring_active"] is False
    life.append(d.store, "ask.check_requested", {"thread_id": TID, "request_id": "stuck"}, key=("stuck",), now=NOW)
    life.append(d.store, "ask.check_started", {"thread_id": TID, "request_id": "stuck"}, key=("stuck",), now=NOW)
    assert (
        life.project_lifecycle(d.store.thread(TID), d.store.events(thread_id=TID), now=NOW + timedelta(minutes=11))[
            "state"
        ]
        == "failed"
    )


def test_invalid_request_id_is_refused_before_work(tmp_path):
    d = fixture(tmp_path)
    result = life.request_deep(TID, ASK, deps=d, request_id="../not-an-id", now=NOW)
    assert result["error"] == "BAD_REQUEST_ID"
    assert not [x for x in d.store.events() if x["kind"] == "ask.research_started"]


def test_partial_evidence_retries_are_bounded(tmp_path):
    calls = []
    d = fixture(tmp_path, partial=True, provider=provider(calls, partial=True))
    d.config["reanswer"]["min_hours_between_per_thread"] = 1
    for offset in (0, 1, 2):
        run(d, now=NOW + timedelta(hours=offset), collect=lambda req: evidence(req, "changed"))
    assert len(calls) == 2
    assert d.store.events(thread_id=TID)[-1]["reason"] == "EVIDENCE_RETRY_LIMIT"


def test_source_result_and_api_completion_race_is_replayed_under_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager

    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    original_lock = d.store.thread_lock
    raced = False

    @contextmanager
    def lock(tid):
        nonlocal raced
        if not raced:
            raced = True
            # API finished after the scheduler's initial thread enumeration.
            core.record_answer(
                AskAnswer(
                    version=2,
                    ask_id=ASK,
                    thread_id=TID,
                    depth="deep",
                    status="deep",
                    summary="Already answered by API",
                    entities=[ENTITY],
                    produced_at=life.stamp(NOW),
                    provenance={"evidence_fingerprint": "changed"},
                ),
                deps=d,
            )
        with original_lock(tid) as acquired:
            yield acquired

    monkeypatch.setattr(d.store, "thread_lock", lock)
    result = run(d, collect=lambda req: evidence(req, "changed"))
    assert result["no_change_count"] == 1 and not calls


def test_failed_research_marks_aggregate_failed_but_preserves_successful_source_check(tmp_path):
    def fail(*a, **kw):
        raise RuntimeError("fixture provider refused")

    d = fixture(tmp_path, provider=fail)
    result = run(d, collect=lambda req: evidence(req, "changed"))
    assert result["failed_count"] == 1 and result["ok"] is False
    row = result["threads"][0]
    canonical = life.project_lifecycle(d.store.thread(TID), d.store.events(thread_id=TID), now=NOW)
    assert row["lifecycle"] == canonical
    assert canonical["last_checked_at"] == life.stamp(NOW)
    assert d.store.cost_today(day="2026-10-26") == 0.25


def test_queued_delivery_reconciles_native_receipt_without_new_send_or_model(tmp_path):
    calls = []
    d = fixture(tmp_path, provider=provider(calls))
    aid = life.latest_answer(d.store.thread(TID))["answer_id"]
    life.append(
        d.store,
        "ask.delivery_status",
        {"thread_id": TID, "answer_id": aid, "delivery": {"state": "queued", "ref": "fixture-outbox"}},
        key=("queued",),
        now=NOW,
    )
    d.delivery_read = lambda ref: {
        "state": "delivered",
        "ref": ref,
        "message_id": "receipt-1",
        "transport_receipt_hash": "fixture",
    }

    def no_send(*a):
        raise AssertionError("reconciliation must not re-send")

    d.telegram_send = no_send
    run(d, events_only=True)
    assert not calls
    projected = life.project_lifecycle(d.store.thread(TID), d.store.events(thread_id=TID), now=NOW)
    assert projected["delivery"]["state"] == "delivered"


def test_queued_earlier_turn_cannot_answer_newer_follow_up(tmp_path):
    calls, reads = [], []
    d = fixture(tmp_path, provider=provider(calls))
    life.append(
        d.store,
        "ask.check_requested",
        {"thread_id": TID, "ask_id": ASK, "request_id": "older-turn", "manual_trigger": True},
        key=("older-turn",),
        now=NOW,
    )
    life.append(
        d.store,
        "ask.asked",
        {"thread_id": TID, "ask_id": "ask_follow_up", "question": "Different follow-up question", "channel": "cc"},
        key=("followup",),
        now=NOW,
    )

    def collect(req):
        reads.append(req["question"])
        return evidence(req, "changed")

    result = run(d, events_only=True, collect=collect)
    assert result["research_count"] == 1
    assert reads == ["What changed at Example Robotics?"]
    assert calls[0]["context"].request.question == reads[0]
    assert len(d.store.thread(TID)["turns"][1]["answers"]) == 0


def test_canonical_source_admission_keeps_schedules_inactive_and_caps_shared():
    import json
    from pathlib import Path
    from scripts.lib import cio_ask_provider_routes as routes

    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "config/llm_process_registry.json").read_text())
    rows = {r["id"]: r for r in registry["processes"]}
    processes = {life.AUTO_PROCESS, *routes.CRITIQUE_PROCESSES.values()}
    for process in processes:
        assert rows[process]["default_mode"] == "automated"
        assert rows[process]["daily_soft_cap"] == 30
        assert rows[process]["daily_cost_cap_usd"] == 5
    routes._configuration(life.AUTO_PROCESS, "anthropic", root)
    for provider, process in routes.CRITIQUE_PROCESSES.items():
        routes._configuration(process, provider, root)
    lanes = {r["lane_id"]: r for r in json.loads((root / "config/lane_registry.json").read_text())["lanes"]}
    allowlist = {r["lane_id"]: r for r in json.loads((root / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    contracts = {r["id"]: r for r in json.loads((root / "config/n8n_health_contracts.json").read_text())["contracts"]}
    for lane in ["cio-ask-lifecycle", "cio-ask-material-events"]:
        assert lanes[lane]["state"] == "NEVER_SCHEDULED"
        assert lanes[lane]["scheduler"]["kind"] == "n8n"
        assert lanes[lane]["scheduler"]["timezone"] == "America/New_York"
        assert allowlist[lane]["live_arg"] is None
        assert set(allowlist[lane]["llm_route"]["process_ids"]) == processes
        assert contracts[lane]["status"] == "REVIEWED"
        assert contracts[lane]["review"]["reviewed_by"].startswith("codex-")
        assert "SOURCE_AND_SYNTHETIC_ONLY" in contracts[lane]["evidence"]["acceptance"]
