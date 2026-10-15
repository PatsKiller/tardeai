"""Regression tests for the 2026-10-15 third-party n8n architecture audit (pinned at e355be188; gap register DD03-DD08,
DD14). Each test first reproduces the auditor's finding shape (the contracts-probes in the evidence packet:
cross_scope_replay, failed_effect_reclaim, malformed_expected_output) against the CURRENT code and asserts the fixed
behaviour.

  DD03  request identity: a replayed key never returns another lane/mode/workflow's row; live relay runs need a
        host-validated key namespace; every executor path refuses an unvalidated p: row; the relay refuses a gateway
        reply for another identity.
  DD04  one retry owner per namespace, typed retry block, durable dead letter on v1 and v2.
  DD05  FAILED is reclaimable only when proven pre-effect.
  DD06  late-write fence (assert_fence) and late completion -> UNKNOWN incident.
  DD07  output verdict bound to the attempt (immutable per-attempt LaneRunReceipt@v2); malformed rules fail.
  DD08  per-request / per-claim policy reload (gateway, relay, executor); unreadable replacement fails safe.
  DD14  relay ROUTES == handlers (GET /momentum-lifecycle); POST /run exact keys; duplicate JSON keys refused.

Hermetic: tmp_path ledgers and files, fake runners (no lane process, no network, no secret, no broker).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from scripts import n8n_coordination_gateway as SRV
from scripts import n8n_run_executor as X
from scripts import n8n_run_relay as R
from scripts.lib import effect_claim as E
from scripts.lib import lane_last_receipt as LR
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import n8n_output_verdict as OV
from scripts.lib import n8n_process_keys as PK
from scripts.lib.n8n_coordination_ledger import (
    CoordinationLedger,
    LedgerNonceStore,
    LedgerReceiptStore,
    LedgerRunStore,
)
from scripts.lib.n8n_policy_reload import PolicyFile
from scripts.lib.n8n_retry_policy import load_policies

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
NOW = datetime(2026, 10, 15, 10, 57, tzinfo=ET)  # inside the hermes-learning learn stage window (slot 10:50)
GRADER = "hermes-learning-outcome-grader"
SOURCES = PK.load_sources()
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def gw(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    ns = SimpleNamespace(
        ledger=ledger,
        nonces=LedgerNonceStore(ledger),
        receipts=LedgerReceiptStore(ledger),
        runs=LedgerRunStore(ledger),
        n=[0],
        path=tmp_path / "ledger.sqlite",
    )
    yield ns
    ledger.close()


def _live_sources() -> dict:
    src = copy.deepcopy(SOURCES)
    src["processes"]["hermes-learning"]["mode"] = "live"
    return src


def _req(
    gw,
    *,
    lane,
    mode,
    key,
    requested_by="n8n:workflow:tradeai-fabric-hermes-learning",
    caller="n8n-relay",
    allow=None,
    sources=None,
    now=NOW,
):
    gw.n[0] += 1
    claim = {
        "v": 1,
        "caller_id": caller,
        "project": "trade-ai",
        "iat": now.timestamp(),
        "exp": now.timestamp() + 120,
        "nonce": f"nonce-audit-{gw.n[0]:04d}",
        "scope": G.SCOPE_RUN,
    }
    req = {
        "claim": claim,
        "signature": hmac.new(N8N, G.canonical(claim), hashlib.sha256).hexdigest(),
        "route": "coordination/run",
        "operation": "run",
        "lane_id": lane,
        "mode": mode,
        "idempotency_key": key,
        "requested_by": requested_by,
    }
    return G.handle_request(
        req,
        key=KEY,
        now=now,
        nonce_store=gw.nonces,
        idempotency_store=gw.receipts,
        expected_origin_sha="a" * 40,
        caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
        run_store=gw.runs,
        run_allowlist=allow if allow is not None else frozenset(ALLOW),
        process_sources=sources if sources is not None else SOURCES,
    )


def _count(gw) -> int:
    return gw.ledger._conn.execute("SELECT count(*) AS n FROM runs").fetchone()["n"]


class Runner:
    def __init__(self, code: int = 0, effect=None) -> None:
        self.calls: list = []
        self.code, self.effect = code, effect

    def __call__(self, argv, *, timeout, env, cwd):
        self.calls.append({"argv": argv, "env": dict(env)})
        if self.effect is not None:
            self.effect(dict(env))
        return SimpleNamespace(returncode=self.code, stdout="ok", stderr="")


def _entry(tmp_path: Path, lane: str = "fixture-lane", **extra) -> dict:
    e = {
        "lane_id": lane,
        "command": ["$PY", "scripts/fake.py"],
        "lock": str(tmp_path / f"{lane}.lock"),
        "timeout_s": 5,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
        "env_allowlist_mode": "report",
    }
    e.update(extra)
    return e


# ── DD03 request identity ─────────────────────────────────────────────────────────────────────────────────────


def test_dd03_auditor_probe_cross_scope_replay_never_returns_another_lane(gw):
    """contracts-probes cross_scope_replay: lane-b/live with an existing p:lane-a:dry_run key returned lane-a's
    RUN_DONE row with duplicate=true. Now: refused, typed, and the original row is untouched."""
    key = f"p:{GRADER}:dry_run:20261015T1050"
    first = _req(gw, lane=GRADER, mode="dry_run", key=key)
    assert first["state"] == "REQUESTED"
    other_lane = "hermes-learning-tag-engine"
    out = _req(gw, lane=other_lane, mode="live", key=key)
    assert out["state"] == "REFUSED" and out["reason"] == "run_process_key_invalid"
    assert out["key_state"] in ("KEY_MISMATCH",) and "lane_id" not in out or out.get("lane_id") != GRADER
    same_lane_live = _req(gw, lane=GRADER, mode="live", key=key)
    assert same_lane_live["state"] == "REFUSED" and _count(gw) == 1


def test_dd03_same_p_key_from_another_workflow_is_a_conflict_not_a_duplicate(gw):
    key = f"p:{GRADER}:dry_run:20261015T1050"
    assert _req(gw, lane=GRADER, mode="dry_run", key=key)["duplicate"] is False
    again = _req(gw, lane=GRADER, mode="dry_run", key=key)
    assert again["state"] == "REQUESTED" and again["duplicate"] is True  # same identity: a true replay
    other = _req(gw, lane=GRADER, mode="dry_run", key=key, requested_by="n8n:workflow:someone-else")
    assert other["reason"] == "run_idempotency_conflict" and other["conflict_fields"] == ["requested_by"]


@pytest.mark.parametrize(
    "change,fields",
    [
        ({"lane_id": "maturity-remeasure"}, ["lane_id"]),
        ({"mode": "live", "caller": "host"}, ["mode"]),
        ({"requested_by": "n8n:workflow:other"}, ["requested_by"]),
    ],
)
def test_dd03_free_form_replay_with_another_identity_is_refused(gw, change, fields):
    key = "legacy-free-form-key-000001"
    base = {"lane": "n8n-lab-watchdog", "mode": "dry_run", "key": key, "requested_by": "n8n:workflow:wf-1"}
    assert _req(gw, **base)["state"] == "REQUESTED"
    req = dict(base)
    if "lane_id" in change:
        req["lane"] = change["lane_id"]
    if "mode" in change:
        req["mode"] = change["mode"]
        req["caller"] = "tradeai-host-x"  # a host-side caller (no namespace rule); the identity check still holds
    if "requested_by" in change:
        req["requested_by"] = change["requested_by"]
    if req.get("caller") == "tradeai-host-x":
        out = G.host_run_request(
            lane_id=req["lane"],
            mode=req["mode"],
            run_id=key,
            requested_by=req["requested_by"],
            caller_id="host",
            run_store=gw.runs,
            run_allowlist=frozenset(ALLOW),
            now=NOW.timestamp(),
        )
    else:
        out = _req(gw, **req)
    assert out["state"] == "REFUSED" and out["reason"] == "run_idempotency_conflict"
    assert out["conflict_fields"] == fields
    assert gw.runs.get(key)["lane_id"] == "n8n-lab-watchdog" and _count(gw) == 1


@pytest.mark.parametrize(
    "key", ["legacy-free-form-live-0001", "x:anything:live:20261015T1050", "wc:lane:20261015T1050:ab"]
)
def test_dd03_live_relay_request_needs_a_validated_namespace(gw, key):
    out = _req(gw, lane="maturity-remeasure", mode="live", key=key)
    assert out["reason"] == "run_key_namespace_refused" and out["key_state"] == "UNVALIDATED_NAMESPACE"
    assert _count(gw) == 0


@pytest.mark.parametrize(
    "key", ["P:hermes-learning-outcome-grader:live:20261015T1050", "D:maturity-remeasure:live:20261015T0640"]
)
def test_dd03_case_variants_cannot_pass_as_free_form(gw, key):
    lane = GRADER if key.lower().startswith("p:") else "maturity-remeasure"
    out = _req(gw, lane=lane, mode="live", key=key)
    assert out["state"] == "REFUSED" and _count(gw) == 0


def test_dd03_host_callers_cannot_submit_p_keys(gw):
    out = G.host_run_request(
        lane_id=GRADER,
        mode="dry_run",
        run_id=f"p:{GRADER}:dry_run:20261015T1050",
        requested_by="diag",
        caller_id="host",
        run_store=gw.runs,
        run_allowlist=frozenset(ALLOW),
        now=NOW.timestamp(),
    )
    assert out["reason"] == "run_process_key_invalid" and out["key_state"] == "HOST_CALLER_REFUSED"


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("mode", ["dry_run", "live"])
def test_dd03_every_executor_path_refuses_an_unvalidated_p_row(gw, tmp_path, v2, mode):
    """A p: row written by any path but the gateway (no validated slot_key) runs nothing, for an UNKEYED lane too:
    the audit's 'universally fail closed' gap (before, only effect-keyed lanes checked the marker)."""
    key = f"p:fixture-lane:{mode}:20261015T1050"
    gw.runs.request(
        run_id=key, lane_id="fixture-lane", mode=mode, requested_by="forged", caller_id="x", now=NOW.timestamp()
    )
    row = gw.runs.claim_next(now=NOW.timestamp() + 1)
    runner = Runner()
    receipt = X.execute(row, _entry(tmp_path), env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, v2=v2)
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "process_key_unvalidated"
    assert runner.calls == []


