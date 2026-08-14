"""Research governance — Deflated Sharpe ratio golden/translation tests (PR-R1)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import deflated_sharpe as ds  # noqa: E402

# Frozen reference vector (Bailey & López de Prado DSR). Trials = 10 Sharpes.
DSR_TRIALS = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
DSR_GOLDEN_BENCHMARK = 0.503279766668363


def test_norm_ppf_matches_known_values():
    # Independent textbook values for the standard-normal inverse CDF.
    assert abs(ds.norm_ppf(0.9) - 1.2815515655446004) < 1e-6
    assert abs(ds.norm_ppf(0.975) - 1.959963984540054) < 1e-6


def test_norm_cdf_symmetric():
    assert abs(ds.norm_cdf(0.0) - 0.5) < 1e-12
    assert abs(ds.norm_cdf(1.96) - 0.975) < 1e-3


def test_deflated_benchmark_golden_reference():
    r = ds.deflated_benchmark_sr(DSR_TRIALS, 10)
    assert r["status"] == "OK"
    assert abs(r["deflated_benchmark_sr"] - DSR_GOLDEN_BENCHMARK) < 1e-9


def test_deflated_benchmark_translation_invariance():
    base = ds.deflated_benchmark_sr(DSR_TRIALS, 10)
    shifted = ds.deflated_benchmark_sr([x + 0.5 for x in DSR_TRIALS], 10)
    # Adding +c to every Sharpe must raise the benchmark by exactly +c.
    assert abs((shifted["deflated_benchmark_sr"] - base["deflated_benchmark_sr"]) - 0.5) < 1e-9


def test_deflated_benchmark_includes_trial_mean():
    """The mean term materially raises the benchmark (the old sigma*maxZ bug)."""
    r = ds.deflated_benchmark_sr(DSR_TRIALS, 10)
    sigma_only = r["trial_sharpe_std"] * r["max_z"]
    assert r["deflated_benchmark_sr"] == pytest.approx(r["trial_sharpe_mean"] + sigma_only, abs=1e-9)
    assert r["deflated_benchmark_sr"] - sigma_only > 0.29  # mean ~ 0.3 is not dropped


def test_deflated_sharpe_requires_consistent_trial_count():
    # 5 observed Sharpes but declared 10 trials => UNAVAILABLE (no silent estimator).
    r = ds.deflated_benchmark_sr([0.2, 0.4, 0.1, 0.5, 0.3], 10)
    assert r["status"] == "UNAVAILABLE"


def test_deflated_sharpe_unknown_trials_unavailable():
    assert ds.deflated_sharpe(1.0, 100, 0.0, 3.0, [], None)["status"] == "UNAVAILABLE"


def test_deflated_sharpe_rejects_nonfinite():
    assert ds.deflated_benchmark_sr([0.2, float("nan"), 0.3], 3)["status"] == "UNAVAILABLE"
    assert ds.psr(float("inf"), 0.0, 100, 0.0, 3.0)["status"] == "UNAVAILABLE"


def test_psr_zero_benchmark_normal():
    p = ds.psr(0.0, 0.0, 100, 0.0, 3.0)
    assert p["status"] == "OK"
    assert abs(p["probability"] - 0.5) < 1e-9


def test_psr_exposes_unambiguous_names():
    r = ds.deflated_sharpe(1.5, 250, -0.2, 4.0, DSR_TRIALS, 10)
    assert r["status"] == "OK"
    for key in ("deflated_benchmark_sr", "psr_z", "probability_sr_exceeds_deflated_benchmark"):
        assert key in r


import pytest  # noqa: E402
