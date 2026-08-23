from scripts.audit_no_local_generative_routing import audit
from scripts.lib.llm_task_policy import allow_local_llm


def test_production_automatic_routing_has_no_local_generation():
    report = audit()
    assert report["violations"] == []
    assert "scripts/watchlist_entry_planner.py" in report["production_files"]
    assert "scripts/directive_keyword_enhancer.py" in report["production_files"]


def test_runtime_flags_cannot_enable_generation(monkeypatch):
    monkeypatch.setenv("RESEARCH_ALLOW_LOCAL_LLM", "1")
    monkeypatch.setenv("LLM_ALLOW_LOCAL_JUDGMENT", "1")
    for task in ("math", "research", "sentiment", "thesis", "cio_synthesis"):
        assert allow_local_llm(task) is False


def test_embedding_contract_is_the_only_local_allowance():
    assert allow_local_llm("embed", local_model="nomic-embed-text") is True
    assert allow_local_llm("embed", local_model="unapproved") is False


def test_physical_decommission_gate_reports_all_source_callers():
    report = audit()
    assert "source_callers" in report
    assert report["source_caller_count"] == len(report["source_callers"])
    assert report["physical_decommission_ready"] is (
        report["violation_count"] == 0 and report["source_caller_count"] == 0
    )
    for row in report["source_callers"]:
        assert row["file"].startswith("scripts/")
        assert int(row["line"]) > 0
        assert row["kind"] in {"generative_endpoint", "local_lane", "local_helper"}


def test_active_cloud_migrations_have_no_local_escape():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    planner = (root / "scripts" / "watchlist_entry_planner.py").read_text(encoding="utf-8")
    enhancer = (root / "scripts" / "directive_keyword_enhancer.py").read_text(encoding="utf-8")
    assert 'default="grok"' in planner
    assert 'choices=list(CLOUD_LANES)' in planner
    assert 'lane="local"' not in planner
    assert '("grok", "chatgpt", "local")' not in enhancer
