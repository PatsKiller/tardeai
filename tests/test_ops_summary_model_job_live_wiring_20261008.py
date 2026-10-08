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
def bridge_plumbing(monkeypatch):
    """The bridge's cost/cap/reservation collaborators, stubbed; process registration stays REAL (the file)."""
    import scripts.lib.cio_governed_model_bridge as B
    B._reset_circuit()
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "0.50")
    import lib.llm_consumption as lc  # noqa: F401 — path set by the bridge's import helper
    lc._REGISTRY = None   # re-read the registry file for this test
    patches = [
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


def test_governance_passes_with_the_entry_present_and_refuses_without_it(bridge_plumbing):
    B = bridge_plumbing
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
