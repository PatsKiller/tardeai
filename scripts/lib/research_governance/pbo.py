"""Research governance — Probability of Backtest Overfitting via CSCV (PR-R1).

Implements Bailey, Borwein, López de Prado & Zhu (2017) "The Probability of
Backtest Overfitting" using Combinatorially Symmetric Cross-Validation (CSCV).

Matrix shape convention (documented and enforced):
    `config_returns` is N configs x T observations, i.e. config_returns[c][t]
    is the return of configuration c at time t. n_configs = len(...),
    n_observations = len(config_returns[0]).

Procedure:
  1. Split the T observations into S disjoint, equal-size submatrices (S even).
  2. Form all C(S, S/2) combinations of S/2 submatrices as in-sample (IS); the
     complement is out-of-sample (OOS).
  3. For each combination: select the IS-best configuration(s) n* (TIES select
     ALL tied-best configs and average their omegas), compute the OOS relative
     rank omega = average_rank / (N+1) where average_rank = 1 is WORST OOS and
     N is BEST OOS (ties share the AVERAGE rank, so reordering economically
     identical configs does not change the result), and the logit
     lambda = ln(omega / (1 - omega)).
  4. PBO = fraction of combinations with lambda < 0 (IS winner below OOS median).

Approximation governance: the default is FULL enumeration. Approximation is an
EXPLICIT opt-in via max_combinations; when active, the result reports
`approx=True`, the sampling method/seed, the sampling fraction, and explicit
limitations. A confirmatory gate must not silently accept an approximate result.

Pure stdlib. Deterministic given a seed.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Optional, Sequence


def _is_finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x))


def _sharpe(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    if std == 0.0:
        return 0.0
    return mean / std


def average_ranks(values: Sequence[float]) -> list[float]:
    """Average ranks of `values`, 1-indexed ascending (1 = smallest = WORST).

    Ties share the average of the ranks they span, so reordering equal values
    does not change the assigned rank.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(order)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # positions i..j (0-indexed) -> ranks (i+1)..(j+1)
        avg = ((i + 1) + (j + 1)) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _cscv_combinations(n_subsets: int, subset_size: int,
                       max_combinations: Optional[int], seed: int):
    all_combos = list(itertools.combinations(range(n_subsets), subset_size))
    if max_combinations is None or len(all_combos) <= max_combinations:
        yield from all_combos
        return
    rng = random.Random(seed)
    yield from rng.sample(all_combos, max_combinations)


def cscv_probability_of_backtest_overfitting(
    config_returns: Sequence[Sequence[float]],
    n_subsets: int = 16,
    max_combinations: Optional[int] = None,
    seed: int = 0,
    performance: str = "sharpe",
) -> dict:
    """Return PBO and logit diagnostics for an N x T configuration-return matrix.

    Full enumeration is the default. Set max_combinations to opt in to a
    deterministic subsample (reported as approx=True).
    """
    configs = [list(col) for col in config_returns]
    n_configs = len(configs)
    if n_configs < 2:
        return {"status": "NOT_APPLICABLE",
                "reason": "PBO requires >= 2 configurations (no selection with one)"}

    lengths = {len(s) for s in configs}
    if len(lengths) != 1:
        return {"status": "UNAVAILABLE", "reason": "configurations have unequal lengths"}
    n_obs = lengths.pop()

    for c in configs:
        for v in c:
            if not _is_finite(v):
                return {"status": "UNAVAILABLE", "reason": "non-finite return in matrix"}

    if n_subsets % 2 != 0:
        return {"status": "UNAVAILABLE", "reason": "n_subsets must be even"}
    if n_obs % n_subsets != 0:
        return {"status": "UNAVAILABLE",
                "reason": f"T={n_obs} not divisible by S={n_subsets}"}
    sub_len = n_obs // n_subsets
    if sub_len < 1:
        return {"status": "UNAVAILABLE", "reason": "empty submatrices"}

    def perf(vals: Sequence[float]) -> float:
        if performance == "sharpe":
            return _sharpe(vals)
        if performance == "mean":
            return sum(vals) / len(vals)
        raise ValueError(f"unknown performance metric: {performance}")

    def flat_perf(col: Sequence[float], idx: Sequence[int]) -> float:
        flat = [v for i in idx for v in col[i * sub_len:(i + 1) * sub_len]]
        return perf(flat)

    total_combos = math.comb(n_subsets, n_subsets // 2)
    combos = list(_cscv_combinations(n_subsets, n_subsets // 2, max_combinations, seed))
    if not combos:
        return {"status": "UNAVAILABLE", "reason": "no combinations generated"}

    logits = []
    for combo in combos:
        is_idx = list(combo)
        oos_idx = [i for i in range(n_subsets) if i not in set(is_idx)]

        is_perf = [flat_perf(col, is_idx) for col in configs]
        best_is = max(is_perf)
        # Ties select ALL IS-best configs; average their omegas.
        is_best_configs = [k for k in range(n_configs) if is_perf[k] == best_is]

        oos_perf = [flat_perf(col, oos_idx) for col in configs]
        oos_ranks = average_ranks(oos_perf)

        omega_sum = sum(oos_ranks[k] / (n_configs + 1) for k in is_best_configs)
        omega = omega_sum / len(is_best_configs)
        logits.append(math.log(omega / (1.0 - omega)))

    pbo = sum(1 for l in logits if l < 0) / len(logits)
    approx = len(logits) < total_combos
    return {
        "status": "OK",
        "pbo": pbo,
        "n_configs": n_configs,
        "n_observations": n_obs,
        "n_subsets": n_subsets,
        "total_combinations": total_combos,
        "combinations_evaluated": len(logits),
        "sampling_fraction": len(logits) / total_combos,
        "approx": approx,
        "sampling_method": "deterministic_subsample" if approx else "full_enumeration",
        "sampling_seed": seed if approx else None,
        "approximation_limitations": (
            "Subsampled CSCV: PBO is an estimate over a random subset of splits; "
            "uncertainty is not quantified. Full enumeration required for "
            "confirmatory use." if approx else None),
        "lambda_distribution": logits,
        "logit_mean": sum(logits) / len(logits),
    }