def test_dd03_retry_suffix_row_needs_its_own_validated_marker(gw, tmp_path):
    key = "p:fixture-lane:dry_run:20261015T1050:a2"
    gw.runs.request(
        run_id=key,
        lane_id="fixture-lane",
        mode="dry_run",
        requested_by="x",
        caller_id="x",
        now=NOW.timestamp(),
        slot_key="p:other-lane:dry_run:20261015T1050",
        attempt=2,
    )
    row = gw.runs.claim_next(now=NOW.timestamp() + 1)
    runner = Runner()
    receipt = X.execute(row, _entry(tmp_path), env={}, state_root=tmp_path, code_root=tmp_path, runner=runner)
    assert receipt["reason"] == "process_key_unvalidated" and runner.calls == []


def test_dd03_validated_p_row_runs_and_relay_rejects_a_foreign_reply(gw, tmp_path):
    key = f"p:{GRADER}:dry_run:20261015T1050"
    _req(gw, lane=GRADER, mode="dry_run", key=key)
    row = gw.runs.claim_next(now=NOW.timestamp() + 1)
    runner = Runner()
    receipt = X.execute(row, _entry(tmp_path, GRADER), env={}, state_root=tmp_path, code_root=tmp_path, runner=runner)
    assert receipt["state"] == "RUN_DONE" and len(runner.calls) == 1
    env = {
        "TRADEAI_N8N_RELAY_BEARER": "b" * 48,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 48,
        "TRADEAI_STATE_ROOT": str(tmp_path),
    }
    foreign = {
        "schema": "RunRequested@v1",
        "state": "RUN_DONE",
        "run_id": key,
        "lane_id": "lane-a",
        "mode": "dry_run",
        "duplicate": True,
    }
    relay = R.Relay(environ=env, allowlist=frozenset({GRADER}), transport=lambda *_: (200, foreign))
    body = json.dumps({"lane_id": GRADER, "mode": "dry_run", "idempotency_key": key}).encode()
    status, out = relay.run("Bearer " + "b" * 48, body)
    assert status == 502 and out["reason"] == "relay_identity_mismatch"


