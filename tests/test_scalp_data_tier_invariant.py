#!/usr/bin/env python3
"""G4.3 — data-tier ladder monotonicity invariant. Reads the LIVE config (not hardcoded values) and
asserts that, ordered by descending data quality, size_multiplier (dcf) is non-increasing and
assumed_slippage_bps is non-decreasing. This is the actual G4 deliverable: whatever the tiers are
named, descending a tier must never relax a risk gate. Impossible to violate silently in a future edit."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
DT = CFG["data_tiers"]
ORDER = DT["quality_order"]          # best data → worst data


def test_quality_order_covers_all_tiers():
    assert set(ORDER) == set(DT["dcf"].keys()) == set(DT["assumed_slippage_bps"].keys())
    assert len(ORDER) == len(set(ORDER))  # no dupes


def test_size_multiplier_non_increasing_with_falling_quality():
    dcf = [float(DT["dcf"][t]) for t in ORDER]
    assert all(dcf[i] >= dcf[i + 1] for i in range(len(dcf) - 1)), f"dcf not non-increasing along {ORDER}: {dcf}"


def test_assumed_slippage_non_decreasing_with_falling_quality():
    slip = [float(DT["assumed_slippage_bps"][t]) for t in ORDER]
    assert all(slip[i] <= slip[i + 1] for i in range(len(slip) - 1)), f"slippage not non-decreasing along {ORDER}: {slip}"


def test_worst_tier_never_has_the_top_multiplier():
    # the concrete failure the ladder exists to prevent: weakest data inheriting the biggest size
    worst = ORDER[-1]
    assert float(DT["dcf"][worst]) == min(float(v) for v in DT["dcf"].values())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
