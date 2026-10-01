"""CIO operator-evidence composition tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_operator_evidence import build_operator_evidence  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def test_retrieved_used_and_rejected_are_distinct_and_receipt_driven(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [
        {"result_id": "res_retrieved", "symbol": "AAA", "created_at": "2026-10-01T10:00:00Z"},
        {"result_id": "res_used", "symbol": "BBB", "used_in_judgment": True, "decision_id": "dec_1", "created_at": "2026-10-01T11:00:00Z"},
        {"result_id": "res_rejected", "symbol": "CCC", "rejection_reason": "contradictory source", "created_at": "2026-10-01T12:00:00Z"},
    ])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    research = result["blocks"]["research"]
    assert research["counts"] == {"retrieved": 1, "used_in_judgment": 1, "rejected": 1, "unknown": 0}
    assert research["used_in_judgment"][0]["decision_id"] == "dec_1"
    assert research["rejected"][0]["reason_used_or_rejected"] == "contradictory source"


def test_missing_receipt_is_not_rejected_or_used(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [{"result_id": "res_unknown", "symbol": "AAA"}])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    artifact = result["blocks"]["research"]["artifacts"][0]
    assert artifact["status"] == "RETRIEVED"
    assert artifact.get("decision_id") is None


def test_source_clock_does_not_advance_when_only_composition_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [{"result_id": "res_clock", "created_at": "2026-10-01T10:00:00Z"}])
    first = build_operator_evidence(now="2026-10-01T11:00:00Z")
    second = build_operator_evidence(now="2026-10-01T12:00:00Z")
    assert first["source_as_of"] == second["source_as_of"] == "2026-10-01T10:00:00Z"
    assert first["composition_as_of"] != second["composition_as_of"]


def test_capability_state_is_backend_runtime_census_not_frontend_field_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "cio_specialist_artifacts.jsonl", [{"artifact_id": "sp_1", "created_at": "2026-10-01T09:00:00Z"}])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    rows = {row["capability"]: row for row in result["blocks"]["capability_coverage"]["rows"]}
    assert rows["specialist artifacts"]["current_status"] == "LIVE"
    assert rows["specialist artifacts"]["reason"] == "durable producer and consumer evidence observed"
    assert rows["InstrumentRecord"]["current_status"] in {"PARTIAL", "DARK", "UNWIRED"}
    assert result["authority"] == "READ_ONLY_ADVISORY"
    assert result["financial_action"] is False
    assert result["mutation"] is False


def test_cio_operator_evidence_api_route_is_read_only():
    import scripts.api_v2 as api_v2

    status, payload = api_v2.handle("/api/v3/cio/operator-evidence")
    assert status == 200
    assert payload["schema"] == "CIOOperatorEvidence@v1"
    assert payload["authority"] == "READ_ONLY_ADVISORY"
    assert payload["financial_action"] is False
