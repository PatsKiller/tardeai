#!/usr/bin/env python3
"""Home v008 "Needs you" — the three approval rails, the closed action list, and the executor seam.

Every test is a property the operator stated or the spec requires:
  * a click counts only from the operator's verified session + same-origin CSRF;
  * the requester can never be the approver;
  * an expired request re-asks and never auto-approves;
  * nothing outside the reviewed action list is reachable;
  * facts that moved are refused in plain English and leave the record open with the button disabled;
  * the read path can tell "nothing needs you" from "could not read".
"""

from __future__ import annotations

import json
import stat
import time
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_approvals as ha  # noqa: E402

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
HEAD = "5c15ddb039e944b9c946d769265aea347943b7b8"
SHA64 = "a" * 64


def _store(tmp_path: Path) -> ha.Store:
    return ha.Store(tmp_path / "state")


def _payload(**overrides):
    base = dict(
        type="merge_pr",
        title="Merge #2504",
        why="Board row 03 is green and reviewed.",
        rule="AGENTS §9 operator-only decision",
        what_happens="Merges PR #2504 at exactly the reviewed head; deploy runs at the next window.",
        risk="The merge lands without a later chance to re-read it.",
        undo="Revert the merge commit; nothing is force-pushed.",
        facts={"pr": 2504, "head_sha": HEAD},
    )
    base.update(overrides)
    return base


def _ask(store: ha.Store, **overrides):
    return ha.create(store, _payload(**overrides), requester={"session": "cc-deepseek-5"}, now=NOW)


class Recorder:
    def __init__(self, ok: bool = True, plain: str = ""):
        self.ok, self.plain = ok, plain
        self.executed = 0
        self.revalidated = []

    def executor(self) -> ha.CallbackExecutor:
        def revalidate(record):
            self.revalidated.append(record["id"])
            return self.ok, self.plain

        def execute(record, actor, progress):
            self.executed += 1
            progress.reached("kicked_off")
            return {"ok": True, "plain": f"Done ({actor})."}

        return ha.CallbackExecutor(revalidate, execute)


def _ctx(principal="tailnet:operator", csrf_ok=True, session="operator-cc", listener="serve_proxy"):
    return ha.server_context(principal=principal, session=session, csrf_ok=csrf_ok, listener=listener)


def _decide(store, request_id, *, actor="operator", ctx=None, executor=None, decision="approve", note="", now=NOW,
            timeout_s=120.0):
    return ha.decide(store, request_id, ctx=_ctx() if ctx is None else ctx, actor=actor, decision=decision,
                     note=note, now=now, executor=executor, timeout_s=timeout_s)


# ── Server-only: decide() cannot be reached by a plain import and two truthy booleans ────────────────────────
def test_a_plain_operator_context_cannot_be_constructed_by_a_client(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        ha.OperatorContext(principal="tailnet:operator", session="x", csrf_ok=True,
                           listener="serve_proxy", _seal=None)  # type: ignore[arg-type]
    assert caught.value.code == "server_context_required"
    assert caught.value.plain  # the card gets a sentence, not a code
    assert store.get(record["id"])["state"] == "open"


def test_decide_refuses_without_a_server_context(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    for bad in (None, {"principal": "operator", "csrf_ok": True}, True):
        with pytest.raises(ha.Refused) as caught:
            ha.decide(store, record["id"], ctx=bad, actor="operator", decision="approve", now=NOW)  # type: ignore[arg-type]
        assert caught.value.code == "server_context_required"
        assert caught.value.plain
    stored = store.get(record["id"])
    assert stored["state"] == "open" and stored["decision"] is None and stored["decided_by"] is None


def test_an_unverified_operator_session_or_csrf_is_refused(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], ctx=_ctx(principal=""))
    assert caught.value.code == "operator_session_required"
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], ctx=_ctx(csrf_ok=False))
    assert caught.value.code == "csrf_required" and caught.value.plain
    stored = store.get(record["id"])
    assert stored["state"] == "open" and stored["decision"] is None


# ── Rail 2: the asker is never the decider ──────────────────────────────────────────────────────────────────
def test_the_requester_identity_cannot_decide_its_own_request(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    # The asking identity is the operator login itself: the only way this rail is reachable once actor == principal.
    record = ha.create(store, _payload(), requester={"session": "operator", "actor": "operator"}, now=NOW)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], actor="operator", executor=rec.executor())
    assert caught.value.code == "approver_is_requester"
    assert rec.executed == 0


