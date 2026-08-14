"""Research governance — White Reality Check null-centered bootstrap tests (PR-R1)."""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import bootstrap_reality_check as rc  # noqa: E402


def _null_family(seed=0, n=100):
    rng = random.Random(seed)
    return [[rng.gauss(0, 1) for _ in range(n)] for _ in range(5)]


def _alternative(seed=0, n=100, drift=0.25):
    rng = random.Random(seed)
    return [[drift + rng.gauss(0, 1) for _ in range(n)] for _ in range(3)]


def test_null_family_does_not_spuriously_reject():
    r = rc.reality_check_pvalue(_null_family(), n_bootstrap=1000, seed=1)
    assert r["status"] == "OK"
    assert r["bootstrap_pvalue"] > 0.1


def test_obvious_alternative_small_pvalue():
    r = rc.reality_check_pvalue(_alternative(), n_bootstrap=1000, seed=1)
    assert r["bootstrap_pvalue"] < 0.01


def test_family_correction_not_more_favorable_than_winner_only():
    rng = random.Random(0)
    strong = [0.2 + rng.gauss(0, 1) for _ in range(100)]
    weak = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(4)]
    single = rc.reality_check_pvalue([strong], n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    family = rc.reality_check_pvalue([strong] + weak, n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    # Searching the full family can only be LESS significant (>=) than cherry-picking.
    assert family >= single


def test_deterministic_seeded_reproducibility():
    data = _alternative(seed=3)
    a = rc.reality_check_pvalue(data, n_bootstrap=500, seed=42)["bootstrap_pvalue"]
    b = rc.reality_check_pvalue(data, n_bootstrap=500, seed=42)["bootstrap_pvalue"]
    assert a == b


def test_rejects_nonfinite_and_bad_params():
    assert rc.reality_check_pvalue([[0.1, float("nan")]])["status"] == "UNAVAILABLE"
    assert rc.reality_check_pvalue([[0.1], [0.2, 0.3]])["status"] == "UNAVAILABLE"
    assert rc.reality_check_pvalue(_null_family(), n_bootstrap=0)["status"] == "UNAVAILABLE"
    assert rc.reality_check_pvalue(_null_family(), mean_block_length=0)["status"] == "UNAVAILABLE"


def test_calendar_family_reports_provenance():
    r = rc.calendar_family_reality_check(
        "september_midterm", _alternative(), n_bootstrap=500, seed=1,
        family_definition_hash="abc123",
    )
    assert r["family_id"] == "september_midterm"
    assert r["family_definition_hash"] == "abc123"
