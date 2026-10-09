"""2026-10-08 (Phase 2 G1): model job #1 (weekly ops summary draft) wired for live use.

Found while wiring: both n8n model-job processes were in config/llm_process_registry.json but absent from the
bridge's server-side policy map, so Step 3 answered UNKNOWN_PROCESS for a *registered* process. The bridge
also maps the n8n_model_job caller by task type now (ops_summary → n8n_ops_summary_draft). Hermetic: the
bridge's MockProvider, patched cost/cap/reservation plumbing exactly as tests/test_cio_governed_model_bridge.py
does, the REAL registry file for the registered/unregistered distinction, fixture answers — never a provider."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest  # noqa: E402

NOW = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)
PROC = "n8n_ops_summary_draft"


@pytest.fixture
def bridge_plumbing(monkeypatch, tmp_path):
    """File registration stays real; a positive fixture explicitly grants fallback and current health.

    Database and provider collaborators are injected. This grants no production registry authority.
    """
    import scripts.lib.cio_governed_model_bridge as B
    B._reset_circuit()
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "0.50")
    import lib.llm_consumption as lc  # noqa: F401 — path set by the bridge's import helper
    lc._REGISTRY = None   # re-read the registry file for this test
    original_process = lc._registry_process

    def explicitly_authorized_process(process_id):
        row = original_process(process_id)
        if row is not None and process_id in {PROC, "n8n_material_digest_draft"}:
            return {**row, "fallback_allowed": True}
        return row

    monkeypatch.setattr(lc, "_registry_process", explicitly_authorized_process)
    monkeypatch.setattr(B, "BIND_MODE", "mock")
    health = tmp_path / "positive-provider-health.json"
    health.write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(), "worst_severity": "OK",
        "findings": [{"lane": "deepseek", "recovered": True, "calls": 4, "failures": 1}],
    }))
    monkeypatch.setenv("TRADEAI_LLM_PROVIDER_HEALTH", str(health))
    monkeypatch.setenv("TRADEAI_DEEPSEEK_BALANCE_HISTORY", str(tmp_path / "absent-balance.jsonl"))
    patches = [
        patch("lib.llm_consumption.ensure_schema", side_effect=RuntimeError("offline fixture forbids DB")),
        patch("lib.llm_consumption._conn", side_effect=RuntimeError("offline fixture forbids DB")),
        patch("lib.llm_consumption.calibrated_projected_usd", return_value={"projected_usd": 0.002, "basis": "test"}),
        patch("lib.llm_model_registry.reject_legacy_model_id", return_value=None),
        patch("lib.consumption_run_manual.validate_paid_cap_config", return_value=None),
        patch("lib.consumption_run_manual.projected_max_cost_usd", return_value=0.002),
        patch("lib.llm_consumption.check_cost_cap", return_value={"allow": True, "spent_process_usd": 0.0}),
        patch("lib.llm_consumption.reserve_projected_cost", return_value=42),
        patch("lib.llm_consumption.settle_reservation", return_value=None),
        patch("lib.llm_model_registry.estimate_usd_cost", return_value={"estimated_cost_usd": 0.0005, "cost_basis": "test",
                                                                          "pricing_effective_at": "2026-10-08"}),
        patch("lib.llm_consumption.log_call", return_value=None),
    ]
    for p in patches:
        p.start()
    yield B
    patch.stopall()


def test_the_process_is_registered_like_the_digest_job():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    by = {p["id"]: p for p in reg["processes"]}
    ops, digest = by[PROC], by["n8n_material_digest_draft"]
    assert ops["lane_policy"] == "deepseek_only" and ops["allowed_lanes"] == digest["allowed_lanes"]
    assert ops["deepseek_allowed_policies"] == ["FAST"] and ops["daily_cost_cap_usd"] <= digest["daily_cost_cap_usd"]
    assert ops["daily_soft_cap"] == 1 and ops["advisory_only"] is True and ops["tools_allowed"] is False
    assert "ops_summary_draft/v1" in ops["description"]


def test_caller_task_type_selects_the_ops_process_server_side_and_cannot_escalate():
    from scripts.lib.cio_governed_model_bridge import resolve_caller
    assert resolve_caller("n8n_model_job", task_type="ops_summary") == PROC
    assert resolve_caller("n8n_model_job", task_type="model_job") == "n8n_material_digest_draft"
    assert resolve_caller("n8n_model_job") == "n8n_material_digest_draft"
    assert resolve_caller("n8n_model_job", task_type="alex_cio_synthesis") == "n8n_material_digest_draft"


def _schema_valid_mock(monkeypatch, B, answer: dict) -> None:
    """2026-10-09 (AGENTS.md 3.0.0 §23.10 P6): the bridge validates n8n_* output against the process schema, so
    the MockProvider's prose is refused there; these tests swap in a schema-valid answer at the provider."""
    real = B.MockProvider.generate

    def generate(self, *a, **k):
        out = real(self, *a, **k)
        out["choices"][0]["message"]["content"] = json.dumps(answer)
        return out
    monkeypatch.setattr(B.MockProvider, "generate", generate)


