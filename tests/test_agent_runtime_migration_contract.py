from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "migrations" / "agentic_runtime" / "0001_mvl.up.sql"
DOWN = ROOT / "migrations" / "agentic_runtime" / "0001_mvl.down.sql"


def test_mvl_schema_contains_only_the_minimum_eight_tables() -> None:
    sql = UP.read_text(encoding="utf-8")
    expected = {
        "agent_runs",
        "agent_artifacts",
        "agent_tool_calls",
        "agent_reviews",
        "agent_scores",
        "kb_lessons",
        "kb_cases",
        "kb_chunks",
    }
    created = {
        line.split("agentic_runtime.", 1)[1].split(" ", 1)[0].strip()
        for line in sql.splitlines()
        if line.startswith("CREATE TABLE agentic_runtime.")
    }
    assert created == expected


def test_schema_is_shadow_lab_only_and_independent_review_is_enforced() -> None:
    sql = UP.read_text(encoding="utf-8")
    assert "environment IN ('LAB', 'SHADOW')" in sql
    assert sql.count("CHECK (producer_agent_id <> reviewer_agent_id)") == 1
    assert sql.count("CHECK (producer_agent_id <> scorer_agent_id)") == 1
    assert "reject_append_only_mutation" in sql
    assert "BEFORE UPDATE OR DELETE" in sql


def test_embedding_rows_require_versioned_provenance() -> None:
    sql = UP.read_text(encoding="utf-8")
    assert "embedding_provider" in sql
    assert "embedding_model" in sql
    assert "embedding_version" in sql
    assert "embedding_provider IS NOT NULL AND embedding_model IS NOT NULL AND embedding_version IS NOT NULL" in sql


def test_migration_has_one_step_rollback() -> None:
    down = DOWN.read_text(encoding="utf-8")
    assert "DROP SCHEMA IF EXISTS agentic_runtime CASCADE" in down
