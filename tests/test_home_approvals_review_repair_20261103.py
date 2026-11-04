"""HOME_APPROVALS_REVIEW_REPAIR_20261103 — the cx-openai-3 whole-head grounds, each pinned.

cx-openai-3 blocked a9ffe5be5 with four P1s and one P2. This file is the regression for each one, written
against the actual source (no stubs of the functions under test):

    F1  requester != approver compared raw strings while authentication is case-insensitive
    F2  a syntactically valid but corrupt record made list_open() look like an empty board
    F3  an exception from revalidate() stranded the .executed marker for good
    F4  question() was an unlocked read-modify-write that could reopen a terminal decision
    +   decide() built the .deciding lock path before validating the request id
    F5  the one-re-run ledger accepted [] / null / false / negative counters as "zero re-runs"
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_approvals as ha  # noqa: E402
from lib import home_approvals_adapters as ada  # noqa: E402

LOGIN = sorted(ha.allowed_logins())[0]
PRINCIPAL = f"tailnet:{LOGIN}"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
HEAD = "5c15ddb039e944b9c946d769265aea347943b7b8"


def _store(tmp_path):
    return ha.Store(tmp_path / "state")


def _payload(**over):
    base = dict(type="merge_pr", title="Merge #2504", why="Green.", rule="AGENTS §9",
                what_happens="Merges #2504 at the reviewed head.", risk="No later re-read.", undo="Revert.",
                facts={"pr": 2504, "head_sha": HEAD})
    base.update(over)
    return base


def _ask(store, requester=None):
    return ha.create(store, _payload(), requester=requester or {"session": "cc-deepseek-5"}, now=NOW)


def _ctx(principal=PRINCIPAL, session="operator-cc"):
    return ha.server_context(principal=principal, session=session, csrf_ok=True, listener="serve_proxy")


class Counter:
    def __init__(self, ok=True):
        self.ok = ok
        self.executed = 0
        self.revalidated = 0

    def executor(self):
        def revalidate(record):
            self.revalidated += 1
            return self.ok, ""

        def execute(record, actor, progress):
            self.executed += 1
            progress.reached("kicked_off")
            return {"ok": True, "plain": "Done."}

        return ha.CallbackExecutor(revalidate, execute)


class Exploding:
    """The pre-decision revalidation passes; the execution-boundary one raises (F3's actual shape)."""

    def __init__(self):
        self.calls = 0

    def executor(self):
        def revalidate(record):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("bridge unavailable")
            return True, ""

        def execute(record, actor, progress):  # pragma: no cover - must never be reached
            raise AssertionError("the action must not run when revalidation failed")

        return ha.CallbackExecutor(revalidate, execute)


# ── F1: one identity, one canonical form ────────────────────────────────────────────────────
def test_the_same_login_in_another_case_cannot_approve_its_own_request(tmp_path):
    store = _store(tmp_path)
    phone = LOGIN.upper() if LOGIN != LOGIN.upper() else LOGIN.capitalize()
    record = _ask(store, requester={"session": "cc-deepseek-5", "actor": f"tailnet:{LOGIN}"})
    counter = Counter()
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=_ctx(principal=f"tailnet:{phone}"), actor=phone,
                  decision="approve", now=NOW, executor=counter.executor())
    assert caught.value.code == "approver_is_requester"
    assert counter.executed == 0 and counter.revalidated == 0
    assert store.get(record["id"])["state"] == "open"


def test_a_tailnet_prefixed_requester_cannot_be_approved_under_the_bare_login(tmp_path):
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "cc-deepseek-5", "actor": f"tailnet:{LOGIN}"})
    counter = Counter()
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                  executor=counter.executor())
    assert caught.value.code == "approver_is_requester"
    assert counter.executed == 0