# ── DD04 retry ownership ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key,owner",
    [
        ("p:x-lane:live:20261015T1050:a2", "run_lane"),
        ("d:x:live:20261015T1050", "host_policy"),
        ("E:x:live:20261015T1050", "host_policy"),
        ("legacy-key-0000000001", "executor_inline"),
    ],
)
def test_dd04_one_retry_owner_per_namespace(key, owner):
    assert X.retry_owner(key) == owner
    assert X.retry_owner({"run_id": "free-form-0000001", "slot_key": key}) == owner


def test_dd04_host_never_reruns_a_run_lane_or_dispatcher_row_inline(gw, tmp_path):
    entry = _entry(tmp_path, retry={"max": 2, "backoff_s": 0, "on": ["RUN_FAILED"]})
    for key, slot, attempts in (
        ("d:fixture-lane:dry_run:20261015T1050", "d:fixture-lane:dry_run:20261015T1050", 1),
        ("free-form-run-key-000001", None, 3),
    ):
        gw.runs.request(
            run_id=key,
            lane_id="fixture-lane",
            mode="dry_run",
            requested_by="x",
            caller_id="x",
            now=NOW.timestamp(),
            slot_key=slot,
        )
        row = gw.runs.claim_next(now=NOW.timestamp() + 1)
        runner = Runner(code=1)
        receipt = X.execute(
            row, entry, env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, sleeper=lambda _s: None
        )
        assert len(runner.calls) == attempts and receipt["attempts"] == attempts
        assert receipt["retry_owner"] == X.retry_owner(row)
        if attempts == 1:
            assert receipt["allowlist_retry"] == "ignored_owner:host_policy"


def test_dd04_v1_drain_writes_the_typed_retry_block_and_a_durable_dead_letter(gw, tmp_path):
    policies = load_policies(ROOT / "config" / "n8n_retry_policies.json")
    key = "d:fixture-lane:dry_run:20261015T1050"
    gw.runs.request(
        run_id=key,
        lane_id="fixture-lane",
        mode="dry_run",
        requested_by="x",
        caller_id="x",
        now=NOW.timestamp(),
        slot_key=key,
        attempt=1,
    )
    X.drain(
        gw.runs,
        {"fixture-lane": _entry(tmp_path)},
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=Runner(code=1),
        policies=policies,
        registry_rows=[],
    )
    row = gw.runs.get(key)
    retry = row["receipt"]["retry"]
    assert row["verdict"] == "terminal"  # unresolved policy (no registry row): single attempt, terminal
    assert retry["owner"] == "host_policy" and retry["retryable"] is False and retry["attempts_remaining"] == 0
    assert retry["dlq_ref"] == key and retry["terminal_reason"] == "exit_1"
    dead = gw.runs.get_dead_letter(key)
    assert dead is not None and dead["last_run_id"] == key
    assert gw.runs.breaker("fixture-lane") is None  # v1 never pauses a lane


def test_dd04_p_retry_is_admitted_only_after_a_retryable_predecessor(gw):
    src = copy.deepcopy(SOURCES)
    src["processes"]["hermes-learning"]["steps"]["outcome_grader"]["max_attempts"] = 3
    base = f"p:{GRADER}:dry_run:20261015T1050"
    a2 = base + ":a2"
    out = _req(gw, lane=GRADER, mode="dry_run", key=a2, sources=src)
    assert out["key_state"] == "ATTEMPT_NOT_RETRYABLE" and out["previous_verdict"] is None
    _req(gw, lane=GRADER, mode="dry_run", key=base, sources=src)
    gw.runs.claim_next(now=NOW.timestamp())
    gw.runs.finish(base, state="RUN_FAILED", receipt={"exit_code": 1})
    gw.runs.set_verdict(base, "terminal")
    assert _req(gw, lane=GRADER, mode="dry_run", key=a2, sources=src)["key_state"] == "ATTEMPT_NOT_RETRYABLE"
    gw.runs.set_verdict(base, "retryable")
    assert _req(gw, lane=GRADER, mode="dry_run", key=a2, sources=src)["state"] == "REQUESTED"


def test_dd04_send_and_learn_stay_single_attempt_whoever_owns_the_retry(tmp_path):
    policies = load_policies(ROOT / "config" / "n8n_retry_policies.json")
    row = {"run_id": f"p:{GRADER}:live:20261015T1050", "lane_id": GRADER, "attempt": 1}
    c = X.retry_contract(
        row,
        {"state": "RUN_FAILED", "reason": "exit_1"},
        "retryable",
        policy=policies.get(None),
        klass="learn",
        code_root=ROOT,
    )
    assert c["max_attempts"] == 1 and c["retryable"] is False and c["dlq_ref"] == row["run_id"]


# ── DD05 effect proof ─────────────────────────────────────────────────────────────────────────────────────────


def _fx(gw, process="audit-process", owner="n8n"):
    fx = E.EffectClaimStore(gw.ledger)
    fx.set_owner(process, owner, expect_epoch=None, by="t", now=100)
    return fx


def test_dd05_auditor_probe_failed_after_possible_effect_is_held(gw):
    """contracts-probes failed_effect_reclaim: CLAIMED -> FAILED ('effect committed then exit75') -> a second claim
    succeeded (attempt 2). Now it is refused until an operator release."""
    fx = _fx(gw)
    key = E.effect_key("audit-process", "20261015T0700", "v1")
    assert fx.claim(key, scheduler="n8n", now=101, run_id="attempt1").ok
    fx.finish(key, state=E.STATE_FAILED, now=102, run_id="attempt1", detail="effect committed then exit75")
    second = fx.claim(key, scheduler="n8n", now=103, run_id="attempt2")
    assert second.ok is False and second.reason == "effect_already_claimed"
    assert fx.release(key, by="op", now=104, note="target reconciled: no row")["state"] == E.STATE_RELEASED
    assert fx.claim(key, scheduler="n8n", now=105, run_id="attempt2").ok


def test_dd05_only_a_proven_pre_effect_failure_is_reclaimable(gw):
    fx = _fx(gw)
    key = E.effect_key("audit-process", "20261015T0700", "v1")
    fx.claim(key, scheduler="n8n", now=101, run_id="r1")
    fx.finish(key, state=E.STATE_FAILED, now=102, run_id="r1", pre_effect=True)
    assert fx.claim(key, scheduler="n8n", now=103, run_id="r2").ok