def test_the_requesting_session_cannot_decide_even_under_another_name(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = ha.create(store, _payload(), requester={"session": "operator-cc"}, now=NOW)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], ctx=_ctx(session="operator-cc"), executor=rec.executor())
    assert caught.value.code == "approver_is_requester"
    assert rec.executed == 0


def test_an_empty_actor_is_refused(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], actor="", executor=rec.executor())
    assert caught.value.code == "actor_not_authenticated"


# ── Rail 3: expiry re-asks, never auto-approves ────────────────────────────────────────────────────────────
def test_an_expired_request_is_not_approved_and_moves_to_expired(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = _ask(store, ttl_hours=1)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], executor=rec.executor(), now=NOW + timedelta(hours=2))
    assert caught.value.code == "request_expired"
    assert rec.executed == 0
    stored = store.get(record["id"])
    assert stored["state"] == "expired" and stored["reask_requested"] is True


def test_expire_due_marks_requests_and_never_approves(tmp_path):
    store = _store(tmp_path)
    record = _ask(store, ttl_hours=1)
    changed = ha.expire_due(store, now=NOW + timedelta(hours=3))
    assert [row["id"] for row in changed] == [record["id"]]
    assert ha.list_open(store, now=NOW + timedelta(hours=3)) == []


# ── The closed action list ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["place_order", "credential_read", "force_push", "delete_repo", "stop_trading", ""])
def test_an_action_outside_the_list_cannot_even_be_stored(tmp_path, kind):
    store = _store(tmp_path)
    with pytest.raises(ha.Refused) as caught:
        _ask(store, type=kind, facts={"pr": 1, "head_sha": HEAD})
    assert caught.value.code == "unknown_action_type"
    assert store.all() == []


def test_the_action_list_is_exactly_the_seven_reviewed_types():
    assert set(ha.ACTION_TYPES) == {"merge_pr", "rerun_ci", "grant", "stop_job", "install_schedule",
                                    "restore_store", "policy_approval"}


def test_every_type_declares_the_facts_it_requires():
    assert set(ha.REQUIRED_FACTS) == set(ha.ACTION_TYPES)
    assert ha.REQUIRED_FACTS["merge_pr"] == ("pr", "head_sha")
    assert ha.REQUIRED_FACTS["rerun_ci"] == ("run_id", "head_sha")


@pytest.mark.parametrize("kind,facts", [
    ("merge_pr", {"pr": 1}),                                        # head missing
    ("merge_pr", {"pr": 1, "head_sha": "abc"}),                     # not a 40-hex sha
    ("rerun_ci", {"run_id": 1, "head_sha": "Z" * 40}),              # not hex
    ("grant", {"grant_id": "g1", "tier": "A", "uses": 1, "expires_at": "nonsense"}),  # bad timestamp
    ("stop_job", {"pid": "x", "start_time_epoch": 1, "cmd_sha256": SHA64}),
    ("install_schedule", {"lane_id": "x", "schedule_expression": "* * * * *"}),
    ("restore_store", {"packet_sha256": "short"}),
    ("policy_approval", {"head_sha": HEAD}),
])
def test_bad_or_missing_facts_are_refused_with_a_plain_reason(tmp_path, kind, facts):
    with pytest.raises(ha.Refused) as caught:
        _ask(_store(tmp_path), type=kind, facts=facts)
    assert caught.value.code in {"facts_incomplete", "facts_invalid"}
    assert caught.value.plain


@pytest.mark.parametrize("field", list(ha.TEXT_FIELDS))
def test_every_plain_english_field_is_required(tmp_path, field):
    payload = _payload()
    payload[field] = "  "
    with pytest.raises(ha.Refused) as caught:
        ha.create(_store(tmp_path), payload, requester={"session": "cc-deepseek-5"}, now=NOW)
    assert caught.value.code == "text_incomplete"


def test_a_request_without_an_asking_session_is_refused(tmp_path):
    with pytest.raises(ha.Refused) as caught:
        ha.create(_store(tmp_path), _payload(), requester={}, now=NOW)
    assert caught.value.code == "requester_unknown"


