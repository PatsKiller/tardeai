"""Capital-plan decisions carry the versioned sizing policy that computed them.

Prod 2026-10-03: build_position_decisions stamped decision_policy_version on each
per-account row, but aggregate_position_decisions (the rows actually served) did
not preserve it, so 0 of 21 live decisions carried it and the canon_frameworks
stage had no methodology_ref. The version is not an input to decision_id or the
digests, so carrying it cannot churn an id.
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

from scripts.lib import cio_capital_plan as cp  # noqa: E402


def _build():
    pv = 500_000.0
    queue = {"items": [{"symbol": "V", "verdict": None, "directive_label": "Advisory TRIM — V", "source": "advisory"}]}
    positions = [
        cp.normalize_position({"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"}, pv),
        cp.normalize_position({"symbol": "V", "market_value": 30_000.0, "account": "schwab_taxable"}, pv),
        cp.normalize_position({"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"}, pv),
    ]
    return cp.build_position_decisions(positions, queue=queue, portfolio_value=pv)


def test_every_served_decision_records_the_real_policy_version():
    rows = _build()
    assert rows
    assert {r.get("decision_policy_version") for r in rows} == {cp.CAPITAL_PLAN_VERSION}


def test_policy_version_is_not_a_hash_input_so_ids_never_churn(monkeypatch):
    before = {r["symbol"]: (r["decision_id"], r["decision_input_digest"], r["decision_evidence_digest"]) for r in _build()}
    monkeypatch.setattr(cp, "CAPITAL_PLAN_VERSION", "capital_plan_9.9.9")
    rows = _build()
    after = {r["symbol"]: (r["decision_id"], r["decision_input_digest"], r["decision_evidence_digest"]) for r in rows}
    assert after == before
    assert {r["decision_policy_version"] for r in rows} == {"capital_plan_9.9.9"}


@pytest.fixture
def lineage_env(tmp_path, monkeypatch):
    root = tmp_path / "cio"
    root.mkdir()
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl", "outcome_checkpoints.jsonl",
                 "decision_dispositions.jsonl", "agent_run_traces.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    # A row stored before this fix: no methodology_ref, as the 21 live rows are.
    (root / "cio_capital_plan_decisions.jsonl").write_text(json.dumps({
        "schema": "CIOCapitalPlanDecision@v1", "decision_id": "dec_0123456789abcdef", "symbol": "SCHD", "action": "Hold",
        "recorded_at": "2026-10-03T14:54:00+00:00", "source_ref": "cio_capital_plan_decisions:dec_0123456789abcdef",
        "producer": "api_v2._cio_capital_plan",
    }) + "\n", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: None
    monkeypatch.setitem(sys.modules, "api_v2", stub)
    import scripts.api_v3_cio as api
    return api


def _canon(api, monkeypatch, live_row):
    monkeypatch.setattr(api, "load_known_decision_catalog",
                        lambda: api.catalog_from_position_decisions([live_row]))
    result = api.get_cio_decision_lineage("dec_0123456789abcdef")
    assert result["ok"] is True, result
    return result["lineage"]["stages"]["canon_frameworks"]


def test_live_policy_version_reaches_the_canon_stage(lineage_env, monkeypatch):
    stage = _canon(lineage_env, monkeypatch, {"decision_id": "dec_0123456789abcdef", "symbol": "SCHD", "stance": "Hold",
                                              "decision_policy_version": "capital_plan_1.3.0"})
    assert stage["state"] == "LIVE"
    assert stage["value"] == "capital_plan_1.3.0"


def test_a_live_row_without_a_version_never_masks_a_stored_one(lineage_env, monkeypatch):
    stage = _canon(lineage_env, monkeypatch, {"decision_id": "dec_0123456789abcdef", "symbol": "SCHD", "stance": "Hold"})
    assert stage["state"] != "LIVE"
    assert stage["value"] is None


def test_only_operator_ratified_claims_become_methodology_refs(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    store = tmp_path / "canon_claims.jsonl"
    claims = [
        {"schema": "CanonClaim@v1", "claim_id": "claim_ratified", "status": "RATIFIED_ADVISORY", "decision_eligible": True},
        {"schema": "CanonClaim@v1", "claim_id": "claim_shadow", "status": "SHADOW", "decision_eligible": False},
        {"schema": "CanonClaim@v1", "claim_id": "claim_ratified_ineligible", "status": "RATIFIED_ADVISORY", "decision_eligible": False},
    ]
    store.write_text("".join(json.dumps({"claim": c}) + "\n" for c in claims), encoding="utf-8")
    monkeypatch.setenv("CIO_CANON_CLAIMS_JSONL", str(store))
    assert api._ratified_methodology_refs() == ["claim_ratified"]
    monkeypatch.setenv("CIO_CANON_CLAIMS_JSONL", str(tmp_path / "missing.jsonl"))
    assert api._ratified_methodology_refs() == []
