"""finviz-enrichment's skipped_reasons must PARTITION attempted_count (queue item 2, 2026-11-07).

The 2026-11-06 13:00 ET receipt said, in one document:

    produced_count 3 · attempted_count 6 · skipped_reasons {"no_view_data": 3, "rejected_non_ticker": 3}

which cannot all be true: 3 produced + 6 skipped > 6 attempted. ``rejected_non_ticker`` is counted over the whole
requested universe in ``_split_equities`` — BEFORE the stale set exists — so a rejected symbol is never attempted.
Counting it as a skip graded a healthy run DEGRADED:

    "Ran live 26 h ago and wrote output, but: skipped 6 items, more than it produced (3)"

fails the production grade (scripts/lib/run_quality.py ``receipt_flags``, ``excluded_notes``). A structurally
refused candidate belongs in ``excluded_reasons``, as news-to-catalyst does for the same defect (WORK-QUEUE item 26).

Hermetic: pure function + the real grading helper. No DB, no network, no file write.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_enrichment as fe  # noqa: E402
from lib.run_quality import excluded_notes, receipt_flags  # noqa: E402

# The live 2026-11-06 shape (served release data/runtime/finviz-enrichment_last.json): 95 requested symbols, 3 of
# them not tickers, 6 stale, 3 refreshed with at least one Finviz view.
LIVE = {"symbols": 95, "stale": 6, "refreshed": 3, "rejected_non_ticker": 3}


def _receipt(out: dict, produced: int | None = None) -> dict:
    """The document write_lane_receipt builds from a lane_output() block (v1 body + additive v2 fields)."""
    return {
        "schema": "LaneRunReceipt@v1",
        "lane_id": "finviz-enrichment",
        "mode": "live",
        "status": "ok",
        "summary": {"symbols": LIVE["symbols"], "stale": LIVE["stale"]},
        "produced_count": LIVE["refreshed"] if produced is None else produced,
        **out,
    }


# ── the account adds up ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("stats", [
    LIVE,
    {"symbols": 95, "stale": 6, "refreshed": 6, "rejected_non_ticker": 3},
    {"symbols": 95, "stale": 6, "refreshed": 0, "rejected_non_ticker": 0},
    {"symbols": 95, "stale": 0, "refreshed": 0, "rejected_non_ticker": 3},
])
def test_produced_plus_skipped_equals_attempted(stats):
    # An empty universe is deliberately NOT in this list: its ``universe_empty_unexpected`` marker is a run-level
    # fatal signal, not an item account, and it is covered by its own test below.
    out = fe.lane_output(stats["symbols"], stats)
    assert out["produced_count"] + sum(out["skipped_reasons"].values()) == out["attempted_count"], out


def test_a_rejected_non_ticker_is_excluded_never_skipped():
    out = fe.lane_output(LIVE["symbols"], LIVE)
    assert out["skipped_reasons"] == {"no_view_data": 3}
    assert out["excluded_reasons"] == {"rejected_non_ticker": 3}
    assert "rejected_non_ticker" not in out["skipped_reasons"]


def test_no_exclusions_is_an_empty_block_not_a_zero():
    # A zero is a claim ("none were rejected"); no keys at all is the same claim made by absence. Prefer absence:
    # the operator's excluded line then simply does not appear.
    out = fe.lane_output(95, {**LIVE, "rejected_non_ticker": 0})
    assert out["excluded_reasons"] == {}


def test_an_unreported_rejection_count_is_unknown_not_zero():
    # No key = the caller did not say. Omitting the block makes no claim; a zero would claim "none were rejected".
    stats = {"symbols": 95, "stale": 6, "refreshed": 3}
    out = fe.lane_output(stats["symbols"], stats)
    assert out["excluded_reasons"] == {}
    assert out["produced_count"] + sum(out["skipped_reasons"].values()) == out["attempted_count"]


# ── the defect the account caused: the production grade ─────────────────────────────────────────────────────


def test_the_live_receipt_shape_no_longer_grades_degraded():
    out = fe.lane_output(LIVE["symbols"], LIVE)
    flags = receipt_flags(_receipt(out), count=out["produced_count"])
    assert flags == [], flags


def test_the_old_account_really_did_flag_it():
    # The pre-fix block, verbatim: this is what produced "skipped 6 items, more than it produced (3)".
    old = {"produced_count": 3, "attempted_count": 6,
           "skipped_reasons": {"no_view_data": 3, "rejected_non_ticker": 3}, "empty_reason": None}
    flags = receipt_flags(_receipt(old), count=3)
    assert "skipped 6 items, more than it produced (3)" in flags


def test_the_operator_still_sees_the_exclusions():
    out = fe.lane_output(LIVE["symbols"], LIVE)
    notes = excluded_notes(_receipt(out))
    assert notes == ["structurally excluded 3 of 9 candidates (rejected_non_ticker = 3) — never eligible, not skips"], notes


# ── fatal signals still reach the receipt ───────────────────────────────────────────────────────────────────


def test_a_failed_universe_read_still_sets_dependency_unavailable():
    out = fe.lane_output(0, {"stale": 0, "refreshed": 0}, universe_failed=True)
    assert out["skipped_reasons"]["dependency_unavailable"] == 1


def test_an_empty_default_universe_still_sets_universe_empty_unexpected():
    out = fe.lane_output(0, {"stale": 0, "refreshed": 0})
    assert out["skipped_reasons"]["universe_empty_unexpected"] == 1
    assert out["empty_reason"] is None


def test_nothing_stale_is_a_typed_no_new_input():
    out = fe.lane_output(95, {**LIVE, "stale": 0, "refreshed": 0})
    assert out["empty_reason"] == "no_new_input"
    assert out["attempted_count"] == 0
