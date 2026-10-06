"""Health counts complete unresolved evidence; it does not imply dashboard P0/P1."""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def collect(monkeypatch):
    path = ROOT / "scripts" / "health_agent.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_f", "collect_risk_protection"}
    ]
    namespace = {"__file__": str(path)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    consensus = types.ModuleType("stop_consensus_check")
    consensus.detect_conflicts = lambda **kwargs: []
    monkeypatch.setitem(sys.modules, "stop_consensus_check", consensus)

    def run(rows):
        calls = []

        def query(sql, params=None, fetch="one"):
            assert sql.lstrip().startswith("SELECT")
            if "FROM stop_lifecycle" in sql:
                return {"c": 0}
            calls.append((sql, fetch))
            return rows

        namespace["_db"] = query
        findings = namespace["collect_risk_protection"]()
        assert len(calls) == 1
        sql, fetch = calls[0]
        assert fetch == "all"
        assert "LIMIT" not in sql
        assert "'24 hours'" in sql
        assert "NOT IN ('resolved','acknowledged')" in sql
        assert "severity IN ('critical','urgent')" in sql
        return findings

    return run


def stop(row_id, account="fixture_account_a", order_id="fixture_order_a", text="oversized"):
    return {
        "id": row_id,
        "source_script": "stop_health",
        "alert_type": "strategic_alert",
        "raw_text": text,
        "parsed_payload": {
            "account": account,
            "order_id": order_id,
            "symbol": "XYZ",
            "condition": "OVERSIZED",
        },
    }


def test_repeated_condition_counts_once_despite_changing_prose(collect):
    findings = collect([stop(1, text="200 versus100"), stop(2, text="200 versus110")])
    assert len(findings) == 1
    assert findings[0]["count"] == 1
    assert findings[0]["severity"] == "warning"
    assert "urgent/critical" in findings[0]["message"]
    assert "P0/P1" not in findings[0]["message"]


def test_distinct_account_order_risks_preserve_escalation_threshold(collect):
    rows = [stop(i, order_id=f"fixture_order_{i}") for i in range(4)]
    rows.append(stop(5, account="fixture_account_b", order_id="fixture_order_0"))
    findings = collect(rows)
    assert findings[0]["count"] == 5
    assert findings[0]["severity"] == "critical"


def test_full_dataset_is_counted_beyond_dashboard_page(collect):
    rows = [stop(i, order_id=f"fixture_order_{i}") for i in range(205)]
    assert collect(rows)[0]["count"] == 205


def test_unknown_evidence_is_not_silently_merged(collect):
    rows = [{"id": i, "source_script": "unknown", "raw_text": ""} for i in range(3)]
    assert collect(rows)[0]["count"] == 3


def test_unavailable_is_visible_and_empty_is_clean(collect):
    assert collect([]) == []
    findings = collect(None)
    assert findings[0]["type"] == "siem_check_unavailable"
    assert findings[0]["severity"] == "warning"


def test_log_timestamp_does_not_create_a_second_connection_incident(collect):
    rows = [
        {
            "id": i,
            "source_script": "atm.log",
            "alert_type": "system_health",
            "raw_text": f"DB_CONNECTION: 2026-10-05 {clock} [atm] ATM protection pass error: connection already closed",
        }
        for i, clock in enumerate(("13:45:10,445", "14:30:11,445"))
    ]
    assert collect(rows)[0]["count"] == 1


def test_unidentifiable_evidence_is_a_visible_warning(collect):
    findings = collect([{"source_script": "unknown", "raw_text": None}])
    assert findings[0]["type"] == "siem_check_unavailable"
    assert findings[0]["severity"] == "warning"