def _live_d_row(gw, lane, slot="20261015T1050", run_id=None):
    key = run_id or f"d:{lane}:live:{slot}"
    gw.runs.request(
        run_id=key,
        lane_id=lane,
        mode="live",
        requested_by="x",
        caller_id="x",
        now=150,
        slot_key=f"d:{lane}:live:{slot}",
    )
    return gw.runs.claim_next(now=151)


@pytest.mark.parametrize(
    "runner_kw,fenced,final,reclaimable",
    [
        ({"code": 3}, False, "FAILED", False),  # commit-before-nonzero: unproven -> held
        ({"code": 0}, False, "DONE", False),  # committed
        ({"code": 124}, False, "UNKNOWN", False),  # timeout
        ({"code": 3}, True, "FAILED", True),  # fenced lane exited before the fence: proven pre-effect
    ],
)
def test_dd05_executor_finish_states(gw, tmp_path, runner_kw, fenced, final, reclaimable):
    fx = _fx(gw, "fixture-lane")
    gate = X.EffectGate(
        fx,
        {"fixture-lane": {"process": "fixture-lane", "input_version": "v1"}},
        clock=lambda: 200.0,
        fenced=frozenset({"fixture-lane"}) if fenced else None,
        ledger_path=gw.path,
    )
    row = _live_d_row(gw, "fixture-lane")
    receipt = X.execute(
        row, _entry(tmp_path), env={}, state_root=tmp_path, code_root=tmp_path, runner=Runner(**runner_kw), effects=gate
    )
    key = receipt["effect"]["key"]
    assert fx.get(key)["state"] == final and receipt["effect"]["final_state"] == final
    assert bool(fx.get(key)["pre_effect"]) is reclaimable
    assert receipt["effect"]["held_for_reconciliation"] is (final in ("FAILED", "UNKNOWN") and not reclaimable)


def test_dd05_spawn_failure_is_proven_pre_effect(gw, tmp_path):
    fx = _fx(gw, "fixture-lane")
    gate = X.EffectGate(fx, {"fixture-lane": {"process": "fixture-lane", "input_version": "v1"}}, clock=lambda: 200.0)

    def boom(*_a, **_k):
        raise OSError(12, "no memory")

    receipt = X.execute(
        _live_d_row(gw, "fixture-lane"),
        _entry(tmp_path),
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=boom,
        effects=gate,
    )
    assert receipt["effect"]["pre_effect_proof"] == "spawn_failed"
    assert fx.get(receipt["effect"]["key"])["pre_effect"] == 1


def test_dd05_kill_before_finish_stays_claimed_and_sequential_cron_then_n8n_has_one_effect(gw, tmp_path):
    fx = _fx(gw, "fixture-lane", owner="cron")
    key = E.effect_key("fixture-lane", "20261015T1050", "v1")
    effects: list[str] = []
    # cron claims and is killed before finish (no finish call): the key stays CLAIMED
    assert fx.claim(key, scheduler="cron", now=130, run_id="cron-1").ok
    effects.append("cron")
    fx.set_owner("fixture-lane", "n8n", expect_epoch=1, by="op", now=140)  # n8n row is admitted at 150, after it
    gate = X.EffectGate(fx, {"fixture-lane": {"process": "fixture-lane", "input_version": "v1"}}, clock=lambda: 200.0)
    runner = Runner(effect=lambda _env: effects.append("n8n"))
    receipt = X.execute(
        _live_d_row(gw, "fixture-lane"),
        _entry(tmp_path),
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=runner,
        effects=gate,
    )
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "effect:effect_already_claimed"
    assert effects == ["cron"]  # one logical target effect, counted at the target


# ── DD06 late writes ──────────────────────────────────────────────────────────────────────────────────────────


def test_dd06_fence_token_reaches_the_lane_and_a_live_claim_passes(gw, tmp_path):
    fx = _fx(gw, "fixture-lane")
    gate = X.EffectGate(
        fx,
        {"fixture-lane": {"process": "fixture-lane", "input_version": "v1"}},
        clock=lambda: 200.0,
        ledger_path=gw.path,
        fenced=frozenset({"fixture-lane"}),
    )
    written: list[str] = []

    def lane(env):
        E.assert_fence(env[E.FENCE_ENV], ledger=env[E.FENCE_LEDGER_ENV])
        written.append("row")

    receipt = X.execute(
        _live_d_row(gw, "fixture-lane"),
        _entry(tmp_path),
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=Runner(effect=lane),
        effects=gate,
    )
    assert written == ["row"] and receipt["effect"]["final_state"] == "DONE"
    assert fx.get(receipt["effect"]["key"])["fence_passed_at"] is not None


@pytest.mark.parametrize("interrupt", ["release", "owner_switch"])
def test_dd06_paused_stale_worker_cannot_write_after_release_or_owner_switch(gw, tmp_path, interrupt):
    fx = _fx(gw, "fixture-lane")
    gate = X.EffectGate(
        fx,
        {"fixture-lane": {"process": "fixture-lane", "input_version": "v1"}},
        clock=lambda: 200.0,
        ledger_path=gw.path,
        fenced=frozenset({"fixture-lane"}),
    )
    written: list[str] = []
    refused: list[str] = []

    def paused_lane(env):
        key = env[E.FENCE_ENV].rsplit(":", 2)[0]
        # the worker is paused; meanwhile the operator acts
        if interrupt == "release":
            fx.release(key, by="op", now=300, note="stuck run released")
        else:
            fx.set_owner("fixture-lane", "cron", expect_epoch=1, by="op", now=300)
        try:
            E.assert_fence(env[E.FENCE_ENV], ledger=env[E.FENCE_LEDGER_ENV])
            written.append("row")
        except E.EffectFenceError as exc:
            refused.append(exc.reason)

    receipt = X.execute(
        _live_d_row(gw, "fixture-lane"),
        _entry(tmp_path),
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=Runner(code=1, effect=paused_lane),
        effects=gate,
    )
    assert written == [] and refused == (["fence_claim_not_held"] if interrupt == "release" else ["fence_epoch_moved"])
    if interrupt == "owner_switch":
        # the late finish is an actionable incident, never a silent DONE/FAILED
        assert receipt["effect"]["incident"] == "effect_late_completion"
        assert fx.get(receipt["effect"]["key"])["state"] == "UNKNOWN"