# ── Executor: revalidate at click time ────────────────────────────────────────────────────────────────────
def test_moved_facts_refuse_the_click_and_leave_the_record_open_and_disabled(tmp_path):
    store = _store(tmp_path)
    rec = Recorder(ok=False, plain="This changed. The head moved since the lead asked; the lead will re-ask.")
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], executor=rec.executor())
    assert caught.value.code == "facts_moved"
    assert "head moved" in caught.value.plain
    assert rec.executed == 0 and rec.revalidated == [record["id"]]
    stored = store.get(record["id"])
    assert stored["state"] == "open" and "head moved" in stored["blocked_reason"]
    assert [row["id"] for row in ha.list_open(store, now=NOW)] == [record["id"]]


def test_with_no_executor_registered_a_click_cannot_do_anything(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"])
    assert caught.value.code == "facts_moved" and "No executor" in caught.value.plain


# ── The happy path leaves durable receipts ───────────────────────────────────────────────────────────────
def test_an_approved_request_runs_once_and_writes_both_ledgers(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = _ask(store)
    done = _decide(store, record["id"], executor=rec.executor())
    assert done["state"] == "executed" and rec.executed == 1
    ledger = [json.loads(line) for line in store.ledger.read_text().splitlines()]
    digest = [json.loads(line) for line in store.digest.read_text().splitlines()]
    assert [row["event"] for row in ledger] == ["created", "approved", "executed"]
    assert digest[0]["event"] == "approved" and digest[0]["facts"] == {"pr": 2504, "head_sha": HEAD}
    assert ledger[1]["approval_source"] == "operator_session+csrf" and ledger[1]["binding"]
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], executor=rec.executor())
    assert caught.value.code == "not_open"
    assert rec.executed == 1


