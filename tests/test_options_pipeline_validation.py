#!/usr/bin/env python3
"""Options pipeline Stage B — paper-outcome ledger + validation gate (advisory).

Covers: outcome recording (upsert shape, honest-input refusals, DB-down honesty),
gate math at exact boundaries (n / profit factor / win rate / calendar months),
the gate-met message ("operator decision required" — never an enablement), the
no-live-enablement invariant (source inspection: the validation module and CLI
have NO write path to execution flags, strategy status, or the strategy YAML),
registry maturity updates touching ONLY trades_taken + metadata, and migration
idempotency (every statement IF NOT EXISTS, purely additive).

    .venv/bin/python -m pytest tests/test_options_pipeline_validation.py -q
"""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import validation as val  # noqa: E402

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


# ── helpers ──────────────────────────────────────────────────────────────────

class FakeExecutor:
    """Captures SQL + params; returns canned rows for fetches."""

    def __init__(self, rows=None, fail=False):
        self.calls = []
        self.rows = rows or []
        self.fail = fail

    def __call__(self, sql, params=None, fetch=None):
        self.calls.append({"sql": sql, "params": params, "fetch": fetch})
        if self.fail:
            return None
        if fetch == "all":
            return self.rows
        return True


def _outcome(i, outcome="win", pnl=100.0, months_ago=4.0, strategy="deep_itm_call"):
    closed = NOW - timedelta(days=months_ago * val.AVG_MONTH_DAYS)
    return {"proposal_id": f"opt_deep_itm_call_SYM{i}", "strategy_id": strategy,
            "symbol": f"SYM{i}", "outcome": outcome, "pnl": pnl,
            "closed_at": closed.isoformat()}


def _outcome_set(wins, losses, *, win_pnl=130.0, loss_pnl=-100.0, first_months_ago=4.0):
    """wins+losses outcomes; the FIRST one is `first_months_ago` old, rest recent."""
    rows = []
    for i in range(wins):
        rows.append(_outcome(i, "win", win_pnl,
                             months_ago=first_months_ago if i == 0 else 0.5))
    for i in range(losses):
        rows.append(_outcome(1000 + i, "loss", loss_pnl,
                             months_ago=first_months_ago if not rows else 0.5))
    return rows


# ── (1) outcome recording ────────────────────────────────────────────────────

def test_record_outcome_upserts_into_ledger():
    ex = FakeExecutor()
    res = val.record_outcome(
        "opt_deep_itm_call_NVDA_paper_model_150p0000_20261016",
        outcome="win", symbol="nvda", pnl=850.0, entry_debit=5500.0,
        exit_value=6350.0, exit_reason="dte_21_roll",
        meta={"discovery_ref": {"candidate_id": 339}}, executor=ex)
    assert res["ok"] is True and res["outcome"] == "win"
    call = ex.calls[0]
    assert "INSERT INTO options_paper_outcomes" in call["sql"]
    assert "ON CONFLICT (proposal_id) DO UPDATE" in call["sql"]   # re-record corrects
    params = call["params"]
    assert params[0].startswith("opt_deep_itm_call_NVDA")
    assert params[1] == "deep_itm_call"
    assert params[2] == "NVDA"                                    # symbol normalized
    assert json.loads(params[-1])["discovery_ref"]["candidate_id"] == 339


def test_record_outcome_refuses_bad_input():
    ex = FakeExecutor()
    assert val.record_outcome("", outcome="win", executor=ex)["ok"] is False
    assert val.record_outcome("p1", outcome="banana", executor=ex)["ok"] is False
    assert val.record_outcome("p1", outcome="win", strategy_id="momentum_scalp",
                              executor=ex)["ok"] is False
    # contradiction guards — a mislabeled outcome would poison the gate math
    assert val.record_outcome("p1", outcome="win", pnl=-50.0, executor=ex)["ok"] is False
    assert val.record_outcome("p1", outcome="loss", pnl=50.0, executor=ex)["ok"] is False
    assert ex.calls == []                                          # nothing written


def test_record_outcome_reports_db_down_honestly():
    res = val.record_outcome("p1", outcome="win", pnl=1.0, executor=FakeExecutor(fail=True))
    assert res["ok"] is False and "NOT recorded" in res["error"]


# ── (2) gate math — exact boundaries ─────────────────────────────────────────

def test_metrics_empty_ledger():
    m = val.compute_gate_metrics([], now=NOW)
    assert m["n_closed"] == 0 and m["win_rate"] is None
    assert m["profit_factor"] is None and m["calendar_months"] == 0.0


def test_metrics_win_rate_scratch_neutral():
    rows = _outcome_set(6, 4) + [_outcome(99, "scratch", 0.0, months_ago=0.2)]
    m = val.compute_gate_metrics(rows, now=NOW)
    assert m["n_closed"] == 11 and m["scratches"] == 1
    assert m["win_rate"] == 0.6                    # 6/(6+4) — scratch not in WR
    assert m["profit_factor"] == round(6 * 130.0 / (4 * 100.0), 4)
    assert m["net_pnl"] == round(6 * 130.0 - 4 * 100.0, 2)


