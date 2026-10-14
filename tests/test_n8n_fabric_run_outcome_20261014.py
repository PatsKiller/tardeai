"""n8n fabric Phase 1 (2026-10-14): the async run-outcome contract.

The executor records a terminal outcome per run (run_outcomes: status success / failed / refused_policy /
skipped_lock, exit code, receipt path, duration, effect key) on both the v1 drain and the v2 workers; the gateway
serves it read-only as ``coordination/run_outcome`` (HMAC claim, read scope; RunOutcome@v1); a refusal is DATA
(status refused_policy, HTTP 200), never a gateway error; the relay forwards GET /run_outcome?run_id=.
Hermetic: tmp_path ledgers and state roots, fake runners, in-process gateway; no live port, relay or n8n."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_coordination_gateway as SRV  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts import n8n_run_relay as R  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib.n8n_coordination_ledger import (  # noqa: E402
    CoordinationLedger,
    LedgerNonceStore,
    LedgerReceiptStore,
    LedgerRunStore,
)
from scripts.lib.n8n_fabric_store import CommsIntentStore, RunOutcomeStore, status_for_state  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402

KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
BEARER = "relay-bearer-not-a-live-secret-0123456789"
SHA = "a" * 40
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
T0 = NOW.timestamp()


def _entry(tmp_path: Path, lane: str) -> dict:
    return {
        "lane_id": lane,
        "command": ["$PY", "scripts/fake.py", "--lane", lane],
        "lock": str(tmp_path / "locks" / f"{lane}.lock"),
        "timeout_s": 60,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
    }


def _runner(code: int, stderr: str = ""):
    def run(argv, *, timeout, env, cwd):
        return SimpleNamespace(returncode=code, stdout="ok", stderr=stderr)

    return run


@pytest.fixture
def led(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield SimpleNamespace(
        ledger=ledger,
        runs=LedgerRunStore(ledger),
        outcomes=RunOutcomeStore(ledger),
        nonces=LedgerNonceStore(ledger),
        receipts=LedgerReceiptStore(ledger),
        tmp=tmp_path,
    )
    ledger.close()


def _request(led, run_id: str, lane: str = "lane-a", mode: str = "live") -> None:
    led.runs.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="t", caller_id="n8n-relay", now=T0)


# ── status mapping ──────────────────────────────────────────────────────────────────────────────────────────────


def test_every_terminal_ledger_state_maps_to_one_of_the_four_statuses():
    assert status_for_state("RUN_DONE") == "success"
    assert status_for_state("RUN_FAILED") == "failed"
    assert status_for_state("RUN_TIMEOUT") == "failed"
    assert status_for_state("RUN_REFUSED") == "refused_policy"
    assert status_for_state("RUN_SKIPPED_LOCK") == "skipped_lock"
    assert status_for_state("REQUESTED") == status_for_state("RUNNING") == "pending"
    assert status_for_state(None) == status_for_state("bogus") == "unknown"


# ── executor: v1 drain records the outcome ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code,stderr,lane_known,want_state,want_status",
    [
        (0, "", True, "RUN_DONE", "success"),
        (3, "", True, "RUN_FAILED", "failed"),
        (0, "safe_flock: skipped (pid 1 running)", True, "RUN_SKIPPED_LOCK", "skipped_lock"),
        (0, "", False, "RUN_REFUSED", "refused_policy"),
    ],
)
def test_v1_drain_records_a_terminal_outcome_with_receipt_path_and_duration(
    led, code, stderr, lane_known, want_state, want_status
):
    state = led.tmp / "state"
    _request(led, "run-outcome-v1-000001")
    allow = {"lane-a": _entry(led.tmp, "lane-a")} if lane_known else {}
    out = X.drain(
        led.runs,
        allow,
        env={"TRADEAI_VENV_PYTHON": sys.executable},
        state_root=state,
        code_root=led.tmp,
        runner=_runner(code, stderr),
        outcomes=led.outcomes,
    )
    assert [r["state"] for r in out] == [want_state]
    row = led.outcomes.get("run-outcome-v1-000001")
    assert row["status"] == want_status and row["run_state"] == want_state and row["lane_id"] == "lane-a"
    assert row["exit_code"] == (None if not lane_known else code)
    assert row["duration_s"] is not None and row["finished_at"]
    receipt_path = Path(row["receipt_path"])
    assert receipt_path == state / "data" / "runtime" / "n8n_runs" / "run-outcome-v1-000001.json"
    assert json.loads(receipt_path.read_text())["state"] == want_state  # rail 8: the receipt exists
    assert row["effect_key"] is None  # no effect gate configured


def test_v1_drain_without_an_outcome_store_is_unchanged(led):
    _request(led, "run-outcome-v1-000002")
    X.drain(
        led.runs,
        {"lane-a": _entry(led.tmp, "lane-a")},
        env={},
        state_root=led.tmp / "state",
        code_root=led.tmp,
        runner=_runner(0),
    )
    assert led.runs.get("run-outcome-v1-000002")["state"] == "RUN_DONE"
    assert led.outcomes.get("run-outcome-v1-000002") is None


def test_an_outcome_write_failure_never_fails_the_run(led, capsys):
    class Broken:
        def record(self, *a, **k):
            import sqlite3

            raise sqlite3.OperationalError("database is locked")

    _request(led, "run-outcome-v1-000003")
    X.drain(
        led.runs,
        {"lane-a": _entry(led.tmp, "lane-a")},
        env={},
        state_root=led.tmp / "state",
        code_root=led.tmp,
        runner=_runner(0),
        outcomes=Broken(),
    )
    assert led.runs.get("run-outcome-v1-000003")["state"] == "RUN_DONE"
    assert '"outcome_record": "failed:OperationalError"' in capsys.readouterr().out


# ── executor: v2 workers record the outcome (and the reaper's) ──────────────────────────────────────────────────


def _v2(led, allow, runner_code=0):
    state = led.tmp / "state"
    state.mkdir(exist_ok=True)
    rows = [{"lane_id": lane, "dispatch": {"retry_policy": "transient-2"}} for lane in allow]
    return X.ExecutorV2(
        led.runs,
        allow,
        env={"TRADEAI_VENV_PYTHON": sys.executable},
        state_root=state,
        code_root=led.tmp,
        workers=2,
        policies=load_policies(),
        clock=lambda: T0 + 5,
        runner_factory=lambda on_spawn, on_beat: _runner(runner_code),
        worker_prefix="test",
        quiet=True,
        registry_rows=rows,
        sleeper=lambda s: None,
        outcomes=led.outcomes,
    )


def test_v2_worker_records_the_outcome_after_finish(led):
    ex = _v2(led, {"lane-a": _entry(led.tmp, "lane-a")}, runner_code=4)
    _request(led, "run-outcome-v2-000001")
    ex.drain_until_idle(deadline_s=10)
    row = led.outcomes.get("run-outcome-v2-000001")
    assert row["status"] == "failed" and row["exit_code"] == 4 and row["attempt"] == 1
    assert Path(row["receipt_path"]).is_file()


def test_v2_reaped_run_records_failed_executor_lost(led):
    ex = _v2(led, {"lane-a": _entry(led.tmp, "lane-a")})
    _request(led, "run-outcome-v2-000002")
    led.runs.claim_next_v2(worker_id="test:w9", now=T0)  # owned by a dead slot of THIS executor
    reaped = ex.reap(T0 + 10_000)
    assert [r["reason"] for r in reaped] == ["executor_lost"]
    row = led.outcomes.get("run-outcome-v2-000002")
    assert row["status"] == "failed" and row["run_state"] == "RUN_TIMEOUT" and row["reason"] == "executor_lost"


# ── gateway: coordination/run_outcome ───────────────────────────────────────────────────────────────────────────


def _claim(nonce: str, *, caller: str, scope: str, key: bytes) -> dict:
    claim = {
        "v": 1,
        "caller_id": caller,
        "project": "trade-ai",
        "iat": T0,
        "exp": T0 + 120,
        "nonce": "nonce-" + nonce,
        "scope": scope,
    }
    return {"claim": claim, "signature": hmac.new(key, G.canonical(claim), hashlib.sha256).hexdigest()}


def _outcome(
    led,
    nonce: str,
    run_id: str,
    *,
    caller="n8n-relay",
    scope=G.SCOPE_READ,
    key=N8N,
    route="coordination/run_outcome",
    operation="run_outcome",
    outcome_store="default",
    **extra,
) -> dict:
    req = {
        **_claim(nonce, caller=caller, scope=scope, key=key),
        "route": route,
        "operation": operation,
        "run_id": run_id,
        **extra,
    }
    return G.handle_request(
        req,
        key=KEY,
        now=NOW,
        nonce_store=led.nonces,
        idempotency_store=led.receipts,
        expected_origin_sha=SHA,
        caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
        run_store=led.runs,
        run_allowlist=frozenset({"lane-a"}),
        outcome_store=led.outcomes if outcome_store == "default" else outcome_store,
    )


def test_run_outcome_serves_the_executor_row(led):
    _request(led, "run-outcome-gw-000001")
    X.drain(
        led.runs,
        {"lane-a": _entry(led.tmp, "lane-a")},
        env={},
        state_root=led.tmp / "state",
        code_root=led.tmp,
        runner=_runner(0),
        outcomes=led.outcomes,
    )
    out = _outcome(led, "g1", "run-outcome-gw-000001")
    assert out["schema"] == "RunOutcome@v1" and out["state"] == "OK" and out["source"] == "outcome"
    assert out["status"] == "success" and out["terminal"] is True and out["exit_code"] == 0
    assert out["receipt_path"].endswith("run-outcome-gw-000001.json") and out["peer_used_as_auth"] is False


def test_refusal_is_data_not_a_gateway_refusal(led):
    _request(led, "run-outcome-gw-000002", lane="lane-gone")
    X.drain(
        led.runs, {}, env={}, state_root=led.tmp / "state", code_root=led.tmp, runner=_runner(0), outcomes=led.outcomes
    )
    out = _outcome(led, "g2", "run-outcome-gw-000002")
    assert out["state"] == "OK" and out["status"] == "refused_policy" and out["reason"] == "lane_not_allowlisted"
    status, body = SRV.dispatch_http(
        "POST",
        "/v1/coordination",
        {},
        json.dumps(
            {
                **_claim("g2b", caller="n8n-relay", scope=G.SCOPE_READ, key=N8N),
                "route": "coordination/run_outcome",
                "operation": "run_outcome",
                "run_id": "run-outcome-gw-000002",
            }
        ).encode(),
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=led.nonces,
        idempotency_store=led.receipts,
        now=NOW,
        caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
        run_store=led.runs,
        outcome_store=led.outcomes,
    )
    assert status == 200 and body["status"] == "refused_policy"  # HTTP 200: n8n never sees an error


def test_pending_unknown_and_runs_row_fallback(led):
    _request(led, "run-outcome-gw-000003")
    assert _outcome(led, "g3", "run-outcome-gw-000003")["status"] == "pending"
    led.runs.claim_next()
    pend = _outcome(led, "g4", "run-outcome-gw-000003")
    assert pend["status"] == "pending" and pend["run_state"] == "RUNNING" and pend["terminal"] is False
    # finished by an executor that does not write run_outcomes: the runs row answers
    led.runs.finish(
        "run-outcome-gw-000003",
        state="RUN_FAILED",
        receipt={"state": "RUN_FAILED", "exit_code": 2, "reason": "exit_2", "mode": "live"},
        now=T0 + 1,
    )
    fb = _outcome(led, "g5", "run-outcome-gw-000003")
    assert fb["source"] == "runs_row" and fb["status"] == "failed" and fb["exit_code"] == 2 and fb["terminal"]
    unk = _outcome(led, "g6", "run-never-requested-0001")
    assert unk["state"] == "OK" and unk["status"] == "unknown" and unk["source"] == "none"


def test_run_outcome_auth_and_shape(led):
    # bad signature
    bad = _outcome(led, "a1", "run-outcome-gw-000009", key=b"x" * 40)
    assert bad["state"] == "REFUSED" and bad["reason"] == "bad_signature"
    # run scope cannot read; intent scope cannot read
    assert _outcome(led, "a2", "run-outcome-gw-000009", scope=G.SCOPE_RUN)["reason"] == "bad_scope"
    assert _outcome(led, "a3", "run-outcome-gw-000009", scope=G.SCOPE_INTENT)["reason"] == "bad_scope"
    # the dispatch key (read scope) may read
    ok = _outcome(led, "a4", "run-outcome-gw-000009", caller="tradeai-dispatch", key=KEY)
    assert ok["state"] == "OK" and ok["status"] == "unknown"
    # replayed nonce
    assert (
        _outcome(led, "a4", "run-outcome-gw-000009", caller="tradeai-dispatch", key=KEY)["reason"] == "replayed_nonce"
    )
    # route/operation must pair; malformed run id; unexpected field; no store
    assert _outcome(led, "a5", "run-outcome-gw-000009", operation="status")["reason"] == "unknown_operation"
    assert _outcome(led, "a6", "x")["reason"] == "malformed_event"
    assert _outcome(led, "a7", "run-outcome-gw-000009", lane_id="lane-a")["reason"] == "unexpected_field"
    assert _outcome(led, "a8", "run-outcome-gw-000009", outcome_store=None)["reason"] == "run_outcome_unavailable"


def test_run_outcome_writes_nothing(led):
    before = led.ledger._conn.execute("SELECT COUNT(*) FROM run_outcomes").fetchone()[0]
    _outcome(led, "w1", "run-outcome-gw-000010")
    assert led.ledger._conn.execute("SELECT COUNT(*) FROM run_outcomes").fetchone()[0] == before
    assert led.runs.get("run-outcome-gw-000010") is None


# ── relay: GET /run_outcome ─────────────────────────────────────────────────────────────────────────────────────


def _relay(led, tmp_path):
    keys = G.build_caller_keys(KEY, n8n_key=N8N)
    intents = CommsIntentStore(led.ledger, routes_path=ROOT / "config" / "n8n_comms_intent_routes.json")
    seen: list[dict] = []

    def transport(url, payload):
        seen.append(payload)
        return SRV.dispatch_http(
            "POST",
            "/v1/coordination",
            {},
            json.dumps(payload).encode(),
            key=KEY,
            expected_origin_sha=SHA,
            nonce_store=led.nonces,
            idempotency_store=led.receipts,
            caller_keys=keys,
            run_store=led.runs,
            outcome_store=led.outcomes,
            intent_store=intents,
        )

    env = {
        R.BEARER_ENV: BEARER,
        R.N8N_KEY_ENV: N8N.decode(),
        "TRADEAI_STATE_ROOT": str(tmp_path / "relay-state"),
        "TRADEAI_N8N_RELAY_LIVE_LANES": "",
    }
    return R.Relay(environ=env, allowlist=frozenset({"lane-a"}), transport=transport, clock=time.time), seen


def test_relay_forwards_run_outcome_with_a_read_claim(led, tmp_path):
    relay, seen = _relay(led, tmp_path)
    _request(led, "run-outcome-rl-000001")
    X.drain(
        led.runs,
        {"lane-a": _entry(led.tmp, "lane-a")},
        env={},
        state_root=led.tmp / "state",
        code_root=led.tmp,
        runner=_runner(0),
        outcomes=led.outcomes,
    )
    status, body = relay.run_outcome("Bearer " + BEARER, "run_id=run-outcome-rl-000001")
    assert status == 200 and body["status"] == "success"
    assert seen[-1]["claim"]["scope"] == G.SCOPE_READ and seen[-1]["route"] == "coordination/run_outcome"
    assert set(seen[-1]) == {"route", "operation", "claim", "signature", "run_id"}
    log = (tmp_path / "relay-state" / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl").read_text()
    assert '"op":"run_outcome"' in log and '"status":"success"' in log


@pytest.mark.parametrize(
    "query", ["", "run_id=short", "run_id=a&run_id=b", "run_id=run-outcome-rl-000001&lane=x", "run_id=bad%20id%20xx"]
)
def test_relay_run_outcome_refuses_bad_queries_before_the_gateway(led, tmp_path, query):
    relay, seen = _relay(led, tmp_path)
    status, body = relay.run_outcome("Bearer " + BEARER, query)
    assert status == 400 and body["reason"] == "relay_bad_query" and seen == []


def test_relay_run_outcome_needs_the_bearer(led, tmp_path):
    relay, seen = _relay(led, tmp_path)
    status, body = relay.run_outcome("Bearer wrong", "run_id=run-outcome-rl-000001")
    assert status == 401 and body["reason"] == "relay_bad_bearer" and seen == []


def test_relay_routes_table_serves_both_new_routes():
    assert ("GET", "/run_outcome") in R.ROUTES and ("POST", "/intent") in R.ROUTES
    assert R.route_supported("GET", "/run_outcome?run_id=abc") and R.route_supported("POST", "/intent")
