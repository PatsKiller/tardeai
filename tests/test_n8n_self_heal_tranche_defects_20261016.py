"""Self-heal tranche: the operator's defect fixes of 2026-10-16 (#1819 + #1820 + #1821 integrated).

1. NO_OUTPUT closes only when the output is fresh by the lane's contract  (tests/test_n8n_self_healing_20261016.py)
2. a lock skip is covered only by verified work in the same mode + slot  (tests/test_n8n_self_healing_20261016.py)
3. fingerprints keep codes and classes; only volatile tokens normalize                    (section 3 here)
4. severity + lifecycle re-evaluated per occurrence; a new episode is a new incident        (section 4)
5. the model-result cache never closes, reopens or suppresses an incident                  (section 5)
6. explicit heal states; a REQUESTED row is never healed                                    (section 6)
7. live heal: parent-slot bound, re-authorized at execution, held on ambiguous/post-effect
   claims (never released), coordinated with the retry owner, code defects to the fix path  (section 7)
8. the producer cannot act without the parent binding                                       (section 8)
9. OAuth-first route + fallback + budget + validation evidence on each diagnosis record      (section 9)

Hermetic: tmp ledger/state, fake DB/store/bridge (shared doubles); no network, no DB, no token store, no send.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from scripts import n8n_failure_diagnosis as cli
from scripts.lib import effect_claim as E
from scripts.lib import n8n_self_heal as H
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

from tests.test_n8n_llm_remediation_20261010 import (  # noqa: F401 — shared doubles + the env fixture
    LOW_LANE,
    NOW,
    FakeDB,
    FakeStore,
    GovernedCall,
    _answer,
    _receipt,
    _records,
    _run,
    _siem_row,
    env,
)
from tests.test_n8n_self_healing_20261016 import PARENT, ParentStore, _add_run, _live_heal_env, _no_defer

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 3. fingerprints


@pytest.mark.parametrize("a,b", [
    ("upstream returned HTTP 401 Unauthorized", "upstream returned HTTP 500 Internal Server Error"),
    ("status_code=401", "status_code=403"),
    ("HTTP 502 Bad Gateway", "HTTP 503 Service Unavailable"),
    ("exit=1 tail=boom", "exit=2 tail=boom"),
    ("ConnectionResetError: [Errno 104] Connection reset", "ConnectionRefusedError: [Errno 111] Connection refused"),
])
def test_meaningful_codes_are_never_merged(a, b):
    assert H.signature("x", "RUN_FAILED", a) != H.signature("x", "RUN_FAILED", b)


@pytest.mark.parametrize("a,b,ka,kb", [
    ("HTTP 401 Unauthorized", "HTTP 500 Internal Server Error", "auth", "server"),
    ("requests.exceptions.ReadTimeout: read timed out", "HTTP 500 Internal Server Error", "timeout", "server"),
    ("KeyError: 'symbol'", "read timed out", "code_error:KeyError", "timeout"),
    ("invalid_grant: token expired", "connection reset by peer", "auth", "network"),
    ("HTTP 429 Too Many Requests", "HTTP 404 Not Found", "rate_limit", "client"),
])
def test_failure_classes_are_kept_apart(a, b, ka, kb):
    assert H.failure_kind(a) == ka and H.failure_kind(b) == kb
    assert H.signature("x", "RUN_FAILED", a) != H.signature("x", "RUN_FAILED", b)


def test_volatile_tokens_normalize():
    a = ("2026-10-16T12:00:01Z pid=4411 run=d:x:live:20261016T1200 wrote /home/u/state/x/2026-10-16.json "
         "id 0f3a9c7e11bb22 HTTP 503 after 12.4s")
    b = ("2026-10-17T09:31:55Z pid=90 run=d:x:live:20261017T0930 wrote /tmp/other/run/2026-10-17.json "
         "id 7777aaaa9999bb HTTP 503 after 3.0s")
    assert H.signature("x", "RUN_FAILED", a) == H.signature("x", "RUN_FAILED", b)
    assert "http=503" in H.normalize_error(a) and "<path>" in H.normalize_error(a) and "<pid>" in H.normalize_error(a)


def test_auth_failure_is_never_transient():
    assert H.classify_failure("HTTP 401 Unauthorized after a timeout") == H.AUTH
    assert H.classify_failure("HTTP 500 Internal Server Error") == H.TRANSIENT


# ---------------------------------------------------------------- 4. severity + episodes


def test_attach_only_to_an_open_episode_of_no_lower_severity():
    ep = {"n": 1, "lead": "lead", "severity": "WARN", "status": "open"}
    assert H.attach_decision(ep, key="k2", severity="WARN") == (True, "duplicate_signature")
    assert H.attach_decision(ep, key="k2", severity="INFO")[0] is True
    up = H.attach_decision(ep, key="k2", severity="CRITICAL")
    assert up[0] is False and up[1] == "severity_upgrade:WARN->CRITICAL"
    assert H.attach_decision({**ep, "status": "resolved"}, key="k2", severity="WARN") == (
        False, "episode_resolved:new_episode")


def test_a_p2_lead_does_not_absorb_a_critical_upgrade(env):
    call = GovernedCall(_answer(action="suggest_only", conf=0.9))
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7, severity="WARN")]), call=call, store=FakeStore()) == 0
    rec = _receipt(env)
    assert rec["escalations"] == [] and rec["digest"][0]["priority"] == "P2"
    # the same failure comes back CRITICAL: not attached, escalated at P1, same episode key
    rows = [_siem_row(rid=7, severity="WARN"), _siem_row(rid=8, severity="CRITICAL")]
    call2 = GovernedCall(_answer(), raise_on_call=True)            # the cached diagnosis is reused: no call
    assert _run(env, ["--apply"], db=FakeDB(rows), call=call2, store=FakeStore()) == 0
    rec = _receipt(env)
    up = next(r for r in rec["results"] if r["siem_id"] == 8)
    assert up["outcome"] != "attached" and up["severity_upgrade"] == "severity_upgrade:WARN->CRITICAL"
    assert up["diagnosis_source"] == "cache"
    (p1,) = rec["escalations"]
    assert p1["priority"] == "P1" and "severity_upgrade" in p1["reason"] and sorted(p1["siem_ids"]) == [7, 8]
    assert rec["digest"] == []


def test_a_recovered_lead_does_not_swallow_a_fresh_failure(env):
    call = GovernedCall(_answer(action="suggest_only", conf=0.9))
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7)]), call=call, store=FakeStore()) == 0
    state = json.loads((env["state"] / cli.STATE_REL).read_text())
    (sig,) = state["episodes"]
    assert state["episodes"][sig]["status"] == "open" and state["episodes"][sig]["n"] == 1
    # the lane recovers (later dry run of the failed mode, verified) -> the lead closes, the episode resolves
    _add_run(env["ledger"], "n8n-wf-abc-43", "RUN_DONE", mode="dry_run", at=NOW + timedelta(minutes=2))
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7)]), call=GovernedCall(_answer(), raise_on_call=True),
                store=FakeStore(), now=NOW + timedelta(minutes=5)) == 0
    state = json.loads((env["state"] / cli.STATE_REL).read_text())
    assert state["episodes"][sig]["status"] == "resolved" and state["escalations"] == {}
    # a FRESH failure of the same signature after recovery: a new episode, a new incident key, not attached
    fresh = _siem_row(rid=9)
    fresh["created_at"] = (NOW + timedelta(minutes=8)).isoformat()
    _add_run(env["ledger"], "n8n-wf-abc-44", "RUN_FAILED", mode="dry_run", at=NOW + timedelta(minutes=8))
    fresh["message"] = fresh["message"].replace("n8n-wf-abc-42", "n8n-wf-abc-44")
    assert _run(env, ["--apply"], db=FakeDB([fresh]), call=GovernedCall(_answer(action="suggest_only", conf=0.9)),
                store=FakeStore(), now=NOW + timedelta(minutes=10)) == 0
    rec = _receipt(env)
    res = rec["results"][0]
    assert res["outcome"] != "attached" and res["episode"] == 2 and res["episode_check"] == "episode_resolved:new_episode"
    assert rec["digest"][0]["key"].endswith("|ep2")


# ---------------------------------------------------------------- 5. cache vs lifecycle


def test_cache_reuse_never_closes_or_suppresses(env):
    call = GovernedCall(_answer(action="suggest_only", conf=0.9))
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7)]), call=call, store=FakeStore()) == 0
    # cycle 2: the diagnosed incident is carried: no call, still open, its escalation untouched
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7)]), call=GovernedCall(_answer(), raise_on_call=True),
                store=FakeStore()) == 0
    rec = _receipt(env)
    assert rec["results"][0]["outcome"] == "carried" and rec["digest"][0]["siem_ids"] == [7]
    assert not [r for r in _records(env) if r.get("outcome") == "carried"]       # a carry writes no record


def test_one_incident_closing_does_not_close_another_on_the_same_escalation():
    state = {"escalations": {"L|sig-a": {"key": "L|sig-a", "siem_ids": [7, 8], "siem_id": 8, "priority": "P2"}},
             "episodes": {"sig-a": {"lead": "k8", "status": "open", "n": 1}}}
    cli._close_incident(state, {"lane": "L", "signature": "sig-a", "siem_id": 7, "incident_key": "k7"}, NOW,
                        H.INCIDENT_RESOLVED)
    assert state["escalations"]["L|sig-a"]["siem_ids"] == [8] and state["episodes"]["sig-a"]["status"] == "open"
    cli._close_incident(state, {"lane": "L", "signature": "sig-a", "siem_id": 8, "incident_key": "k8"}, NOW,
                        H.INCIDENT_RESOLVED)
    assert state["escalations"] == {} and state["episodes"]["sig-a"]["status"] == "resolved"


# ---------------------------------------------------------------- 6. explicit heal states


def _ledger_run(ledger, run_id, state, *, mode="live", parent=None, **receipt):
    led = CoordinationLedger(ledger)
    store = LedgerRunStore(led)
    kw = {"parent_run_id": parent} if parent else {}
    store.request(run_id=run_id, lane_id=LOW_LANE, mode=mode, requested_by=cli.REQUESTED_BY, caller_id=cli.CALLER_ID,
                  now=NOW.timestamp() + 10, **kw)
    if state != "REQUESTED":
        store.claim_next(now=NOW.timestamp() + 11)
        store.finish(run_id, state=state, now=NOW.timestamp() + 20,
                     receipt={"schema": "RunReceipt@v1", "exit_code": 0 if state == "RUN_DONE" else 1, "mode": mode,
                              "finished_at": (NOW + timedelta(seconds=20)).isoformat(), **receipt})
    led.close()


def _pending(run_id, *, event_type="RUN_FAILED", mode="live", slot=None):
    return {"pending": {"k1": {"lane": LOW_LANE, "siem_id": 7, "action_id": H.LIVE_HEAL_ACTION, "signature": "sig-a",
                               "episode": 1, "event_type": event_type, "failure_mode": mode, "slot": slot,
                               "phases": [mode], "phase_idx": 0, "run_id": run_id,
                               "requested_ts": NOW.timestamp(), "heal_state": H.RECOVERY_REQUESTED}}}


RETRY_RUN = "rem-k1-abcdefgh-live"
SLOT = ["n8n-selftest-fail", "live", "20261010T0155"]


def _advance(env, state, observer=None):
    return cli.advance_pending(state, ledger=env["ledger"], store_factory=FakeStore, allowlist={}, now=NOW
                               + timedelta(minutes=1), apply=True, output_observer=observer or (lambda *a: None))


def test_a_requested_row_is_never_healed(env):
    _ledger_run(env["ledger"], RETRY_RUN, "REQUESTED", parent=PARENT)
    (ev,) = _advance(env, _pending(RETRY_RUN, slot=SLOT))
    assert ev["outcome"] == "waiting" and ev["heal_state"] == H.RECOVERY_REQUESTED
    assert not H.is_healed(ev["heal_state"])


def test_run_done_without_verified_output_is_attempt_executed_not_healed(env):
    _ledger_run(env["ledger"], RETRY_RUN, "RUN_DONE", parent=PARENT)          # exit 0, but no output proof
    (ev,) = _advance(env, _pending(RETRY_RUN, slot=SLOT))
    assert ev["heal_state"] == H.ATTEMPT_EXECUTED and not H.is_healed(ev["heal_state"])
    assert ev["outcome"].startswith("attempt_executed:not_recovered") and ev["escalate"] == "P1"


def test_no_output_heal_needs_the_output_fresh_by_contract(env):
    _ledger_run(env["ledger"], RETRY_RUN, "RUN_DONE", parent=PARENT, output_signal_mtime_before=1.0,
                output_signal_mtime_after=2.0)
    stale = lambda *a: {"verdict": "LATE", "last_output_at": (NOW + timedelta(seconds=20)).isoformat()}  # noqa: E731
    (ev,) = _advance(env, _pending(RETRY_RUN, event_type="NO_OUTPUT", slot=SLOT), stale)
    assert ev["heal_state"] == H.ATTEMPT_EXECUTED and "output_not_fresh_by_contract" in ev["outcome"]
    fresh = lambda *a: {"verdict": "FRESH", "last_output_at": (NOW + timedelta(seconds=20)).isoformat()}  # noqa: E731
    (ev,) = _advance(env, _pending(RETRY_RUN, event_type="NO_OUTPUT", slot=SLOT), fresh)
    assert ev["heal_state"] == H.INCIDENT_RESOLVED and ev["resolve"] is True


def test_verified_live_heal_resolves_the_incident(env):
    _ledger_run(env["ledger"], RETRY_RUN, "RUN_DONE", parent=PARENT, output_verdict={"verdict": "produced"})
    state = _pending(RETRY_RUN, slot=SLOT)
    state["escalations"] = {f"{LOW_LANE}|sig-a": {"key": f"{LOW_LANE}|sig-a", "siem_ids": [7], "priority": "P2"}}
    (ev,) = _advance(env, state)
    assert ev["heal_state"] == H.INCIDENT_RESOLVED and ev["output_recovered"]["basis"] == "verified_run_same_mode"
    cli.apply_results({"results": []}, [ev], state, {}, now=NOW, store_factory=FakeStore, allowlist={},
                      root=env["state"])
    assert state["escalations"] == {}


def test_a_dry_rerun_never_heals_a_live_failure(env):
    _ledger_run(env["ledger"], "rem-k1-abcdefgh-dry_run", "RUN_DONE", mode="dry_run")
    (ev,) = _advance(env, _pending("rem-k1-abcdefgh-dry_run", mode="live"))
    assert ev["heal_state"] == H.ATTEMPT_EXECUTED and "mode_mismatch" in ev["outcome"] and ev["escalate"] == "P2"


# ---------------------------------------------------------------- 7. live heal


def test_retry_coordination_with_the_retry_owner():
    parent = {"run_id": PARENT, "state": "RUN_FAILED", "requested_at": "2026-10-10T01:55:00+00:00"}

    def with_retry(**r):
        return {**parent, "receipt_json": json.dumps({"retry": r})}

    assert H.retry_coordination(parent) == (True, "no_owner_decision")
    assert H.retry_coordination(with_retry(owner="host_policy", verdict="retryable", retryable=True)) == (
        False, "host_retry_pending")
    assert H.retry_coordination(with_retry(owner="host_policy", verdict="retryable", retryable=False))[1] == \
        "host_retry_budget_exhausted"
    assert H.retry_coordination(with_retry(owner="host_policy", verdict="terminal", retryable=False))[1].startswith(
        "host_verdict_terminal")
    assert H.retry_coordination(with_retry(owner="run_lane", verdict="retryable", retryable=True))[1] == \
        "retry_owner:run_lane"
    a2 = {"run_id": PARENT + ":a2", "state": "RUN_FAILED", "requested_at": "2026-10-10T02:00:00+00:00"}
    assert H.retry_coordination(parent, [a2])[1].startswith("slot_already_retried")
    assert H.retry_coordination(None) == (False, "parent_missing")
    assert H.retry_coordination({**parent, "state": "RUN_DONE"})[0] is False


@pytest.mark.parametrize("claim,ok,why", [
    (None, True, "no_claim:pre_effect"),
    ({"state": "FAILED", "pre_effect": 1}, True, "failed_pre_effect"),
    ({"state": "FAILED", "pre_effect": 0}, False, "held:failed_unproven_pre_effect"),
    ({"state": "FAILED", "pre_effect": 1, "fence_passed_at": "2026-10-16T12:00:00Z"}, False, "held:post_fence"),
    ({"state": "DONE"}, False, "held:effect_done"),
    ({"state": "CLAIMED"}, False, "held:claim_in_flight"),
    ({"state": "UNKNOWN"}, False, "held:ambiguous_unknown"),
])
def test_effect_hold(claim, ok, why):
    assert H.effect_hold(claim) == (ok, why)
    assert H.effect_hold(None, readable=False) == (False, "held:effect_ledger_unreadable")


def _effect_claim(ledger, state, *, pre_effect=False):
    fx = E.EffectClaimStore(CoordinationLedger(ledger))
    fx.set_owner(LOW_LANE, "n8n", expect_epoch=None, by="op", now=NOW.timestamp() - 100)
    key = E.effect_key(LOW_LANE, "20261010T0155", "v1")
    assert fx.claim(key, scheduler="n8n", now=NOW.timestamp() - 90, run_id=PARENT, admitted_at=NOW.timestamp() - 95).ok
    if state != "CLAIMED":
        fx.finish(key, state=state, now=NOW.timestamp() - 80, run_id=PARENT, pre_effect=pre_effect)
    return key


def test_post_effect_failure_is_held_and_the_claim_is_never_released(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    _add_run(e["ledger"], PARENT, "RUN_FAILED", mode="live", stderr="connection reset by peer")
    key = _effect_claim(e["ledger"], E.STATE_FAILED, pre_effect=False)
    store = ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer(), raise_on_call=True),
                store=store, deferral=_no_defer) == 0
    rec = _receipt(e)
    res = rec["results"][0]
    assert res["outcome"] == "held" and res["effect_hold"]["verdict"] == "held:failed_unproven_pre_effect"
    assert store.requests == [] and rec["escalations"][0]["priority"] == "P1"
    row = E.EffectClaimStore(CoordinationLedger(e["ledger"])).get(key)
    assert row["state"] == E.STATE_FAILED and not row["pre_effect"]           # untouched: no release, no reclaim


def test_pre_effect_failure_is_healed_once_bound_to_the_parent(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    _add_run(e["ledger"], PARENT, "RUN_FAILED", mode="live", stderr="connection reset by peer")
    _effect_claim(e["ledger"], E.STATE_FAILED, pre_effect=True)
    store = ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer(), raise_on_call=True),
                store=store, deferral=_no_defer) == 0
    res = _receipt(e)["results"][0]
    assert res["effect_hold"]["verdict"] == "failed_pre_effect" and res["reauthorization"] == "ok"
    assert res["heal_state"] == H.RECOVERY_REQUESTED and store.requests[0]["parent_run_id"] == PARENT
    assert _receipt(e)["counts"]["heal_recovery_requested"] == 1 and _receipt(e)["counts"]["heal_incident_resolved"] == 0


def test_host_retry_pending_means_no_double_retry(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    led = CoordinationLedger(e["ledger"])
    runs = LedgerRunStore(led)
    runs.request(run_id=PARENT, lane_id=LOW_LANE, mode="live", requested_by="n8n", caller_id="n8n-relay",
                 now=NOW.timestamp() - 80)
    runs.claim_next(now=NOW.timestamp() - 70)
    runs.finish(PARENT, state="RUN_FAILED", now=NOW.timestamp() - 60, receipt={
        "schema": "RunReceipt@v1", "exit_code": 1, "mode": "live", "stderr_tail": "connection reset by peer",
        "retry": {"owner": "host_policy", "verdict": "retryable", "retryable": True, "attempt": 1, "max_attempts": 2}})
    led.close()
    store = ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer(action="suggest_only", conf=0.9)),
                store=store, deferral=_no_defer) == 0
    res = _receipt(e)["results"][0]
    assert res["live_heal_gate"] == "retry_owner:host_retry_pending" and store.requests == []


def test_authorization_is_rechecked_immediately_before_execution(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    _add_run(e["ledger"], PARENT, "RUN_FAILED", mode="live", stderr="connection reset by peer")
    real = cli.apply_results

    def drop_from_live_list(*a, **kw):          # the operator removes the lane from the live list mid-cycle
        monkeypatch.setenv(H.LIVE_LIST_ENV, "some-other-lane")
        return real(*a, **kw)

    monkeypatch.setattr(cli, "apply_results", drop_from_live_list)
    store = ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer(), raise_on_call=True),
                store=store, deferral=_no_defer) == 0
    res = _receipt(e)["results"][0]
    assert res["live_heal_gate"] == "ok" and res["reauthorization"] == "not_on_live_list"
    assert store.requests == [] and "reauthorization:not_on_live_list" in res["outcome"]


def test_code_defect_goes_to_the_fix_path_never_a_rerun(env):
    row = _siem_row(error="exit=1 tail=TypeError: unsupported operand type(s)")
    store = FakeStore()
    assert _run(env, ["--apply"], db=FakeDB([row]), call=GovernedCall(_answer(action="rerun_dry_run", conf=0.95)),
                store=store) == 0
    rec = _receipt(env)
    res = rec["results"][0]
    assert store.requests == [] and res["decision"]["reason"] == "code_defect:fix_pr_release"
    assert res["fix_path"]["route"] == "fix_pr_release" and res["fix_path"]["failure_kind"] == "code_error:TypeError"
    assert rec["digest"][0]["route"] == "fix_pr_release"
    # the hook for the code-defect fixer (Claude Code iterative fixing, built separately): a stable id + evidence
    (d,) = [r for r in _records(env) if r["kind"] == "diagnosis"]
    cd = d["code_defect"]
    assert cd["schema"] == cli.CODE_DEFECT_SCHEMA and cd["consumer"] == "claude_code_iterative_fix"
    assert cd["defect_id"] == f"cd-{LOW_LANE}-{res['signature'].removeprefix('sig-')}-ep1"
    ev = cd["evidence"]
    assert ev["siem_id"] == 7 and ev["incident_key"] == res["incident_key"] and ev["failed_run_id"] == "n8n-wf-abc-42"
    assert ev["diagnoses_store"] == str(cli.DIAGNOSES_REL) and ev["receipt"] == cli.RECEIPT_REL
    assert ev["evidence_pack"]["ref"] and (env["state"] / "data" / "runtime" / ev["evidence_pack"]["ref"]).is_file()
    assert rec["digest"][0]["fix_path"]["defect_id"] == cd["defect_id"]       # the escalation carries the same id


def test_the_diagnoser_never_releases_an_effect_claim():
    src = (ROOT / "scripts" / "n8n_failure_diagnosis.py").read_text(encoding="utf-8")
    assert ".release(" not in src and "release_dead_letter" not in src
    assert "UPDATE effect_claims" not in src and "DELETE FROM effect_claims" not in src
    assert "effect_claims WHERE effect_key" in src and "mode=ro" in src      # the only claim access: read-only


# ---------------------------------------------------------------- 8. parent binding


def test_producer_cannot_act_without_the_parent_binding():
    res = {"lane": LOW_LANE, "incident_key": "siem7-abcdef012345",
           "_action": {"action_id": H.LIVE_HEAL_ACTION, "handler": "ledger_request_run", "mode_sequence": ["live"]}}
    store = FakeStore()
    called = []
    got = cli.execute_action(store, res, allowlist={LOW_LANE: {}}, now=1.0,
                             reauthorize=lambda r: called.append(r) or (True, "ok"))
    assert got == {"ok": False, "outcome": "refused:live_heal_requires_parent_binding"}
    assert store.requests == [] and called == []
    # with a parent but no re-authorization hook, it still cannot act
    got = cli.execute_action(store, {**res, "_parent_run_id": PARENT}, allowlist={LOW_LANE: {}}, now=1.0)
    assert got["outcome"] == "refused:live_heal_requires_reauthorization" and store.requests == []


# ---------------------------------------------------------------- 9. LLM route evidence


class RoutedCall(GovernedCall):
    """The bridge's envelope with a route: grok rate-limited, chatgpt served (OAuth first, no DeepSeek)."""

    def __call__(self, messages, **kw):
        out = super().__call__(messages, **kw)
        out["_tradeai"].update(
            provider="chatgpt", reasoning_tier="FAST",
            routing_decision={"route_profile": "n8n_oauth_first", "served_lane": "chatgpt_oauth"},
            route_receipts=[{"lane": "grok_oauth", "provider": "grok", "outcome": "rate_limited", "attempt": 1},
                            {"lane": "chatgpt_oauth", "provider": "chatgpt", "outcome": "ok", "attempt": 1}])
        return out