def test_execute_is_idempotent_by_id(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = _ask(store)
    done = _decide(store, record["id"], executor=rec.executor())
    again = ha.execute(store, done, actor="operator", now=NOW, executor=rec.executor())
    assert again["state"] == "executed" and rec.executed == 1


def test_a_failed_action_still_leaves_the_decision_on_record(tmp_path):
    store = _store(tmp_path)

    def boom(record, actor):
        raise RuntimeError("gh refused the merge")

    executor = ha.CallbackExecutor(lambda record: (True, ""), ha.two_arg(boom))
    record = _ask(store)
    result = _decide(store, record["id"], executor=executor)
    assert result["state"] == "failed" and "gh refused" in result["result"]["plain"]
    events = [json.loads(line)["event"] for line in store.ledger.read_text().splitlines()]
    assert events == ["created", "approved", "failed"]


def test_a_timeout_records_what_was_attempted(tmp_path):
    store = _store(tmp_path)

    def slow(record, actor, progress):
        progress.reached("gh_pr_merge_started")
        time.sleep(0.5)
        progress.reached("gh_pr_merge_returned")
        return {"ok": True}

    executor = ha.CallbackExecutor(lambda record: (True, ""), slow)
    record = _ask(store)
    result = _decide(store, record["id"], executor=executor, timeout_s=0.05)
    assert result["state"] == "failed"
    attempted = result["result"]["attempted"]
    assert result["result"]["outcome"] == "timed_out_unconfirmed"
    assert attempted["type"] == "merge_pr"
    assert attempted["facts"] == {"pr": 2504, "head_sha": HEAD}
    assert attempted["timeout_s"] == 0.05
    assert attempted["step_reached"] == "gh_pr_merge_started"
    assert [step["step"] for step in attempted["steps"]] == ["gh_pr_merge_started"]
    ledger = [json.loads(line) for line in store.ledger.read_text().splitlines()]
    assert ledger[-1]["event"] == "timed_out_unconfirmed" and ledger[-1]["outcome"] == "timed_out_unconfirmed"
    assert ledger[-1]["attempted"]["step_reached"] == "gh_pr_merge_started"
    digest = [json.loads(line) for line in store.digest.read_text().splitlines()]
    assert digest[-1]["event"] == "timed_out_unconfirmed"


def test_a_partial_failure_records_the_step_it_reached(tmp_path):
    store = _store(tmp_path)

    def half_done(record, actor, progress):
        progress.reached("review_evidence_registered")
        progress.reached("merge_api_called")
        raise RuntimeError("API returned 405")

    executor = ha.CallbackExecutor(lambda record: (True, ""), half_done)
    record = _ask(store)
    result = _decide(store, record["id"], executor=executor)
    assert result["state"] == "failed" and result["result"]["outcome"] == "failed"
    attempted = result["result"]["attempted"]
    assert [step["step"] for step in attempted["steps"]] == ["review_evidence_registered", "merge_api_called"]
    assert attempted["step_reached"] == "merge_api_called"
    assert "API returned 405" in result["result"]["plain"]


def test_a_decline_is_recorded_and_runs_nothing(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = _ask(store)
    declined = _decide(store, record["id"], decision="decline", note="Not now", executor=rec.executor())
    assert declined["state"] == "declined" and declined["decline_reason"] == "Not now"
    assert rec.executed == 0
    assert json.loads(store.ledger.read_text().splitlines()[-1])["event"] == "declined"


def test_a_question_is_recorded_without_deciding_anything(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    asked = ha.question(store, record["id"], actor="operator", note="Which head is reviewed?", now=NOW)
    assert asked["state"] == "open" and asked["question"]["note"] == "Which head is reviewed?"
    assert json.loads(store.ledger.read_text().splitlines()[-1])["event"] == "question"
    with pytest.raises(ha.Refused) as caught:
        ha.question(store, record["id"], actor="operator", note="  ", now=NOW)
    assert caught.value.code == "question_empty"


# ── Store integrity: private, atomic, and an unreadable record is an ERROR ────────────────────────────────
def test_the_store_is_private_and_leaves_no_temp_files(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    path = store.path(record["id"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_an_unreadable_record_is_an_error_not_an_empty_board(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    store.path(record["id"]).write_text("{not json")
    with pytest.raises(ha.Refused) as caught:
        ha.list_open(store, now=NOW)
    assert caught.value.code == "store_unreadable"


def test_a_missing_store_reads_as_empty(tmp_path):
    assert ha.list_open(ha.Store(tmp_path / "nothing-here"), now=NOW) == []


def test_every_write_lands_under_the_given_state_root(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    _decide(store, record["id"], executor=Recorder().executor())
    assert all(str(path).startswith(str(tmp_path)) for path in tmp_path.rglob("*"))
    assert (tmp_path / "state" / "needs_you" / "ledger.jsonl").exists()
    assert (tmp_path / "state" / "coordination" / "digest_approvals.jsonl").exists()


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────────
def _cli_ask(store_root: Path) -> int:
    return ha.main(["--state-root", str(store_root), "--json", "ask", "--type", "rerun_ci", "--title", "Re-run CI",
                    "--why", "One flaky shard", "--rule", "AGENTS §7", "--what-happens", "Re-runs the failed jobs once",
                    "--risk", "None material", "--undo", "Nothing to undo", "--requester", "cc-deepseek-5",
                    "--facts", json.dumps({"run_id": 41683436869, "head_sha": HEAD})])


def test_the_cli_creates_and_lists_requests(tmp_path, capsys):
    root = tmp_path / "state"
    assert _cli_ask(root) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["type"] == "rerun_ci" and created["facts"]["run_id"] == 41683436869
    assert ha.main(["--state-root", str(root), "--json", "list"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == [created["id"]]


def test_the_cli_refuses_a_decision_without_the_server_flags(tmp_path, capsys):
    root = tmp_path / "state"
    store = ha.Store(root)
    record = _ask(store)
    code = ha.main(["--state-root", str(root), "approve", record["id"], "--actor", "operator"])
    assert code == 2
    assert json.loads(capsys.readouterr().err)["code"] == "server_context_required"


def test_the_cli_refuses_to_run_without_a_state_root(monkeypatch):
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    with pytest.raises(SystemExit):
        ha.main(["--json", "list"])


# ── The event stream the Telegram nudge lane (piece D) reads ────────────────────────────────────────────────
OPEN_EVENTS = {"created", "updated", "pending", "open", "requested"}          # scripts/approvals_notify.py
CLOSED_EVENTS = {"resolved", "declined", "approved", "expired", "cancelled", "canceled", "done"}


def _events(store: ha.Store) -> list[dict]:
    return [json.loads(line) for line in store.events.read_text().splitlines()]


def test_a_created_request_appears_on_the_nudge_stream_with_a_plain_requester(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    rows = _events(store)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "ApprovalRequestEvent@v1" and row["event"] == "created"
    assert row["id"] == record["id"] and row["type"] == "merge_pr"
    assert row["title"] and row["why"] and row["facts"] == {"pr": 2504, "head_sha": HEAD}
    assert row["requester"] == "cc-deepseek-5"                      # a string, as piece D expects
    assert row["requester_detail"]["session"] == "cc-deepseek-5"
    assert row["expires_at"] == record["expires_at"]


def test_the_stream_closes_a_request_once_it_is_decided(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    _decide(store, record["id"], executor=Recorder().executor())
    events = [row["event"] for row in _events(store)]
    assert events == ["created", "approved"]

    # The same reduction piece D does: newest row per id, closed when the event is a closed event.
    newest = {}
    for row in _events(store):
        newest[row["id"]] = row
    assert newest[record["id"]]["event"] in CLOSED_EVENTS


def test_decline_expiry_and_a_question_are_published(tmp_path):
    store = _store(tmp_path)
    first = _ask(store)
    _decide(store, first["id"], decision="decline", note="no", executor=Recorder().executor())
    assert [r["event"] for r in _events(store) if r["id"] == first["id"]][-1] == "declined"

    second = _ask(store)
    ha.question(store, second["id"], actor="operator", note="which head?", now=NOW)
    assert [r["event"] for r in _events(store) if r["id"] == second["id"]][-1] == "updated"
    assert "updated" in OPEN_EVENTS

    third = _ask(store, ttl_hours=1)
    ha.expire_due(store, now=NOW + timedelta(hours=3))
    assert [r["event"] for r in _events(store) if r["id"] == third["id"]][-1] == "expired"


def test_a_moved_fact_keeps_the_request_open_on_the_stream(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    with pytest.raises(ha.Refused):
        _decide(store, record["id"], executor=Recorder(ok=False, plain="head moved").executor())
    last = _events(store)[-1]
    assert last["event"] == "updated" and last["id"] == record["id"]
    assert last["state"] == "open"


# ── Codex's seven paired-safety counterexamples, each closed ────────────────────────────────────────────────
def test_a_denied_directory_is_an_error_not_an_empty_board(tmp_path):
    store = _store(tmp_path)
    _ask(store)
    store.requests_dir.chmod(0o000)
    try:
        with pytest.raises(ha.Refused) as caught:
            ha.list_open(store, now=NOW)
        assert caught.value.code == "store_unreadable" and caught.value.plain
        with pytest.raises(ha.Refused):
            store.all()
    finally:
        store.requests_dir.chmod(0o700)


def test_a_record_tampered_after_approval_never_reaches_an_executor(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    record = _ask(store)
    stored = store.get(record["id"])
    stored.update({"state": "approved", "binding": ha._binding_of(stored), "decision": "approve"})
    store.put(stored)
    tampered = store.get(record["id"])
    tampered["type"] = "place_order"
    tampered["facts"] = {"pr": 1, "head_sha": "f" * 40}
    store.put(tampered)
    with pytest.raises(ha.Refused) as caught:
        ha.execute(store, tampered, actor="operator", now=NOW, executor=rec.executor())
    assert caught.value.code in {"binding_mismatch", "record_invalid"}
    assert rec.executed == 0
    assert store.get(record["id"])["state"] == "open"


def test_live_facts_changing_at_the_execution_boundary_refuse_the_run(tmp_path):
    store = _store(tmp_path)
    calls = {"n": 0}

    def revalidate(record):
        calls["n"] += 1
        return (True, "") if calls["n"] == 1 else (False, "The head moved while the click was being processed.")

    def execute(record, actor, progress):  # pragma: no cover - must never run
        raise AssertionError("executed despite a moved fact at the execution boundary")

    executor = ha.CallbackExecutor(revalidate, execute)
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], executor=executor)
    assert caught.value.code == "facts_moved"
    stored = store.get(record["id"])
    assert stored["state"] == "open" and "head moved" in stored["blocked_reason"]
    assert calls["n"] == 2                                     # once before the decision, once at execution


def test_a_concurrent_second_decision_is_refused(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    (store.requests_dir / f"{record['id']}.deciding").write_text("")
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], executor=Recorder().executor())
    assert caught.value.code == "decision_in_progress"
    assert store.get(record["id"])["state"] == "open"


def test_a_duplicate_request_id_cannot_reset_a_decided_request(tmp_path):
    store = _store(tmp_path)
    record = ha.create(store, _payload(), requester={"session": "cc-deepseek-5"}, now=NOW, request_id="apr-fixed")
    _decide(store, record["id"], executor=Recorder().executor())
    with pytest.raises(ha.Refused) as caught:
        ha.create(store, _payload(), requester={"session": "cc-deepseek-5"}, now=NOW, request_id="apr-fixed")
    assert caught.value.code == "duplicate_request_id"
    assert store.get("apr-fixed")["state"] == "executed"


def test_the_executor_is_never_retried_after_it_raised(tmp_path):
    store = _store(tmp_path)
    calls = {"n": 0}

    def boom(record, actor, progress):
        calls["n"] += 1
        raise TypeError("raised after the effect")

    record = _ask(store)
    result = _decide(store, record["id"], executor=ha.CallbackExecutor(lambda r: (True, ""), boom))
    assert result["state"] == "failed" and calls["n"] == 1


def test_a_timed_out_action_is_unconfirmed_and_cannot_be_restarted(tmp_path):
    store = _store(tmp_path)

    def slow(record, actor, progress):
        time.sleep(0.4)
        progress.reached("late_effect")
        return {"ok": True}

    executor = ha.CallbackExecutor(lambda r: (True, ""), slow)
    record = _ask(store)
    result = _decide(store, record["id"], executor=executor, timeout_s=0.05)
    assert result["state"] == "failed"
    assert result["result"]["outcome"] == "timed_out_unconfirmed"
    assert result["result"]["needs_reconciliation"] is True
    assert "may still be running" in result["result"]["plain"]
    calls = {"n": 0}

    def counting(record, actor, progress):
        calls["n"] += 1
        return {"ok": True}

    again = ha.execute(store, result, actor="operator", now=NOW,
                       executor=ha.CallbackExecutor(lambda r: (True, ""), counting))
    assert again["state"] == "failed" and calls["n"] == 0          # settled: never restarted
    assert (store.requests_dir / f"{record['id']}.executed").exists()  # the marker that blocks a restart


def test_a_false_result_is_recorded_as_failed_with_a_digest_row(tmp_path):
    store = _store(tmp_path)
    executor = ha.CallbackExecutor(lambda r: (True, ""),
                                   lambda record, actor, progress: {"ok": False, "plain": "The merge was refused."})
    record = _ask(store)
    result = _decide(store, record["id"], executor=executor)
    assert result["state"] == "failed" and result["result"]["outcome"] == "refused"
    digest = [json.loads(line) for line in store.digest.read_text().splitlines()]
    assert digest[-1]["event"] == "refused"


def test_an_agent_or_unauthenticated_listener_cannot_mint_a_context(tmp_path):
    for principal, listener in (("agent:other-worker", "serve_proxy"), ("service", "serve_proxy"),
                                ("tailnet:operator", "cli"), ("", "serve_proxy")):
        with pytest.raises(ha.Refused) as caught:
            ha.server_context(principal=principal, session="x", csrf_ok=True, listener=listener)
        assert caught.value.code == "operator_session_required"


def test_the_recorded_actor_must_be_the_verified_login(tmp_path):
    store = _store(tmp_path)
    record = _ask(store)
    with pytest.raises(ha.Refused) as caught:
        _decide(store, record["id"], actor="cc-deepseek-5", executor=Recorder().executor())
    assert caught.value.code == "actor_not_authenticated"
    assert store.get(record["id"])["state"] == "open"


def test_the_cli_cannot_decide_even_with_its_flags(tmp_path, capsys):
    root = tmp_path / "state"
    store = ha.Store(root)
    record = _ask(store)
    code = ha.main(["--state-root", str(root), "approve", record["id"], "--actor", "operator", "--session", "operator-cc"])
    assert code == 2
    assert json.loads(capsys.readouterr().err)["code"] == "server_context_required"
    assert store.get(record["id"])["state"] == "open"