def test_dd06_late_done_becomes_unknown_incident(gw):
    fx = _fx(gw)
    key = E.effect_key("audit-process", "20261015T0700", "v1")
    fx.claim(key, scheduler="n8n", now=101, run_id="r1")
    fx.set_owner("audit-process", "cron", expect_epoch=1, by="op", now=102)
    row = fx.finish(key, state=E.STATE_DONE, now=103, run_id="r1")
    assert row["state"] == "UNKNOWN" and row["fenced_late"] == 1 and row["late_completion"] is True
    assert row["detail"].startswith("late_completion:DONE")


def test_dd06_fence_refuses_without_a_token_or_after_a_reclaim(gw):
    with pytest.raises(E.EffectFenceError, match="fence_missing"):
        E.assert_fence("", ledger=gw.path)
    fx = _fx(gw)
    key = E.effect_key("audit-process", "20261015T0700", "v1")
    first = fx.claim(key, scheduler="n8n", now=101, run_id="r1")
    token = E.fence_token(key, first.epoch, first.attempt)
    fx.release(key, by="op", now=102, note="x")
    fx.claim(key, scheduler="n8n", now=103, run_id="r2")
    with pytest.raises(E.EffectFenceError) as exc:
        E.assert_fence(token, ledger=gw.path)
    assert exc.value.reason == "fence_attempt_moved"


def test_dd06_declared_fenced_lanes_call_assert_fence_and_unfenced_keyed_lanes_are_listed():
    """Only a lane that calls assert_fence() is late-write safe. A late_write_fenced declaration must be true of the
    lane's source; every other keyed lane is listed (docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §7)."""
    cfg = ROOT / "config" / "n8n_effect_keys.json"
    fenced = E.load_fenced_lanes(cfg)
    for lane in fenced:
        scripts = [t for t in ALLOW[lane]["command"] if t.endswith(".py")]
        assert any("assert_fence" in (ROOT / s).read_text() for s in scripts), lane
    keyed = set(E.load_effect_lanes(cfg))
    unfenced = sorted(keyed - fenced)
    doc = (ROOT / "docs" / "architecture" / "n8n" / "N8N_CONTRACTS_DESIGN.md").read_text()
    assert f"{len(unfenced)} effect-keyed lanes" in doc
    for lane in E.load_effect_config(cfg):  # the six n8n-armed keys are named one by one
        assert f"`{lane}`" in doc, lane


# ── DD07 output truth ─────────────────────────────────────────────────────────────────────────────────────────

RULE = {
    "schema": "N8nExpectedOutput@v1",
    "unit": "items",
    "rule": "min_produced",
    "min_produced": 1,
    "produced_field": "produced_count",
    "fatal_skip_reasons": ["no_runner"],
    "empty_allowed_reasons": [],
    "evidence": [{"kind": "store_rows", "ref": "items rows created_at >= started_at"}],
}


def _lane_writes(tmp_path, *, produced, skipped=None, run_id_override=None, v2=True):
    def lane(env):
        import os

        saved = dict(os.environ)
        os.environ.update({k: v for k, v in env.items() if k.startswith("TRADEAI_RUN") or k == LR.CODE_SHA_ENV})
        if run_id_override is not None:
            os.environ[LR.RUN_ID_ENV] = run_id_override
        try:
            kw = {"produced_count": produced, "skipped_reasons": skipped or {}} if v2 else {}
            LR.write_lane_receipt(
                "fixture-lane", ok=True, exit_code=0, path=tmp_path / "data/runtime/fixture-lane_last.json", **kw
            )
        finally:
            os.environ.clear()
            os.environ.update(saved)

    return lane


def _exec_live(gw, tmp_path, lane, rules):
    row = _live_d_row(gw, "fixture-lane")
    return X.execute(
        row,
        _entry(tmp_path),
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=Runner(effect=lane),
        outputs=rules,
    )


def test_dd07_no_rule_is_unchanged(gw, tmp_path):
    receipt = _exec_live(gw, tmp_path, None, {})
    assert receipt["state"] == "RUN_DONE" and receipt["output_verdict"] == {"verdict": "no_rule"}


def test_dd07_produced_on_this_attempts_receipt(gw, tmp_path):
    receipt = _exec_live(gw, tmp_path, _lane_writes(tmp_path, produced=3), {"fixture-lane": RULE})
    assert receipt["state"] == "RUN_DONE" and receipt["output_verdict"]["verdict"] == "produced"
    att = LR.attempt_receipt_path("fixture-lane", receipt["run_id"], tmp_path)
    doc = json.loads(att.read_text())
    assert doc["schema"] == "LaneRunReceipt@v2" and doc["run_id"] == receipt["run_id"] and doc["exit"] == 0


def test_dd07_worker_pool_no_runner_case_fails(gw, tmp_path):
    receipt = _exec_live(
        gw, tmp_path, _lane_writes(tmp_path, produced=0, skipped={"no_runner": 12}), {"fixture-lane": RULE}
    )
    assert receipt["state"] == "RUN_FAILED" and receipt["reason"] == "empty_output"
    assert receipt["output_verdict"]["why"] == "fatal_skip"


@pytest.mark.parametrize(
    "lane_kw,why",
    [
        ({"produced": 5, "run_id_override": "an-earlier-run-0000001"}, "attempt_receipt_missing"),  # stale/wrong run
        ({"produced": 5, "v2": False}, "attempt_receipt_missing"),  # v1 receipt: no attempt file
    ],
)
def test_dd07_stale_or_v1_or_missing_evidence_is_unverifiable(gw, tmp_path, lane_kw, why):
    receipt = _exec_live(gw, tmp_path, _lane_writes(tmp_path, **lane_kw), {"fixture-lane": RULE})
    assert receipt["state"] == "RUN_FAILED" and receipt["reason"] == "output_unverifiable"
    assert receipt["output_verdict"]["why"] == why


def test_dd07_forged_attempt_receipt_for_another_lane_is_unverifiable():
    doc = {"schema": "LaneRunReceipt@v2", "run_id": "r1", "lane_id": "other", "status": "ok", "produced_count": 9}
    out = OV.evaluate(RULE, doc, run_id="r1", lane_id="fixture-lane", mode="live")
    assert out["verdict"] == "unverifiable" and out["why"] == "receipt_identity_mismatch"
    doc2 = dict(doc, lane_id="fixture-lane", attempted_count=2)
    assert OV.evaluate(RULE, doc2, run_id="r1", lane_id="fixture-lane", mode="live")["why"] == "counts_inconsistent"


