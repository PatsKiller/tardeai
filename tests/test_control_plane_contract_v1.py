"""Frozen ControlPlane@v1.0.0 — fixtures parse; UI must not invent states."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.control_plane_contract_v1 import (
    EVIDENCE_CLASS,
    RUNTIME_STATUS,
    SCHEMA,
    WORKFLOW_NODE_KINDS,
    contract_version,
    list_fixtures,
    load_fixture,
    validate_envelope,
)

ROOT = Path(__file__).resolve().parents[1]


def test_version_file_matches_schema():
    assert contract_version() == SCHEMA == "ControlPlane@v1.0.0"


def test_all_fixtures_validate():
    names = list_fixtures()
    assert set(names) >= {
        "agents", "workflows", "research", "stores", "identity",
        "notifications", "learning", "maturity", "audit", "system",
    }
    for name in names:
        doc = load_fixture(name)
        assert validate_envelope(doc) == []


def test_agents_fixture_covers_all_runtime_states():
    states = {a["state"] for a in load_fixture("agents")["payload"]["agents"]}
    assert set(RUNTIME_STATUS) <= states


def test_workflow_fixture_has_full_lineage():
    traces = load_fixture("workflows")["payload"]["traces"]
    kinds = [n["kind"] for n in traces[0]["nodes"]]
    assert kinds == list(WORKFLOW_NODE_KINDS)
    assert traces[0]["evidence_class"] in EVIDENCE_CLASS


def test_identity_never_mints():
    assert load_fixture("identity")["payload"]["never_mint_from_ticker"] is True
    states = {r["state"] for r in load_fixture("identity")["payload"]["rows"]}
    assert "UNRESOLVED_WITH_REASON" in states
    assert "CONFIRMED" in states


def test_learning_kinds_required_by_r24():
    kinds = {i["kind"] for i in load_fixture("learning")["payload"]["items"]}
    assert {
        "decision", "checkpoint", "outcome", "lesson", "hypothesis",
        "experiment", "specialist_performance", "model_performance",
        "routing_candidate",
    } <= kinds
    assert load_fixture("learning")["payload"]["auto_promotions"] == 0


def test_ts_contract_exists_and_does_not_infer():
    src = (ROOT / "apps/command-center-v3/src/control-plane/contractV1.ts").read_text()
    assert "ControlPlane@v1.0.0" in src
    assert "LIVE_EVENT_DRIVEN" in src
    assert "inferRuntime" not in src


def test_envelope_rejects_frontend_computation_flags():
    doc = load_fixture("agents")
    bad = dict(doc, computes_maturity=True)
    errs = validate_envelope(bad)
    assert any("computes_maturity" in e for e in errs)
