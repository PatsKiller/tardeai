"""HermesResearchLinks@v1 / AgentRuntimeProof@v1 — read-only reverse index tests."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib import cio_cross_surface_links as xs


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _fixture(root: Path) -> Path:
    cio = root / "cio"
    cio.mkdir()
    _jsonl(cio / "hermes_research_results.jsonl", [
        {"result_id": "rr_000000000001", "research_id": "res_000000000001", "symbol": "CSCO", "plan_id": "plan_1",
         "completed_ts": "2026-10-02T14:15:20+00:00", "provenance": {"agent": "hermes"}},
        {"result_id": "rr_000000000002", "research_id": "res_000000000002", "symbol": "PHIO",
         "completed_ts": "2026-10-02T15:45:31+00:00", "provenance": {"agent": "hermes"}},
    ])
    _jsonl(cio / "cio_research_impacts.jsonl", [
        {"schema": "ResearchImpact@v1", "result_id": "rr_000000000001", "new_product_id": "prod_abc",
         "impact": "NO_MATERIAL_CHANGE", "as_of": "2026-10-02T14:16:19+00:00"},
    ])
    (cio / "intelligence_lineages.json").write_text(json.dumps({"lineages": {
        "lin_1": {"research_result_ids": ["rr_000000000001"], "decision_id": "cio_books_1",
                  "advisory_use": {"product_id": "prod_abc", "at": "2026-10-02T14:16:21+00:00"},
                  "thesis_id": "desk@v5", "cio_case_id": "plan_1"},
    }}), encoding="utf-8")
    (cio / "cio_investment_brief.json").write_text(json.dumps({
        "decision_id": "cio_books_2", "as_of": "2026-10-02T15:00:00+00:00",
        "governed_verdicts": [{"thesis": {"symbol": "CSCO", "symbol_thesis_version": "symbol_csco@v3",
                                          "source_refs": ["rr_000000000001"]}}],
        "research_cases": {"items": []},
    }), encoding="utf-8")
    _jsonl(cio / "cio_workflow_lineage.jsonl", [
        {"record_type": "node", "node_id": "res_000000000001", "node_type": "RESEARCH", "workflow_id": "wf_1"},
    ])
    _jsonl(cio / "agent_run_traces.jsonl", [
        {"agent": "alex", "trigger": "material_scan", "status": "completed", "ended_at": "2026-10-02T15:45:19+00:00",
         "wake_id": "wake_1", "decision": {"decision_id": "dec_1"}},
        {"agent": "alex", "trigger": "manual", "status": "completed", "ended_at": "2026-10-02T16:00:00+00:00",
         "wake_id": "wake_manual", "decision": {"decision_id": "dec_2"}},
    ])
    _jsonl(cio / "aif_memory_retrievals.jsonl", [{"at": "2026-10-02T15:47:25+00:00", "query": "x", "retrieval_status": "OK"}])
    xs.clear_cache()
    return cio


def test_hermes_run_links_to_decisions_from_recorded_refs(tmp_path):
    cio = _fixture(tmp_path)
    out = xs.build_hermes_research_links(cio, limit=10)
    assert out["schema"] == "HermesResearchLinks@v1"
    item = next(i for i in out["items"] if i["result_id"] == "rr_000000000001")
    assert item["decision_link"]["state"] == "RECORDED"
    assert set(item["decision_ids"]) == {"prod_abc", "cio_books_1"}
    prod = next(d for d in item["decisions"] if d["id"] == "prod_abc")
    assert "cio_research_impacts.jsonl#ResearchImpact@v1" in prod["sources"]
    assert "intelligence_lineages.json#IntelligenceLineage@v1" in prod["sources"]
    assert set(item["thesis_refs"]) == {"desk@v5", "symbol_csco@v3"}
    assert item["symbol"] == "CSCO"
    assert item["workflow_ids"] == ["wf_1"]
    assert out["by_decision"]["prod_abc"] == ["rr_000000000001"]


def test_unreferenced_result_is_not_recorded_never_inferred(tmp_path):
    cio = _fixture(tmp_path)
    out = xs.build_hermes_research_links(cio, limit=10)
    item = next(i for i in out["items"] if i["result_id"] == "rr_000000000002")
    # Same day, other decisions exist — but no store names this result, so nothing is linked.
    assert item["decision_link"]["state"] == "NOT_RECORDED"
    assert item["decision_ids"] == []
    assert item["thesis_refs"] == []
    assert out["counts"]["decision_link_not_recorded"] == 1


def test_decision_filter_returns_only_consumed_results(tmp_path):
    cio = _fixture(tmp_path)
    out = xs.build_hermes_research_links(cio, decision_id="prod_abc")
    assert [i["result_id"] for i in out["items"]] == ["rr_000000000001"]


def test_agent_proof_separates_recorded_not_recorded_and_not_exposed(tmp_path):
    cio = _fixture(tmp_path)
    links = xs.build_hermes_research_links(cio, limit=10)
    proof = xs.build_agent_runtime_proof(cio, agent_ids=["alex", "sentinel", "hermes"], research_links=links)
    alex = proof["agents"]["alex"]
    assert alex["last_natural_wake"]["state"] == "RECORDED"
    assert alex["last_natural_wake"]["wake_id"] == "wake_1"  # manual trigger is not a natural wake
    assert alex["decisions_contributed"]["value"] == 2
    assert alex["last_memory_retrieval"]["state"] == "NOT_EXPOSED"
    assert proof["fields"]["last_memory_retrieval"]["attributable"] is False
    assert proof["agents"]["sentinel"]["last_natural_wake"]["state"] == "NOT_RECORDED"
    hermes = proof["agents"]["hermes"]
    assert hermes["last_research_action"]["state"] == "RECORDED"
    assert hermes["last_research_action"]["value"] == "rr_000000000002"
    assert hermes["decisions_contributed"]["state"] == "RECORDED"
    assert proof["financial_action"] is False


def test_api_dispatch_serves_links_read_only(tmp_path, monkeypatch):
    cio = _fixture(tmp_path)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio))
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import api_v3_hermes

    out = api_v3_hermes.get_hermes_research_links({"result_id": ["rr_000000000001"]})
    assert out["items"][0]["decision_link"]["state"] == "RECORDED"
    proof = api_v3_hermes.get_agent_runtime_proof({"agents": "alex"})
    assert "alex" in proof["agents"]