def test_each_diagnosis_record_carries_route_fallback_budget_and_validation(env):
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=RoutedCall(_answer(action="suggest_only", conf=0.9)),
                store=FakeStore()) == 0
    (d,) = [r for r in _records(env) if r["kind"] == "diagnosis"]
    llm = d["llm"]
    assert llm["route"]["profile"] == "n8n_oauth_first" and llm["route"]["served_provider"] == "chatgpt"
    assert llm["fallback"]["tried"] == ["grok:rate_limited", "chatgpt:ok"] and llm["fallback"]["fell_back"] is True
    assert llm["fallback"]["deepseek_escalated"] is False
    assert llm["budget"]["per_call_cap_usd"] == 0.05 and llm["budget"]["daily_cap_usd"] == 0.10
    assert llm["budget"]["max_calls_per_signature"] == 3 and llm["budget"]["projected_usd"] > 0
    assert llm["validation"]["verdict_ok"] is True and llm["validation"]["grounded"] is True
    assert llm["authority"]["model_grants_execution"] is False
    assert d["diagnosis_source"] == "model"


def test_routing_policy_is_oauth_first_with_one_capped_deepseek_escalation():
    pol = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text(encoding="utf-8"))

    def find(node):
        if isinstance(node, dict):
            if "n8n_lane_failure_diagnosis" in node and isinstance(node["n8n_lane_failure_diagnosis"], dict) \
                    and "primary" in node["n8n_lane_failure_diagnosis"]:
                return node["n8n_lane_failure_diagnosis"]
            for v in node.values():
                got = find(v)
                if got:
                    return got
        return None

    row = find(pol)
    assert [row[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
    assert row["route_profile"] == "n8n_oauth_first" and row["cost_ceiling_usd"] <= 0.05
    assert row["reasoning_lane"]["provider"] == "deepseek"


def test_model_output_never_grants_live_execution(env, tmp_path, monkeypatch):
    """Even with every live-heal condition true, a model CHOOSING rerun_live_once is a suggestion (P2), never a run."""
    e = _live_heal_env(env, tmp_path, monkeypatch)
    monkeypatch.delenv(H.LIVE_LIST_ENV)                 # the deterministic gate refuses -> falls to the model
    store = ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]),
                call=GovernedCall(_answer(action="rerun_live_once", conf=0.99)), store=store, deferral=_no_defer) == 0
    res = _receipt(e)["results"][0]
    assert res["live_heal_gate"] == "live_list_unavailable"
    assert res["decision"]["reason"] == "live_heal_not_model_selectable" and store.requests == []