def test_an_independent_requester_still_executes_once(tmp_path):
    """The control: canonicalisation must not refuse a genuinely different identity."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "some-agent-session", "actor": "tailnet:someone-else"})
    counter = Counter()
    out = ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                    executor=counter.executor())
    assert out["state"] == "executed" and counter.executed == 1


# ── F2: a corrupt record is an error, never an empty board ───────────────────────────────────
@pytest.mark.parametrize("body", ['{}', '{"schema": "nope"}', '{"state": "open"}',
                                   '{"schema": "HomeApprovalRequest@v1", "type": "merge_pr", "state": "open", '
                                   '"facts": {"pr": 2504, "head_sha": "' + HEAD + '"}}',
                                   '[]', '"text"', "17"])
def test_a_valid_json_but_corrupt_record_is_store_unreadable(tmp_path, body):
    store = _store(tmp_path)
    keep = _ask(store)
    assert ha.list_open(store, now=NOW)          # the good record still shows
    (store.requests_dir / "2026-11-03T17-00-00Z-deadbeef.json").write_text(body)
    with pytest.raises(ha.Refused) as caught:
        ha.list_open(store, now=NOW)
    assert caught.value.code == "store_unreadable"
    assert keep["id"]


def test_a_record_missing_from_the_projection_cannot_vanish_silently(tmp_path):
    store = _store(tmp_path)
    keep = _ask(store)
    (keep and None)
    target = store.requests_dir / "2026-11-03T17-00-00Z-deadbeef.json"
    target.write_text("{}")
    with pytest.raises(ha.Refused) as caught:
        ha.list_open(store, now=NOW)
    assert caught.value.code == "store_unreadable"
    assert target.name in caught.value.plain


# ── F3: a pre-effect failure does not strand the execution marker ────────────────────────────
def test_a_revalidation_exception_releases_the_marker_and_keeps_the_approval(tmp_path):
    """The first revalidation (before the decision) passes; the execution-boundary one raises."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "agent-x"})
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                  executor=Exploding().executor())
    assert caught.value.code == "revalidation_failed"
    marker = store.requests_dir / f"{record['id']}.executed"
    assert not marker.exists(), "the marker must be released so a corrected retry can run"
    stored = store.get(record["id"])
    assert stored["state"] == "approved", "the operator's approval must survive an unstarted action"
    assert stored.get("blocked_reason")
    retry = Counter()
    out = ha.execute(store, store.require(record["id"]), actor=LOGIN, now=NOW, executor=retry.executor())
    assert out["state"] == "executed" and retry.executed == 1


# ── F4: question() is a transition, not an unlocked overwrite ────────────────────────────────
def test_a_question_cannot_reopen_a_decided_request(tmp_path):
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "agent-x"})
    ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
              executor=Counter().executor())
    assert store.get(record["id"])["state"] == "executed"
    with pytest.raises(ha.Refused) as caught:
        ha.question(store, record["id"], actor=LOGIN, note="why this?", now=NOW)
    assert caught.value.code == "not_open"
    assert store.get(record["id"])["state"] == "executed", "a terminal decision must not be overwritten"