def test_metrics_profit_factor_undefined_without_losses():
    m = val.compute_gate_metrics(_outcome_set(5, 0), now=NOW)
    assert m["profit_factor"] is None              # never inf, never fabricated
    assert "no losing trades" in m["profit_factor_note"]


def test_gate_boundary_n_trades():
    gate = {"min_closed_paper_trades": 30, "min_win_rate": 0.55,
            "min_profit_factor": 1.3, "min_calendar_months": 3}
    # 29 trades → n fails even with stellar PF/WR
    rows29 = _outcome_set(20, 9)
    v = val.evaluate_gate(val.compute_gate_metrics(rows29, now=NOW), gate)
    assert v["gate_met"] is False
    assert any(c["id"] == "min_closed_paper_trades" and not c["pass"] for c in v["checks"])
    assert "29/30" in v["message"]
    # 30 trades at exactly the thresholds → all pass
    rows30 = _outcome_set(18, 12, win_pnl=130.0, loss_pnl=-100.0)   # WR .60, PF 1.95
    v = val.evaluate_gate(val.compute_gate_metrics(rows30, now=NOW), gate)
    assert v["gate_met"] is True


def test_gate_boundary_profit_factor():
    gate = {"min_closed_paper_trades": 4, "min_win_rate": 0.40,
            "min_profit_factor": 1.3, "min_calendar_months": 3}
    # PF exactly 1.3: 2 wins ×130 / 2 losses ×100 = 1.3 → pass (gte)
    at = val.compute_gate_metrics(_outcome_set(2, 2, win_pnl=130.0), now=NOW)
    assert at["profit_factor"] == 1.3
    assert val.evaluate_gate(at, gate)["gate_met"] is True
    # PF 1.29 → fail
    below = val.compute_gate_metrics(_outcome_set(2, 2, win_pnl=129.0), now=NOW)
    v = val.evaluate_gate(below, gate)
    assert v["gate_met"] is False
    assert any(c["id"] == "min_profit_factor" and not c["pass"] for c in v["checks"])


def test_gate_boundary_win_rate():
    gate = {"min_closed_paper_trades": 20, "min_win_rate": 0.55,
            "min_profit_factor": 1.0, "min_calendar_months": 3}
    # 11/20 = .55 exactly → pass
    v = val.evaluate_gate(val.compute_gate_metrics(_outcome_set(11, 9), now=NOW), gate)
    assert v["gate_met"] is True
    # 10/20 = .50 → fail on WR (PF still fine: 10×130 vs 10×100)
    v = val.evaluate_gate(val.compute_gate_metrics(_outcome_set(10, 10), now=NOW), gate)
    assert v["gate_met"] is False
    assert any(c["id"] == "min_win_rate" and not c["pass"] for c in v["checks"])


def test_gate_boundary_calendar_months():
    gate = {"min_closed_paper_trades": 4, "min_win_rate": 0.40,
            "min_profit_factor": 1.0, "min_calendar_months": 3}
    young = val.compute_gate_metrics(
        _outcome_set(3, 1, first_months_ago=2.5), now=NOW)
    v = val.evaluate_gate(young, gate)
    assert v["gate_met"] is False
    assert any(c["id"] == "min_calendar_months" and not c["pass"] for c in v["checks"])
    aged = val.compute_gate_metrics(
        _outcome_set(3, 1, first_months_ago=3.2), now=NOW)
    assert val.evaluate_gate(aged, gate)["gate_met"] is True


def test_gate_met_is_a_report_not_a_switch():
    rows = _outcome_set(20, 10)                     # WR .667, PF 2.6, 4 months
    report = val.validation_status("deep_itm_call", outcomes=rows, now=NOW)
    assert report["ok"] is True and report["gate_met"] is True
    assert "operator decision required" in report["message"]
    assert report["advisory_only"] is True
    # config echo still shows the paper lock — the gate changed nothing
    assert report["execution"]["live_allowed"] is False
    assert report["paper_only"] is True
    assert report["progress_label"] == "paper validation 30/30"


def test_gate_not_met_message_and_progress_label():
    report = val.validation_status("deep_itm_call", outcomes=_outcome_set(2, 1), now=NOW)
    assert report["gate_met"] is False
    assert report["message"].startswith("gate not met")
    assert report["progress_label"] == "paper validation 3/30"
    assert val.validation_status("covered_call", outcomes=[])["ok"] is False


# ── (3) registry maturity — advisory blob only ───────────────────────────────

