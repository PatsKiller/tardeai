"""The Oscillator Affiliations board must read each oscillator from its own store.

PR #973 fixed the READING field (rs20 vs breadth_pct). Three defects survived it,
all reproduced against the real producer snapshots on 2026-09-12.

    industry_momentum_latest.json  top-level keys include 'captured_at'
                                   and DO NOT include 'generated_at'

    sector_momentum_latest.json    rows[0] has one 'state' field and no
                                   'breadth_state'

So the industry row read `snap["generated_at"]` -> None -> the UI rendered the
literal string "never" beside a live reading of -19.59, and the breadth row read
the SAME `rows[0]["state"]` as the RS row, so the two oscillators could never
display different states. A board whose purpose is to say which oscillator a
reading came from was doing the opposite.
"""

from __future__ import annotations

import pytest

from scripts.api_v2 import _attach_oscillator_reading

INDUSTRY_SNAP = {
    "captured_at": "2026-09-11T20:20:03.782705+00:00",
    "capture_kind": "intraday",
    "industries": [
        {"industry": "Advertising Agencies", "rel1m": 4.24, "state": "LEADING"},
    ],
}

SECTOR_SNAP = {
    "generated_at": "2026-09-11T21:27:36.181350+00:00",
    "rows": [{"sector": "Technology", "rs20": 1.22, "breadth_pct": 26, "state": "LEADING"}],
    "market": {"styles": [{"s20": -1.86, "state": "NARROWING"}]},
}


def _row(oid):
    return {"oscillator_id": oid, "state": None, "reading": None, "as_of": None}


def test_industry_age_reads_the_timestamp_the_producer_actually_emits():
    """PR #974 defect 1. The producer stamps captured_at; the board read
    generated_at, which the snapshot does not have."""
    row = _row("industry_momentum_quadrant")
    _attach_oscillator_reading(row, "industry_momentum_quadrant", INDUSTRY_SNAP)
    assert row["reading"] == 4.24
    assert row["as_of"] == "2026-09-11T20:20:03.782705+00:00", (
        "as_of is None, so the UI renders the literal 'never' next to a live reading"
    )


def test_breadth_does_not_borrow_the_rs_oscillators_state():
    """The row carries ONE state field, computed for RS. Showing it as the
    breadth state makes the two oscillators permanently identical."""
    rs, breadth = _row("sector_momentum_rs"), _row("sector_breadth_20dma")
    _attach_oscillator_reading(rs, "sector_momentum_rs", SECTOR_SNAP)
    _attach_oscillator_reading(breadth, "sector_breadth_20dma", SECTOR_SNAP)
    assert rs["reading"] == 1.22 and breadth["reading"] == 26
    assert rs["state"] == "LEADING"
    assert breadth["state"] is None, (
        "breadth has no state of its own in the producer snapshot; an absent "
        "state must read as absent, not as the RS oscillator's state"
    )


def test_a_breadth_state_is_used_when_the_producer_does_emit_one():
    """The fix must not hardcode None — it must read breadth's own field if the
    producer ever starts emitting it."""
    snap = {
        "generated_at": "2026-09-11T21:27:36Z",
        "rows": [{"rs20": 1.22, "breadth_pct": 26, "state": "LEADING", "breadth_state": "NARROW"}],
    }
    row = _row("sector_breadth_20dma")
    _attach_oscillator_reading(row, "sector_breadth_20dma", snap)
    assert row["state"] == "NARROW"


def test_an_oscillator_with_no_reading_publishes_no_timestamp():
    """A row with state=None and reading=None used to publish a foreign
    producer's generated_at, which renders as a concrete age for a reading that
    does not exist."""
    row = _row("sector_comovement")
    _attach_oscillator_reading(row, "sector_comovement", SECTOR_SNAP)
    if row["reading"] is None and row["state"] is None:
        assert row["as_of"] is None, (
            "published an age for a reading that does not exist"
        )


def test_an_empty_snapshot_leaves_every_field_absent():
    for oid in (
        "sector_momentum_rs",
        "style_spread",
        "sector_breadth_20dma",
        "industry_momentum_quadrant",
    ):
        row = _row(oid)
        _attach_oscillator_reading(row, oid, {})
        assert row["reading"] is None and row["as_of"] is None and row["state"] is None


def test_style_spread_still_reads_its_own_field():
    row = _row("style_spread")
    _attach_oscillator_reading(row, "style_spread", SECTOR_SNAP)
    assert row["reading"] == -1.86
    assert row["state"] == "NARROWING"
