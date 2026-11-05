"""ONBOARDING §12 rule 3 — one batched escalation per supervisor run (operator 2026-11-03).

Verbatim operator complaint: six P1 Telegrams from one supervisor run. The standard: "ONE batched
Telegram per supervisor run as a list — never six separate P1s. Page the operator ONLY for an
operator-only decision." These tests drive the real `cycle()` with six incidents that would each
have paged individually and assert exactly one message, its priority, its contents, and that every
incident still records its own delivered escalation row (so the once-per-episode suppression holds).
AGENTS §28.14 additionally requires exhausted attempts to page P1; that urgency does not make the work operator-only.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_spec = importlib.util.spec_from_file_location("batch_incident_supervisor_under_test",
                                               ROOT / "scripts/lib/incident_supervisor.py")
S = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = S
_spec.loader.exec_module(S)
from scripts.lib import incidents as L  # noqa: E402

T0 = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(hours=2)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("external effects forbidden in synthetic incident tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(S.subprocess, "run", forbidden)


def _cfg(**over):
    cfg = json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text(encoding="utf-8"))
    cfg["policy"].update({"max_incidents_per_cycle": 6, "max_attempts_per_incident": 3})
    cfg["policy"].update(over)
    return cfg


def _seed(d: Path, *, n: int = 6, refused_first: bool = False) -> list[str]:
    ids = []
    for i in range(n):
        title = "credential exposure" if refused_first and i == 0 else f"lane outage {i}"
        rec, _created = L.open_incident(
            source={"kind": "watcher", "watcher": "lane_health"},
            title=title, where=f"tests/fixture_{i}", severity="P1" if title == "credential exposure" else "P2",
            d=d, now=T0,
        )
        # Three counted supervisor actions put each incident at the attempts cap, so the cycle
        # escalates without ever calling the model (the model stub below fails the test if called).
        for _ in range(3):
            L.attempt(rec["id"], actor="incident_supervisor", action="runbook", result="noop", ok=False,
                      d=d, now=T0)
        ids.append(rec["id"])
    return ids


def _run(tmp_path: Path, cfg, pages: list, now=NOW):
    def model(_prompt):
        raise AssertionError("the model must not be called for an attempts-cap escalation")

    def notify(text, producer, priority="P2"):
        pages.append({"text": text, "producer": producer, "priority": priority})
        return True

    deps = S.Deps(model=model, run=lambda *_a, **_k: (0, "ok"), notify=notify,
                  fixer=lambda *_a, **_k: {"rc": 0})
    return S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "ps", release_root=tmp_path, cfg=cfg,
                   deps=deps, apply=True, now=now, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)


def test_six_incidents_produce_exactly_one_batched_message(tmp_path):
    ids = _seed(tmp_path / "ledger")
    pages: list = []
    out = _run(tmp_path, _cfg(), pages)

    assert len(pages) == 1, f"expected one batched page, got {len(pages)}: {pages}"
    page = pages[0]
    assert page["priority"] == "P1"  # AGENTS §28.14: attempts exhausted, even without operator-only authority
    assert page["producer"] == "incident_supervisor:batch"
    for iid in ids:
        assert iid in page["text"]
    assert page["text"].count("•") == 6
    assert "unresolved 120 min" in page["text"]          # time unresolved is in the list
    assert page["text"].count("Next:") == 6              # the exact next action per entry
    assert "operator-only" not in page["text"]

    # Every incident still records its own delivered escalation row: the batch is one message, not
    # one anonymous send, so the per-incident/episode suppression keeps working.
    assert len(out["escalated"]) == 6 and all(row["delivered"] is True for row in out["escalated"])
    assert all(row["priority"] == "P1" for row in out["escalated"])

    # A second cycle does not page again for the same delivered reason class.
    out2 = _run(tmp_path, _cfg(), pages, now=NOW + timedelta(minutes=10))
    assert len(pages) == 1
    assert out2["escalated"] == []


def test_a_batch_with_an_operator_only_decision_is_p1(tmp_path):
    ids = _seed(tmp_path / "ledger", refused_first=True)
    pages: list = []
    out = _run(tmp_path, _cfg(), pages)

    assert len(pages) == 1
    page = pages[0]
    assert page["priority"] == "P1"
    assert "operator-only decision" in page["text"]
    assert ids[0] in page["text"] and ids[-1] in page["text"]
    assert page["text"].count("•") == 6
    assert {row["operator_only"] for row in out["escalated"]} == {True, False}
    assert all(row["priority"] == "P1" for row in out["escalated"])


def test_a_failed_batch_records_undelivered_rows_for_the_retry_path(tmp_path):
    _seed(tmp_path / "ledger")
    pages: list = []

    def notify(_text, _producer, priority="P2"):
        raise RuntimeError("telegram down")

    def model(_prompt):
        raise AssertionError("no model")

    deps = S.Deps(model=model, run=lambda *_a, **_k: (0, "ok"), notify=notify, fixer=lambda *_a, **_k: {})
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "ps", release_root=tmp_path, cfg=_cfg(),
                  deps=deps, apply=True, now=NOW, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert len(out["escalated"]) == 6
    assert all(row["delivered"] is False for row in out["escalated"])  # queued for the retry path


def _fault_deps(pages, *, result=True):
    def model(_prompt):
        return json.dumps({"class": "code_defect", "action": "repair synthetic worker",
                           "params": {}, "rationale": "synthetic dispatch fault"}), "anthropic"

    def notify(text, producer, priority="P2"):
        pages.append({"text": text, "producer": producer, "priority": priority})
        if result == "raises":
            raise RuntimeError("synthetic notifier failure")
        return result

    def fixer(*_args, **_kwargs):
        raise RuntimeError("synthetic later dispatch fault")

    return S.Deps(model=model, run=lambda *_a, **_k: (0, "ok"), notify=notify, fixer=fixer)


def _cycle_with(tmp_path, deps, *, apply=True, now=NOW):
    return S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "ps", release_root=tmp_path,
                   cfg=_cfg(escalate_after_minutes=9999), deps=deps, apply=apply, now=now,
                   environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)


@pytest.mark.parametrize("retry_result", [True, False, "raises"])
def test_later_dispatch_fault_keeps_blocked_operator_page_durably_retryable(tmp_path, retry_result):
    d = tmp_path / "ledger"
    first = _seed(d, n=1, refused_first=True)[0]
    second, _ = L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                               title="synthetic worker needs repair", where="tests/synthetic_worker",
                               severity="P2", d=d, now=T0 + timedelta(seconds=1))
    pages = []
    with pytest.raises(RuntimeError, match="synthetic later dispatch fault"):
        _cycle_with(tmp_path, _fault_deps(pages, result=False))
    rec = L.load_records(d)[first]
    assert rec["status"] == "blocked"
    pending = S._pending_escalation(rec)
    assert pending and pending["key"] == "refused_scope" and pending["delivered"] is False
    assert len(pages) == 1 and pages[0]["priority"] == "P1", "even a failed cycle must attempt its one batch"
    pages.clear()
    events = [e for e in L.read_events(d) if e["incident_id"] == first]
    assert next(i for i, e in enumerate(events) if e["kind"] == "escalate") < next(
        i for i, e in enumerate(events) if e["kind"] == "block"), "retry obligation precedes blocking"

    # Retire only the unrelated synthetic fault; recovery must be delivery-only for the first incident.
    L.operator_close(second["id"], decision_ref="fixture:retired", comment="synthetic test fault retired",
                     d=d, now=NOW + timedelta(seconds=1))
    model_calls = []
    deps = _fault_deps(pages, result=retry_result)
    deps.model = lambda _p: model_calls.append(_p) or pytest.fail("a delivery retry called the model")
    out = _cycle_with(tmp_path, deps, now=NOW + timedelta(minutes=1))
    assert len(pages) == 1 and pages[0]["priority"] == "P1" and first in pages[0]["text"]
    assert len(out["escalated"]) == 1 and out["escalated"][0]["delivered"] is (retry_result is True)
    assert model_calls == []
    if retry_result is not True:
        assert S._pending_escalation(L.load_records(d)[first]) is not None
        _cycle_with(tmp_path, _fault_deps(pages), now=NOW + timedelta(minutes=2))
        assert len(pages) == 2
    assert S._pending_escalation(L.load_records(d)[first]) is None
    sent = len(pages)
    _cycle_with(tmp_path, _fault_deps(pages), now=NOW + timedelta(minutes=3))
    assert len(pages) == sent, "a delivered obligation must not page again"


@pytest.mark.parametrize("site", ["refused", "attempts_cap", "prior_failed", "new_failed", "needs_operator"])
def test_failed_pending_write_refuses_block_before_any_notify(tmp_path, monkeypatch, site):
    d = tmp_path / "ledger"
    if site in ("refused", "attempts_cap"):
        first = _seed(d, n=1, refused_first=site == "refused")[0]
    else:
        rec, _ = L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                                 title="synthetic worker failure", where="tests/synthetic_worker",
                                 d=d, now=T0)
        first = rec["id"]
        if site == "prior_failed":
            L.attempt(first, actor=S.ACTOR, action="fixer_dispatch", result="synthetic failed dispatch",
                      ok=False, d=d, now=T0)
    initial_status = L.load_records(d)[first]["status"]
    expected_status = "fixing" if site == "new_failed" else initial_status
    pages = []
    deps = _fault_deps(pages)
    cls = "needs_operator" if site == "needs_operator" else "code_defect"
    deps.model = lambda _p: (json.dumps({"class": cls, "action": "synthetic next step",
                                       "params": {}, "rationale": "synthetic"}), "anthropic")
    deps.fixer = lambda *_a, **_k: {"rc": 2, "admitted": []}

    def fail_pending(*_args, **_kwargs):
        raise OSError("synthetic pending ledger unavailable")

    monkeypatch.setattr(L, "escalate", fail_pending)
    with pytest.raises(OSError, match="synthetic pending ledger unavailable"):
        _cycle_with(tmp_path, deps)
    assert L.load_records(d)[first]["status"] == expected_status, "failed intent must not commit a blocked state"
    assert not any(e["kind"] == "block" for e in L.read_events(d)), "no block without a durable obligation"
    assert pages == [], "an unrecordable obligation must not reach notification"


def test_interruption_before_flush_leaves_one_retry_then_suppresses(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    first = _seed(d, n=1, refused_first=True)[0]
    pages = []
    flush = S._flush_escalations

    class InterruptedCycle(BaseException):
        pass

    def interrupt(*_args, **_kwargs):
        raise InterruptedCycle()

    monkeypatch.setattr(S, "_flush_escalations", interrupt)
    with pytest.raises(InterruptedCycle):
        _cycle_with(tmp_path, _fault_deps(pages))
    assert pages == []
    assert S._pending_escalation(L.load_records(d)[first]) is not None
    monkeypatch.setattr(S, "_flush_escalations", flush)
    _cycle_with(tmp_path, _fault_deps(pages), now=NOW + timedelta(minutes=1))
    _cycle_with(tmp_path, _fault_deps(pages), now=NOW + timedelta(minutes=2))
    assert len(pages) == 1 and first in pages[0]["text"]


def test_dry_run_plans_pending_page_without_appending_an_obligation(tmp_path):
    d = tmp_path / "ledger"
    first = _seed(d, n=1, refused_first=True)[0]
    before = L.events_path(d).read_bytes()
    pages = []
    out = _cycle_with(tmp_path, _fault_deps(pages), apply=False)
    assert [row["id"] for row in out["would_escalate"]] == [first]
    assert L.events_path(d).read_bytes() == before and pages == []


def test_one_delivered_reason_does_not_erase_another_pending_reason(tmp_path):
    d = tmp_path / "ledger"
    first = _seed(d, n=1, refused_first=True)[0]
    for key, delivered in [("time_box", False), ("refused_scope", False), ("refused_scope", True)]:
        L.escalate(first, actor=S.ACTOR, reason=key, key=key, delivered=delivered, episode=1, d=d, now=NOW)
    pending = S._pending_escalation(L.load_records(d)[first])
    assert pending and pending["key"] == "time_box"
    L.escalate(first, actor=S.ACTOR, reason="time_box", key="time_box", delivered=True, episode=1, d=d, now=NOW)
    assert S._pending_escalation(L.load_records(d)[first]) is None


def test_latest_pending_reason_tracks_event_order_not_first_key_insertion():
    rec = {"episode": 1, "escalations": [
        {"key": key, "reason": key, "delivered": False, "episode": 1}
        for key in ("refused_scope", "time_box", "refused_scope")
    ]}
    assert S._pending_escalation(rec)["key"] == "refused_scope"


def test_a_delivered_reason_wins_over_a_late_stale_pending_append():
    rec = {"episode": 1, "escalations": [
        {"key": "refused_scope", "delivered": delivered, "episode": 1}
        for delivered in (False, True, False)
    ]}
    assert S._pending_escalation(rec) is None, "a concurrent stale intent cannot undo a real delivered receipt"


@pytest.mark.parametrize("first_result", [True, False, "raises"])
def test_recurring_unrelated_fault_cannot_starve_operator_delivery(tmp_path, first_result):
    d = tmp_path / "ledger"
    first = _seed(d, n=1, refused_first=True)[0]
    second, _ = L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                               title="synthetic recurring worker fault", where="tests/recurring_worker",
                               severity="P2", d=d, now=T0 + timedelta(seconds=1))
    pages = []
    deps = _fault_deps(pages)

    def notify(text, producer, priority="P2"):
        pages.append({"text": text, "producer": producer, "priority": priority})
        if len(pages) == 1:
            if first_result == "raises":
                raise RuntimeError("synthetic first delivery fault")
            return first_result
        return True

    deps.notify = notify
    previous_receipt = json.dumps({"schema": S.RECEIPT_SCHEMA, "as_of": L.iso(T0), "mode": "apply"})
    (d / "supervisor_last.json").write_text(previous_receipt)
    for tick in range(3):
        with pytest.raises(RuntimeError, match="synthetic later dispatch fault"):
            _cycle_with(tmp_path, deps, now=NOW + timedelta(minutes=tick))
        assert L.load_records(d)[second["id"]]["status"] in L.UNRESOLVED, "do not retire the recurring fault"
    assert len(pages) == (1 if first_result is True else 2), "the unrelated fault must not starve or duplicate delivery"
    assert all(page["priority"] == "P1" and first in page["text"] for page in pages)
    assert S._pending_escalation(L.load_records(d)[first]) is None
    assert (d / "supervisor_last.json").read_text() == previous_receipt, "a failed cycle must keep its completed clock"


def test_exception_flush_keeps_one_batch_for_all_already_queued_incidents(tmp_path):
    d = tmp_path / "ledger"
    ids = _seed(d, n=5, refused_first=True)
    L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                    title="synthetic last worker fault", where="tests/last_worker",
                    severity="P2", d=d, now=T0 + timedelta(seconds=1))
    pages = []
    with pytest.raises(RuntimeError, match="synthetic later dispatch fault"):
        _cycle_with(tmp_path, _fault_deps(pages))
    assert len(pages) == 1 and pages[0]["text"].count("•") == 5
    assert all(iid in pages[0]["text"] for iid in ids)
    assert all(S._pending_escalation(L.load_records(d)[iid]) is None for iid in ids)


@pytest.mark.parametrize("transition", ["closed", "fixed", "reopened", "delivered"])
def test_exception_flush_does_not_page_a_superseded_episode(tmp_path, transition):
    d = tmp_path / "ledger"
    first = _seed(d, n=1, refused_first=True)[0]
    L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                    title="synthetic concurrent worker fault", where="tests/concurrent_worker",
                    severity="P2", d=d, now=T0 + timedelta(seconds=1))
    pages = []
    deps = _fault_deps(pages)

    def supersede_then_fail(*_args, **_kwargs):
        if transition == "closed":
            L.operator_close(first, decision_ref="fixture:closed", comment="synthetic decision", d=d, now=NOW)
        elif transition == "fixed":
            L.fix(first, actor="fixture", fix_refs=[{"kind": "pr", "ref": "fixture"}], d=d, now=NOW)
        elif transition == "delivered":
            L.escalate(first, actor="fixture", reason="refused scope", key="refused_scope",
                       delivered=True, episode=1, d=d, now=NOW)
        else:
            L.append_event({"kind": "reopen", "incident_id": first, "actor": "fixture"}, d=d, now=NOW)
        raise RuntimeError("synthetic later dispatch fault")

    deps.fixer = supersede_then_fail
    with pytest.raises(RuntimeError, match="synthetic later dispatch fault"):
        _cycle_with(tmp_path, deps)
    assert pages == [], "the old obligation no longer describes the current incident state/episode"


def test_invalid_config_preserves_its_error_without_inventing_a_ledger(tmp_path):
    d = tmp_path / "missing-ledger"
    pages = []
    with pytest.raises(KeyError, match="policy"):
        S.cycle(d=d, state_root=tmp_path / "ps", release_root=tmp_path, cfg={},
                deps=_fault_deps(pages), apply=True, now=NOW, environ={}, root=ROOT)
    assert not d.exists() and pages == []


def test_failed_cycle_does_not_advance_the_real_ops_supervisor_clock(tmp_path):
    d = tmp_path / "ledger"
    _seed(d, n=1, refused_first=True)
    L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                    title="synthetic worker fault", where="tests/clock_worker", d=d,
                    now=T0 + timedelta(seconds=1))
    last_success = {"schema": S.RECEIPT_SCHEMA, "as_of": L.iso(T0), "mode": "apply"}
    (d / "supervisor_last.json").write_text(json.dumps(last_success))
    spec = importlib.util.spec_from_file_location("incident_clock_view_under_test", ROOT / "scripts/lib/incidents_view.py")
    view = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = view
    spec.loader.exec_module(view)
    pages = []
    with pytest.raises(RuntimeError, match="synthetic later dispatch fault"):
        _cycle_with(tmp_path, _fault_deps(pages))
    assert len(pages) == 1, "deliver the already owed batch despite the fault"
    assert view.payload(d, now=NOW)["supervisor_as_of"] == L.iso(T0), "Ops must not date a failed cycle as completed"


# AGENTS 28.14: exhausted automated attempts page once at P1, without inventing operator-only authority.
def _cloud_exhausted_run(tmp_path, pages, *, result=True, cfg=None, now=NOW):
    def no_model(_prompt):
        pytest.fail("exhaustion/delivery-only retries must not invoke a model")

    def notify(text, producer, priority="P2"):
        pages.append({"text": text, "producer": producer, "priority": priority})
        if result == "raises":
            raise RuntimeError("synthetic exhausted-page transport failure")
        return result

    deps = S.Deps(model=no_model, run=lambda *_a, **_k: pytest.fail("unexpected runbook"), notify=notify,
                  fixer=lambda *_a, **_k: pytest.fail("unexpected fixer"))
    return S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "ps", release_root=tmp_path,
                   cfg=cfg or _cfg(), deps=deps, apply=True, now=now,
                   environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)


def test_cloud_exhausted_initial_page_is_p1_without_operator_only_authority(tmp_path):
    ids = _seed(tmp_path / "ledger", n=2)
    pages = []
    out = _cloud_exhausted_run(tmp_path, pages)
    assert len(pages) == 1 and pages[0]["priority"] == "P1"
    assert all(iid in pages[0]["text"] for iid in ids)
    assert len(out["blocked"]) == 2
    assert {row["key"] for row in out["escalated"]} == {"max_attempts"}
    assert all(row["priority"] == "P1" and row["operator_only"] is False for row in out["escalated"])
    assert "operator-only decision" not in pages[0]["text"]
    _cloud_exhausted_run(tmp_path, pages, now=NOW + timedelta(minutes=1))
    assert len(pages) == 1, "a delivered exhausted episode must not page again"


@pytest.mark.parametrize("first_result", [False, "raises"])
@pytest.mark.parametrize("retry_result", [True, False, "raises"])
def test_cloud_exhausted_false_or_error_delivery_retry_retains_p1(tmp_path, first_result, retry_result):
    iid = _seed(tmp_path / "ledger", n=1)[0]
    pages = []
    first = _cloud_exhausted_run(tmp_path, pages, result=first_result)
    assert L.load_records(tmp_path / "ledger")[iid]["status"] == "blocked"
    assert first["escalated"][0]["delivered"] is False
    pending = S._pending_escalation(L.load_records(tmp_path / "ledger")[iid])
    assert pending["key"] == "max_attempts"
    retry = _cloud_exhausted_run(tmp_path, pages, result=retry_result, now=NOW + timedelta(minutes=1))
    assert len(pages) == 2 and all(page["priority"] == "P1" for page in pages)
    assert len(retry["escalated"]) == 1
    assert retry["escalated"][0]["operator_only"] is False
    assert retry["escalated"][0]["delivered"] is (retry_result is True)
    if retry_result is True:
        assert S._pending_escalation(L.load_records(tmp_path / "ledger")[iid]) is None
    else:
        assert S._pending_escalation(L.load_records(tmp_path / "ledger")[iid])["key"] == "max_attempts"


def test_cloud_exhausted_mixed_with_routine_diagnostics_still_sends_one_p1(tmp_path):
    iid = _seed(tmp_path / "ledger", n=1)[0]
    diagnostic, _ = L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                                    title="synthetic routine diagnostic", where="tests/routine",
                                    severity="P2", d=tmp_path / "ledger", now=T0 + timedelta(seconds=1))
    pages = []
    out = _cloud_exhausted_run(tmp_path, pages, cfg=_cfg(max_model_calls_per_day=0))
    assert len(pages) == 1 and pages[0]["priority"] == "P1"
    assert iid in pages[0]["text"] and diagnostic["id"] in pages[0]["text"]
    assert {row["key"] for row in out["escalated"]} == {"max_attempts", "time_box"}
    assert all(row["operator_only"] is False for row in out["escalated"])
    assert "operator-only decision" not in pages[0]["text"]


def test_cloud_exhausted_routine_only_timebox_remains_p2(tmp_path):
    L.open_incident(source={"kind": "watcher", "watcher": "lane_health"},
                    title="synthetic routine diagnostic", where="tests/routine", severity="P2",
                    d=tmp_path / "ledger", now=T0)
    pages = []
    out = _cloud_exhausted_run(tmp_path, pages, cfg=_cfg(max_model_calls_per_day=0))
    assert len(pages) == 1 and pages[0]["priority"] == "P2"
    assert {row["key"] for row in out["escalated"]} == {"time_box"}
    assert all(row["operator_only"] is False for row in out["escalated"])


def test_cloud_exhausted_p1_enters_real_quiet_hour_router_delivery_path(tmp_path, monkeypatch):
    from zoneinfo import ZoneInfo

    spec = importlib.util.spec_from_file_location("batch_priority_router_under_test", ROOT / "scripts/telegram_alert_router.py")
    router = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = router
    spec.loader.exec_module(router)
    monkeypatch.setenv("TRADEAI_INCIDENT_NOTIFIER_QUIET_START", "22:00")
    monkeypatch.setenv("TRADEAI_INCIDENT_NOTIFIER_QUIET_END", "07:00")
    monkeypatch.setenv("TRADEAI_INCIDENT_NOTIFIER_TZ", "America/New_York")
    quiet_now = datetime(2030, 1, 7, 23, 0, tzinfo=ZoneInfo("America/New_York"))
    assert router.intent_in_quiet_hours(quiet_now) is True
    _seed(tmp_path / "ledger", n=1)
    pages = []
    _cloud_exhausted_run(tmp_path, pages)
    assert len(pages) == 1
    actual = router.route_intent(pages[0]["text"], pages[0]["priority"], dedupe_minutes=0,
                                 producer=pages[0]["producer"], now=quiet_now)
    control = router.route_intent(pages[0]["text"], "P2", dedupe_minutes=0,
                                  producer=pages[0]["producer"], now=quiet_now)
    assert control["decision"] == "HELD_QUIET_HOURS" and control["deliver"] is False
    assert actual["priority"] == "P1" and actual["decision"] == "DELIVER" and actual["deliver"] is True
