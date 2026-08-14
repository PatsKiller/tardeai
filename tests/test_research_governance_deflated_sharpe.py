"""Research governance — deflated Sharpe ratio dry tests (PR-R1)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import deflated_sharpe as ds  # noqa: E402


def test_norm_cdf_basics():
    assert abs(ds.norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(ds.norm_cdf(1.96) - 0.975) < 1e-3


def test_norm_ppf_inverse():
    assert abs(ds.norm_ppf(0.5) - 0.0) < 1e-6
    assert abs(ds.norm_ppf(0.975) - 1.959964) < 1e-4
    assert abs(ds.norm_ppf(0.025) + 1.959964) < 1e-4


def test_psr_known_value():
    # Non-normal adjustment: symmetric normal => PSR of 0 Sharpe = 0.5.
    r = ds.psr(observed_sharpe=0.0, benchmark_sharpe=0.0, n_observations=100,
               skewness=0.0, kurtosis=3.0)
    assert r["status"] == "OK"
    assert abs(r["probability"] - 0.5) < 1e-9


def test_psr_high_sharpe_is_high_probability():
    r = ds.psr(observed_sharpe=1.0, benchmark_sharpe=0.0, n_observations=250,
               skewness=0.0, kurtosis=3.0)
    assert r["probability"] > 0.999


def test_psr_requires_two_observations():
    r = ds.psr(observed_sharpe=1.0, benchmark_sharpe=0.0, n_observations=1,
               skewness=0.0, kurtosis=3.0)
    assert r["status"] == "UNAVAILABLE"


def test_dsr_unknown_trials_is_unavailable():
    r = ds.deflated_sharpe(observed_sharpe=1.0, n_observations=100,
                           skewness=0.0, kurtosis=3.0, trial_sharpes=[], n_trials=None)
    assert r["status"] == "UNAVAILABLE"


def test_dsr_single_trial_is_unavailable():
    r = ds.deflated_sharpe(observed_sharpe=1.0, n_observations=100,
                           skewness=0.0, kurtosis=3.0, trial_sharpes=[0.5], n_trials=1)
    assert r["status"] == "UNAVAILABLE"


def test_dsr_with_trial_distribution_is_ok():
    r = ds.deflated_sharpe(observed_sharpe=1.5, n_observations=250,
                           skewness=-0.2, kurtosis=4.0,
                           trial_sharpes=[0.2, 0.4, 0.1, 0.5, 0.3], n_trials=10)
    assert r["status"] == "OK"
    assert r["deflated_benchmark"] > 0
    assert 0.0 <= r["probability"] <= 1.0


def test_dsr_threshold_grows_with_trial_count():
    trials = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
    t_low = ds.deflated_sharpe_threshold(trials, n_trials=10)
    t_high = ds.deflated_sharpe_threshold(trials, n_trials=1000)
    # More trials => larger deflation => higher benchmark threshold.
    assert t_high["threshold"] > t_low["threshold"]
