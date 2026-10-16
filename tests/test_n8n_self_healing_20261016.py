"""n8n self-healing tier (operator 2026-10-16 "yes make self healing now").

Measured 2026-10-16: 612 diagnosis events, 12 diagnosed, 0 remediation runs, 695 open escalations. Pins:
1. signatures: the same failure (timestamps / ids differ) is ONE signature; another lane or kind is another;
2. classification: timeout / connection reset / HTTP 5xx are transient; psycopg2 InterfaceError is a code error;
3. deterministic tier: lock skip covered by the slot's other run, later successful run, executor_lost -> reaper;
4. live-heal gate: every refusal branch (owner, stage, sender, broker words, P1, severity, class, effect key, cap);
5. CLI: dedupe (one model call per signature, the rest attached, one collapsed escalation), auto-close with no
   model call, the live heal requested through the gateway path with no model call, a code error never live-healed,
   the per-signature call cap, P1 -> escalations with what was tried, P2 -> digest only;
6. catalogue: rerun_live_once offered at canary/cutover only, validated.

Hermetic: tmp ledger, fake DB/store/bridge (shared doubles from tests/test_n8n_llm_remediation_20261010.py); no
network, no DB, no token store, no send.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from scripts import n8n_failure_diagnosis as cli
from scripts import n8n_selftest_fail as selftest
from scripts.lib import n8n_remediation_catalogue as C
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


# ---------------------------------------------------------------- 1-2. signature + classification


def test_signature_ignores_timestamps_and_ids_but_not_lane_or_kind():
    a = H.signature("lane-a", "NO_OUTPUT", "lane-a:NO_OUTPUT: {'expected_by': '2026-10-15T13:00:00+00:00', 'n': 3}")
    b = H.signature("lane-a", "NO_OUTPUT", "lane-a:NO_OUTPUT: {'expected_by': '2026-10-16T13:00:00+00:00', 'n': 7}")
    assert a == b and a.startswith("sig-")
    assert H.signature("lane-b", "NO_OUTPUT", "lane-b:NO_OUTPUT: {'n': 3}") != a
    assert H.signature("lane-a", "RUN_FAILED", "lane-a:NO_OUTPUT: {'n': 3}") != a
    run1 = H.signature("x", "RUN_FAILED", "mode=live run=d:x:live:20261016T0815 exit=1 tail=boom")
    run2 = H.signature("x", "RUN_FAILED", "mode=live run=d:x:live:20261017T0815 exit=1 tail=boom")
    assert run1 == run2


@pytest.mark.parametrize("text,expected", [
    ("requests.exceptions.ReadTimeout: read timed out", H.TRANSIENT),
    ("ConnectionResetError: [Errno 104] Connection reset by peer", H.TRANSIENT),
    ("psycopg2.OperationalError: server closed the connection unexpectedly", H.TRANSIENT),
    ("HTTP 503 Service Unavailable from upstream", H.TRANSIENT),
    ("skipped_reasons dependency_unavailable", H.TRANSIENT),
    ("psycopg2.InterfaceError: connection already closed", H.CODE_ERROR),
    ("TypeError: unsupported operand type(s)", H.CODE_ERROR),
    ("KeyError: 'symbol' after a timeout", H.CODE_ERROR),        # a code error wins over a transient word
    ("flock: cannot open lock file /tmp/x.lock: No space left on device", H.UNKNOWN),
])
def test_classify_failure(text, expected):
    assert H.classify_failure(text) == expected


def test_run_timeout_event_is_transient():
    assert H.classify_failure("", event_type="RUN_TIMEOUT") == H.TRANSIENT


# ---------------------------------------------------------------- 3. deterministic tier (pure)


def _r(run_id, state, mode="live", req="2026-10-16T12:15:00+00:00", fin="2026-10-16T12:16:00+00:00", **rec):
    return {"run_id": run_id, "state": state, "mode": mode, "requested_at": req, "finished_at": fin, "exit_code": 0
            if state == "RUN_DONE" else 1, "receipt_json": json.dumps(rec) if rec else None}


T = NOW.timestamp()


SKIP = "d:lane-x:live:20261016T1215"
COVER = "e:lane-x:live:20261016T1215"


def test_lock_skip_covered_by_a_verified_run_of_the_same_mode_and_slot_auto_closes():
    runs = [_r(COVER, "RUN_DONE", req="2026-10-16T12:15:01+00:00", output_verdict={"verdict": "produced"}),
            _r(SKIP, "RUN_SKIPPED_LOCK", req="2026-10-16T12:15:00+00:00", reason="flock_held")]
    v = H.deterministic_verdict({"event_type": "RUN_SKIPPED_LOCK"}, fields={"run": SKIP, "error": "flock_held"},
                                runs=runs, now=T)
    assert v["kind"] == "auto_close" and v["outcome"] == "covered" and v["evidence"] == [f"run:{COVER}"]
    assert v["heal_state"] == H.OUTPUT_RECOVERED


def test_lock_skip_without_a_covering_run_is_not_closed():
    runs = [_r(SKIP, "RUN_SKIPPED_LOCK", reason="flock_held"),
            _r("d:lane-x:live:20261016T0900", "RUN_DONE", req="2026-10-16T09:00:00+00:00",
               fin="2026-10-16T09:01:00+00:00", output_verdict={"verdict": "produced"})]
    assert H.deterministic_verdict({"event_type": "RUN_SKIPPED_LOCK"}, fields={"run": SKIP}, runs=runs,
                                   now=T) is None


# ---- defect fix 2: a lock skip is covered only by verified work in the SAME mode and SAME semantic slot


@pytest.mark.parametrize("cover,why", [
    # a nearby DRY run (same slot time, seconds apart) never covers a live skip
    (_r("e:lane-x:dry_run:20261016T1215", "RUN_DONE", mode="dry_run", req="2026-10-16T12:15:01+00:00"),
     "dry_never_covers_live"),
    # a live run of a NEIGHBOURING slot (inside the old 10-minute window) does not cover this slot
    (_r("e:lane-x:live:20261016T1220", "RUN_DONE", req="2026-10-16T12:16:00+00:00",
        output_verdict={"verdict": "produced"}), "other_slot"),
    # a free-form run id has no semantic slot: nothing proves it did this slot's work
    (_r("n8n-wf-abc-99", "RUN_DONE", req="2026-10-16T12:15:01+00:00", output_verdict={"verdict": "produced"}),
     "no_semantic_slot"),
    # same slot and mode, RUN_DONE, but nothing verifies the live output (no output verdict, no signal advance)
    (_r(COVER, "RUN_DONE", req="2026-10-16T12:15:01+00:00"), "unverified_live"),
    # same slot and mode, but the output verdict failed
    (_r(COVER, "RUN_DONE", req="2026-10-16T12:15:01+00:00", output_verdict={"verdict": "empty_violation"}),
     "failed_output_verdict"),
    # another lane's run in the same slot
    (_r("e:lane-y:live:20261016T1215", "RUN_DONE", req="2026-10-16T12:15:01+00:00",
        output_verdict={"verdict": "produced"}), "other_lane"),
])
def test_lock_skip_is_not_covered_by_the_wrong_run(cover, why):
    runs = [cover, _r(SKIP, "RUN_SKIPPED_LOCK", req="2026-10-16T12:15:00+00:00", reason="flock_held")]
    assert H.deterministic_verdict({"event_type": "RUN_SKIPPED_LOCK"}, fields={"run": SKIP, "error": "flock_held"},
                                   runs=runs, now=T) is None, why


def test_dry_lock_skip_is_covered_by_a_dry_run_of_the_same_slot():
    skip = "d:lane-x:dry_run:20261016T1215"
    runs = [_r("e:lane-x:dry_run:20261016T1215", "RUN_DONE", mode="dry_run", req="2026-10-16T12:15:01+00:00"),
            _r(skip, "RUN_SKIPPED_LOCK", mode="dry_run", reason="flock_held")]
    v = H.deterministic_verdict({"event_type": "RUN_SKIPPED_LOCK"}, fields={"run": skip}, runs=runs, now=T)
    assert v["outcome"] == "covered"


def test_failure_followed_by_a_later_success_of_the_same_mode_self_recovers():
    runs = [_r("later", "RUN_DONE", mode="live", fin="2026-10-16T13:16:00+00:00",
               output_verdict={"verdict": "produced"}),
            _r("bad", "RUN_FAILED", mode="live", fin="2026-10-16T12:16:00+00:00")]
    v = H.deterministic_verdict({"event_type": "RUN_FAILED"}, fields={"run": "bad", "error": "mode=live exit=1"},
                                runs=runs, now=T)
    assert v["outcome"] == "self_recovered" and v["evidence"] == ["run:later"]
    # a later DRY run does not prove a live failure recovered
    runs[0]["mode"] = "dry_run"
    assert H.deterministic_verdict({"event_type": "RUN_FAILED"}, fields={"run": "bad", "error": "mode=live exit=1"},
                                   runs=runs, now=T) is None


# ---- defect fix 1: NO_OUTPUT stays open until the OUTPUT recovered by the lane's contract

NO_OUT = {"event_type": "NO_OUTPUT", "created_at": "2026-10-16T12:00:00+00:00"}
FRESH = {"verdict": "FRESH", "last_output_at": "2026-10-16T12:40:00+00:00", "basis": "cron:*/15 x2"}


def test_no_output_is_not_closed_by_a_later_live_run_done_alone():
    live = [_r("l1", "RUN_DONE", mode="live", fin="2026-10-16T12:30:00+00:00")]
    assert H.deterministic_verdict(NO_OUT, fields={}, runs=live, now=T) is None
    stale = {"verdict": "STALE", "last_output_at": "2026-10-15T12:00:00+00:00"}
    assert H.deterministic_verdict(NO_OUT, fields={}, runs=live, now=T, output_state=stale) is None


def test_no_output_is_not_closed_by_an_advancing_mtime_alone():
    sig = [_r("d2", "RUN_DONE", mode="dry_run", fin="2026-10-16T12:30:00+00:00",
              output_signal_mtime_before=1.0, output_signal_mtime_after=2.0),
           _r("l2", "RUN_DONE", mode="live", fin="2026-10-16T12:31:00+00:00",
              output_signal_mtime_before=1.0, output_signal_mtime_after=2.0)]
    assert H.deterministic_verdict(NO_OUT, fields={}, runs=sig, now=T) is None
    late = {"verdict": "LATE", "last_output_at": "2026-10-16T12:31:00+00:00"}       # advanced, but not fresh
    assert H.deterministic_verdict(NO_OUT, fields={}, runs=sig, now=T, output_state=late) is None


def test_no_output_is_not_closed_by_a_fresh_signal_that_predates_the_breach():
    old = {"verdict": "FRESH", "last_output_at": "2026-10-16T11:59:00+00:00"}
    assert H.deterministic_verdict(NO_OUT, fields={}, runs=[], now=T, output_state=old) is None


def test_no_output_closes_when_the_output_is_fresh_by_contract():
    v = H.deterministic_verdict(NO_OUT, fields={}, runs=[], now=T, output_state=FRESH)
    assert v["outcome"] == "output_recovered" and v["basis"] == "output_contract_fresh"
    assert v["heal_state"] == H.OUTPUT_RECOVERED


def test_no_output_closes_when_a_later_live_run_produced_its_expected_output():
    live = [_r("l3", "RUN_DONE", mode="live", fin="2026-10-16T12:30:00+00:00", output_verdict={"verdict": "produced"})]
    v = H.deterministic_verdict(NO_OUT, fields={}, runs=live, now=T)
    assert v["outcome"] == "output_recovered" and v["basis"] == "expected_output_produced"
    dry = [_r("d3", "RUN_DONE", mode="dry_run", fin="2026-10-16T12:30:00+00:00", output_verdict={"verdict": "produced"})]
    assert H.deterministic_verdict(NO_OUT, fields={}, runs=dry, now=T) is None


def test_failure_with_unknown_mode_is_not_closed_by_any_run():
    runs = [_r("later", "RUN_DONE", mode="dry_run", fin="2026-10-16T13:16:00+00:00")]
    assert H.deterministic_verdict({"event_type": "RUN_FAILED", "created_at": "2026-10-16T12:00:00+00:00"},
                                   fields={"error": "exit=1"}, runs=runs, now=T) is None


def test_executor_lost_goes_to_the_reaper():
    v = H.deterministic_verdict({"event_type": "RUN_TIMEOUT"}, fields={"error": "state=RUN_TIMEOUT reason=executor_lost"},
                                runs=[], now=T)
    assert v["kind"] == "reap" and v["action_id"] == "reap_orphan_run"


# ---------------------------------------------------------------- 4. live-heal gate (pure)


REG = {"lane_id": "lane-x", "state": "ACTIVE", "scheduler": {"kind": "cron", "stage": "canary"},
       "dispatch": {"class": "ingest", "priority": 5}}
SPEC = {"process": "lane-x", "input_version": "v1"}
ENTRY = {"severity": "Low"}


def _gate(lane="lane-x", **kw):
    args = {"registry_row": REG, "effect_spec": SPEC, "effect_owner": "n8n", "failure_class": H.TRANSIENT,
            "catalogue_entry": ENTRY, "cutover_policy": None, "live_heals_today": 0,
            "live_lanes": frozenset({lane})}
    args.update(kw)
    return H.live_heal_gate(lane, **args)


def test_live_heal_gate_allows_the_happy_path():
    assert _gate() == (True, "ok")
    assert _gate(registry_row={**REG, "scheduler": {"stage": "cutover"}})[0] is True


@pytest.mark.parametrize("kw,lane,reason", [
    ({"effect_owner": "cron"}, "lane-x", "effect_owner_not_n8n"),
    ({"effect_owner": None}, "lane-x", "effect_owner_not_n8n"),
    ({"registry_row": {**REG, "scheduler": {"stage": "shadow"}}}, "lane-x", "stage_not_canary_or_cutover"),
    ({"registry_row": {**REG, "dispatch": {"class": "notify"}}}, "lane-x", "sender_lane"),
    ({}, "morning-brief-send", "sender_lane"),
    ({}, "broker-stop-sync", "broker_order_stop_options_lane"),
    ({"registry_row": {**REG, "family": "F09"}}, "lane-x", "broker_order_stop_options_lane"),
    ({"registry_row": {**REG, "dispatch": {"class": "ingest", "priority": 0}}}, "lane-x", "p1_lane"),
    ({"cutover_policy": {"p1_lanes": ["lane-x"]}}, "lane-x", "p1_lane"),
    ({"catalogue_entry": {"severity": "High"}}, "lane-x", "severity_High"),
    ({"failure_class": H.CODE_ERROR}, "lane-x", "failure_not_transient"),
    ({"effect_spec": None}, "lane-x", "no_effect_key"),
    ({"live_heals_today": 1}, "lane-x", "live_heal_daily_cap"),
    ({"failure_class": H.AUTH}, "lane-x", "failure_not_transient:auth"),
    ({"live_lanes": None}, "lane-x", "live_list_unavailable"),
    ({"live_lanes": frozenset({"other"})}, "lane-x", "not_on_live_list"),
    ({"cutover_policy": {"holds": {"lane-x": "operator_hold"}}}, "lane-x", "cutover_policy_hold"),
    ({"cutover_policy": {"p1_last": ["lane-x"]}}, "lane-x", "p1_lane"),
    ({"cutover_policy": {"families": {"lane-x": "F09"}}}, "lane-x", "broker_order_stop_options_lane"),
    ({"cutover_policy": {"families": {"lane-x": "F07"}}}, "lane-x", "broker_order_stop_options_lane"),
])
def test_live_heal_gate_refusals(kw, lane, reason):
    ok, why = _gate(lane=lane, **kw)
    assert ok is False and why.startswith(reason)


# ---------------------------------------------------------------- 5. CLI


def _no_defer(pid):
    return type("Dec", (), {"defer": False, "reason": "DEFERRAL_DISABLED"})()


def _add_run(ledger, run_id, state, *, mode="dry_run", lane=LOW_LANE, at=NOW - timedelta(seconds=60), stderr=""):
    led = CoordinationLedger(ledger)
    store = LedgerRunStore(led)
    store.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="n8n:workflow:abc", caller_id="n8n-relay",
                  now=at.timestamp() - 20)
    store.claim_next(now=at.timestamp() - 10)
    store.finish(run_id, state=state, now=at.timestamp(),
                 receipt={"schema": "RunReceipt@v1", "exit_code": 0 if state == "RUN_DONE" else 1, "mode": mode,
                          "stderr_tail": stderr, "finished_at": at.isoformat()})
    led.close()


def test_duplicate_signature_is_diagnosed_once_and_attached(env):
    call = GovernedCall(_answer(action="suggest_only", conf=0.9, cites=["siem:8"]))   # newest row leads
    rows = [_siem_row(rid=7), _siem_row(rid=8)]          # same lane, same failure text -> one signature
    assert _run(env, ["--apply"], db=FakeDB(rows), call=call, store=FakeStore()) == 0
    rec = _receipt(env)
    assert len(call.seen) == 1
    outcomes = sorted(r["outcome"] for r in rec["results"])
    assert outcomes == ["attached", "diagnosed"]
    assert rec["counts"]["attached"] == 1 and rec["counts"]["signatures"] == 1
    # one collapsed escalation (P2 suggest_only -> digest), carrying both SIEM ids
    assert rec["escalations"] == [] and len(rec["digest"]) == 1
    assert rec["digest"][0]["siem_ids"] == [7, 8] and rec["digest"][0]["attached"] == 1
    assert rec["digest"][0]["route"] == "digest"
    # next cycle: both are CARRIED (cached diagnosis, no call) and stay open; the escalation is not suppressed
    call2 = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB(rows), call=call2, store=FakeStore()) == 0
    rec2 = _receipt(env)
    assert rec2["counts"]["carried"] == 2 and rec2["counts"]["model_called"] == 0
    assert rec2["digest"][0]["siem_ids"] == [7, 8]


def test_signature_cap_is_per_signature_not_per_lane(env):
    state_p = env["state"] / cli.STATE_REL
    state_p.parent.mkdir(parents=True, exist_ok=True)
    day = NOW.date().isoformat()
    other = H.signature(LOW_LANE, "RUN_FAILED", "a different failure")
    state_p.write_text(json.dumps({"days": {day: {"spend_usd": 0.0, "calls": 3, "lane_calls": {LOW_LANE: 3},
                                                   "lane_remediations": {}, "sig_calls": {other: 3},
                                                   "signatures": {}, "lane_live_heals": {}}}}))
    call = GovernedCall(_answer(action="suggest_only", conf=0.9))
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore()) == 0
    assert len(call.seen) == 1, "the lane's other signature spent its cap; this one still gets its diagnosis"


def test_later_success_auto_closes_without_a_model_call(env):
    _add_run(env["ledger"], "n8n-wf-abc-43", "RUN_DONE", mode="dry_run")
    call = GovernedCall(_answer(), raise_on_call=True)
    store = FakeStore()
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=store) == 0
    rec = _receipt(env)
    res = rec["results"][0]
    assert res["outcome"] == "auto_closed:self_recovered" and res["deterministic"]["evidence"] == ["run:n8n-wf-abc-43"]
    assert rec["escalations"] == [] and rec["digest"] == [] and store.requests == []
    assert rec["counts"]["auto_closed"] == 1 and rec["counts"]["model_called"] == 0
    assert rec["consecutive_blind"] == 0, "a cycle settled deterministically is not a blind diagnoser"
    recs = _records(env)
    assert recs[-1]["outcome"] == "auto_closed:self_recovered" and recs[-1]["deterministic"]["outcome"] == "self_recovered"


def _live_heal_env(env, tmp_path, monkeypatch, stage="canary"):
    allow = dict(selftest.PROPOSED_ALLOWLIST_ENTRY)
    reg_row = {"lane_id": LOW_LANE, "state": "ACTIVE", "scheduler": {"kind": "n8n", "expression": "dispatcher",
                                                                      "stage": stage}}
    entry = C.build_entry(LOW_LANE, [], allow=allow, registry_row=reg_row, critical_ids={})
    cat = tmp_path / "cat_live.json"
    cat.write_text(json.dumps({"schema": C.SCHEMA, "lanes": [entry]}))
    reg = tmp_path / "reg_live.json"
    reg.write_text(json.dumps({"lanes": [reg_row]}))
    fx = tmp_path / "effect_keys.json"
    fx.write_text(json.dumps({"lanes": {LOW_LANE: {"process": LOW_LANE, "input_version": "v1"}}}))
    monkeypatch.setattr(cli, "EFFECT_KEYS", fx)
    monkeypatch.setattr(cli, "_effect_owner_ro", lambda ledger, process: "n8n")
    monkeypatch.setenv(H.LIVE_LIST_ENV, LOW_LANE)          # the relay's live list (re-read before execution)
    return {**env, "catalogue": cat, "registry": reg}


PARENT = f"d:{LOW_LANE}:live:20261010T0155"


class ParentStore(FakeStore):
    """FakeStore that knows the failed live parent (host_run_request validates it before queueing)."""

    def get(self, run_id):
        if run_id == PARENT:
            return {"run_id": PARENT, "lane_id": LOW_LANE, "mode": "live", "state": "RUN_FAILED"}
        return None


def test_no_failed_live_slot_parent_means_no_live_heal(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    call, store = GovernedCall(_answer(action="suggest_only", conf=0.9)), ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=store, deferral=_no_defer) == 0
    res = _receipt(e)["results"][0]
    assert res["live_heal_gate"] == "no_failed_live_slot_parent" and store.requests == [] and len(call.seen) == 1


def test_transient_failure_of_an_n8n_canary_lane_is_live_healed_once(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    _add_run(e["ledger"], PARENT, "RUN_FAILED", mode="live", stderr="connection reset by peer")
    call, store = GovernedCall(_answer(), raise_on_call=True), ParentStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=store, deferral=_no_defer) == 0
    rec = _receipt(e)
    res = rec["results"][0]
    assert res["failure_class"] == H.TRANSIENT and res["live_heal_gate"] == "ok"
    assert res["decision"]["action_id"] == "rerun_live_once" and res["retry_parent_run_id"] == PARENT
    assert [(r["mode"], r["run_id"]) for r in store.requests] == [("live", f"rem-{res['incident_key']}-live")]
    assert store.requests[0]["requested_by"] == cli.REQUESTED_BY
    assert store.requests[0]["parent_run_id"] == PARENT     # slot-bound: the executor claims the parent's slot
    state = json.loads((e["state"] / cli.STATE_REL).read_text())
    assert state["days"][NOW.date().isoformat()]["lane_live_heals"] == {LOW_LANE: 1}
    assert rec["escalations"] == []
    # a second, different transient failure the same day: the 1/lane/day cap stops a second live heal
    call2 = GovernedCall(_answer(action="suggest_only", conf=0.9))
    store2 = FakeStore()
    row2 = _siem_row(rid=9, error="exit=1 tail=ReadTimeout read timed out")
    assert _run(e, ["--apply"], db=FakeDB([_siem_row(), row2]), call=call2, store=store2, deferral=_no_defer) == 0
    res2 = next(r for r in _receipt(e)["results"] if r["siem_id"] == 9)
    assert res2["live_heal_gate"] == "live_heal_daily_cap" and store2.requests == []


def test_code_error_is_never_live_healed_and_escalates_p1_once_with_what_was_tried(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch)
    row = _siem_row(error="exit=1 tail=psycopg2.InterfaceError: connection already closed")
    call, store = GovernedCall(_answer(action="suggest_only", conf=0.4)), FakeStore()
    assert _run(e, ["--apply"], db=FakeDB([row]), call=call, store=store, deferral=_no_defer) == 0
    rec = _receipt(e)
    res = rec["results"][0]
    assert res["failure_class"] == H.CODE_ERROR and res["live_heal_gate"].startswith("failure_not_transient")
    assert store.requests == [] and len(call.seen) == 1
    # low confidence -> P1, once per signature, saying what was tried
    assert len(rec["escalations"]) == 1 and rec["digest"] == []
    esc = rec["escalations"][0]
    assert esc["priority"] == "P1" and esc["route"] == "operator_once" and esc["key"] == f"{LOW_LANE}|{res['signature']}"
    assert "tried=" in esc["detail"] and "live_heal:no(failure_not_transient" in esc["tried"]


def test_shadow_lane_gets_no_live_heal(env, tmp_path, monkeypatch):
    e = _live_heal_env(env, tmp_path, monkeypatch, stage="shadow")
    call, store = GovernedCall(_answer(action="suggest_only", conf=0.9)), FakeStore()
    assert _run(e, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=store, deferral=_no_defer) == 0
    res = _receipt(e)["results"][0]
    assert "live_heal_gate" not in res          # the catalogue offers no rerun_live_once at shadow
    assert store.requests == [] and len(call.seen) == 1


def test_handler_refuses_live_at_shadow_even_for_rerun_live_once(tmp_path):
    reg = [{"lane_id": LOW_LANE, "state": "ACTIVE", "scheduler": {"kind": "n8n", "expression": "dispatcher",
                                                                   "stage": "shadow"}}]
    allow = {LOW_LANE: dict(selftest.PROPOSED_ALLOWLIST_ENTRY)}
    got = cli.handle_request_run(FakeStore(), lane=LOW_LANE, mode="live", run_id="rem-abcdefghijklmnop-live",
                                 allowlist=allow, now=NOW.timestamp(), registry_rows=reg,
                                 live_stages=C.LIVE_HEAL_STAGES)
    assert got["ok"] is False and "needs_stage_canary_or_cutover:shadow" in got["outcome"]
    phases, dropped = cli.rerun_phases({"action_id": "rerun_live_once", "mode_sequence": ["live"]}, LOW_LANE, reg)
    assert phases == ["dry_run"] and dropped == "stage=shadow"


def test_dry_run_still_writes_nothing_with_the_new_tier(env, capsys):
    _add_run(env["ledger"], "n8n-wf-abc-43", "RUN_DONE", mode="dry_run")
    assert _run(env, ["--dry-run"], db=FakeDB([_siem_row(rid=7), _siem_row(rid=8)])) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    # each occurrence is closed on its OWN evidence (lifecycle first), not by riding the lead
    assert out["counts"]["auto_closed"] == 2 and out["counts"]["attached"] == 0
    assert not (env["state"] / cli.STATE_REL).exists() and not (env["state"] / cli.RECEIPT_REL).exists()


# ---------------------------------------------------------------- 6. catalogue


def test_catalogue_offers_rerun_live_once_at_canary_and_validates_it():
    allow = dict(selftest.PROPOSED_ALLOWLIST_ENTRY)
    canary = {"lane_id": LOW_LANE, "state": "ACTIVE", "scheduler": {"kind": "cron", "stage": "canary"}}
    e = C.build_entry(LOW_LANE, [], allow=allow, registry_row=canary, critical_ids={})
    act = C.lane_action(e, "rerun_live_once")
    assert act and act["mode_sequence"] == ["live"] and act["max_per_lane_per_day"] == 1 and act["auto"] is True
    assert C.lane_action(e, "rerun_dry_then_live") is None           # dry-then-live stays cutover-only
    doc = {"schema": C.SCHEMA, "lanes": [e]}
    assert C.validate_catalogue(doc) == []
    bad = json.loads(json.dumps(doc))
    bad["lanes"][0]["registry"]["stage"] = "shadow"
    assert any("rerun_live_once needs registry stage canary or cutover" in x for x in C.validate_catalogue(bad))
    shadow = {**canary, "scheduler": {"kind": "cron", "stage": "shadow"}}
    assert C.lane_action(C.build_entry(LOW_LANE, [], allow=allow, registry_row=shadow, critical_ids={}),
                         "rerun_live_once") is None


def test_committed_catalogue_live_once_rows_are_canary_or_cutover():
    from pathlib import Path

    doc = json.loads((Path(__file__).resolve().parents[1] / "config" / "n8n_remediation_catalogue.json").read_text())
    assert C.validate_catalogue(doc) == []
    rows = [e for e in doc["lanes"] if C.lane_action(e, "rerun_live_once")]
    assert rows, "the regenerated catalogue offers rerun_live_once somewhere"
    assert all(e["registry"]["stage"] in ("canary", "cutover") for e in rows)
