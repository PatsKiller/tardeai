from pathlib import Path

from scripts.lib.cio_lineage import LineageStore, record_hermes_completion, record_hermes_request


def test_hermes_lineage_is_idempotent_and_checkpoints(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-1", "research_id": "research-1", "symbol": "SCHD", "reason": "operator requested"}
    workflow = record_hermes_request(request, path=path)
    assert workflow.startswith("wf_")
    record_hermes_request(request, path=path)
    result = record_hermes_completion(request, {"research_id": "research-1", "result_id": "result-1", "summary": "fresh evidence"}, path=path)
    assert result["workflow_id"] == workflow
    assert result["checkpoint_id"].startswith("cp_")
    before = path.read_text()
    record_hermes_completion(request, {"research_id": "research-1", "result_id": "result-1", "summary": "fresh evidence"}, path=path)
    assert path.read_text() == before


def test_lineage_never_grants_execution_authority(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "p", "research_id": "r", "symbol": "SCHG"}
    record_hermes_completion(request, {"research_id": "r", "result_id": "rr"}, path=path)
    assert '"authority": "READ_ONLY_ADVISORY"' in path.read_text()
