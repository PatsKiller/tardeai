from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_runtime" / "lab_classify_readonly.sh"


def _text() -> str:
    return SCRIPT.read_text()


def test_classifier_is_bound_to_isolated_lab_cluster() -> None:
    text = _text()
    assert "/usr/bin/psql" in text
    assert "/home/johnclaw/tradeai-lab/sock" in text
    assert "LAB_PORT=5433" in text
    assert "/home/johnclaw/tradeai-lab/pg17" in text
    assert "trade_ai_agentic_lab" in text
    assert "5432_FORBIDDEN" in text


def test_classifier_uses_noninteractive_peer_metadata_access() -> None:
    text = _text()
    assert "-w -X -v ON_ERROR_STOP=1" in text
    assert "expected LAB socket is unavailable" in text
    assert "REFUSED_NON_LAB_TARGET" in text
    assert "READ_ONLY_METADATA_NO_ROW_CONTENTS" in text


def test_classifier_contains_no_database_mutation_sql() -> None:
    text = _text().upper()
    forbidden = (
        "CREATE DATABASE",
        "DROP DATABASE",
        "CREATE ROLE",
        "ALTER ROLE",
        "DROP ROLE",
        "CREATE SCHEMA",
        "DROP SCHEMA",
        "GRANT ",
        "REVOKE ",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "TRUNCATE ",
        "COPY ",
    )
    for token in forbidden:
        assert token not in text


def test_classifier_does_not_read_application_rows() -> None:
    text = _text().lower()
    assert "select *" not in text
    assert "table_count" in text
    assert "view_count" in text
    assert "sequence_count" in text
    assert "user_relation_count" in text