def test_dd07_legitimate_noop_is_distinct_from_no_runner():
    rule = dict(RULE, rule="empty_allowed", empty_allowed_reasons=["no_new_items"])
    ok = {
        "schema": "LaneRunReceipt@v2",
        "run_id": "r",
        "lane_id": "l",
        "status": "ok",
        "produced_count": 0,
        "attempted_count": 0,
        "skipped_reasons": {},
        "empty_reason": "no_new_items",
    }
    assert OV.evaluate(rule, ok, run_id="r", lane_id="l", mode="live")["verdict"] == "empty_allowed"
    bad = dict(ok, skipped_reasons={"no_runner": 4}, attempted_count=4)
    assert OV.evaluate(rule, bad, run_id="r", lane_id="l", mode="live")["verdict"] == "empty_violation"


def test_dd07_attempt_receipt_is_immutable(tmp_path, monkeypatch):
    monkeypatch.setenv(LR.RUN_ID_ENV, "d:x:live:20261015T1050")
    last = tmp_path / "data/runtime/x_last.json"
    LR.write_lane_receipt("x", ok=True, exit_code=0, path=last, produced_count=1)
    LR.write_lane_receipt("x", ok=True, exit_code=0, path=last, produced_count=99)
    att = json.loads(LR.attempt_receipt_path("x", "d:x:live:20261015T1050", tmp_path).read_text())
    assert att["produced_count"] == 1 and json.loads(last.read_text())["produced_count"] == 99


def test_dd07_auditor_probe_malformed_rule_fails_the_checker_and_the_run():
    """contracts-probes malformed_expected_output: numeric produced_field/unit and evidence=[{}] passed FW-M6."""
    import check_n8n_workflow_framework as F  # scripts/ on sys.path via conftest

    bad = {
        "schema": "N8nExpectedOutput@v1",
        "rule": "empty_allowed",
        "produced_field": 42,
        "unit": 42,
        "fatal_skip_reasons": [],
        "evidence": [{}],
    }
    assert F._check_expected_output({"id": "proof", "expected_output": bad})["status"] == "fail"
    assert OV.evaluate(bad, {}, run_id="r", lane_id="l", mode="live")["why"] == "rule_invalid"
    assert OV.evaluate(RULE, None, run_id="r", lane_id="l", mode="dry_run")["verdict"] == "dry_run_exempt"


# ── DD08 revocation ───────────────────────────────────────────────────────────────────────────────────────────


def _allowlist_file(path: Path, lanes: list[str]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "N8nRunAllowlist@v1",
                "lanes": [
                    {
                        "lane_id": lane,
                        "command": ["$PY", "x.py"],
                        "lock": f"/tmp/{lane}.lock",
                        "timeout_s": 5,
                        "dry_run_arg": [],
                        "live_arg": None,
                    }
                    for lane in lanes
                ],
            }
        )
    )
    return path


def test_dd08_gateway_revocation_applies_on_the_next_request(gw, tmp_path):
    f = _allowlist_file(tmp_path / "allow.json", ["n8n-lab-watchdog"])
    src = SRV.run_allowlist_source(f)
    req = dict(lane="n8n-lab-watchdog", mode="dry_run", requested_by="n8n:workflow:w")
    assert _req(gw, key="revoke-test-key-00001", allow=src, **req)["state"] == "REQUESTED"
    _allowlist_file(f, ["other-lane"])
    out = _req(gw, key="revoke-test-key-00002", allow=src, **req)
    assert out["reason"] == "run_lane_not_allowlisted"
    f.write_text("{not json")
    assert _req(gw, key="revoke-test-key-00003", allow=src, **req)["reason"] == "run_lane_not_allowlisted"
    assert src.error == "policy_unreadable"


def test_dd08_relay_revocation_applies_on_the_next_request(tmp_path):
    f = _allowlist_file(tmp_path / "allow.json", ["n8n-lab-watchdog"])
    env = {
        "TRADEAI_N8N_RELAY_BEARER": "b" * 48,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 48,
        "TRADEAI_STATE_ROOT": str(tmp_path),
    }
    relay = R.Relay(
        environ=env, allowlist=SRV.run_allowlist_source(f), transport=lambda *_: (200, {"state": "REQUESTED"})
    )
    body = json.dumps({"lane_id": "n8n-lab-watchdog", "mode": "dry_run", "idempotency_key": "relay-revoke-000001"})
    assert relay.run("Bearer " + "b" * 48, body.encode())[0] == 200
    _allowlist_file(f, [])
    assert relay.run("Bearer " + "b" * 48, body.encode())[1]["reason"] == "relay_lane_not_allowlisted"


def test_dd08_executor_refuses_a_queued_or_claimed_run_revoked_before_spawn(gw, tmp_path):
    f = tmp_path / "allow.json"
    f.write_text(json.dumps({"schema": "N8nRunAllowlist@v1", "lanes": [_entry(tmp_path)]}))
    src = X.allowlist_source(f)
    for key in ("revoked-queued-run-0001", "revoked-queued-run-0002"):
        gw.runs.request(
            run_id=key, lane_id="fixture-lane", mode="dry_run", requested_by="x", caller_id="x", now=NOW.timestamp()
        )
    assert src()  # the executor loaded it before the loop
    f.write_text(json.dumps({"schema": "N8nRunAllowlist@v1", "lanes": []}))  # operator revokes the lane
    runner = Runner()
    out = X.drain(gw.runs, src, env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, max_runs=1)
    assert out[0]["reason"] == "lane_not_allowlisted" and runner.calls == []
    assert out[0]["policy"]["allowlist_version"] == src.version
    f.write_text("{broken")  # an unreadable replacement fails safe, it does not serve the cached allowlist
    out = X.drain(gw.runs, src, env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, max_runs=1)
    assert out[0]["reason"] == "allowlist_unreadable" and runner.calls == []


