"""Reflection journal persistence + learning classification fixtures.

No production mutation. No paid traffic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_nightly_reflection import (  # noqa: E402
    persist_reflection,
    reflect,
    resolve_journal_paths,
)
from scripts.lib import cio_production_case as cs  # noqa: E402


DEC = {
    "decision_id": "dec_journal_fix",
    "decision_input_digest": "in_journal",
    "decision_evidence_digest": "ev_journal",
}


def _ids():
    return {
        "input_digest": DEC["decision_input_digest"],
        "evidence_digest": DEC["decision_evidence_digest"],
    }


def _open(cases_path: Path, **payload):
    return cs.append_event(
        cs.case_id_for(DEC["decision_id"], DEC["decision_input_digest"], DEC["decision_evidence_digest"]),
        cs.DECISION_OPENED,
        {"symbol": "TEST", **payload},
        DEC["decision_id"],
        DEC["decision_input_digest"],
        DEC["decision_evidence_digest"],
        path=cases_path,
    )


def test_resolve_journal_paths_are_distinct():
    snap, hist = resolve_journal_paths()
    assert snap != hist
    assert snap.suffix == ".json"
    assert hist.suffix == ".jsonl"


def test_out_path_jsonl_does_not_alias_snapshot(tmp_path: Path):
    p = tmp_path / "cio_reflection_candidates.jsonl"
    snap, hist = resolve_journal_paths(p)
    assert snap != hist
    assert snap.name.endswith(".json")
    assert hist == p


def test_multiple_reflections_append_valid_jsonl(tmp_path: Path):
    hist = tmp_path / "cio_reflection_candidates.jsonl"
    rec = {
        "at": "2026-08-17T00:00:00+00:00",
        "cases_seen": 1,
        "scored": 0,
        "proposals": [],
        "auto_promotions": 0,
        "mutates_production": False,
        "authority": "READ_ONLY_ADVISORY",
    }
    snap, history = resolve_journal_paths(hist)
    persist_reflection(rec, snapshot_path=snap, history_path=history)
    rec2 = dict(rec)
    rec2["at"] = "2026-08-17T01:00:00+00:00"
    rec2["cases_seen"] = 2
    persist_reflection(rec2, snapshot_path=snap, history_path=history)
    lines = [ln for ln in history.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    parsed = [json.loads(ln) for ln in lines]
    assert parsed[0]["cases_seen"] == 1
    assert parsed[1]["cases_seen"] == 2
    assert "\n  " not in lines[0]
    snap_obj = json.loads(snap.read_text())
    assert snap_obj["cases_seen"] == 2
    assert snap_obj["auto_promotions"] == 0
    assert snap_obj["mutates_production"] is False
    assert snap_obj["authority"] == "READ_ONLY_ADVISORY"


def test_classification_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cases = tmp_path / "cases.jsonl"
    monkeypatch.setattr(cs, "DEFAULT_PATH", cases)
    # 1. unscored open
    cs.append_event(
        "case_open", cs.DECISION_OPENED, {"symbol": "OPEN"},
        "dec_open", "in_o", "ev_o", path=cases,
    )
    # 2. matured scored
    cs.append_event(
        "case_scored", cs.DECISION_OPENED, {"symbol": "SCORED"},
        "dec_scored", "in_s", "ev_s", path=cases,
    )
    cs.append_event(
        "case_scored", cs.OPERATOR_DISPOSITION, {"disposition": "ack"},
        "dec_scored", "in_s", "ev_s", path=cases,
    )
    cs.append_event(
        "case_scored", cs.OPERATOR_NOTE, {"note": "held through the print"},
        "dec_scored", "in_s", "ev_s", path=cases,
    )
    cs.append_event(
        "case_scored",
        cs.OUTCOME_OBSERVED,
        {"outcome_status": "POSITIVE", "evaluation_horizon": "20d", "maturity_at": "2026-08-01T00:00:00+00:00"},
        "dec_scored", "in_s", "ev_s", path=cases,
    )
    cs.append_event(
        "case_scored",
        cs.DARWIN_SCORED,
        {"eligible": True, "darwin_status": "SCORED", "score": 80, "auto_promoted": False},
        "dec_scored", "in_s", "ev_s", path=cases,
    )
    # 3. disposition without outcome
    cs.append_event(
        "case_contra", cs.DECISION_OPENED, {"symbol": "CONTRA"},
        "dec_contra", "in_c", "ev_c", path=cases,
    )
    cs.append_event(
        "case_contra", cs.OPERATOR_DISPOSITION, {"disposition": "ack"},
        "dec_contra", "in_c", "ev_c", path=cases,
    )
    out = reflect(cases_path=cases, out_path=tmp_path / "ref.jsonl")
    assert out["cases_seen"] == 3
    assert out["scored"] == 1
    kinds = {p["kind"] for p in out["proposals"]}
    assert "candidate_lesson" in kinds
    assert "unresolved_contradiction" in kinds
    assert out["auto_promotions"] == 0
    assert out["mutates_production"] is False
    hist = tmp_path / "ref.jsonl"
    lines = [json.loads(ln) for ln in hist.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    snap = json.loads((tmp_path / "ref.json").read_text())
    assert snap["scored"] == 1
