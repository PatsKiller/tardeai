"""Research governance — Probabilistic & Deflated Sharpe Ratio (PR-R1).

Implements Bailey & López de Prado (2014) "The Deflated Sharpe Ratio: Correcting
for Selection Bias, Backtest Overfitting and Non-Normality" and the earlier
Probabilistic Sharpe Ratio (PSR).

Formulas (independent reimplementation; not copied from any reference code):

  PSR(SR*) = Phi( z ), with

      z = (SR_hat - SR*) * sqrt(n-1) / sqrt(1 - gamma3*SR_hat + ((gamma4 - 1)/4)*SR_hat^2)

  where gamma3 is skewness and gamma4 is PEARSON (raw) kurtosis (normal = 3).
  Excess kurtosis = raw - 3.

  Deflated benchmark SR* (expected maximum Sharpe over the search family):

      SR* = mu + sigma * maxZ

      maxZ = (1 - gamma) * Z^{-1}(1 - 1/N) + gamma * Z^{-1}(1 - 1/(N*e))

  where mu/sigma are the mean/std of the N trial Sharpe ratios, gamma is the
  Euler-Mascheroni constant, e is Euler's number, and Z^{-1} is the standard
  normal inverse CDF. The trial-distribution MEAN is part of the benchmark: a
  search family whose Sharpes are all shifted up by +c must raise the deflated
  benchmark by +c (translation invariance).

Applicability: DSR requires a KNOWN trial count AND the trial-Sharpe
distribution; otherwise UNAVAILABLE (never silently treated as a single trial).

Pure stdlib. Deterministic.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

EULER_MASCHERONI = 0.5772156649015328606
EULER_NUMBER = math.e


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# Acklam's rational approximation of the standard-normal inverse CDF (~1e-9).
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


def _is_finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x))


def psr(
    observed_sharpe: float,
    benchmark_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    sharpe_frequency: Optional[str] = None,
) -> dict:
    """Probabilistic Sharpe Ratio (non-normal adjusted).

    `kurtosis` is PEARSON (raw) kurtosis (normal = 3).

    The denominator square is validated BEFORE sqrt: pathological skew/kurtosis
    that make `1 - gamma3*SR + ((gamma4-1)/4)*SR^2` non-positive or non-finite
    return UNAVAILABLE rather than raising.
    """
    for name, v in (("observed_sharpe", observed_sharpe), ("benchmark_sharpe", benchmark_sharpe),
                    ("skewness", skewness), ("kurtosis", kurtosis)):
        if not _is_finite(v):
            return {"status": "UNAVAILABLE", "reason": f"non-finite input: {name}"}
    if n_observations < 2:
        return {"status": "UNAVAILABLE", "reason": "need >= 2 observations"}
    denominator_sq = (
        1.0 - skewness * observed_sharpe
        + ((kurtosis - 1.0) / 4.0) * (observed_sharpe ** 2)
    )
    if not _is_finite(denominator_sq) or denominator_sq <= 0.0:
        return {"status": "UNAVAILABLE", "reason": "degenerate higher moments (denominator <= 0)"}
    denominator = math.sqrt(denominator_sq)
    z_stat = (
        (observed_sharpe - benchmark_sharpe)
        * math.sqrt(n_observations - 1)
        / denominator
    )
    result = {
        "status": "OK",
        "psr_z": z_stat,
        "probability": norm_cdf(z_stat),
        "benchmark_sharpe": benchmark_sharpe,
    }
    if sharpe_frequency is not None:
        result["sharpe_frequency"] = sharpe_frequency
    return result


def deflated_benchmark_sr(
    trial_sharpes: Sequence[float],
    n_trials: Optional[int],
) -> dict:
    """Deflated benchmark SR* = mu + sigma * maxZ (Bailey & López de Prado).

    Requires the trial-Sharpe distribution and a KNOWN, CONSISTENT trial count.
    """
    if n_trials is None:
        return {"status": "UNAVAILABLE", "reason": "trial count unknown"}
    if n_trials < 2:
        return {"status": "UNAVAILABLE", "reason": "trial count must be >= 2"}
    sharpe_list = [float(s) for s in trial_sharpes]
    for s in sharpe_list:
        if not _is_finite(s):
            return {"status": "UNAVAILABLE", "reason": "non-finite trial Sharpe"}
    # Consistency: the observed trial-Sharpe count must match the declared count.
    if len(sharpe_list) != n_trials:
        return {"status": "UNAVAILABLE",
                "reason": f"declared n_trials={n_trials} != observed {len(sharpe_list)}"
                          " trial Sharpes (no effective-trials estimator documented)"}
    if len(sharpe_list) < 2:
        return {"status": "UNAVAILABLE",
                "reason": "single trial has no Sharpe variance; DSR not meaningful"}

    mu = sum(sharpe_list) / len(sharpe_list)
    var = sum((s - mu) ** 2 for s in sharpe_list) / (len(sharpe_list) - 1)
    sigma = math.sqrt(var)
    if sigma <= 0.0 or not _is_finite(sigma):
        return {"status": "UNAVAILABLE", "reason": "zero Sharpe variance"}

    p_k = 1.0 - 1.0 / n_trials
    p_ke = 1.0 - 1.0 / (n_trials * EULER_NUMBER)
    max_z = (1.0 - EULER_MASCHERONI) * norm_ppf(p_k) \
        + EULER_MASCHERONI * norm_ppf(p_ke)
    threshold = mu + sigma * max_z
    return {
        "status": "OK",
        "deflated_benchmark_sr": threshold,
        "trial_sharpe_mean": mu,
        "trial_sharpe_std": sigma,
        "n_trials": n_trials,
        "max_z": max_z,
    }


def deflated_sharpe(
    observed_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    trial_sharpes: Sequence[float],
    n_trials: Optional[int],
    sharpe_frequency: Optional[str] = None,
    trial_sharpe_frequency: Optional[str] = None,
    return_frequency: Optional[str] = None,
    confirmatory: bool = False,
) -> dict:
    """Deflated Sharpe Ratio: PSR against the deflated benchmark SR*.

    Sharpe convention contract:
      * `sharpe_frequency` / `trial_sharpe_frequency` (PER_PERIOD | ANNUALIZED)
        must MATCH (an annualized Sharpe cannot be compared against a per-period
        trial distribution).
      * `return_frequency` (DAILY | WEEKLY | MONTHLY | ...) is the sampling
        frequency of the underlying returns.

    FAIL-CLOSED: a confirmatory result requires an explicit, fully-specified
    convention (all three present and coherent); otherwise UNAVAILABLE. The
    wrapper NEVER upgrades an underlying PSR UNAVAILABLE to OK.
    """
    if confirmatory:
        missing = []
        if not sharpe_frequency:
            missing.append("sharpe_frequency")
        if not trial_sharpe_frequency:
            missing.append("trial_sharpe_frequency")
        if not return_frequency:
            missing.append("return_frequency")
        if missing:
            return {"status": "UNAVAILABLE",
                    "reason": f"confirmatory DSR requires explicit convention: {missing}",
                    "deflated_benchmark_sr": None, "psr_z": None,
                    "probability_sr_exceeds_deflated_benchmark": None}
        if sharpe_frequency != trial_sharpe_frequency:
            return {"status": "UNAVAILABLE",
                    "reason": f"Sharpe frequency mismatch: observed={sharpe_frequency} "
                              f"vs trial={trial_sharpe_frequency}",
                    "deflated_benchmark_sr": None, "psr_z": None,
                    "probability_sr_exceeds_deflated_benchmark": None}
    elif (sharpe_frequency is not None and trial_sharpe_frequency is not None
          and sharpe_frequency != trial_sharpe_frequency):
        return {"status": "UNAVAILABLE",
                "reason": f"Sharpe frequency mismatch: observed={sharpe_frequency} "
                          f"vs trial={trial_sharpe_frequency}",
                "deflated_benchmark_sr": None, "psr_z": None,
                "probability_sr_exceeds_deflated_benchmark": None}

    benchmark = deflated_benchmark_sr(trial_sharpes, n_trials)
    if benchmark["status"] != "OK":
        return {"status": "UNAVAILABLE", "reason": benchmark["reason"],
                "deflated_benchmark_sr": None, "psr_z": None,
                "probability_sr_exceeds_deflated_benchmark": None}
    psr_res = psr(observed_sharpe, benchmark["deflated_benchmark_sr"],
                  n_observations, skewness, kurtosis,
                  sharpe_frequency=sharpe_frequency)
    if psr_res["status"] != "OK":
        # FAIL-CLOSED: never upgrade an underlying PSR failure to a DSR OK.
        return {"status": "UNAVAILABLE", "reason": psr_res.get("reason", "PSR unavailable"),
                "deflated_benchmark_sr": benchmark["deflated_benchmark_sr"],
                "psr_z": None, "probability_sr_exceeds_deflated_benchmark": None}
    result = {
        "status": "OK",
        "deflated_benchmark_sr": benchmark["deflated_benchmark_sr"],
        "psr_z": psr_res["psr_z"],
        "probability_sr_exceeds_deflated_benchmark": psr_res["probability"],
        "n_trials": n_trials,
        "sharpe_frequency": sharpe_frequency,
        "trial_sharpe_frequency": trial_sharpe_frequency,
        "return_frequency": return_frequency,
        "confirmatory": confirmatory,
    }
    return result