# ---------------------------------------------------------------- review fix A: a monitoring outage preserves state


class BrokenDB(FakeDB):
    """The SIEM read fails (a monitoring outage): the cursor raises on the SELECT."""

    def cursor(self):
        raise RuntimeError("system_health_events unreachable")


def _down():
    raise RuntimeError("db down")


@pytest.mark.parametrize("outage", ["connect_fails", "read_fails"])
def test_monitoring_outage_preserves_incident_state_and_raises_p1(env, outage):
    call = GovernedCall(_answer(action="suggest_only", conf=0.9))
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7)]), call=call, store=FakeStore()) == 0
    before = json.loads((env["state"] / cli.STATE_REL).read_text())
    assert before["escalations"] and [e["status"] for e in before["episodes"].values()] == ["open"]
    before["pending"] = {"k-pend": {"lane": LOW_LANE, "run_id": "rem-k-pend-abcdefgh-dry_run", "siem_id": 7,
                                    "phases": ["dry_run"], "phase_idx": 0, "requested_ts": NOW.timestamp()}}
    (env["state"] / cli.STATE_REL).write_text(json.dumps(before))
    later = NOW + timedelta(minutes=5)
    if outage == "connect_fails":
        rc = cli.main(["--apply"], conn_factory=_down, governed_call=GovernedCall(_answer(), raise_on_call=True),
                      now=later, catalogue_path=env["catalogue"], registry_path=env["registry"],
                      allowlist_path=env["allowlist"], deferral=_no_defer, store_factory=FakeStore)
    else:
        rc = _run(env, ["--apply"], db=BrokenDB([]), call=GovernedCall(_answer(), raise_on_call=True),
                  store=FakeStore(), now=later)
    assert rc == 1
    after = json.loads((env["state"] / cli.STATE_REL).read_text())
    # nothing pruned, nothing resolved, nothing advanced: the empty row list meant UNKNOWN, not "all closed"
    assert after["escalations"] == before["escalations"]
    assert after["episodes"] == before["episodes"] and after["diagnosed"] == before["diagnosed"]
    assert after["pending"] == before["pending"]
    rec = _receipt(env)
    assert rec["incident_state_preserved"] is True and rec["pending"] == []
    outage_p1 = [e for e in rec["escalations"] if e["reason"] == cli.MONITORING_OUTAGE_REASON]
    assert len(outage_p1) == 1 and outage_p1[0]["priority"] == "P1"
    assert rec["digest"] == [e for e in before["escalations"].values() if e["priority"] != "P1"]


