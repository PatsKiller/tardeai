"""Research governance — PBO/CSCV dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import pbo  # noqa: E402


def _matrix(n_configs: int, n_obs: int):
    # Deterministic pseudo-return matrix: config i has a small persistent edge.
    out = []
    for i in range(n_configs):
        out.append([((i + 1) * 0.001) + (((j * 7 + i * 13) % 5) - 2) * 0.005
                    for j in range(n_obs)])
    return out


def test_pbo_single_config_not_applicable():
    r = pbo.cscv_probability_of_backtest_overfitting([[0.01, 0.02]])
    assert r["status"] == "NOT_APPLICABLE"


def test_pbo_requires_divisible_length():
    m = _matrix(3, 10)  # 10 not divisible by default S=16
    r = pbo.cscv_probability_of_backtest_overfitting(m, n_subsets=16)
    assert r["status"] == "UNAVAILABLE"


def test_pbo_computes_in_range():
    m = _matrix(3, 16)
    r = pbo.cscv_probability_of_backtest_overfitting(m, n_subsets=4, seed=0)
    assert r["status"] == "OK"
    assert 0.0 <= r["pbo"] <= 1.0
    assert r["n_configs"] == 3
    assert r["n_combinations_evaluated"] == 6  # C(4,2)


def test_pbo_deterministic_given_seed():
    m = _matrix(4, 32)
    r1 = pbo.cscv_probability_of_backtest_overfitting(m, n_subsets=4, seed=7)
    r2 = pbo.cscv_probability_of_backtest_overfitting(m, n_subsets=4, seed=7)
    assert r1["pbo"] == r2["pbo"]


def test_pbo_unequal_lengths_unavailable():
    r = pbo.cscv_probability_of_backtest_overfitting([[0.01, 0.02], [0.01, 0.02, 0.03]])
    assert r["status"] == "UNAVAILABLE"


def test_pbo_odd_subsets_unavailable():
    r = pbo.cscv_probability_of_backtest_overfitting(_matrix(3, 9), n_subsets=3)
    assert r["status"] == "UNAVAILABLE"
