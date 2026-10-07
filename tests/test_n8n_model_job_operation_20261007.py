"""Gateway `model_job` operation (tranche D follow-up): STARTED event -> governed job -> artifact REFERENCE or typed refusal.
The governed call is injected; no bridge, no provider, no socket."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_model_job as M  # noqa: E402

KEY = b"k" * 32
SHA = "a" * 40
GOOD = {"headline": "AMC filed an 8-K", "items": [{"symbol": "AMC", "change_guid": "d13460e0", "summary": "8-K"}],
        "sources_cited": ["d13460e0"], "confidence_note": "artifact only", "recommendation": "NONE"}


def _claim(nonce, now):
    claim = {"v": 1, "caller_id": "n8n-lab", "project": "trade-ai", "iat": now, "exp": now + 60, "nonce": "nonce-mj-" + nonce, "scope": "coordination_read"}
    return {"claim": claim, "signature": hmac.new(KEY, G.canonical(claim), hashlib.sha256).hexdigest()}


def _call(op, nonce, nonces, store, **extra):
    now = time.time()
    route = "coordination/status" if op in ("status", "list") else "coordination/event"
    return G.handle_request({**_claim(nonce, now), "route": route, "operation": op, **extra}, key=KEY,
                            now=dt.datetime.fromtimestamp(now, dt.timezone.utc), nonce_store=nonces, idempotency_store=store, expected_origin_sha=SHA)


def _event(idem):
    return {"event_id": "evt-" + idem, "source_project": "trade-ai", "lane_id": "material-change-digest", "schema_version": G.SCHEMA_VERSION,
            "origin_sha": SHA, "subject_key": "AMC", "source_timestamp": "2026-10-07T04:30:00+00:00", "deadline": "2026-10-07T06:30:00+00:00",
            "artifact_ref": "data/runtime/material_changes_digest_input.json", "authority_class": "coordination_read",
            "correlation_id": "corr-" + idem, "idempotency_key": idem}


def _job(root, idem):
    raw = json.dumps({"changes": [{"change_guid": "d13460e0", "symbol": "AMC"}]}).encode()
    (root / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "data" / "runtime" / "material_changes_digest_input.json").write_bytes(raw)
    return {"process_id": "n8n_material_digest_draft", "artifact_ref": {"store": "data/runtime", "ref": "material_changes_digest_input.json", "sha256": hashlib.sha256(raw).hexdigest()},
            "correlation_id": idem, "deadline": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(),
            "output_schema_id": "material_change_digest_draft/v1"}


def _ok(answer=GOOD):
    def call(messages, *, process_id, response_format, request_id):
        return {"governance_pass": True, "process_id": process_id, "reservation_id": 7, "cost_estimate": 0.001, "model_id": "deepseek-flash",
                "provider": "deepseek", "mock": False, "usage": {"total_tokens": 500}, "choices": [{"message": {"content": json.dumps(answer)}}]}
    return call


def test_model_job_writes_an_artifact_reference_on_a_started_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(G, "MODEL_JOB_GOVERNED_CALL", _ok())
    nonces, store = {}, {}
    idem = "idem-mj-0001"
    assert _call("accept_event", "1", nonces, store, event=_event(idem))["state"] == "ACCEPTED"
    early = _call("model_job", "2", nonces, store, idempotency_key=idem, job=_job(tmp_path, idem))
    assert early["reason"] == "illegal_transition:ACCEPTED->ARTIFACT_WRITTEN"        # must be STARTED first
    assert _call("claim", "3", nonces, store, idempotency_key=idem)["state"] == "CLAIMED"
    assert _call("start", "4", nonces, store, idempotency_key=idem)["state"] == "STARTED"
    r = _call("model_job", "5", nonces, store, idempotency_key=idem, job=_job(tmp_path, idem))
    assert r["state"] == "ARTIFACT_WRITTEN" and r["artifact_ref"]["ref"].startswith("n8n_model_jobs/") and r["effects"] == []
    assert r["model_job"]["cost"]["reservation_id"] == 7 and r["outbound"] == "blocked"
    written = json.loads((tmp_path / "data" / "runtime" / r["artifact_ref"]["ref"]).read_text())
    assert written["artifact_out"]["body"]["recommendation"] == "NONE"
    assert _call("status", "6", nonces, store, idempotency_key=idem)["state"] == "ARTIFACT_WRITTEN"


def test_model_job_refusals_are_typed_and_leave_the_event_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(G, "MODEL_JOB_GOVERNED_CALL", lambda *a, **k: {"error": {"code": "DAILY_COST_CAP_EXCEEDED", "status": 429}, "governance_pass": False})
    nonces, store = {}, {}
    idem = "idem-mj-0002"
    _call("accept_event", "1", nonces, store, event=_event(idem)); _call("claim", "2", nonces, store, idempotency_key=idem); _call("start", "3", nonces, store, idempotency_key=idem)
    r = _call("model_job", "4", nonces, store, idempotency_key=idem, job=_job(tmp_path, idem))
    assert r["state"] == "REFUSED" and r["reason"] == "typed_refusal:over_cap" and r.get("artifact_ref") is None
    # a job carrying a secret or a foreign correlation id never reaches the bridge
    called = []
    monkeypatch.setattr(G, "MODEL_JOB_GOVERNED_CALL", lambda *a, **k: (called.append(1), _ok()(*a, **k))[1])
    idem2 = "idem-mj-0003"
    _call("accept_event", "5", nonces, store, event=_event(idem2)); _call("claim", "6", nonces, store, idempotency_key=idem2); _call("start", "7", nonces, store, idempotency_key=idem2)
    bad = dict(_job(tmp_path, idem2), correlation_id="someone-elses-key-0001")
    assert _call("model_job", "8", nonces, store, idempotency_key=idem2, job=bad)["reason"] == "project_mismatch"
    leaky = {**_job(tmp_path, idem2), "api_key": "sk-x"}
    assert _call("model_job", "9", nonces, store, idempotency_key=idem2, job=leaky)["reason"] == "malformed_event"
    assert called == []


def test_bridge_caller_maps_to_the_small_cap_process_server_side():
    from scripts.lib.cio_governed_model_bridge import resolve_caller
    assert resolve_caller("n8n_model_job") == "n8n_material_digest_draft"
    assert resolve_caller("n8n_model_job", task_type="alex_cio_synthesis") == "n8n_material_digest_draft"   # task type cannot escalate


def test_bridge_transport_failures_become_provider_outage(monkeypatch):
    monkeypatch.setenv(M.BRIDGE_URL_ENV, "http://127.0.0.1:1/v1/chat/completions")
    r = M.bridge_governed_call([{"role": "user", "content": "x"}], process_id="n8n_material_digest_draft", request_id="r", timeout_s=2)
    assert r["error"]["code"] == "PROVIDER_TIMEOUT" and r["governance_pass"] is False
