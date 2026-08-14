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
  3. For each combination: pick the IS-best configuration n* (ties broken by
     lowest index, deterministic), then compute its OOS relative rank
     omega = rank / (N+1) where rank = 1 is WORST OOS and rank = N is BEST OOS,
     and logit lambda = ln(omega / (1 - omega)).
  4. PBO = fraction of combinations with lambda < 0 (IS winner is below the OOS
     median).

Applicability: N >= 2 (one config has no "selection"), T divisible by S, S even.
When C(S, S/2) is impractically large we subsample combinations deterministically
(seeded) and report `approx=True` with the sampling fraction.

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
    max_combinations: Optional[int] = 2000,
    seed: int = 0,
    performance: str = "sharpe",
) -> dict:
    """Return PBO and logit diagnostics for an N x T configuration-return matrix."""
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

    def is_best_config(is_idx: Sequence[int]) -> int:
        is_perf = []
        for col in configs:
            flat = [v for i in is_idx for v in col[i * sub_len:(i + 1) * sub_len]]
            is_perf.append(perf(flat))
        # Deterministic tie-break: lowest index wins on equal IS performance.
        return max(range(n_configs), key=lambda k: (is_perf[k], -k))

    def oos_rank(best: int, oos_idx: Sequence[int]) -> tuple[int, int]:
        oos_perf = []
        for col in configs:
            flat = [v for i in oos_idx for v in col[i * sub_len:(i + 1) * sub_len]]
            oos_perf.append(perf(flat))
        # rank 1 = WORST OOS, N = BEST OOS; ties broken by lower index ranking higher.
        rank = 1 + sum(1 for k in range(n_configs)
                       if (oos_perf[k], k) < (oos_perf[best], best))
        return rank, n_configs

    total_combos = math.comb(n_subsets, n_subsets // 2)
    combos = list(_cscv_combinations(n_subsets, n_subsets // 2, max_combinations, seed))
    if not combos:
        return {"status": "UNAVAILABLE", "reason": "no combinations generated"}

    logits = []
    for combo in combos:
        is_idx = list(combo)
        oos_idx = [i for i in range(n_subsets) if i not in set(is_idx)]
        best = is_best_config(is_idx)
        rank, ncfg = oos_rank(best, oos_idx)
        omega = rank / (ncfg + 1)
        logits.append(math.log(omega / (1.0 - omega)))

    pbo = sum(1 for l in logits if l < 0) / len(logits)
    return {
        "status": "OK",
        "pbo": pbo,
        "n_configs": n_configs,
        "n_observations": n_obs,
        "n_subsets": n_subsets,
        "total_combinations": total_combos,
        "combinations_evaluated": len(logits),
        "sampling_fraction": len(logits) / total_combos,
        "approx": len(logits) < total_combos,
        "logit_mean": sum(logits) / len(logits),
    }
