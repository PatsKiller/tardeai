"""Research governance — multiple-testing validation tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import multiple_testing as mt  # noqa: E402


def test_bonferroni_reference():
    r = mt.bonferroni([0.001, 0.01, 0.2, 0.5], alpha=0.05)
    assert r["rejected"] == [True, True, False, False]
    assert r["adjusted"][0] == pytest.approx(0.004)


def test_holm_more_powerful_than_bonferroni():
    p = [0.001, 0.01, 0.02, 0.04]
    bh = mt.holm(p, alpha=0.05)
    assert bh["rejected"] == [True, True, True, True]


def test_bh_fdr_rejects_smallest():
    r = mt.benjamini_hochberg([0.001, 0.5, 0.9], alpha=0.05)
    assert r["rejected"][0] is True


@pytest.mark.parametrize("bad", [
    [0.5, -0.1],
    [0.5, 1.5],
    [0.5, float("nan")],
    [0.5, float("inf")],
    [0.5, float("-inf")],
])
def test_invalid_pvalues_rejected(bad):
    with pytest.raises(ValueError):
        mt.bonferroni(bad, alpha=0.05)
    with pytest.raises(ValueError):
        mt.holm(bad, alpha=0.05)
    with pytest.raises(ValueError):
        mt.benjamini_hochberg(bad, alpha=0.05)


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.05, 1.05, float("nan"), float("inf")])
def test_invalid_alpha_rejected(alpha):
    with pytest.raises(ValueError):
        mt.bonferroni([0.01, 0.02], alpha=alpha)


def test_empty_input_ok():
    assert mt.bonferroni([], alpha=0.05)["adjusted"] == []
