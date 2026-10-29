"""The hermes_score_snapshots_2h SLO compares like-with-like (2026-10-29 false-positive fix).

The scorer writes far fewer rows pre-market than during market hours
(hermes_watchlist_scorer._tier_plan: market = S0+S1, pre-market 7-8h = S0+S2, 8-9:30h = S0,
off-hours = S0 once/hour + no-change skip ~100%). The old baseline daily_median/12 assumed uniform
24h volume and false-WARNed every pre-market morning (349 rows vs ~1569 on 2026-10-29 09:15 ET,
while the live receipt showed 800 scored / 0 errored). The baseline is now the median of the SAME
ET clock-hour across the trailing 7 days, x2 for the 2h window. Hermetic: no DB, no broker.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pipeline_freshness_slo as pfs  # noqa: E402


def _check():
    return next(c for c in pfs.CHECKS if c[0] == "hermes_score_snapshots_2h")


def test_baseline_is_same_clock_hour_not_daily_median():
    name, recent, baseline, factor = _check()
    assert "/12" not in baseline, "daily-median/12 baseline reintroduced"
    assert "EXTRACT(HOUR" in baseline and "AT TIME ZONE 'America/New_York'" in baseline
    # x2 approximates the 2h window against a single same-clock-hour median.
    assert re.search(r"\)\*2\b", baseline), "baseline must scale the same-hour median to a 2h window"
    assert factor == 1.0
    # recent window unchanged (2h) — the fix is the baseline only.
    assert "INTERVAL '2 hours'" in recent


def test_no_other_check_regressed_to_a_daily_median_baseline():
    """Only the scorer check changed; every other check keeps its existing baseline shape."""
    for name, _r, baseline, _f in pfs.CHECKS:
        if name == "hermes_score_snapshots_2h":
            continue
        assert "EXTRACT(HOUR FROM (scored_at" not in baseline, f"{name} unexpectedly rewired"
