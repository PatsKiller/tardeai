#!/usr/bin/env python3
"""Home v008 "Needs you" — the three approval rails, the closed action list, and the executor seam.

Every test here is a property the operator stated or the spec requires:
  * a click counts only from the operator's verified session + same-origin CSRF;
  * the requester can never be the approver;
  * an expired request re-asks and never auto-approves;
  * nothing outside the reviewed action list is reachable;
  * facts that moved are refused in plain English, and nothing runs.
"""

from __future__ import annotations

import json

import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import needs_you as ny  # noqa: E402

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
HEAD = "5c15ddb039e944b9c946d769265aea347943b7b8"


def _store(tmp_path: Path) -> ny.Store:
    return ny.Store(tmp_path / "state")


def _ask(store: ny.Store, **overrides):
    base = dict(
        action_type="merge_pr",
        title="Merge #2504",
        why="Board row 03 is green and reviewed.",
        approve_does="Merges PR #2504 at exactly the reviewed head.",
        risk="If the head moved this is refused, not merged.",
        undo="Revert the merge commit.",
        requester={"actor": "cc-deepseek-5", "session": "cc-deepseek-5", "vendor": "claude"},
        facts={"pr": 2504, "head": HEAD},
        now=NOW,
    )
    base.update(overrides)
    return ny.create_request(store, **base)


def _approval(**overrides) -> ny.Approval:
    base = dict(approver="operator", operator_session=True, csrf_ok=True, session="operator-cc")
    base.update(overrides)
    return ny.Approval(**base)


class Recorder:
    def __init__(self, ok: bool = True, plain: str = ""):
        self.ok, self.plain = ok, plain
        self.executed = 0
        self.seen = []

    def executor(self) -> ny.CallbackExecutor:
        def revalidate(request):
            self.seen.append(request["request_id"])
            return self.ok, self.plain

        def execute(request, approver):
            self.executed += 1
            return {"ok": True, "plain": f"Done ({approver})."}

        return ny.CallbackExecutor(revalidate, execute)


# ── Rail 1: the click must come from the operator's own session ───────────────────────────────────────────────
def test_an_approval_without_an_operator_session_is_refused_and_runs_nothing(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    request = _ask(store)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(operator_session=False), executor=rec.executor(), now=NOW)
    assert caught.value.code == "operator_session_required"
    assert rec.executed == 0
    assert store.get(request["request_id"])["status"] == "open"


def test_an_approval_without_the_csrf_check_is_refused(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    request = _ask(store)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(csrf_ok=False), executor=rec.executor(), now=NOW)
    assert caught.value.code == "csrf_required"
    assert rec.executed == 0


# ── Rail 2: the asker is never the approver ──────────────────────────────────────────────────────────────────
def test_the_requester_identity_cannot_approve_its_own_request(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    request = _ask(store)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(approver="cc-deepseek-5"), executor=rec.executor(), now=NOW)
    assert caught.value.code == "approver_is_requester"
    assert rec.executed == 0


def test_the_requesting_session_cannot_approve_even_under_another_name(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    request = _ask(store)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(approver="someone", session="cc-deepseek-5"),
                   executor=rec.executor(), now=NOW)
    assert caught.value.code == "approver_is_requester"
    assert rec.executed == 0


# ── Rail 3: expiry re-asks, never auto-approves ─────────────────────────────────────────────────────────────
def test_an_expired_request_is_not_approved_and_moves_to_needs_reask(tmp_path):
    store, rec = _store(tmp_path), Recorder()
    request = _ask(store, ttl_hours=1)
    later = NOW + timedelta(hours=2)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(), executor=rec.executor(), now=later)
    assert caught.value.code == "request_expired"
    assert rec.executed == 0
    assert store.get(request["request_id"])["status"] == "needs_reask"


def test_expire_due_marks_requests_and_never_approves(tmp_path):
    store = _store(tmp_path)
    request = _ask(store, ttl_hours=1)
    changed = ny.expire_due(store, now=NOW + timedelta(hours=3))
    assert [row["request_id"] for row in changed] == [request["request_id"]]
    assert store.get(request["request_id"])["status"] == "needs_reask"
    assert ny.open_requests(store, now=NOW + timedelta(hours=3)) == []


# ── The closed action list ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["place_order", "credential_read", "force_push", "delete_repo", "stop_trading", ""])
def test_an_action_outside_the_list_cannot_even_be_stored(tmp_path, kind):
    store = _store(tmp_path)
    with pytest.raises(ny.Refused) as caught:
        _ask(store, action_type=kind, facts={"pr": 1, "head": HEAD})
    assert caught.value.code == "unknown_action_type"
    assert store.all() == []


def test_every_listed_action_needs_its_exact_bound_facts(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ny.Refused) as caught:
        ny.create_request(store, action_type="merge_pr", title="t", why="w", approve_does="a", risk="r", undo="u",
                          requester={"actor": "x", "session": "s", "vendor": "v"}, facts={"pr": 1}, now=NOW)
    assert caught.value.code == "facts_incomplete"
    bad = dict(facts={"pr": 1, "head": "abc"})
    with pytest.raises(ny.Refused) as caught:
        ny.create_request(store, action_type="merge_pr", title="t", why="w", approve_does="a", risk="r", undo="u",
                          requester={"actor": "x", "session": "s", "vendor": "v"}, now=NOW, **bad)
    assert caught.value.code == "facts_invalid"