def test_governance_passes_with_the_entry_present_and_refuses_without_it(bridge_plumbing, monkeypatch):
    B = bridge_plumbing
    _schema_valid_mock(monkeypatch, B, OPS_ANSWER)
    ok = B.execute_governed_call([{"role": "user", "content": "weekly ops summary"}], process_id=PROC,
                                 response_format={"type": "json_object"}, max_tokens=512)
    assert "error" not in ok, ok.get("error")
    assert ok["_tradeai"]["governance_pass"] is True and ok["_tradeai"]["mock"] is True
    assert "deepseek-flash" in ok["model"]
    # the digest process, registered since tranche D, now resolves too (it answered UNKNOWN_PROCESS before)
    assert B.resolve_model_policy("n8n_material_digest_draft")["requested_policy"] == "FAST"
    # absent entry → the same typed refusal the digest tests rely on
    with patch("lib.llm_consumption.get_process_config", return_value={"registered": False, "process_id": "nope"}):
        no = B.execute_governed_call([{"role": "user", "content": "x"}], process_id="nope")
    assert no["error"]["code"] == "PROCESS_NOT_REGISTERED" and no["governance_pass"] is False


def _state_root(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "runtime" / "lane_governance_packet_last.json").write_text(json.dumps({
        "schema": "LaneGovernancePacket@v1", "period": "weekly", "period_key": "2026-W41",
        "summary": {"lanes": {"LIVE": 1}, "incidents_open": 0}}), encoding="utf-8")
    return root


