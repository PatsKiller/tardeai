"""R-07 (2026-09-15): a drained desk suggestion still under review keeps its verdict and state."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import cio_opportunity_queue as q  # noqa: E402

HIT_DIVI = {"symbol": "DIVI", "source": "reentry", "directive_label": "Re-entry READY TO REVIEW: DIVI",
            "surfaced_at": "2026-09-15T14:20:02+00:00"}
STAGED_DIVI = {"symbol": "DIVI", "source": "reentry", "directive_label": "Re-entry READY TO REVIEW: DIVI",
               "verdict": None, "state": "READY TO REVIEW", "rs_score": None,
               "surfaced_at": "2026-09-15T14:20:02+00:00", "drained": True}
STAGED_CLOSED = dict(STAGED_DIVI, symbol="CAST", state="NEAR ENTRY")


def _executor(hits, staged_by_table):
    def run(sql, params=None, fetch=None):
        if "FROM watch_directive_hits" in sql:
            return hits
        for tbl, rows in staged_by_table.items():
            if f"FROM {tbl}" in sql:
                return [dict(r) for r in rows]
        return []
    return run


def test_state_survives_the_drain_while_the_hit_is_under_review():
    rows = q.fetch_desk_suggestions(_executor([HIT_DIVI], {"reentry_directive_hits_staging": [STAGED_DIVI]}))
    assert [(r["symbol"], r.get("state")) for r in rows] == [("DIVI", "READY TO REVIEW")]
    assert "drained" not in rows[0]


def test_a_drained_row_whose_review_is_closed_is_not_resurrected():
    rows = q.fetch_desk_suggestions(_executor([], {"reentry_directive_hits_staging": [STAGED_CLOSED]}))
    assert rows == []


def test_an_undrained_row_is_read_as_before():
    rows = q.fetch_desk_suggestions(_executor([], {"reentry_directive_hits_staging": [dict(STAGED_CLOSED, drained=False)]}))
    assert [(r["symbol"], r["state"]) for r in rows] == [("CAST", "NEAR ENTRY")]


def test_a_hit_with_no_staging_row_is_still_queued():
    rows = q.fetch_desk_suggestions(_executor([dict(HIT_DIVI, symbol="ARMP")], {}))
    assert [r["symbol"] for r in rows] == ["ARMP"]


def test_the_queue_counts_one_opportunity_per_reviewed_name():
    rows = q.fetch_desk_suggestions(_executor([HIT_DIVI], {"reentry_directive_hits_staging": [STAGED_DIVI]}))
    assert q.build_opportunity_queue(rows)["count"] == 1
