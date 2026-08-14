"""Research governance — Probabilistic & Deflated Sharpe Ratio (PR-R1).

Implements Bailey & López de Prado (2014) "The Deflated Sharpe Ratio" and the
earlier Probabilistic Sharpe Ratio (PSR).

- PSR(SR*) = probability that the observed Sharpe exceeds a benchmark SR*, given
  the sample's skewness and kurtosis (non-normal adjustment).
- DSR replaces SR* with a deflated threshold that accounts for the number of
  trials and the variance of their Sharpe ratios, so a strategy that "won" a
  big search is not credited with the naive probability.

Applicability rule (enforced): if the trial count / trial-Sharpe distribution is
UNKNOWN, the result is UNAVAILABLE — never silently treated as a single trial.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

EULER_MASCHERONI = 0.5772156649015328606
EULER_NUMBER = math.e


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# Acklam's rational approximation of the standard-normal inverse CDF.
_NPPF_A = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
           1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
_NPPF_B = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
           6.680131188771972e01, -1.328068155288572e01]
_NPPF_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
           -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
_NPPF_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
           3.754408661907416e00]
_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam, ~1e-9 accuracy)."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be in (0, 1)")
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        num = (((((_NPPF_C[0] * q + _NPPF_C[1]) * q + _NPPF_C[2]) * q
                 + _NPPF_C[3]) * q + _NPPF_C[4]) * q + _NPPF_C[5])
        den = ((((_NPPF_D[0] * q + _NPPF_D[1]) * q + _NPPF_D[2]) * q
                + _NPPF_D[3]) * q + 1.0)
        return num / den
    if p > _P_HIGH:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        num = (((((_NPPF_C[0] * q + _NPPF_C[1]) * q + _NPPF_C[2]) * q
                 + _NPPF_C[3]) * q + _NPPF_C[4]) * q + _NPPF_C[5])
        den = ((((_NPPF_D[0] * q + _NPPF_D[1]) * q + _NPPF_D[2]) * q
                + _NPPF_D[3]) * q + 1.0)
        return -num / den
    q = p - 0.5
    r = q * q
    num = (((((_NPPF_A[0] * r + _NPPF_A[1]) * r + _NPPF_A[2]) * r
             + _NPPF_A[3]) * r + _NPPF_A[4]) * r + _NPPF_A[5]) * q
    den = (((((_NPPF_B[0] * r + _NPPF_B[1]) * r + _NPPF_B[2]) * r
             + _NPPF_B[3]) * r + _NPPF_B[4]) * r + 1.0)
    return num / den


def psr(
    observed_sharpe: float,
    benchmark_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
) -> dict:
    """Probabilistic Sharpe Ratio (non-normal adjusted)."""
    if n_observations < 2:
        return {"status": "UNAVAILABLE", "reason": "need >= 2 observations"}
    denominator = math.sqrt(
        1.0 - skewness * observed_sharpe
        + ((kurtosis - 1.0) / 4.0) * (observed_sharpe ** 2)
    )
    if denominator <= 0.0:
        return {"status": "UNAVAILABLE", "reason": "degenerate higher moments"}
    z_stat = (
        (observed_sharpe - benchmark_sharpe)
        * math.sqrt(n_observations - 1)
        / denominator
    )
    return {
        "status": "OK",
        "z_stat": z_stat,
        "probability": norm_cdf(z_stat),
        "benchmark_sharpe": benchmark_sharpe,
    }


def deflated_sharpe_threshold(
    trial_sharpes: Sequence[float],
    n_trials: Optional[int],
) -> dict:
    """Bailey & López de Prado deflated benchmark SR*.

    Requires the trial-Sharpe distribution; unknown trial count => UNAVAILABLE.
    """
    if n_trials is None:
        return {"status": "UNAVAILABLE", "reason": "trial count unknown"}
    if n_trials < 1:
        return {"status": "UNAVAILABLE", "reason": "trial count must be >= 1"}
    if len(trial_sharpes) == 0:
        return {"status": "UNAVAILABLE", "reason": "no trial-Sharpe distribution"}
    if len(trial_sharpes) == 1:
        return {
            "status": "UNAVAILABLE",
            "reason": "single trial has no Sharpe variance; DSR not meaningful",
        }
    mean = sum(trial_sharpes) / len(trial_sharpes)
    var = sum((s - mean) ** 2 for s in trial_sharpes) / (len(trial_sharpes) - 1)
    std = math.sqrt(var)
    if std <= 0.0:
        return {"status": "UNAVAILABLE", "reason": "zero Sharpe variance"}
    p_k = 1.0 - 1.0 / n_trials
    p_ke = 1.0 - 1.0 / (n_trials * EULER_NUMBER)
    threshold = std * (
        (1.0 - EULER_MASCHERONI) * norm_ppf(p_k)
        + EULER_MASCHERONI * norm_ppf(p_ke)
    )
    return {"status": "OK", "threshold": threshold, "n_trials": n_trials,
            "trial_sharpe_std": std}


def deflated_sharpe(
    observed_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    trial_sharpes: Sequence[float],
    n_trials: Optional[int],
) -> dict:
    """Deflated Sharpe Ratio: PSR against the deflated benchmark."""
    threshold_res = deflated_sharpe_threshold(trial_sharpes, n_trials)
    if threshold_res["status"] != "OK":
        return {"status": "UNAVAILABLE", "reason": threshold_res["reason"],
                "deflated_benchmark": None, "deflated_sharpe_ratio": None,
                "probability": None}
    psr_res = psr(observed_sharpe, threshold_res["threshold"], n_observations,
                  skewness, kurtosis)
    return {
        "status": "OK",
        "deflated_benchmark": threshold_res["threshold"],
        "deflated_sharpe_ratio": psr_res.get("z_stat"),
        "probability": psr_res.get("probability"),
        "n_trials": n_trials,
    }