def test_fixture_valid_draft_becomes_an_artifact_through_the_ops_schema(tmp_path, monkeypatch):
    import report_lane_governance_packet as P
    root = _state_root(tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    out = P.draft_ops_summary(root=root, period="weekly", key="2026-W41", now=NOW, governed_call=P.fixture_call("valid"))
    assert out["state"] == "ARTIFACT_WRITTEN", out
    art = json.loads(Path(out["artifact"]).read_text(encoding="utf-8"))
    assert art["job"]["process_id"] == PROC and art["receipt"]["state"] == "ARTIFACT_WRITTEN"
    refused = P.draft_ops_summary(root=root, period="weekly", key="2026-W41", now=NOW, governed_call=P.fixture_call("over_cap"))
    assert refused["state"] == "REFUSED" and refused["reason"] == "over_cap"


def test_live_call_carries_the_ops_task_type_and_plan_mode_never_calls(tmp_path, monkeypatch):
    import report_lane_governance_packet as P
    import scripts.lib.n8n_model_job as M
    seen = {}

    class _Resp:
        def __init__(self):
            self.status = 200
        def read(self):
            return json.dumps({"error": {"code": "PROVIDER_UNAVAILABLE", "status": 503}, "governance_pass": False}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["task_type"] = req.headers.get("X-tradeai-task-type") or req.get_header("X-tradeai-task-type")
        seen["caller"] = req.get_header("X-tradeai-agent")
        return _Resp()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    r = P.live_call()([{"role": "user", "content": "x"}], process_id=PROC, request_id="r")
    assert seen == {"task_type": "ops_summary", "caller": "n8n_model_job"} and r["governance_pass"] is False

    root = _state_root(tmp_path)
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: calls.append(1))
    plan = P.plan_ops_summary(root=root, period="weekly", key="2026-W41", now=NOW)
    assert calls == [] and plan["would_call"] is False
    assert plan["caller_maps_to"] == PROC and plan["registered"] is True and plan["policy"]["model_id"]
    assert plan["prompt"]["fits_max_input"] is True and plan["ready"] is True
    assert not list((root / "data").glob("governance/*")), "plan mode writes no artifact"
    # 2026-10-08: ready also means the server-side task type and the rendered template agree with the live path
    assert plan["task_type_derived"] == "ops_summary" and plan["task_type_ok"] is True and plan["governance_envelope"] == "_tradeai"
    assert plan["template"] == {"id": "ops_summary_draft.v1", "invalid": None, "matches_inline_prompt": True}
    monkeypatch.setattr(M, "PROCESS_TASK_TYPE", {"n8n_material_digest_draft": "model_job"})
    plan = P.plan_ops_summary(root=root, period="weekly", key="2026-W41", now=NOW)
    assert plan["task_type_ok"] is False and plan["task_type_refusal"] == "process_not_registered" and plan["ready"] is False


# ── 2026-10-08 (Day 0, Agent C): the three live-path defects, proven against the bridge code ─────────────────────

def test_fixture_call_returns_the_nested_envelope_and_the_job_reads_it():
    import report_lane_governance_packet as P
    body = P.fixture_call("valid")([{"role": "user", "content": "x"}], process_id=PROC, response_format={"type": "json_object"},
                                   request_id="corr-ops-weekly-2026-W41", task_type="ops_summary")
    assert "governance_pass" not in body and body["_tradeai"]["governance_pass"] is True and body["_tradeai"]["process_id"] == PROC
    assert body["_tradeai"]["task_type_seen"] == "ops_summary"


def _ops_job(root: Path, correlation_id: str) -> dict:
    import hashlib
    raw = (root / "data" / "runtime" / "lane_governance_packet_last.json").read_bytes()
    return {"process_id": PROC, "output_schema_id": "ops_summary_draft/v1", "correlation_id": correlation_id,
            "deadline": "2026-10-08T03:00:00+00:00",
            "artifact_ref": {"store": "data/runtime", "ref": "lane_governance_packet_last.json", "sha256": hashlib.sha256(raw).hexdigest()}}


OPS_ANSWER = {"headline": "ops", "sections": [{"area": "lanes", "summary": "ok"}], "open_items": [],
              "sources_cited": ["lane_governance_packet_last.json"], "confidence_note": "stub", "recommendation": "NONE"}


def test_a_real_bridge_success_through_execute_governed_call_is_accepted_by_run_model_job(bridge_plumbing, tmp_path, monkeypatch):
    """Defect 1, end to end: the governed call is the bridge's own execute_governed_call (MockProvider, plumbing
    stubbed); its Step 10 envelope is what run_model_job must parse. Before 2026-10-08 this was
    `governance_refused: governance_pass false`."""
    import scripts.lib.n8n_model_job as M
    B = bridge_plumbing
    root = _state_root(tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    seen = {}

    _schema_valid_mock(monkeypatch, B, OPS_ANSWER)   # mock prose -> schema-valid answer at the provider; envelope untouched

    def governed(messages, *, process_id, response_format, request_id, task_type=None, **named):
        seen.update(process_id=process_id, request_id=request_id, task_type=task_type)
        return B.execute_governed_call(messages, process_id=process_id, response_format=response_format, max_tokens=512, request_id=request_id)
    rec = M.run_model_job(_ops_job(root, "corr-ops-weekly-2026-W41"), governed_call=governed, now=NOW, root=root)
    assert (rec["state"], rec["reason"]) == ("ARTIFACT_WRITTEN", None), rec
    assert rec["cost"]["reservation_id"] == 42 and rec["cost"]["mock"] is True and rec["cost"]["bridge_request_id"] == "corr-ops-weekly-2026-W41"
    assert rec["cost"]["model_id"].startswith("deepseek") and rec["cost"]["provider"] == "deepseek"
    assert seen == {"process_id": PROC, "request_id": "corr-ops-weekly-2026-W41", "task_type": "ops_summary"}


def _handler(B, body: bytes, headers: dict):
    import email.message
    import io
    h = B.GovernedBridgeHandler.__new__(B.GovernedBridgeHandler)
    h.path, h.command, h.request_version = "/v1/chat/completions", "POST", "HTTP/1.1"
    h.requestline, h.client_address, h.server, h.close_connection = "POST /v1/chat/completions HTTP/1.1", ("127.0.0.1", 0), None, True
    h.headers = email.message.Message()
    for k, v in {**headers, "Content-Length": str(len(body))}.items():
        h.headers[k] = v
    h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
    return h


def test_the_bridge_handler_threads_the_body_request_id_into_the_governed_call(monkeypatch):
    """Defect 2a (2026-10-08): do_POST read `request_id` nowhere, so execute_governed_call minted its own id."""
    import scripts.lib.cio_governed_model_bridge as B
    calls = []

    def fake_execute(messages, **kw):
        calls.append(kw)
        return {"id": kw.get("request_id"), "choices": []}
    monkeypatch.setattr(B, "execute_governed_call", fake_execute)
    body = json.dumps({"model": "tradeai_governed", "messages": [{"role": "user", "content": "x"}], "request_id": "corr-ops-weekly-2026-W41"}).encode()
    h = _handler(B, body, {"X-TradeAI-Agent": "n8n_model_job", "X-TradeAI-Task-Type": "ops_summary", "Content-Type": "application/json"})
    h.do_POST()
    assert calls[-1]["process_id"] == PROC and calls[-1]["request_id"] == "corr-ops-weekly-2026-W41"
    assert b'"id": "corr-ops-weekly-2026-W41"' in h.wfile.getvalue()
    # an unsafe or absent id is dropped (the bridge mints its own), never passed through
    for bad in ("x" * 65, "has space", "", 12, None, "é"):
        h = _handler(B, json.dumps({"messages": [{"role": "user", "content": "x"}], "request_id": bad}).encode(),
                     {"X-TradeAI-Agent": "n8n_model_job", "Content-Type": "application/json"})
        h.do_POST()
        assert calls[-1]["request_id"] is None, bad
    assert B.client_request_id_from("corr-ops-weekly-2026-W41") == "corr-ops-weekly-2026-W41"


class _Resp:
    def __init__(self, payload: bytes):
        self.status_code, self.headers, self._payload, self.closed = 200, {"x-request-id": "prov-req-77"}, payload, False

    def iter_content(self, chunk_size=8192):
        yield self._payload

    def close(self):
        self.closed = True


def test_a_canary_call_with_request_id_x_emits_a_cost_event_whose_client_request_id_is_x(bridge_plumbing, tmp_path, monkeypatch):
    """Defect 2b, end to end: execute_governed_call(request_id=X) -> RealProvider (HTTP stubbed, key stubbed) ->
    provider_cost event with client_request_id == X, in a scratch log that run_model_job then joins (MEASURED).
    Never a network call, never the live key store: get_deepseek_api_key is replaced before the provider runs."""
    import requests

    import lib.llm_model_registry as lmr
    import scripts.lib.n8n_model_job as M
    B = bridge_plumbing
    root = _state_root(tmp_path)
    log = root / "data" / "runtime" / "provider_cost" / "events.jsonl"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("PROVIDER_COST_EVENT_LOG", str(log))
    monkeypatch.setenv("CIO_PROVIDER_REQUEST_JOURNAL_JSONL", str(tmp_path / "journal.jsonl"))
    monkeypatch.setattr(lmr, "get_deepseek_api_key", lambda: ("test-key-not-real", "deepseek_tradeai", False))
    posted = {}

    def fake_post(url, **kw):
        posted.update(kw)
        return _Resp(json.dumps({"id": "prov", "model": kw["json"]["model"], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                                 "choices": [{"message": {"role": "assistant", "content": json.dumps(OPS_ANSWER)}, "finish_reason": "stop"}]}).encode())
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(B, "BIND_MODE", "canary")
    B.RealProvider._instance = None
    X = "corr-ops-weekly-2026-W41"
    try:
        out = B.execute_governed_call([{"role": "user", "content": "weekly ops summary"}], process_id=PROC,
                                      response_format={"type": "json_object"}, max_tokens=512, request_id=X)
    finally:
        B.RealProvider._instance = None
    assert "error" not in out, out.get("error")
    assert posted["headers"]["X-TradeAI-Request-Id"] == X and posted["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert out["_tradeai"]["request_id"] == X and out["_tradeai"]["mock"] is False and out["_tradeai"]["reservation_id"] == 42
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["client_request_id"] for r in rows] == [X] and rows[0]["outcome"] == "success" and rows[0]["request_id"] == "prov-req-77"
    assert "test-key-not-real" not in log.read_text()
    joined = M._cost_event_for(X, root=root)
    assert joined and joined["event_id"] == rows[0]["event_id"]
    # the whole job now settles MEASURED on that join
    rec = M.run_model_job(_ops_job(root, X), governed_call=lambda *a, **k: out, now=NOW, root=root)
    assert rec["state"] == "ARTIFACT_WRITTEN" and rec["cost"]["settlement"] == "MEASURED" and rec["cost"]["provider_cost_event"]["event_id"] == joined["event_id"]
