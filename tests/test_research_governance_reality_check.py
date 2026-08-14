"""Research governance — Reality Check / STW dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import bootstrap_reality_check as rc  # noqa: E402


def _family(n_rules=3, n_obs=60):
    out = []
    for i in range(n_rules):
        out.append([((i + 1) * 0.0005) + (((j * 11 + i * 5) % 7) - 3) * 0.01
                    for j in range(n_obs)])
    return out


def test_reality_check_pvalue_in_range():
    r = rc.reality_check_pvalue(_family(), n_bootstrap=500, seed=0)
    assert r["status"] == "OK"
    assert 0.0 < r["bootstrap_pvalue"] <= 1.0
    assert r["n_rules"] == 3


def test_reality_check_empty_family_unavailable():
    r = rc.reality_check_pvalue([], n_bootstrap=100)
    assert r["status"] == "UNAVAILABLE"


def test_reality_check_unequal_lengths_unavailable():
    r = rc.reality_check_pvalue([[0.1, 0.2], [0.1, 0.2, 0.3]])
    assert r["status"] == "UNAVAILABLE"


def test_reality_check_deterministic():
    fam = _family()
    r1 = rc.reality_check_pvalue(fam, n_bootstrap=200, seed=3)
    r2 = rc.reality_check_pvalue(fam, n_bootstrap=200, seed=3)
    assert r1["bootstrap_pvalue"] == r2["bootstrap_pvalue"]


def test_calendar_family_propagates_id():
    r = rc.calendar_family_reality_check("sep_midterm", _family(), n_bootstrap=200, seed=1)
    assert r["family_id"] == "sep_midterm"
    assert r["status"] == "OK"


def test_strong_family_beats_weak_family():
    # A clearly-superior family should have a lower (more significant) p-value
    # than a family of near-zero differentials, on the same bootstrap budget.
    strong = [[0.05 if j % 2 == 0 else 0.03 for j in range(60)],
              [0.04 if j % 3 == 0 else 0.02 for j in range(60)]]
    weak = [[((j * 7) % 5 - 2) * 0.001 for j in range(60)],
            [((j * 9) % 5 - 2) * 0.001 for j in range(60)]]
    rs = rc.reality_check_pvalue(strong, n_bootstrap=1000, seed=0)
    rw = rc.reality_check_pvalue(weak, n_bootstrap=1000, seed=0)
    assert rs["observed_max_mean"] > rw["observed_max_mean"]
    assert rs["bootstrap_pvalue"] < rw["bootstrap_pvalue"]
