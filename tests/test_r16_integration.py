"""R16 integration: live-shaped historical outcomes without inventing joins."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.api_v3_cio as api
from scripts.lib.cio_institutional_learning import (
    append_outcome,
    build_outcome_observation,
    classify_traceability,
    inventory_decisions,
    reject_lookahead,
)

pytestmark = pytest.mark.tier0
CUR = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def _live_outcomes(limit: int = 25) -> list[dict]:
    path = CUR / "data/cio/cio_outcomes.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event_type") != "OUTCOME_RECORDED":
            continue
        pay = row.get("payload") or {}
        out.append(pay)
        if len(out) >= limit:
            break
    return out


LIVE = _live_outcomes(25)
# pad if isolated CI has no CURRENT store
if len(LIVE) < 25:
    LIVE = LIVE + [
        {"cio_action_id": f"act-{i}", "outcome_status": "POSITIVE", "operator_disposition": "ACCEPTED", "context_refs": []}
        for i in range(25 - len(LIVE))
    ]


@pytest.mark.parametrize("i", range(25))
def test_live_outcome_payloads_are_partial_not_fabricated(i: int) -> None:
    pay = LIVE[i]
    decision = {
        "decision_id": pay.get("cio_action_id") or pay.get("decision_id"),
        "recommendation": "HOLD",
        "created_at": "2026-06-01T00:00:00+00:00",
        "as_of": "2026-06-01T00:00:00+00:00",
        "evidence_refs": pay.get("context_refs") or [],
        "runtime_source_sha": None,
        "subject_guid": None,
    }
    status = classify_traceability(decision)
    assert status in {"PARTIAL", "UNRESOLVED"}
    assert status != "FULLY_TRACEABLE"  # live store lacks security_guid / runtime sha


@pytest.mark.parametrize("i", range(25))
def test_historical_outcome_append_does_not_rewrite(i: int) -> None:
    pay = LIVE[i]
    did = str(pay.get("cio_action_id") or f"dec_pad_{i}")
    decision = {
        "decision_id": did,
        "subject_guid": "unresolved",
        "created_at": "2026-06-01T00:00:00+00:00",
        "as_of": "2026-06-01T00:00:00+00:00",
        "recommendation": "HOLD",
        "evidence_refs": ["hist"],
        "runtime_source_sha": "historical",
    }
    obs = build_outcome_observation(
        decision_id=did,
        subject_guid="unresolved",
        horizon="event-relative",
        original_decision_state={"disposition": pay.get("operator_disposition")},
        realized_state={"status": pay.get("outcome_status")},
        source_refs=["cio_outcomes.jsonl"],
        source_as_of="2026-08-01T00:00:00+00:00",
    )
    store: list = []
    rec = append_outcome(store, obs, [decision])
    assert rec["history_rewritten"] is False
    assert rec["appended"] is True


def test_inventory_live_scan_results_partial() -> None:
    scan_path = CUR / "data/audit/cio_material_scan_last.json"
    if not scan_path.is_file():
        pytest.skip("CURRENT scan receipt absent")
    scan = json.loads(scan_path.read_text())
    rows = []
    for r in scan.get("results") or []:
        ev = r.get("evaluate") or {}
        rows.append({
            "decision_id": ev.get("decision_id") or r.get("case_id"),
            "recommendation": r.get("event_type"),
            "created_at": scan.get("at"),
            "as_of": scan.get("at"),
            "evidence_refs": [],
            "runtime_source_sha": None,
            "subject_guid": None,
        })
    cov = inventory_decisions(rows)
    assert cov["fabricated_joins"] is False
    assert cov["counts"]["FULLY_TRACEABLE"] == 0


def test_learning_cockpit_cannot_self_promote() -> None:
    row = api.get_learning_cockpit_v1()
    assert row["gui_cannot_self_promote"] is True
    assert row["max_unattended_stage"] == "REVIEW_READY"
    assert row["sample_lesson"]["status"] == "PROVISIONAL"
    assert row["memory_behavior_influence"] == 0


def test_lookahead_rejects_future_thesis_in_replay() -> None:
    audit = reject_lookahead(
        {"evidence": [{"id": "later", "as_of": "2027-01-01T00:00:00+00:00"}]},
        as_of="2026-08-01T00:00:00+00:00",
    )
    assert audit["allowed"] is False
