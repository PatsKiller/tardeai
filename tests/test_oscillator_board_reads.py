#!/usr/bin/env python3
"""The Oscillator Affiliations board must read each oscillator from ITS OWN
place in the snapshot.

Cause: the first implementation read `rows[0]` for every sector-scope
oscillator, so "Style Rotation" and "Sector Breadth" both displayed the first
sector's RS20 (e.g. Sector Rotation 4.06 / LEADING when every style was
LAGGING and breadth was 27%). That is the exact "which oscillator is this"
confusion the board exists to remove.

Driven hermetically (no DB, no captured file): a synthetic snapshot mirroring
the real sector_momentum_latest.json shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import api_v2  # noqa: E402

SNAP = {
    "generated_at": "2026-09-11T21:00:00Z",
    "rows": [
        {"etf": "XLK", "sector": "Technology", "state": "LEADING",
         "rs20": 4.06, "breadth_pct": 27},
        {"etf": "XLI", "sector": "Industrials", "state": "LAGGING",
         "rs20": -2.7, "breadth_pct": 24},
    ],
    "market": {
        "styles": [
            {"key": "growth_vs_value", "pair": "VUG-VTV", "s20": -1.86, "state": "LAGGING"},
        ]
    },
}


def _row(oid: str) -> dict:
    return {"oscillator_id": oid, "state": None, "reading": None, "as_of": None}


def test_sector_rotation_reads_the_first_sector_rs20():
    row = _row("sector_momentum_rs")
    api_v2._attach_oscillator_reading(row, "sector_momentum_rs", SNAP)
    assert row["reading"] == 4.06
    assert row["state"] == "LEADING"


def test_style_spread_reads_styles_not_the_sector_rows():
    """The regression: style must show LAGGING -1.86, not the sector's LEADING 4.06."""
    row = _row("style_spread")
    api_v2._attach_oscillator_reading(row, "style_spread", SNAP)
    assert row["reading"] == -1.86
    assert row["state"] == "LAGGING"


def test_sector_breadth_reads_breadth_not_rs20():
    """The regression: breadth must show 27 (%), not RS20 4.06."""
    row = _row("sector_breadth_20dma")
    api_v2._attach_oscillator_reading(row, "sector_breadth_20dma", SNAP)
    assert row["reading"] == 27
    # breadth is a raw percent; state is inherited from the sector row only
    # for a representative context, never a fabricated oscillator state.


def test_sector_comovement_reads_nothing_but_marks_freshness():
    row = _row("sector_comovement")
    api_v2._attach_oscillator_reading(row, "sector_comovement", SNAP)
    assert row["as_of"] == "2026-09-11T21:00:00Z"
    assert row["reading"] is None  # co-movement is a count, not a level


def test_negative_control_style_and_sector_never_share_a_reading():
    """Even with only one sector row, style and sector must not collide."""
    s = _row("sector_momentum_rs")
    t = _row("style_spread")
    api_v2._attach_oscillator_reading(s, "sector_momentum_rs", SNAP)
    api_v2._attach_oscillator_reading(t, "style_spread", SNAP)
    assert s["reading"] != t["reading"], (
        "sector and style readings are identical — the board is showing one "
        "oscillator's value for another"
    )


def test_industry_reads_captured_at_not_generated_at():
    """The industry snapshot stamps `captured_at`, not `generated_at`.

    Reading the wrong field made the live board show "Age: never" for a
    snapshot that is perfectly fresh, which reads as a dead producer.
    """
    snap = {
        "captured_at": "2026-09-11T12:00:00Z",
        "generated_at": None,
        "industries": [{"state": "IMPROVING", "rel1m": -19.59}],
    }
    row = _row("industry_momentum_quadrant")
    api_v2._attach_oscillator_reading(row, "industry_momentum_quadrant", snap)
    assert row["as_of"] == "2026-09-11T12:00:00Z"
    assert row["state"] == "IMPROVING"
    assert row["reading"] == -19.59

