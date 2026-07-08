"""Tests for LLM consumption monitoring + oauth_lane_status."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_registry_has_processes():
    import json
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    by_id = {p["id"]: p for p in reg["processes"]}
    assert "holding_protection_advisor" in by_id
    assert "holding_protection_advisor_batch" in by_id
    assert "oauth_lane_keepalive" in by_id
    assert reg.get("default_mode") == "manual"
    assert reg.get("lane_policies")
    assert by_id["cloud_review"].get("default_mode") == "automated"
    assert by_id["oauth_lane_keepalive"].get("default_mode") == "automated"
    assert by_id["holding_protection_advisor"].get("default_mode") == "manual"
    assert by_id["holding_protection_advisor"].get("lane_policy") == "grok_only"
    assert by_id["broker_cloud_oversight"].get("lane_policy") == "both_preferred"
    assert by_id["cloud_consensus_verdict"].get("lane_policy") == "ensemble"
    assert by_id["watchlist_cio_synthesis"].get("default_mode") == "manual"


def test_oauth_lane_status_module_exports():
    src = (SCRIPTS / "lib" / "oauth_lane_status.py").read_text()
    assert "def lane_available" in src
    assert "def lane_status" in src
    assert "free_oauth" in src


def test_llm_consumption_gate_manual_blocks():
    lc = _load("llm_consumption", SCRIPTS / "lib" / "llm_consumption.py")
    d = lc.should_call("holding_protection_advisor", "grok", manual_trigger=False)
    assert d.get("mode") in ("manual", "automated")
    if d.get("mode") == "manual":
        assert d.get("allow") is False
        assert d.get("reason") == "manual_mode"


def test_api_has_consumption_routes():
    api = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "/api/v2/consumption/overview" in api
    assert "/api/v2/consumption/process-mode" in api
    assert "/api/v2/consumption/run-manual" in api
    assert "/api/v2/consumption/stop-advisory-batch" in api
    assert 'b.get("lanes")' in api or "raw_lanes" in api


def test_llm_lane_process_id_param():
    src = (SCRIPTS / "llm_lane.py").read_text()
    assert "process_id" in src
    assert "gate_and_generate" in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all passed")