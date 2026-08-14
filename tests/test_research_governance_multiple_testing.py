"""Research governance — multiple-testing dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import multiple_testing as mt  # noqa: E402


def test_bonferroni_known_result():
    r = mt.bonferroni([0.001, 0.01, 0.2, 0.5], alpha=0.05)
    assert r["rejected"] == [True, True, False, False]
    assert r["adjusted"][0] == 0.004
    assert r["adjusted"][2] == 0.8


def test_holm_is_monotonic_and_rejects():
    r = mt.holm([0.001, 0.01, 0.2, 0.5], alpha=0.05)
    assert r["rejected"] == [True, True, False, False]


def test_bh_rejects_expected():
    r = mt.benjamini_hochberg([0.001, 0.01, 0.2, 0.5], alpha=0.05)
    assert r["rejected"][0] is True
    assert r["rejected"][1] is True
    # q-values are clamped to [0,1]
    assert all(0.0 <= q <= 1.0 for q in r["adjusted"])


def test_bh_qvalues_non_decreasing_in_rank():
    # BH q-values, sorted by p ascending, must be monotone (step-up property).
    pvals = [0.05, 0.01, 0.03, 0.001, 0.1]
    r = mt.benjamini_hochberg(pvals, alpha=0.05)
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    q_in_order = [r["adjusted"][i] for i in order]
    assert q_in_order == sorted(q_in_order)


def test_empty_input():
    for fn in (mt.bonferroni, mt.holm, mt.benjamini_hochberg):
        r = fn([], alpha=0.05)
        assert r["adjusted"] == []
        assert r["rejected"] == []
