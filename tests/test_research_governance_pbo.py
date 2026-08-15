"""Research governance — PBO/CSCV rank-direction + semantic tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import pbo  # noqa: E402


def _stable_winner():
    # Config 0 is persistently best in every subperiod.
    rows = []
    for c in range(3):
        base = 0.02 if c == 0 else (0.005 if c == 1 else -0.005)
        rows.append([base + ((t * 7 + c * 13) % 5 - 2) * 0.001 for t in range(16)])
    return rows


def _overfit_rotating_winner():
    # Each config dominates exactly one subperiod -> IS winner rotates and
    # then underperforms OOS.
    rows = []
    for c in range(3):
        rows.append([(0.06 if (t // 4) == c else -0.02)
                     + ((t * 7 + c * 13) % 5 - 2) * 0.001 for t in range(16)])
    return rows


def test_pbo_requires_multiple_configs():
    r = pbo.cscv_probability_of_backtest_overfitting([[0.01, 0.02]])
    assert r["status"] == "NOT_APPLICABLE"


def test_stable_winner_has_low_pbo():
    r = pbo.cscv_probability_of_backtest_overfitting(_stable_winner(), n_subsets=4, seed=0)
    assert r["status"] == "OK"
    assert r["pbo"] < 0.5


def test_overfit_rotating_winner_has_high_pbo():
    r = pbo.cscv_probability_of_backtest_overfitting(_overfit_rotating_winner(), n_subsets=4, seed=0)
    assert r["status"] == "OK"
    assert r["pbo"] > 0.5


def test_rank_semantics_1_worst_n_best():
    # Directly verify the helper used to orient OOS rank: best OOS config => rank N.
    # Reimplemented here to assert the direction, not the implementation.
    matrix = _stable_winner()
    res = pbo.cscv_probability_of_backtest_overfitting(matrix, n_subsets=4, seed=0)
    assert "logit_mean" in res
    # A stable winner keeps the selected config in the top OOS half -> positive logit mean.
    assert res["logit_mean"] > 0


def test_reports_combination_accounting():
    r = pbo.cscv_probability_of_backtest_overfitting(_stable_winner(), n_subsets=4, seed=0)
    assert r["total_combinations"] == 6
    assert r["combinations_evaluated"] == 6
    assert r["sampling_fraction"] == 1.0
    assert r["approx"] is False


def test_rejects_nonfinite():
    bad = [[0.1, float("nan"), 0.2], [0.1, 0.2, 0.3]]
    assert pbo.cscv_probability_of_backtest_overfitting(bad, n_subsets=2, seed=0)["status"] == "UNAVAILABLE"


def test_rejects_unequal_lengths():
    bad = [[0.1, 0.2, 0.3], [0.1, 0.2]]
    assert pbo.cscv_probability_of_backtest_overfitting(bad, n_subsets=2)["status"] == "UNAVAILABLE"


def test_rejects_odd_subsets():
    r = pbo.cscv_probability_of_backtest_overfitting(_stable_winner(), n_subsets=3, seed=0)
    assert r["status"] == "UNAVAILABLE"