def test_dd08_effect_config_is_reloaded_per_run(gw, tmp_path):
    cfg = tmp_path / "keys.json"
    cfg.write_text(json.dumps({"schema": "N8nEffectKeys@v1", "lanes": {}}))
    gate = X.EffectGate(E.EffectClaimStore(gw.ledger), {}, config_path=cfg, clock=lambda: 200.0)
    row = _live_d_row(gw, "fixture-lane")
    assert gate.begin(row, "fixture-lane", "live") == (None, None)
    cfg.write_text(
        json.dumps(
            {
                "schema": "N8nEffectKeys@v1",
                "lanes": {"fixture-lane": {"process": "fixture-lane", "input_version": "v1"}},
            }
        )
    )
    block, refusal = gate.begin(row, "fixture-lane", "live")
    assert refusal == "effect:effect_no_owner"  # now keyed: fail closed until an owner row exists
    cfg.write_text("{bad")
    assert gate.begin(row, "fixture-lane", "live")[1] == "effect:effect_config_unreadable"


def test_dd08_policy_file_reads_once_per_change(tmp_path):
    f = tmp_path / "p.json"
    f.write_text("1")
    pf = PolicyFile(f, lambda raw: int(raw), fail_value=-1)
    assert pf() == 1 and pf() == 1 and pf.loads == 1
    f.write_text("22")
    assert pf() == 22 and pf.loads == 2 and pf.version is not None
    f.unlink()
    assert pf() == -1 and pf.error == "policy_unreadable"


# ── DD14 relay route table and body strictness ────────────────────────────────────────────────────────────────


def test_dd14_one_route_definition_and_eight_handlers():
    assert len(R.ROUTES) == 8 and ("GET", "/momentum-lifecycle") in R.ROUTES
    assert set(R.ROUTE_HANDLERS) == set(R.ROUTES)
    for name in R.ROUTE_HANDLERS.values():
        assert callable(getattr(R.Relay, name)), name
    src = (ROOT / "scripts" / "n8n_run_relay.py").read_text()
    handler = src[src.index("def handler_for(") :]
    assert not re.search(
        r'self\.path == "/|path == "/',
        handler.split("def _serve", 1)[1].split("def do_GET")[0].replace('("GET", "/status")', ""),
    ), "dispatch must go through ROUTE_HANDLERS only"


@pytest.mark.parametrize(
    "body,reason",
    [
        (
            '{"lane_id": "n8n-lab-watchdog", "mode": "dry_run", "idempotency_key": "extra-key-000000001", "x": 1}',
            "relay_unexpected_field",
        ),
        (
            '{"lane_id": "n8n-lab-watchdog", "mode": "live", "mode": "dry_run", "idempotency_key": "dup-key-0000000001"}',
            "relay_unexpected_field",
        ),
        (
            '{"lane_id": "n8n-lab-watchdog", "lane_id": "other", "idempotency_key": "dup-key-0000000002"}',
            "relay_unexpected_field",
        ),
    ],
)
def test_dd14_run_body_is_exact_and_duplicate_keys_are_refused(tmp_path, body, reason):
    env = {
        "TRADEAI_N8N_RELAY_BEARER": "b" * 48,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 48,
        "TRADEAI_STATE_ROOT": str(tmp_path),
    }
    calls: list = []
    relay = R.Relay(
        environ=env,
        allowlist=frozenset({"n8n-lab-watchdog"}),
        transport=lambda *_: calls.append(1) or (200, {"state": "REQUESTED"}),
    )
    status, out = relay.run("Bearer " + "b" * 48, body.encode())
    assert status == 400 and out["reason"] == reason and calls == []


def test_dd14_event_and_intent_refuse_duplicate_keys(tmp_path):
    env = {
        "TRADEAI_N8N_RELAY_BEARER": "b" * 48,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 48,
        "TRADEAI_STATE_ROOT": str(tmp_path),
    }
    relay = R.Relay(environ=env, allowlist=frozenset(), transport=lambda *_: (200, {}))
    dup = b'{"domain": "fabric", "domain": "x"}'
    assert relay.intent("Bearer " + "b" * 48, dup)[1]["reason"] == "relay_malformed_body"
    assert relay.event("Bearer " + "b" * 48, b'{"lane_id": "a", "lane_id": "b"}')[1]["reason"] == "relay_malformed_body"


# ── docs stay honest ──────────────────────────────────────────────────────────────────────────────────────────


def test_docs_no_longer_claim_startup_cached_policy_or_universal_p_refusal():
    ref = (ROOT / "docs" / "architecture" / "n8n" / "N8N_REFERENCE_ARCHITECTURE.md").read_text()
    con = (ROOT / "docs" / "architecture" / "n8n" / "N8N_CONTRACTS_DESIGN.md").read_text()
    assert "gateway accepts as a caller key; executor refuses a LIVE `p:` run" not in con
    assert "repeated `idempotency_key` returns the original row (no second run)" not in con
    assert "run_idempotency_conflict" in con and "run_idempotency_conflict" in ref
    assert "`exit`" in con  # the lane receipt field is exit, not exit_code


def test_now_fixture_is_inside_the_learn_window():
    assert NOW - timedelta(minutes=7) == datetime(2026, 10, 15, 10, 50, tzinfo=ET)
    assert NOW.tzinfo is not None and NOW.astimezone(timezone.utc).hour == 14


# ── live-safety: replay the exact POST /run body every ACTIVE workflow sends (#1767 follow-up) ──────────────────

ACTIVE = json.loads((ROOT / "docs/implementation/n8n-maturity/data/n8n_active_workflows_20261015.json").read_text())
#: TRADEAI_N8N_RELAY_LIVE_LANES as documented live today (docs/implementation/n8n-maturity/N8N_CONFIGURATION.md).
RELAY_LIVE = (
    "n8n-pilot-dispatch n8n-incident-fanin n8n-research-intake-consumer crontab-snapshot-for-health-agent "
    "maturity-remeasure"
)
#: The $json each templated body is evaluated against (what the upstream node hands it at run time).
DUE_ITEM = {
    "lane_id": "maturity-remeasure",
    "mode": "live",
    "idempotency_key": "d:maturity-remeasure:live:20261015T0640",
}
RUN_LANE_ITEM = {"lane_id": GRADER, "mode": "dry_run", "idempotency_key": f"p:{GRADER}:dry_run:20261015T1050"}
#: Refusal reasons introduced by #1767; none of them may hit a currently active workflow.
NEW_REASONS = {
    "run_key_namespace_refused",
    "relay_unexpected_field",
    "run_idempotency_conflict",
    "relay_identity_mismatch",
    "process_key_unvalidated",
}
#: Refusals that predate #1767 and are recorded as such (scorecard: archive approved, lane not allowlisted).
PREEXISTING = {
    "catalyst-calibration-monitor-shadow": "relay_lane_not_allowlisted",
    "watch-directives-monitor-shadow": "relay_lane_not_allowlisted",
}