def test_the_action_list_is_exactly_the_seven_reviewed_types():
    assert set(ny.ACTION_TYPES) == {"merge_pr", "rerun_ci", "grant", "stop_job", "install_schedule",
                                    "restore_store", "policy_approval"}


# ── Executor: revalidate at click time, refuse moved facts ──────────────────────────────────────────────────
def test_moved_facts_refuse_the_click_in_plain_english_and_run_nothing(tmp_path):
    store = _store(tmp_path)
    rec = Recorder(ok=False, plain="This changed. The head moved since the lead asked; the lead will re-ask.")
    request = _ask(store)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(), executor=rec.executor(), now=NOW)
    assert caught.value.code == "facts_moved"
    assert "head moved" in caught.value.plain
    assert rec.executed == 0
    assert rec.seen == [request["request_id"]]
    stored = store.get(request["request_id"])
    assert stored["status"] == "stale" and "head moved" in stored["blocked_reason"]


def test_with_no_executor_a_click_cannot_do_anything(tmp_path):
    store = _store(tmp_path)
    request = _ask(store)
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(), now=NOW)
    assert caught.value.code == "facts_moved"
    assert "No executor" in caught.value.plain


# ── The happy path leaves durable receipts ──────────────────────────────────────────────────────────────────
def test_an_approved_request_runs_once_and_writes_both_ledgers(tmp_path):
    store = _store(tmp_path)
    rec = Recorder()
    request = _ask(store)
    done = ny.approve(store, request["request_id"], _approval(), executor=rec.executor(), now=NOW)
    assert done["status"] == "done" and rec.executed == 1
    ledger = [json.loads(line) for line in store.ledger.read_text().splitlines()]
    digest = [json.loads(line) for line in store.digest.read_text().splitlines()]
    assert [row["event"] for row in ledger] == ["created", "approved", "executed"]
    assert digest[0]["event"] == "approved" and digest[0]["approval_source"] == "operator_session+csrf"
    assert digest[0]["request_sha256"] and digest[0]["facts"] == {"pr": 2504, "head": HEAD}
    with pytest.raises(ny.Refused) as caught:
        ny.approve(store, request["request_id"], _approval(), executor=rec.executor(), now=NOW)
    assert caught.value.code == "not_open"
    assert rec.executed == 1


def test_the_store_is_private_and_leaves_no_temp_files(tmp_path):
    store = _store(tmp_path)
    request = _ask(store)
    path = store.path(request["request_id"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_a_failed_action_still_leaves_the_decision_on_record(tmp_path):
    store = _store(tmp_path)

    def boom(request, approver):
        raise RuntimeError("gh refused the merge")

    executor = ny.CallbackExecutor(lambda request: (True, ""), boom)
    request = _ask(store)
    result = ny.approve(store, request["request_id"], _approval(), executor=executor, now=NOW)
    assert result["status"] == "failed"
    events = [json.loads(line)["event"] for line in store.ledger.read_text().splitlines()]
    assert events == ["created", "approved", "failed"]


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_cli_creates_and_lists_requests(tmp_path, capsys):
    store_root = tmp_path / "state"
    assert ny.main(["--state-root", str(store_root), "--json", "ask", "--type", "rerun_ci", "--title", "Re-run CI",
                    "--why", "One flaky shard", "--approve-does", "Re-runs the failed jobs once",
                    "--requester", "cc-deepseek-5", "--facts", json.dumps({"run_id": 41683436869, "head": HEAD})]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["action_type"] == "rerun_ci" and created["facts"]["run_id"] == 41683436869
    assert ny.main(["--state-root", str(store_root), "--json", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [row["request_id"] for row in listed] == [created["request_id"]]


def test_the_cli_refuses_an_approval_that_does_not_carry_the_server_flags(tmp_path, capsys):
    store_root = tmp_path / "state"
    store = ny.Store(store_root)
    request = _ask(store)
    code = ny.main(["--state-root", str(store_root), "approve", request["request_id"], "--approver", "operator"])
    assert code == 2
    assert json.loads(capsys.readouterr().err)["code"] == "operator_session_required"


def test_the_cli_refuses_to_run_without_a_state_root(monkeypatch):
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    with pytest.raises(SystemExit):
        ny.main(["--json", "list"])


def test_every_write_lands_under_the_given_state_root(tmp_path):
    # No default location and no stray writes: every file this module creates is beneath the root it was handed.
    store = _store(tmp_path)
    before = {p for p in tmp_path.rglob("*")}
    request = _ask(store)
    rec = Recorder()
    ny.approve(store, request["request_id"], _approval(), executor=rec.executor(), now=NOW)
    created = {p for p in tmp_path.rglob("*")} - before
    assert created, "the module wrote nothing"
    assert all(str(path).startswith(str(tmp_path)) for path in created)
    assert (tmp_path / "state" / "needs_you" / "ledger.jsonl").exists()
    assert (tmp_path / "state" / "coordination" / "digest_approvals.jsonl").exists()
