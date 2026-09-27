"""Contradiction candidates are derived incrementally (2026-09-27 due diligence).

Every accepted research result re-derived all pairs of all deltas (31 s, 117k
candidates) inside the Hermes worker callback. Only pairs with the new delta are
new; ids must equal the full derivation. Hermetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import research_contradiction as rc  # noqa: E402


def _deltas():
    rows = []
    for i, (sym, cls) in enumerate([("V", "STRENGTHENS"), ("V", "WEAKENS"), ("MA", "STRENGTHENS"),
                                     ("V", "INVALIDATES"), ("MA", "WEAKENS"), ("V", "CONFIRMS")]):
        rows.append({"delta_id": f"rtd_{i:02d}", "symbol": sym, "classification": cls,
                     "source_refs": [f"ev_{sym}"],
                     "metadata": {"factual": {"sector": {"value": "Financials"}},
                                  "judgment": {"theme": {"tags": {"theme": "payments"}}}}})
    return rows


def test_fixture_produces_candidates():
    assert len(rc.find_contradiction_candidates(_deltas())) >= 6


def test_incremental_ids_equal_the_full_derivation_for_new_pairs():
    rows = _deltas()
    full = rc.find_contradiction_candidates(rows)
    for new in (rows[-1:], rows[-2:], rows[:1], [rows[1], rows[3]]):
        ids = {r["delta_id"] for r in new}
        expect = {c["candidate_id"] for c in full if c["left_artifact_id"] in ids or c["right_artifact_id"] in ids}
        got = {c["candidate_id"] for c in rc.find_contradiction_candidates(rows, new_records=new)}
        assert got == expect


def test_persist_with_new_records_appends_only_new_pairs(tmp_path):
    rows = _deltas()
    path = tmp_path / "cands.jsonl"
    first = rc.persist_candidates(rows[:-1], path=path)
    after = rc.persist_candidates(rows, path=path, new_records=rows[-1:])
    full_all = {c["candidate_id"] for c in rc.find_contradiction_candidates(rows)}
    import json
    on_disk = {json.loads(x)["candidate_id"] for x in path.read_text().splitlines() if x.strip()}
    assert on_disk == full_all
    assert after["written"] == len(full_all) - first["written"]