def test_a_concurrent_transition_blocks_the_question(tmp_path):
    """The lock the fix takes is the same shape decide() uses: a held marker refuses, it never overwrites."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "agent-x"})
    (store.requests_dir / f"{record['id']}.deciding").write_text("")
    with pytest.raises(ha.Refused) as caught:
        ha.question(store, record["id"], actor=LOGIN, note="why this?", now=NOW)
    assert caught.value.code == "transition_in_progress"


# ── request id: validated before any lock path is built ──────────────────────────────────────
def test_a_traversal_shaped_id_is_refused_before_a_lock_path_exists(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, "../../outside", ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW)
    assert caught.value.code == "invalid_request_id"
    assert not (store.requests_dir.parent.parent / "outside.deciding").exists()


# ── F5: a corrupt re-run ledger is not "zero re-runs" ────────────────────────────────────────
@pytest.mark.parametrize("body", ["[]", "null", "false", '"x"', "{", '{"head": -1}', '{"head": "many"}'])
def test_a_malformed_rerun_history_is_an_error(tmp_path, body):
    path = tmp_path / "reruns.json"
    path.write_text(body)
    counts, error = ada._load_reruns(path)
    assert error, f"{body!r} must not read as an empty ledger"
    assert counts == {}


def test_a_well_formed_rerun_history_still_reads(tmp_path):
    path = tmp_path / "reruns.json"
    path.write_text(json.dumps({HEAD: 1}))
    counts, error = ada._load_reruns(path)
    assert error == "" and counts == {HEAD: 1}


def test_a_missing_history_is_zero_runs_not_an_error(tmp_path):
    counts, error = ada._load_reruns(tmp_path / "absent.json")
    assert counts == {} and error == ""


# ── F4, the reviewer's own interleaving: reproduce it, not just the marker ───────────────────
def test_the_stale_question_interleaving_cannot_overwrite_a_decision(tmp_path, monkeypatch):
    """cx-openai-3's probe shape: question pauses after its read; decide+execute complete; question resumes.

    On the frozen head before this repair the question took a private marker, so the decision ran
    through and the resumed question wrote its stale open snapshot over a terminal row. With one
    shared transition marker the resumed question must either be refused or re-read the terminal
    state — never write the snapshot it read on the way in.
    """
    import threading

    store = _store(tmp_path)
    record = _ask(store, requester={"session": "agent-x"})
    rid = record["id"]
    gate_ready = threading.Event()
    release_gate = threading.Event()
    outcome = {}

    real_require = store.require

    def pausing_require(request_id):
        got = real_require(request_id)
        if threading.current_thread().name == "question-thread":
            gate_ready.set()
            release_gate.wait(5)
        return got

    monkeypatch.setattr(store, "require", pausing_require)

    def run_question():
        try:
            outcome["question"] = ha.question(store, rid, actor=LOGIN, note="why?", now=NOW)
        except ha.Refused as exc:
            outcome["question_refused"] = exc.code

    thread = threading.Thread(target=run_question, name="question-thread")
    thread.start()
    assert gate_ready.wait(5), "the question thread never reached its read"

    try:
        ha.decide(store, rid, ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                  executor=Counter().executor())
        outcome["decide"] = "ran"
    except ha.Refused as exc:
        outcome["decide_refused"] = exc.code
    release_gate.set()
    thread.join(5)

    final = real_require(rid)
    assert not (final["state"] == "open" and "question" in final and outcome.get("decide") == "ran"), (
        f"a stale question snapshot overwrote the decision: {outcome} / state={final['state']}")
    assert final["state"] in ("open", "executed"), final["state"]
    if outcome.get("decide") == "ran":
        assert final["state"] == "executed"
        assert "question_refused" in outcome, "the losing question must refuse, not silently write"


# ── R1 / R2: identity handling on the approval boundary (cx-openai-3, second round) ─────────
def test_a_transport_prefix_with_a_space_is_still_the_same_identity(tmp_path):
    """R1: `_canonical_actor` stripped before removing `tailnet:`, not after, so a prefix plus a space
    survived as a leading space and named a different identity than the one it was."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "cc-deepseek-5", "actor": f"tailnet: {LOGIN}"})
    counter = Counter()
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                  executor=counter.executor())
    assert caught.value.code == "approver_is_requester"
    assert counter.executed == 0 and counter.revalidated == 0
    assert store.get(record["id"])["state"] == "open"


def test_the_canonicaliser_agrees_across_spellings():
    login = LOGIN.casefold()
    for spelling in (LOGIN, f" tailnet:{LOGIN} ", f"tailnet: {LOGIN}", f"TAILNET:{LOGIN.upper()}",
                     f"tailnet:tailnet:{LOGIN}"):
        assert ha._canonical_actor(spelling) == login, spelling