def test_a_readable_empty_siem_still_prunes(env):
    """The fix is narrow: a READABLE source with no open rows still closes the old incidents."""
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7)]),
                call=GovernedCall(_answer(action="suggest_only", conf=0.9)), store=FakeStore()) == 0
    assert _run(env, ["--apply"], db=FakeDB([]), call=GovernedCall(_answer(), raise_on_call=True),
                store=FakeStore(), now=NOW + timedelta(minutes=5)) == 0
    after = json.loads((env["state"] / cli.STATE_REL).read_text())
    assert after["escalations"] == {} and [e["status"] for e in after["episodes"].values()] == ["resolved"]
    assert not [e for e in _receipt(env)["escalations"] if e["reason"] == cli.MONITORING_OUTAGE_REASON]


# ---------------------------------------------------------------- review fix B: P1 floor for CRITICAL / URGENT


def _deferred(pid):
    return type("Dec", (), {"defer": True, "reason": "OUTSIDE_OFFPEAK_WINDOW"})()


@pytest.mark.parametrize("sev", ["CRITICAL", "URGENT"])
@pytest.mark.parametrize("branch", ["suggest_only", "deferred", "signature_cap", "model_refused", "low_budget"])
def test_a_first_critical_or_urgent_occurrence_is_never_p2(env, sev, branch):
    call = GovernedCall(_answer(action="suggest_only", conf=0.95))
    deferral = _no_defer
    if branch == "deferred":
        deferral = _deferred
    if branch == "model_refused":
        call = GovernedCall("not json at all")
    if branch in ("signature_cap", "low_budget"):
        sig = H.signature(LOW_LANE, "RUN_FAILED", "exit=1 tail=SELFTEST_INDUCED_FAILURE")
        day = {"spend_usd": 0.0, "calls": 3, "lane_calls": {}, "lane_remediations": {}, "sig_calls": {sig: 3},
               "signatures": {}, "lane_live_heals": {}}
        if branch == "low_budget":
            day.update(spend_usd=9.99, calls=999, sig_calls={})
        p = env["state"] / cli.STATE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"days": {NOW.date().isoformat(): day}}))
        call = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7, severity=sev)]), call=call, store=FakeStore(),
                deferral=deferral) == 0
    rec = _receipt(env)
    res = rec["results"][0]
    assert res["decision"]["priority"] == "P1" and f"p1_floor:{sev}" in res["decision"]["reason"]
    assert rec["digest"] == [] and [e["priority"] for e in rec["escalations"]] == ["P1"]


