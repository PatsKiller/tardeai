"""P4/P5 diligence — cheap budget/hop/governance invariants + sample audit.

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. No vendor calls. No budget raise.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_corpus_index as corpus
from scripts.lib import cio_research_budget as budget
from scripts.lib import cio_research_gate as gate
from scripts.lib import cio_residual_web as residual
from scripts.lib.cio_instrument_record import new_record
from scripts.lib.cio_specialist_artifact import build, validate
from scripts import cio_research_governance_census as census
from scripts import cio_specialist_sample_audit as sample_audit


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


# ── P4: budget / hop / free-first ladder ─────────────────────────────────


def test_research_budget_daily_cap_is_five_and_not_raised():
    assert budget.DAILY_CAP == 5
    assert budget.HELD_SLOTS + budget.CASH_SLOTS + budget.REENTRY_OR_WATCH_SLOTS == 5
    assert budget.MBI_BEHAVIOR == 0


def test_residual_web_one_hop_per_subject_per_day():
    assert residual.MAX_HOPS_PER_SUBJECT_PER_DAY == 1
    assert residual.DAILY_SUBJECT_BUDGET == 3
    rec = new_record("HELD", "NOC", symbols=["NOC"], market_value=25_000.0)
    legal = residual.legality(
        rec,
        gate_decision={"decision": gate.RESIDUAL_DECISION, "reason": "pro_unresolved"},
        plan={"material": True},
        hops_today=1,
        now=NOW,
    )
    assert legal["legal"] is False
    assert "under_daily_subject_cap" in legal["failed_checks"]
    assert any(c.get("check") == "under_daily_subject_cap" and not c.get("ok")
               for c in legal.get("checks") or [])


def test_grade_c_or_d_cannot_corpus_hit():
    assert corpus.CLOSING_GRADES == frozenset({"A", "B"})
    assert "C" not in corpus.CLOSING_GRADES
    assert "D" not in corpus.CLOSING_GRADES


def test_gate_ladder_is_free_first_then_paid():
    assert gate.DECISIONS[:3] == ("skip", "reuse", "corpus_hit")
    assert "flash" in gate.DECISIONS
    assert "pro" in gate.DECISIONS
    assert "grok_critique" in gate.DECISIONS
    # residual rung remains the openai token; lane executes it
    assert gate.RESIDUAL_DECISION == "openai"
    assert gate.LANE_FOR[gate.RESIDUAL_DECISION] == "residual_web"


def test_collapse_same_day_keeps_one_decision_per_subject():
    # collapse keys on (kind, symbol, day) for paid decisions — see gate module.
    decisions = [
        {"kind": "HELD", "symbol": "NOC", "research_id": "res_a", "decision": "flash"},
        {"kind": "HELD", "symbol": "NOC", "research_id": "res_b", "decision": "flash"},
        {"kind": "HELD", "symbol": "RTX", "research_id": "res_c", "decision": "flash"},
    ]
    report = gate.collapse_same_day_duplicates(decisions, now=NOW)
    assert report["collapsed"] == 1
    noc = [d for d in decisions
           if d.get("symbol") == "NOC" and d.get("reason") != "duplicate_subject_same_day"]
    assert len(noc) == 1
    assert decisions[1]["decision"] == "skip"
    assert decisions[1]["reason"] == "duplicate_subject_same_day"


def test_governance_census_json_shape(tmp_path: Path):
    # Point at repo root (has reference series + modules); stores may be absent.
    root = Path(__file__).resolve().parents[1]
    doc = census.census(root)
    assert doc["schema"] == "CIOResearchGovernanceCensus@v1"
    assert doc["memory_behavior_influence"] == 0
    assert doc["invariants"]["research_budget"]["daily_cap"] == 5
    assert doc["invariants"]["residual_web"]["max_hops_per_subject_per_day"] == 1
    assert doc["invariants"]["corpus"]["grade_c_or_d_may_corpus_hit"] is False
    assert doc["free_first"]["fred_series_count"] >= 1


# ── P5: specialist sample structural invariants ──────────────────────────


def test_specialist_artifact_schema_rejects_unknown_provider():
    with pytest.raises(ValueError):
        build(artifact_id="a1", provider="not_a_provider", outcome="VALID")


def test_specialist_sample_audit_on_fixtures(tmp_path: Path):
    root = tmp_path
    cio = root / "data" / "cio"
    cio.mkdir(parents=True)

    live = build(
        artifact_id="live_1",
        provider="grok_critique",
        outcome="PARTIAL",
        workflow_id=None,
        plan_id="plan_x",
        research_id="res_live",
        cost_usd=0.0,
    )
    (cio / "cio_specialist_artifacts.jsonl").write_text(
        json.dumps(live) + "\n", encoding="utf-8"
    )

    # lineage recovers workflow
    lineage = {
        "schema": "CIOWorkflowLineage@v1",
        "workflow_id": "wf_abc",
        "node_id": "res_live",
        "node_type": "RESEARCH",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
    }
    (cio / "cio_workflow_lineage.jsonl").write_text(
        json.dumps(lineage) + "\n", encoding="utf-8"
    )

    # IR + plan bind
    ir = new_record("HELD", "SPCX", symbols=["SPCX"])
    (cio / "cio_instrument_records.jsonl").write_text(
        json.dumps(ir) + "\n", encoding="utf-8"
    )
    (cio / "cio_plans_projection.json").write_text(
        json.dumps({
            "plans": {
                "plan_x": {
                    "plan_id": "plan_x",
                    "symbols": ["SPCX"],
                    "status": "draft",
                    "situation_type": "S1_POSITION_LIFECYCLE",
                }
            }
        }),
        encoding="utf-8",
    )
    # hermes empty — sample stays at live-only when limit>=1
    (cio / "hermes_research_results.jsonl").write_text("", encoding="utf-8")

    doc = sample_audit.audit(root, limit=100)
    assert doc["live_specialist_artifact_n"] == 1
    assert doc["sample_n"] == 1
    row = doc["rows"][0]
    assert row["workflow_id_recovered"] == "wf_abc"
    assert row["same_workflow_bind"] is True
    assert row["same_instrument_record_bind"] is True
    assert row["orphan_workflow"] is False
    assert row["orphan_instrument"] is False
    assert row["scorecard"]["accuracy"] == "DATA_UNAVAILABLE"
    assert row["scorecard"]["relevance"] == "DATA_UNAVAILABLE"
    assert row["scorecard"]["consistency"] == "PASS"
    assert validate(live) == []


def test_specialist_sample_marks_orphan_without_lineage_or_ir(tmp_path: Path):
    root = tmp_path
    cio = root / "data" / "cio"
    cio.mkdir(parents=True)
    live = build(
        artifact_id="orphan_1",
        provider="stub",
        outcome="VALID",
        research_id="res_missing",
    )
    (cio / "cio_specialist_artifacts.jsonl").write_text(
        json.dumps(live) + "\n", encoding="utf-8"
    )
    (cio / "cio_workflow_lineage.jsonl").write_text("", encoding="utf-8")
    (cio / "cio_instrument_records.jsonl").write_text("", encoding="utf-8")
    (cio / "cio_plans_projection.json").write_text("{}", encoding="utf-8")
    (cio / "hermes_research_results.jsonl").write_text("", encoding="utf-8")

    doc = sample_audit.audit(root, limit=10)
    row = doc["rows"][0]
    assert row["orphan_workflow"] is True
    assert row["orphan_instrument"] is True
    assert doc["orphans"]["orphan_workflow_count"] == 1