@pytest.mark.parametrize("requester", ["absent", "empty", "sessionless"])
def test_a_request_that_does_not_say_who_asked_is_refused(tmp_path, requester):
    """R2: deleting or emptying the requester block made requester != approver unevaluable, and the
    same operator could then approve their own request."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "cc-deepseek-5", "actor": f"tailnet:{LOGIN}"})
    path = store.requests_dir / f"{record['id']}.json"
    doc = json.loads(path.read_text())
    if requester == "absent":
        doc.pop("requester", None)
    elif requester == "empty":
        doc["requester"] = {}
    else:
        doc["requester"] = {"actor": f"tailnet:{LOGIN}"}
    path.write_text(json.dumps(doc))

    with pytest.raises(ha.Refused) as caught:
        ha.list_open(store, now=NOW)
    assert caught.value.code == "store_unreadable", "a corrupt request must not render as an empty board"

    counter = Counter()
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                  executor=counter.executor())
    assert caught.value.code == "record_invalid"
    assert counter.executed == 0 and counter.revalidated == 0


# ── R4 / R3: the session-identity class (cx-openai-4, second round) ─────────────────────────
@pytest.mark.parametrize("bad_session", [True, False, 1, 0, [], ["s"], {}, {"s": 1}, 1.5, None])
def test_a_non_string_requester_session_is_a_corrupt_record(tmp_path, bad_session):
    """R4: str() coercion turned JSON true/1/[]/{} into identities that never match the approver, so
    approver_is_requester stopped firing and an operator could approve their own request."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "cc-deepseek-5", "actor": f"tailnet:{LOGIN}"})
    path = store.requests_dir / f"{record['id']}.json"
    doc = json.loads(path.read_text())
    doc["requester"]["session"] = bad_session
    path.write_text(json.dumps(doc))

    with pytest.raises(ha.Refused) as caught:
        ha.list_open(store, now=NOW)
    assert caught.value.code == "store_unreadable"

    counter = Counter()
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=_ctx(), actor=LOGIN, decision="approve", now=NOW,
                  executor=counter.executor())
    assert caught.value.code == "record_invalid"
    assert counter.executed == 0 and counter.revalidated == 0


def test_create_refuses_a_non_string_requester_session(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ha.Refused) as caught:
        ha.create(store, _payload(), requester={"session": True}, now=NOW)
    assert caught.value.code == "requester_unknown"
    assert not list(store.requests_dir.glob("*.json"))


def test_the_session_rule_is_one_function():
    """The class guard: identity must come from _session_text, never from str() of an arbitrary value."""
    for value in (True, 1, [], {}, 1.5, None, "   "):
        assert ha._session_text(value) is None, value
    assert ha._session_text("  op-1  ") == "op-1"


def test_create_and_server_context_normalise_a_padded_session_identically(tmp_path):
    """R3: the two paths normalised differently, so one padded session looked like two identities."""
    store = _store(tmp_path)
    padded = "  operator-session-7  "
    record = _ask(store, requester={"session": padded})
    assert record["requester"]["session"] == "operator-session-7"

    context = ha.server_context(principal=PRINCIPAL, session=padded, csrf_ok=True, listener="serve_proxy")
    assert context.session == "operator-session-7"

    counter = Counter()
    with pytest.raises(ha.Refused) as caught:
        ha.decide(store, record["id"], ctx=context, actor=LOGIN, decision="approve", now=NOW,
                  executor=counter.executor())
    assert caught.value.code == "approver_is_requester", "the same padded session must be the same identity"
    assert counter.executed == 0


def test_a_differently_padded_session_is_still_a_different_identity(tmp_path):
    """The control for the other direction: normalisation must not collapse real differences."""
    store = _store(tmp_path)
    record = _ask(store, requester={"session": "  session-a  "})
    counter = Counter()
    out = ha.decide(store, record["id"], ctx=_ctx(session="session-b"), actor=LOGIN, decision="approve",
                    now=NOW, executor=counter.executor())
    assert out["state"] == "executed" and counter.executed == 1
