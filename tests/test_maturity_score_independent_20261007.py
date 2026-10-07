"""The maturity headline is not an input. Absent proofs score 1."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import maturity_remeasure as mr  # noqa: E402


def _empty() -> dict:
    return {
        "overall": 4.7,
        "degraded_share": None,
        "decide_contexts": 0,
        "influence_modes": {},
        "lanes_with_contexts": 0,
        "mir_commits": 0,
        "lessons_promoted": 0,
        "checkpoints": 0,
        "resumes": 0,
        "write_path_lanes": 0,
        "write_path_live": 0,
        "fanout_items": 0,
        "silos_total": 0,
        "silos_conformant": 0,
        "gir_entities": 0,
        "gir_edges": 0,
        "filing_events": 0,
        "verdicts_resolved": 0,
        "contexts_committed": 0,
        "routing_receipts": 0,
        "lanes_beating": 0,
        "breaches": 0,
        "ladder_receipts": 0,
        "ladder_paged": 0,
        "retrieval_receipts": 0,
        "retrieval_hit_fresh": 0,
        "verdicts": 0,
        "chooser_receipts": 0,
        "ring2_rows": 0,
        "chooser_enforced": 0,
        "contexts_refused": 0,
        "conformance_as_of": None,
        "gate_receipts": 0,
        "gate_block_mode": False,
        "heartbeat_files": 0,
    }


def test_a_headline_overall_does_not_raise_the_score():
    rows = mr.score(_empty())
    assert {row["domain"] for row in rows} == set(mr.DOMAINS)
    assert all(row["score"] == 1 for row in rows)
