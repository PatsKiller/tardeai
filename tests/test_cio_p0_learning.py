"""P0-4 / P0-5 / P0-6 — canonical event-sourced cases, Darwin after maturity.

12  OPEN + DISPOSITION + NOTE materialize to ONE case_id
14  OPEN case cannot Darwin-score (eligible False, NOT_MATURED)
15  unmatured => NOT_MATURED
16  matured POSITIVE => deterministic score, auto_promote 0
17  reflect sees disposition + note + outcome together
18  reflection does not auto-ratify
    record_disposition never creates a disp_ case_id
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib import cio_production_case as cs
from scripts.lib.cio_nightly_reflection import reflect


DEC = {
    "decision_id": "dec_p0",
    "symbol": "SCHD",
    "action": "TRIM",
    "decision_input_digest": "in_p0",
    "decision_evidence_digest": "ev_p0",
    "why_now": "concentration above fire line",
    "current_weight_pct": 12.0,
    "recommended_delta_usd": -5000,
}


@pytest.fixture
def cases_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "cio_production_cases.jsonl"
    monkeypatch.setattr(cs, "DEFAULT_PATH", p)
    return p


def _open(research=None):
    return cs.open_case_from_decision(DEC, research=research)


def _ids():
    return {
        "input_digest": DEC["decision_input_digest"],
        "evidence_digest": DEC["decision_evidence_digest"],
    }


def test_12_open_disposition_note_materialize_one_case_id(cases_path: Path):
    opened = _open()
    cid = opened["case_id"]
    assert cid.startswith("case_")
    assert cid == cs.case_id_for(
        DEC["decision_id"], DEC["decision_input_digest"], DEC["decision_evidence_digest"],
    )
    assert not cid.startswith("disp_")
    assert not cid.startswith("note_")

    cs.record_disposition(DEC["decision_id"], {"disposition": "ack", "rating": 4}, **_ids())
    cs.record_note(DEC["decision_id"], "wait for price buffer", **_ids())

    joined = cs.materialize_case(cid)
    assert joined["case_id"] == cid
    assert joined["decision_id"] == DEC["decision_id"]
    assert (joined.get("operator_disposition") or {}).get("disposition") == "ack"
    assert "wait for price buffer" in str(joined.get("note") or "")
    assert any("wait for price buffer" in str(n) for n in (joined.get("notes") or []))

    all_cases = cs.materialize_cases()
    assert len(all_cases) == 1
    assert all_cases[0]["case_id"] == cid

    events = cs.load_events()
    assert {e["case_id"] for e in events} == {cid}
    types = {e["event_type"] for e in events}
    assert cs.DECISION_OPENED in types
    assert cs.OPERATOR_DISPOSITION in types
    assert cs.OPERATOR_NOTE in types


def test_14_open_case_cannot_darwin_score(cases_path: Path):
    opened = _open()
    joined = cs.materialize_case(opened["case_id"])
    assert joined["status"] == "OPEN"
    result = cs.score_case_darwin(joined)
    assert result["eligible"] is False
    assert result["darwin_status"] == "NOT_MATURED"
    assert result["score"] is None
    ms = cs.maybe_score_if_mature(joined)
    assert ms["eligible"] is False
    assert ms["darwin_status"] == "NOT_MATURED"
    assert not any(e.get("event_type") == cs.DARWIN_SCORED for e in cs.load_events())


def test_15_unmatured_not_matured(cases_path: Path):
    opened = _open()
    cs.record_disposition(DEC["decision_id"], {"disposition": "ack"}, **_ids())
    awaiting = cs.materialize_case(opened["case_id"])
    r1 = cs.score_case_darwin(awaiting)
    assert r1["eligible"] is False
    assert r1["darwin_status"] == "NOT_MATURED"
    assert r1["score"] is None

    cs.record_outcome(
        DEC["decision_id"],
        {"outcome_status": "PENDING_MATURATION"},
        **_ids(),
    )
    pending = cs.materialize_case(opened["case_id"])
    r2 = cs.score_case_darwin(pending)
    assert r2["eligible"] is False
    assert r2["darwin_status"] == "NOT_MATURED"
    assert r2["score"] is None
    assert cs.maybe_score_if_mature(pending).get("eligible") is False
    assert not any(e.get("event_type") == cs.DARWIN_SCORED for e in cs.load_events())

    empty = cs.score_case_darwin({
        "status": "AWAITING_OUTCOME",
        "outcome": {"outcome_status": ""},
    })
    assert empty["darwin_status"] == "NOT_MATURED"
    assert empty["eligible"] is False


def test_16_matured_positive_deterministic_score_auto_promote_0(cases_path: Path, tmp_path: Path):
    opened = _open()
    cs.record_disposition(DEC["decision_id"], {"disposition": "ack"}, **_ids())
    cs.record_outcome(
        DEC["decision_id"],
        {
            "outcome_status": "POSITIVE",
            "evaluation_horizon": "20d",
            "maturity_at": "2026-08-15T00:00:00+00:00",
        },
        **_ids(),
    )
    joined = cs.materialize_case(opened["case_id"])
    assert joined["status"] in {"MATURED", "SCORED"}
    r1 = cs.score_case_darwin(joined)
    r2 = cs.score_case_darwin(joined)
    assert r1["eligible"] is True
    assert r1["darwin_status"] == "SCORED"
    assert r1["score"] == r2["score"]
    assert r1["score"] == 80  # 50 + ack 10 + POSITIVE 20
    assert joined.get("auto_promoted") is False

    ms = cs.maybe_score_if_mature(joined)
    assert ms["eligible"] is True
    assert ms["score"] == 80
    assert any(e.get("event_type") == cs.DARWIN_SCORED for e in cs.load_events())
    assert all(e.get("auto_promoted") is False for e in cs.load_events())

    out = reflect(cases_path=cases_path, out_path=tmp_path / "ref.json")
    assert out["auto_promotions"] == 0


def test_17_reflect_sees_disposition_note_outcome_together(cases_path: Path, tmp_path: Path):
    _open()
    cs.record_disposition(DEC["decision_id"], {"disposition": "ack", "rating": 5}, **_ids())
    cs.record_note(DEC["decision_id"], "held through the print", **_ids())
    cs.record_outcome(
        DEC["decision_id"],
        {"outcome_status": "POSITIVE", "evaluation_horizon": "20d"},
        **_ids(),
    )
    out = reflect(cases_path=cases_path, out_path=tmp_path / "ref.json")
    assert out["cases_seen"] == 1
    joined = out["joined_cases"][0]
    assert (joined.get("operator_disposition") or {}).get("disposition") == "ack"
    assert "held through the print" in str(joined.get("note") or "")
    assert (joined.get("outcome") or {}).get("outcome_status") == "POSITIVE"

    found = [
        p for p in out["proposals"]
        if p.get("kind") == "candidate_lesson"
        and p.get("disposition")
        and p.get("note")
        and p.get("outcome")
    ]
    assert found, out["proposals"]
    assert "held through the print" in str(found[0]["note"])
    assert found[0]["outcome"]["outcome_status"] == "POSITIVE"


def test_18_reflection_does_not_auto_ratify(cases_path: Path, tmp_path: Path):
    opened = _open(research={"decision_use_audit": {"status": "UNAVAILABLE"}})
    cs.record_disposition(DEC["decision_id"], {"disposition": "ack"}, **_ids())
    cs.record_note(DEC["decision_id"], "operator note", **_ids())
    out = reflect(cases_path=cases_path, out_path=tmp_path / "ref.json")
    assert out["auto_promotions"] == 0
    assert out["mutates_production"] is False
    assert all(p.get("state") != "RATIFIED" for p in out["proposals"])
    # OPEN / unmatured must not be counted as Darwin-scored.
    assert out["scored"] == 0
    opened_join = cs.materialize_case(opened["case_id"])
    assert opened_join["status"] != "SCORED"
    assert cs.score_case_darwin(opened_join)["eligible"] is False


def test_record_disposition_does_not_create_disp_case_id(cases_path: Path):
    opened = _open()
    rec = cs.record_disposition(
        DEC["decision_id"],
        {
            "disposition": "done",
            "decision_input_digest": DEC["decision_input_digest"],
            "decision_evidence_digest": DEC["decision_evidence_digest"],
        },
    )
    assert rec["case_id"] == opened["case_id"]
    assert rec["case_id"].startswith("case_")
    assert not rec["case_id"].startswith("disp_")
    assert rec["event_type"] == cs.OPERATOR_DISPOSITION

    # Legacy append_case(disp_*) must rewrite to the canonical id.
    rewritten = cs.append_case({
        "case_id": f"disp_{DEC['decision_id']}",
        "status": "DISPOSITION",
        "decision_id": DEC["decision_id"],
        "operator_disposition": {
            "disposition": "reject",
            "decision_input_digest": DEC["decision_input_digest"],
            "decision_evidence_digest": DEC["decision_evidence_digest"],
        },
    })
    assert rewritten["case_id"] == opened["case_id"]
    assert not rewritten["case_id"].startswith("disp_")

    events = cs.load_events()
    assert events
    assert all(not str(e.get("case_id")).startswith("disp_") for e in events)
    assert all(not str(e.get("case_id")).startswith("note_") for e in events)
    assert all(str(e.get("case_id")).startswith("case_") for e in events)

    rows = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert all(not str(r.get("case_id")).startswith("disp_") for r in rows)
