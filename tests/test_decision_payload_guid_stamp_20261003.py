"""DecisionPayload@v1 carries the registry's CONFIRMED security_guid at build time.

Measured 2026-10-03: of 2,509 natural decisions only material_scan rows carried a
GUID; advisory, reentry, watch and holdings decisions named a symbol the identity
registry already confirms, so lineage security_identity read UNKNOWN. These tests
use an isolated registry, never the production one.
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

from scripts.lib.agent_decision_payload import build_decision_payload  # noqa: E402
from scripts.lib.cio_decision_lineage_projection import project_decision_lineage  # noqa: E402

GUID = "sec_11111111-2222-3333-4444-555555555555"


def _entity(guid: str | None, status: str) -> dict:
    return {"schema": "RegisteredEntity@v1", "subject_guid": guid or "tkr_x", "security_guid": guid,
            "identity_status": status, "active": True, "aliases": []}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "identity_registry.json"
    doc = {
        "schema": "IdentityRegistry@v1",
        "entities": {
            GUID: _entity(GUID, "CONFIRMED"),
            "sec_candidate": _entity("sec_candidate", "CANDIDATE"),
            "tkr_unresolved": {**_entity(None, "UNRESOLVED_WITH_REASON"), "subject_guid": "tkr_unresolved"},
        },
        "by_symbol": {"SCHG": GUID, "NEWCO": "sec_candidate", "ZZZT": "tkr_unresolved"},
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(path))
    return path


def _payload(symbol, **extra):
    return build_decision_payload(decision_id=f"dec_holdings_{symbol}_HOLD", wake_id="wake_h", trace_id="tr_h",
                                  symbol=symbol, surface="holdings", current_action="HOLD", extra=extra or None)


def test_confirmed_symbol_is_stamped_and_security_identity_projects_live(registry, tmp_path, monkeypatch):
    payload = _payload("SCHG")
    assert payload["security_guid"] == GUID

    import scripts.api_v3_cio as api
    cio = tmp_path / "cio"
    cio.mkdir()
    trace = {"agent": "alex", "role": "holdings", "trace_id": "tr_h", "wake_id": "wake_h",
             "started_at": payload["as_of"], "ended_at": payload["as_of"], "status": "completed",
             "decision": payload}
    (cio / "agent_run_traces.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    nat = api._natural_runtime_decision(payload["decision_id"], cio)
    stage = project_decision_lineage(payload["decision_id"], decision=nat["decision"],
                                     decision_source="AgentRunTrace@v1")["stages"]["security_identity"]
    assert stage["state"] == "LIVE"
    assert stage["value"] == GUID


@pytest.mark.parametrize("symbol", ["ZZZT", "NEWCO", "NOTREG", None])
def test_unconfirmed_or_unknown_symbols_are_not_stamped(registry, symbol):
    payload = _payload(symbol)
    assert "security_guid" not in payload
    stage = project_decision_lineage(payload["decision_id"], decision={**payload, "source_ref": "x"},
                                     decision_source="AgentRunTrace@v1")["stages"]["security_identity"]
    assert stage["state"] != "LIVE"


def test_producer_supplied_guid_is_never_overwritten(registry):
    assert _payload("SCHG", security_guid="sec_from_producer")["security_guid"] == "sec_from_producer"
    stamped = _payload("SCHG", subject_guid="subj_from_producer")
    assert stamped["subject_guid"] == "subj_from_producer"
    assert "security_guid" not in stamped


def test_unreadable_or_broken_registry_still_builds(tmp_path, monkeypatch):
    bad = tmp_path / "identity_registry.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(bad))
    assert "security_guid" not in _payload("SCHG")

    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "missing.json"))
    assert "security_guid" not in _payload("SCHG")

    broken = types.ModuleType("scripts.lib.identity_registry")
    monkeypatch.setitem(sys.modules, "scripts.lib.identity_registry", broken)  # no load_cached -> ImportError
    payload = _payload("SCHG")
    assert payload["decision_id"] == "dec_holdings_SCHG_HOLD" and "security_guid" not in payload