def test_warn_occurrence_keeps_its_p2(env):
    assert _run(env, ["--apply"], db=FakeDB([_siem_row(rid=7, severity="WARN")]),
                call=GovernedCall(_answer(action="suggest_only", conf=0.95)), store=FakeStore()) == 0
    rec = _receipt(env)
    assert rec["escalations"] == [] and rec["digest"][0]["priority"] == "P2"


@pytest.mark.parametrize("kind", ["attach", "carry"])
def test_dedupe_or_cache_never_holds_a_critical_occurrence_below_p1(kind, tmp_path):
    """A P2 escalation that a CRITICAL occurrence rides (attached or carried) is lifted to P1."""
    res = {"lane": "L", "signature": "sig-a", "episode": 1, "incident_key": "k8", "siem_id": 8,
           "severity": "CRITICAL", "outcome": "attached" if kind == "attach" else "carried",
           "decision": {"kind": kind, "priority": None, "reason": "x", "action_id": None}}
    state = {"escalations": {"L|sig-a": {"key": "L|sig-a", "siem_ids": [7], "priority": "P2", "route": "digest",
                                         "reason": "suggest_only"}}}
    cli.apply_results({"results": [res]}, [], state, {}, now=NOW, store_factory=FakeStore, allowlist={},
                      root=tmp_path)
    esc = state["escalations"]["L|sig-a"]
    assert esc["priority"] == "P1" and esc["route"] == "operator_once" and esc["reason"].startswith("p1_floor:CRITICAL")


def test_pending_failure_of_a_critical_incident_escalates_p1(env):
    _ledger_run(env["ledger"], RETRY_RUN, "RUN_DONE", parent=PARENT)          # ran, not verified
    st = _pending(RETRY_RUN, slot=SLOT)
    st["pending"]["k1"]["severity"] = "CRITICAL"
    (ev,) = _advance(env, st)
    assert ev["severity"] == "CRITICAL"
    assert cli._escalation(ev, "P2", ev["outcome"], NOW)["priority"] == "P1"
