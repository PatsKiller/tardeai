"""security_identity: a labelled read-time registry lookup for symbol-only decisions.

Measured 2026-10-03: 526 natural decisions record a symbol the identity registry
already resolves but carry no GUID, so security_identity read UNKNOWN. The lookup
is surfaced as ``identity_registry:<guid>``, never as a producer record, and a
producer-stamped GUID always wins. Operator approved the labelled read-time path.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

AS_OF = "2026-10-02T11:20:33+00:00"
GUID = "11111111-2222-5333-8444-555555555555"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({
        "schema": "IdentityRegistry@v1",
        "entities": {GUID: {"subject_guid": GUID, "security_guid": GUID, "identity_status": "CONFIRMED",
                            "last_seen": "2026-10-01T09:00:00+00:00", "active": True},
                     "22222222-3333-5444-8555-666666666666": {"subject_guid": "22222222-3333-5444-8555-666666666666",
                                                              "identity_status": "UNRESOLVED_WITH_REASON"}},
        "by_symbol": {"SCHG": GUID, "ALIAS": "22222222-3333-5444-8555-666666666666"},
        "events": {},
        "updated_at": "2026-10-01T09:00:00+00:00",
    }), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(reg))
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: None
    monkeypatch.setitem(sys.modules, "api_v2", stub)


def _root(tmp_path: Path, decision: dict) -> Path:
    root = tmp_path / "cio"
    root.mkdir()
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    trace = {"agent": "alex", "role": "reentry", "trace_id": "tr_1", "wake_id": "wake_1",
             "started_at": AS_OF, "ended_at": AS_OF, "status": "completed",
             "decision": {"decision_id": decision["decision_id"], "as_of": AS_OF, "current_action": "WAIT",
                          "inputs_digest": "ctx_1", "wake_id": "wake_1", "trace_id": "tr_1", **decision}}
    (root / "agent_run_traces.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    return root


def _identity_stage(monkeypatch, root: Path, did: str) -> dict:
    import scripts.api_v3_cio as api

    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage(did)
    assert result["ok"] is True, result
    return result["lineage"]["stages"]["security_identity"]


def test_symbol_only_decision_resolves_labelled_as_read_time(tmp_path, monkeypatch):
    stage = _identity_stage(monkeypatch, _root(tmp_path, {"decision_id": "dec_r1", "symbol": "schg"}), "dec_r1")
    assert stage["state"] == "LIVE"
    assert stage["value"] == GUID
    assert stage["source_ref"] == f"identity_registry:{GUID}"
    assert stage["producer"] == "identity_registry.lookup_symbol (read-time)"
    assert stage["evidence_class"] == "READ_TIME_RESOLUTION"
    assert stage["source_as_of"]


def test_producer_stamped_guid_wins_over_registry(tmp_path, monkeypatch):
    stamped = "99999999-8888-5777-8666-555555555555"
    root = _root(tmp_path, {"decision_id": "dec_r2", "symbol": "SCHG", "security_guid": stamped})
    stage = _identity_stage(monkeypatch, root, "dec_r2")
    assert stage["value"] == stamped
    assert not str(stage["source_ref"]).startswith("identity_registry:")


@pytest.mark.parametrize("symbol", ["ZZZZ", "DATA_UNAVAILABLE", "", "ALIAS"])
def test_unknown_or_placeholder_symbol_is_never_resolved(tmp_path, monkeypatch, symbol):
    stage = _identity_stage(monkeypatch, _root(tmp_path, {"decision_id": "dec_r3", "symbol": symbol}), "dec_r3")
    assert stage["state"] != "LIVE"
    assert stage["value"] is None


def test_unreadable_registry_degrades_to_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "missing" / "registry.json"))
    stage = _identity_stage(monkeypatch, _root(tmp_path, {"decision_id": "dec_r4", "symbol": "SCHG"}), "dec_r4")
    assert stage["state"] == "UNKNOWN"