def _run_nodes(wf: dict) -> list[dict]:
    return [n for n in wf.get("nodes", []) if str((n.get("parameters") or {}).get("url") or "").endswith("}}/run")]


def _render_body(expr: str, *, json_item: dict, workflow_id: str, execution_id: str) -> str:
    """Evaluate the node's n8n body expression in node.js with the n8n globals it reads."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node.js not available")
    body = expr.strip()
    assert body.startswith("={{") and body.endswith("}}"), body[:40]
    js = (
        f"const $json = {json.dumps(json_item)};\n"
        f"const $workflow = {{id: {json.dumps(workflow_id)}}};\n"
        f"const $execution = {{id: {json.dumps(execution_id)}}};\n"
        "const $ = () => ({first: () => ({json: {}})});\n"
        f"process.stdout.write(String({body[3:-2]}));\n"
    )
    return subprocess.run([node, "-e", js], capture_output=True, text=True, check=True, timeout=30).stdout


def _gateway_transport(gw, monkeypatch):
    """The relay's transport, wired to the REAL gateway handle_request on a tmp ledger with the real allowlist. Only
    the d: slot computation is stubbed (compute_due needs the live registry clock); that path is unchanged here."""
    from scripts.lib import n8n_due as D

    monkeypatch.setattr(G, "_load_due_inputs", lambda *_a, **_k: ([], "", {}, "", None, ""))
    monkeypatch.setattr(
        D,
        "check_slot_key",
        lambda key, *_a, **_k: SimpleNamespace(
            ok=True, state="DUE", slot_key=key, attempt=1, parent_run_id=None, klass=None, priority=None
        ),
    )
    allow = SRV.run_allowlist_source(ROOT / "config" / "n8n_run_allowlist.json")

    def transport(_url, payload):
        out = G.handle_request(
            payload,
            key=KEY,
            now=NOW,
            nonce_store=gw.nonces,
            idempotency_store=gw.receipts,
            expected_origin_sha="a" * 40,
            caller_keys=G.build_caller_keys(KEY, n8n_key=b"k" * 48),
            run_store=gw.runs,
            run_allowlist=allow,
            process_sources=SOURCES,
            due_sources=object(),
        )
        return (403 if out.get("state") == "REFUSED" else 200), out

    return transport


@pytest.mark.parametrize("wf", ACTIVE["workflows"], ids=[w["id"] for w in ACTIVE["workflows"]])
def test_active_workflow_run_bodies_are_not_refused_by_1767(gw, tmp_path, monkeypatch, wf):
    doc = json.loads((ROOT / wf["file"]).read_text())
    nodes = _run_nodes(doc)
    if not nodes:
        assert wf["id"] in ("tradeai-momentum-lifecycle-candidate", "tradeai-fabric-error")  # no POST /run node
        return
    env = {
        "TRADEAI_N8N_RELAY_BEARER": "b" * 48,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 48,
        "TRADEAI_STATE_ROOT": str(tmp_path),
        "TRADEAI_N8N_RELAY_LIVE_LANES": RELAY_LIVE,
    }
    relay = R.Relay(
        environ=env,
        allowlist=SRV.run_allowlist_source(ROOT / "config" / "n8n_run_allowlist.json"),
        transport=_gateway_transport(gw, monkeypatch),
        clock=lambda: NOW.timestamp(),
    )
    item = RUN_LANE_ITEM if wf["id"] == "tradeai-fabric-run-lane" else DUE_ITEM
    for i, node in enumerate(nodes):
        body = _render_body(
            node["parameters"]["jsonBody"], json_item=item, workflow_id=wf["live_id"], execution_id=str(4242 + i)
        )
        status, out = relay.run("Bearer " + "b" * 48, body.encode())
        assert out.get("reason") not in NEW_REASONS, (wf["id"], body, out)
        if wf["id"] in PREEXISTING:
            assert out["reason"] == PREEXISTING[wf["id"]], (wf["id"], out)
            continue
        sent = json.loads(body)
        assert status == 200 and out["state"] == "REQUESTED", (wf["id"], body, out)
        assert out["lane_id"] == sent["lane_id"] and out["mode"] == sent["mode"]
        if "idempotency_key" not in sent:  # generated per-lane workflow: the relay mints the execution-bound key
            assert out["run_id"].startswith("n8n-wf-") and out["mode"] == wf["mode"]
        # a transport retry of the same execution is the same request: a true duplicate, never a conflict
        status2, again = relay.run("Bearer " + "b" * 48, body.encode())
        assert again["duplicate"] is True and again["run_id"] == out["run_id"], again
        assert again.get("reason") not in NEW_REASONS and status2 == 200


def test_relay_minted_namespace_cannot_be_chosen_by_n8n(gw, tmp_path):
    env = {
        "TRADEAI_N8N_RELAY_BEARER": "b" * 48,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 48,
        "TRADEAI_STATE_ROOT": str(tmp_path),
        "TRADEAI_N8N_RELAY_LIVE_LANES": "maturity-remeasure",
    }
    calls: list = []
    relay = R.Relay(
        environ=env,
        allowlist=frozenset({"maturity-remeasure"}),
        transport=lambda *_: calls.append(1) or (200, {"state": "REQUESTED"}),
    )
    for key in ("n8n-wf-forged-0000000001", "N8N-WF-forged-0000000001"):
        body = json.dumps({"lane_id": "maturity-remeasure", "mode": "live", "idempotency_key": key}).encode()
        assert relay.run("Bearer " + "b" * 48, body)[1]["reason"] == "relay_bad_run_id"
    assert calls == []
    # the gateway admits the relay-minted namespace for a LIVE relay run
    out = _req(
        gw,
        lane="maturity-remeasure",
        mode="live",
        key="n8n-wf-c0d4c7845e5c4fcc-4242",
        requested_by="n8n:workflow:c0d4c7845e5c4fcc",
    )
    assert out["state"] == "REQUESTED"
