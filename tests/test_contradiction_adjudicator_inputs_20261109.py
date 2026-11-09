"""LQ-20261107-1614 — the contradiction adjudicator sees the artifacts it judges, and judges real contradictions first.

Two input defects meant no LEFT / RIGHT / BOTH_STALE verdict could be reached:
1. ``artifact_text`` keyed every row by its FIRST id field. A thesis-delta row carries both ``research_id`` and
   ``delta_id``, so an ``rtd_`` ref never matched and the judge was told "body not on file". The body keys it read
   (summary / recommendation) are not delta fields either.
2. ``select_pairs`` ranked by digest subject with no regard for whether the pair is about one symbol. Most
   candidates are cross-symbol sector pairs, which cannot be a thesis contradiction, so the cap was spent on them.
Synthetic rows only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import contradiction_adjudicator as ca  # noqa: E402


def _write(root: Path, name: str, rows: list[dict]) -> None:
    p = root / "data" / "cio" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


DELTA = {"delta_id": "rtd_aaa", "research_id": "rr_shared", "symbol": "ZZZA", "classification": "WEAKENS",
         "reason_summary": "synthetic: margin guide cut", "confidence": 0.7, "evidence_as_of": "2026-01-02",
         "what_changed": ["guide"], "what_did_not_change": ["dividend"], "research_gaps_remaining": ["q4"]}
DELTA2 = {**DELTA, "delta_id": "rtd_bbb", "classification": "CONFIRMS", "reason_summary": "synthetic: guide held"}
RESULT = {"result_id": "hr_1", "research_id": "rr_shared", "result": {"summary": "synthetic research summary",
                                                                     "recommendation": "watch"}}


def test_a_delta_resolves_by_delta_id_even_with_a_research_id(tmp_path):
    _write(tmp_path, "research_thesis_deltas.jsonl", [DELTA, DELTA2])
    text = ca.artifact_text("rtd_aaa", tmp_path, None)
    assert "body not on file" not in text
    body = json.loads(text)
    assert body["reason_summary"] == "synthetic: margin guide cut" and body["classification"] == "WEAKENS"
    assert body["what_did_not_change"] == ["dividend"] and body["research_gaps_remaining"] == ["q4"]
    assert json.loads(ca.artifact_text("rtd_bbb", tmp_path, None))["classification"] == "CONFIRMS"


def test_an_exact_id_beats_a_shared_research_id(tmp_path):
    _write(tmp_path, "hermes_research_results.jsonl", [RESULT])
    _write(tmp_path, "research_thesis_deltas.jsonl", [DELTA])
    assert json.loads(ca.artifact_text("hr_1", tmp_path, None))["summary"] == "synthetic research summary"
    assert json.loads(ca.artifact_text("rtd_aaa", tmp_path, None))["classification"] == "WEAKENS"
    assert "body not on file" in ca.artifact_text("rtd_missing", tmp_path, None)


def test_the_index_is_built_once_and_reused(tmp_path, monkeypatch):
    _write(tmp_path, "research_thesis_deltas.jsonl", [DELTA, DELTA2])
    idx = ca.build_artifact_index(tmp_path)
    calls = []
    monkeypatch.setattr(ca, "read_jsonl", lambda *a, **k: calls.append(a) or [])
    assert json.loads(ca.artifact_text("rtd_bbb", tmp_path, idx))["classification"] == "CONFIRMS"
    assert calls == []


def _cand(cid, ls, rs):
    return {"schema": "ResearchContradictionCandidate@v1", "candidate_id": cid, "status": "CANDIDATE",
            "left_artifact_id": cid + "l", "right_artifact_id": cid + "r", "left_symbol": ls, "right_symbol": rs,
            "shared_context": ["factual.sector"], "opposition": {}}


def test_same_symbol_pairs_are_judged_before_cross_symbol_pairs():
    # the same-symbol pairs are the OLDEST rows, so newest-first order alone never reaches them
    cands = [_cand("s1", "ZZB", "ZZB"), _cand("s2", "zzc", "ZZC")] + [_cand(f"x{i}", "ZZA", f"ZZ{i}")
                                                                     for i in range(30)]
    sel = ca.select_pairs(cands, already=set(), max_pairs=3)
    assert [c["candidate_id"] for c in sel][:2] in (["s1", "s2"], ["s2", "s1"])
    assert len(sel) == 3  # cross-symbol pairs still fill the remaining slots


def test_already_judged_same_symbol_pairs_are_skipped():
    cands = [_cand("s1", "ZZB", "ZZB"), _cand("x1", "ZZA", "ZZD")]
    assert [c["candidate_id"] for c in ca.select_pairs(cands, already={"s1"}, max_pairs=5)] == ["x1"]


# ---------------------------------------------------------------- the contract

def _v(cid, verdict, ls="ZZA", rs="ZZD", missing=False):
    return {"candidate_id": cid, "verdict": verdict, "left_symbol": ls, "right_symbol": rs,
            "rationale": "[artifact x: body not on file]" if missing else "synthetic"}


def test_health_is_broken_when_the_judge_only_sees_missing_bodies_and_sector_pairs():
    verdicts = [_v(f"x{i}", "NOT_A_CONTRADICTION", missing=i % 2 == 0) for i in range(30)]
    verdicts += [_v(f"m{i}", "UNRESOLVED", missing=True) for i in range(10)]
    h = ca.health(verdicts, [_cand("s1", "ZZB", "ZZB")])
    assert h["verdict"] == "BROKEN" and h["confirmed"] == 0
    assert "artifact_bodies_missing" in h["reason"] and "cross_symbol_judged_before_same_symbol" in h["reason"]


def test_health_ok_when_a_confirmed_contradiction_is_reachable():
    verdicts = [_v(f"s{i}", "NOT_A_CONTRADICTION", "ZZB", "ZZB") for i in range(24)] + [_v("s99", "LEFT", "ZZB", "ZZB")]
    h = ca.health(verdicts, [])
    assert (h["verdict"], h["reason"], h["confirmed"]) == ("OK", "confirmed_reachable", 1)


def test_health_degraded_and_unverifiable_edges():
    some_missing = [_v(f"s{i}", "NOT_A_CONTRADICTION", "ZZB", "ZZB", missing=i < 5) for i in range(25)]
    some_missing.append(_v("s99", "RIGHT", "ZZB", "ZZB"))
    assert ca.health(some_missing, [])["verdict"] == "DEGRADED"
    assert ca.health([_v("a", "LEFT")], [])["verdict"] == "UNVERIFIABLE"
