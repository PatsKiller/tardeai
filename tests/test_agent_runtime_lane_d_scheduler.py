from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.agent_runtime.agents import run_once
from scripts.agent_runtime.agents.definitions import FLEET, SECOND_WAVE_AGENT_IDS

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations" / "agentic_runtime"
UNITS = ROOT / "config" / "systemd" / "agent_runtime"


# ---- apply.sh: prepare-only / refuses without --apply -----------------------

def test_apply_script_refuses_without_apply_flag() -> None:
    result = subprocess.run(
        ["bash", str(MIG / "apply.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3
    assert "PREPARE-ONLY" in result.stdout
    assert "no --apply flag" in result.stdout.lower()


def test_apply_script_refuses_apply_without_dsn() -> None:
    result = subprocess.run(
        ["bash", str(MIG / "apply.sh"), "--apply", "up"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 4
    assert "refusing to apply" in result.stderr.lower()


def test_apply_script_refuses_production_dsn() -> None:
    result = subprocess.run(
        ["bash", str(MIG / "apply.sh"), "--apply", "up"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TRADE_AI_LAB_DSN": "postgres://h/trade_ai_prod"},
    )
    assert result.returncode == 5
    assert "production" in result.stderr.lower()


# ---- role SQL: least privilege ---------------------------------------------

def _statements(path: Path) -> list[str]:
    """SQL statements with line comments stripped, split on semicolons."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("--")]
    body = " ".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def test_role_sql_creates_three_scoped_roles_without_elevation() -> None:
    sql = (MIG / "0002_roles.up.sql").read_text(encoding="utf-8")
    for role in ("agentic_runtime_lab_rw", "agentic_runtime_shadow_rw", "agentic_runtime_reader"):
        assert f"CREATE ROLE {role}" in sql
    # No elevated attributes anywhere.
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in sql
    assert "SUPERUSER LOGIN" not in sql
    # Every table-level GRANT is scoped to agentic_runtime.<table> only.
    for stmt in _statements(MIG / "0002_roles.up.sql"):
        if stmt.startswith("GRANT") and " ON " in stmt and " ON SCHEMA" not in stmt and "ALL TABLES IN SCHEMA agentic_runtime" not in stmt:
            assert "agentic_runtime." in stmt, stmt


def test_reader_role_is_read_only() -> None:
    sql = (MIG / "0002_roles.up.sql").read_text(encoding="utf-8")
    assert "REVOKE INSERT, UPDATE, DELETE" in sql
    # Reader is only ever granted USAGE or SELECT, never a write privilege.
    for stmt in _statements(MIG / "0002_roles.up.sql"):
        if stmt.startswith("GRANT") and "agentic_runtime_reader" in stmt:
            grant_clause = stmt.split(" ON ", 1)[0]
            assert "INSERT" not in grant_clause
            assert "UPDATE" not in grant_clause
            assert "DELETE" not in grant_clause


def test_no_trading_or_broker_tables_referenced_in_roles() -> None:
    # Scan only privilege statements; COMMENT prose legitimately names the deny list.
    grants = " ".join(
        s for s in _statements(MIG / "0002_roles.up.sql")
        if s.startswith(("GRANT", "REVOKE", "ALTER DEFAULT PRIVILEGES"))
    ).lower()
    for forbidden in ("trade_approvals", "schwab", "broker", "positions", "orders", "two_factor", "2fa", "account_"):
        assert forbidden not in grants, forbidden


def test_roles_down_drops_all_three_roles() -> None:
    sql = (MIG / "0002_roles.down.sql").read_text(encoding="utf-8")
    for role in ("agentic_runtime_lab_rw", "agentic_runtime_shadow_rw", "agentic_runtime_reader"):
        assert f"DROP ROLE {role}" in sql


# ---- run_once.py: fail-closed ----------------------------------------------

def test_run_once_refuses_without_operator_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RUNTIME_OPERATOR_AUTH", raising=False)
    rc = run_once.main(["--agent", "sentinel", "--once"])
    assert rc == run_once.EX_NOPERM


def test_run_once_refuses_disabled_agent_even_with_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_OPERATOR_AUTH", "1")
    monkeypatch.setenv("AGENT_RUNTIME_QUEUE_MODULE", "some.module")
    rc = run_once.main(["--agent", SECOND_WAVE_AGENT_IDS[0], "--once"])
    assert rc == run_once.EX_NOPERM


def test_run_once_refuses_without_queue_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_OPERATOR_AUTH", "1")
    monkeypatch.delenv("AGENT_RUNTIME_QUEUE_MODULE", raising=False)
    rc = run_once.main(["--agent", "sentinel", "--once"])
    assert rc == run_once.EX_CONFIG


def test_run_once_never_dispatches_in_this_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_OPERATOR_AUTH", "1")
    monkeypatch.setenv("AGENT_RUNTIME_QUEUE_MODULE", "some.module")
    rc = run_once.main(["--agent", "sentinel", "--once"])
    assert rc == run_once.EX_CONFIG  # named but dispatch disabled


# ---- systemd units: disabled + gated ---------------------------------------

def test_units_are_present_and_gated_disabled() -> None:
    service = (UNITS / "tradeai-agent-runtime@.service").read_text(encoding="utf-8")
    timer = (UNITS / "tradeai-agent-runtime@.timer").read_text(encoding="utf-8")
    assert "ConditionPathExists=/etc/tradeai/agent_runtime_enabled" in service
    assert "ConditionPathExists=/etc/tradeai/agent_runtime_enabled" in timer
    assert "AGENT_RUNTIME_OPERATOR_AUTH=0" in service
    assert "Type=oneshot" in service
    assert "--once" in service
    assert "NoNewPrivileges=true" in service


def test_every_agent_has_a_documented_queue_instance() -> None:
    readme = (UNITS / "README.md").read_text(encoding="utf-8")
    for agent_id in FLEET:
        assert f"tradeai-agent-runtime@{agent_id}" in readme
