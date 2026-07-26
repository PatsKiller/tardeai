from __future__ import annotations

import pytest

from scripts.agent_runtime.lab_preflight import (
    DISPOSABLE_ACK,
    LabPreflightError,
    LabTarget,
    psql_argv,
)


def good_target(**overrides: object) -> LabTarget:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 5433,
        "database": "trade_ai_agentic_lab",
        "data_directory": "/home/johnclaw/tradeai-lab/pg17",
        "migration_role": "agentic_lab_migrator",
        "reader_role": "trade_ai_shadow_ro",
        "writer_role": "agentic_runtime_lab_rw",
        "disposable_ack": DISPOSABLE_ACK,
    }
    values.update(overrides)
    return LabTarget(**values)  # type: ignore[arg-type]


def test_valid_inventoried_lab_target_passes() -> None:
    target = good_target()
    target.validate()
    summary = target.sanitized_summary()
    assert summary["port"] == 5433
    assert summary["disposable_ack_verified"] is True
    assert summary["dsn_or_secret_included"] is False
    assert "disposable_ack" not in summary


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"port": 5432}, "production PostgreSQL port 5432 is forbidden"),
        ({"database": "trade_ai"}, "explicitly named disposable LAB database"),
        ({"database": "postgres"}, "explicitly named disposable LAB database"),
        ({"data_directory": "/var/lib/postgresql/17/main"}, "production PostgreSQL data directory"),
        ({"data_directory": "/tmp/pg17"}, "must be beneath /home/johnclaw/tradeai-lab"),
        ({"host": "0.0.0.0"}, "explicit loopback"),
        ({"disposable_ack": ""}, "acknowledgement is required"),
        ({"reader_role": "hermes_readonly"}, "reader_role must be trade_ai_shadow_ro"),
        ({"writer_role": "trade_ai"}, "writer_role must be agentic_runtime_lab_rw"),
        ({"migration_role": "postgres"}, "migration_role must be an explicit lowercase migrator identity"),
        ({"migration_role": "AGENTIC_LAB_MIGRATOR"}, "migration_role must be an explicit lowercase migrator identity"),
    ],
)
def test_invalid_or_production_like_targets_fail(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(LabPreflightError, match=message):
        good_target(**overrides).validate()


def test_psql_command_is_explicit_and_alias_proof() -> None:
    argv = psql_argv(good_target(), role="agentic_lab_migrator")
    assert argv[0] == "/usr/bin/psql"
    assert ("-h", "127.0.0.1") == (argv[4], argv[5])
    assert ("-p", "5433") == (argv[6], argv[7])
    assert "trade_ai_agentic_lab" in argv
    assert "5432" not in argv
    assert not any("password" in item.lower() or "://" in item for item in argv)


def test_unapproved_role_cannot_receive_command() -> None:
    with pytest.raises(LabPreflightError, match="three approved LAB identities"):
        psql_argv(good_target(), role="trade_ai")
