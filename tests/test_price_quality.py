"""Corrupt-price detection — audit finding C3, Stage B.

Fixtures are the real production shapes, because the two mistakes worth guarding
against are both shapes rather than thresholds: a *run* of corrupt rows that
hides from neighbour comparison, and a *split* that an over-eager rule flags on
both sides.
"""
from __future__ import annotations

from scripts.lib.price_quality import (
    REASON_DEVIATION,
    REASON_NAN,
    REASON_NON_POSITIVE,
    classify_series,
    find_corrupt_rows,
)


def _flat(price: float, n: int, start: int = 0) -> list[tuple[str, float]]:
    return [(f"d{start + i:03d}", price) for i in range(n)]


def test_nvda_run_is_caught():
    """The known-bad case: 3 consecutive corrupt rows between ~$200 closes.

    Adjacent-row comparison misses this entirely -- each corrupt row's neighbour
    is also corrupt, so the step between them is small. This is why the baseline
    is a window median with the immediate neighbours excluded.
    """
    rows = _flat(200.0, 8) + [("d008", 0.66), ("d009", 0.18), ("d010", 0.05)] + _flat(208.0, 8, 11)
    flagged = find_corrupt_rows(rows)

    assert [f.date for f in flagged] == ["d008", "d009", "d010"]
    assert all(f.reason == REASON_DEVIATION for f in flagged)
    assert all(f.ratio and f.ratio > 100 for f in flagged)


def test_reverse_split_is_not_flagged():
    """A 1:400 step that persists is a split, not corruption — flag nothing.

    An earlier single-median version flagged BOTH sides of exactly this shape on
    SRNE (0.0008 -> 0.2954, sustained), which would have quarantined good rows.
    """
    rows = _flat(0.0007, 10) + _flat(0.2954, 10, 10)
    assert find_corrupt_rows(rows) == []


def test_isolated_dip_inside_the_post_split_regime_is_caught():
    """SRNE's real corruption: one stale 0.0008 between sustained 0.2954s."""
    rows = _flat(0.2954, 8) + [("d008", 0.0008)] + _flat(0.2954, 8, 9)
    flagged = find_corrupt_rows(rows)

    assert [f.date for f in flagged] == ["d008"]


def test_spike_up_inside_a_low_regime_is_caught():
    """HAO's shape: a single ~$90 print inside a ~$0.73 series."""
    rows = _flat(0.73, 8) + [("d008", 90.62)] + _flat(0.71, 8, 9)
    flagged = find_corrupt_rows(rows)

    assert [f.date for f in flagged] == ["d008"]
    assert flagged[0].price == 90.62


def test_nan_and_non_positive_need_no_baseline():
    """A price cannot be NaN or zero — no window required to know that."""
    rows = _flat(10.0, 5) + [("d005", float("nan")), ("d006", 0.0)] + _flat(10.0, 5, 7)
    by_reason = {f.date: f.reason for f in find_corrupt_rows(rows)}

    assert by_reason["d005"] == REASON_NAN
    assert by_reason["d006"] == REASON_NON_POSITIVE


def test_ordinary_volatility_is_left_alone():
    """A 40% crash is not corruption. The rule must not touch real moves."""
    rows = _flat(100.0, 8) + [("d008", 60.0)] + _flat(58.0, 8, 9)
    assert find_corrupt_rows(rows) == []


def test_short_series_declines_to_judge():
    """Too little surrounding data to form a baseline: say nothing, don't guess."""
    assert find_corrupt_rows([("d000", 100.0), ("d001", 0.01)]) == []


def test_series_edges_are_not_flagged_for_lack_of_context():
    """The first and last rows have no two-sided baseline, so they are left alone.

    A deliberate blind spot: judging an edge row means extrapolating, and a wrong
    quarantine is worse than a missed one. Recorded so it is a known limit.
    """
    rows = [("d000", 0.01)] + _flat(200.0, 12, 1)
    assert find_corrupt_rows(rows) == []


def test_classify_reports_steps_separately():
    """Splits are counted, not silently ignored — the caller can see the decision."""
    rows = _flat(0.0007, 10) + _flat(0.2954, 10, 10)
    result = classify_series(rows)

    assert result["corrupt_rows"] == 0
    assert result["step_like_rows"] >= 1


def test_findings_serialize():
    rows = _flat(200.0, 8) + [("d008", 0.05)] + _flat(200.0, 8, 9)
    d = find_corrupt_rows(rows)[0].as_dict()

    assert d["date"] == "d008"
    assert d["reason"] == REASON_DEVIATION
    assert d["schema"] == "PriceQualityFinding@v1"