def test_registry_update_touches_only_trades_taken_and_metadata():
    ex = FakeExecutor()
    report = val.validation_status("deep_itm_call", outcomes=_outcome_set(3, 2), now=NOW)
    res = val.update_registry_maturity("deep_itm_call", executor=ex, status_report=report)
    assert res["ok"] is True
    assert res["paper_validation"]["advisory_only"] is True
    sql = ex.calls[-1]["sql"]
    assert "UPDATE strategy_registry" in sql
    # ONLY these columns may be written — never lifecycle/eligibility/activation
    set_clause = sql.split("SET", 1)[1].split("WHERE", 1)[0]
    for forbidden in ("status", "active", "live", "execution", "eligible",
                      "paper_only", "allowed"):
        assert forbidden not in set_clause.lower(), f"registry write touches '{forbidden}'"
    assert "trades_taken" in set_clause and "metadata" in set_clause


# ── (4) no-live-enablement invariant — source inspection ─────────────────────

VALIDATION_SOURCES = [
    ROOT / "scripts" / "lib" / "options_pipeline" / "validation.py",
    ROOT / "scripts" / "options_validation_status.py",
]
FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service",
    "schwab_transport", "schwab_pilot_orders", "alpaca_trade_api", "alpaca",
    "trade_executor", "order_executor", "telegram_2fa", "two_factor",
    "options_execution_policy",
}


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def test_validation_module_has_no_live_allowed_write_path():
    """live_allowed may be READ (config echo) but never assigned/UPDATEd/dumped."""
    for path in VALIDATION_SOURCES:
        src = path.read_text(encoding="utf-8")
        # no YAML/config write surface at all
        assert "yaml.dump" not in src and "yaml.safe_dump" not in src
        assert not re.search(r"open\([^)]*['\"]w['\"]", src), f"{path.name} opens a file for write"
        # no SQL UPDATE may mention live/status/active/execution columns
        for m in re.finditer(r"UPDATE\s+\w+.*?(?=\"\"\")", src, re.S | re.I):
            stmt = m.group(0).lower()
            for forbidden in ("live_allowed", "live_eligible", "status", "active",
                              "execution_mode", "paper_only"):
                assert forbidden not in stmt, \
                    f"{path.name} SQL write path touches '{forbidden}'"
        # no python assignment ever sets a live/execution flag
        for node in ast.walk(_tree(path)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for t in targets:
                names = {n.attr for n in ast.walk(t) if isinstance(n, ast.Attribute)}
                names |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
                for s in ast.walk(t):
                    if isinstance(s, ast.Subscript) and isinstance(s.slice, ast.Constant):
                        names.add(str(s.slice.value))
                bad = names & {"live_allowed", "live_eligible", "auto_eligible"}
                assert not bad, f"{path.name} assigns {bad}"


def test_validation_module_no_forbidden_broker_imports():
    for path in VALIDATION_SOURCES:
        mods = set()
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        bad = mods & FORBIDDEN_MODULES
        assert not bad, f"{path.name} imports forbidden broker/submit modules: {bad}"


def test_validation_module_only_writes_two_tables():
    """The ONLY tables the validation layer writes are the outcomes ledger and
    the registry's advisory columns — no queue, no proposals, no config tables."""
    src = (VALIDATION_SOURCES[0]).read_text(encoding="utf-8")
    written = set(re.findall(r"(?:INSERT INTO|(?<!DO )UPDATE)\s+(\w+)", src, re.I))
    assert written == {"options_paper_outcomes", "strategy_registry"}


# ── (5) migration idempotent + additive ──────────────────────────────────────

MIGRATION = ROOT / "migrations" / "2026_07_05_options_paper_outcomes.sql"


def test_migration_is_idempotent_and_additive():
    sql = MIGRATION.read_text(encoding="utf-8")
    # Strip all comment lines, then require every remaining statement to be
    # CREATE ... IF NOT EXISTS — safe to run any number of times.
    code = "\n".join(line for line in sql.splitlines()
                     if not line.strip().startswith("--"))
    statements = [s.strip() for s in code.split(";") if s.strip()]
    assert statements, "migration contains no executable statements"
    for stmt in statements:
        head = stmt.upper()
        assert head.startswith("CREATE TABLE IF NOT EXISTS") \
            or head.startswith("CREATE INDEX IF NOT EXISTS"), \
            f"non-idempotent/non-additive statement: {head[:60]}"
    for destructive in ("DROP ", "TRUNCATE", "DELETE ", "ALTER "):
        assert destructive not in sql.upper()
    assert "options_paper_outcomes" in sql
    assert "UNIQUE" in sql.upper()                  # proposal_id upsert target


def test_migration_matches_record_outcome_columns():
    """Every column record_outcome() writes must exist in the migration DDL."""
    sql = MIGRATION.read_text(encoding="utf-8")
    for col in ("proposal_id", "strategy_id", "symbol", "opened_at", "closed_at",
                "entry_debit", "exit_value", "pnl", "pnl_r", "outcome",
                "exit_reason", "notes", "meta"):
        assert re.search(rf"^\s+{col}\s", sql, re.M), f"migration missing column {col}"
