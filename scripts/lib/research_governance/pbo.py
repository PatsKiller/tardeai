"""Research governance — Probability of Backtest Overfitting via CSCV (PR-R1).

Implements Bailey, Borwein, López de Prado & Zhu (2017) "The Probability of
Backtest Overfitting" using Combinatorially Symmetric Cross-Validation (CSCV).

Procedure:
  1. Split the T×N matrix (T observations, N configurations) into S disjoint,
     equal-size submatrices (S even).
  2. Form all C(S, S/2) combinations of S/2 submatrices as in-sample (IS); the
     complement is out-of-sample (OOS).
  3. For each combination: pick the IS-best configuration n*, then compute its
     OOS relative rank r = rank(n*)/(N+1), and logit λ = ln(r/(1-r)).
  4. PBO = fraction of combinations with λ < 0 (IS winner is below OOS median).

Applicability: N >= 2 (one config has no "selection"), T divisible by S, S even.
When C(S, S/2) is impractically large we subsample combinations deterministically
(seeded) and record that the estimate is approximate.

Pure stdlib. Deterministic given a seed.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Optional, Sequence


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


def _cscv_combinations(n_subsets: int, subset_size: int, max_combinations: Optional[int], seed: int):
    """Yield the IS-subset combinations, optionally deterministically subsampled."""
    all_combos = list(itertools.combinations(range(n_subsets), subset_size))
    if max_combinations is None or len(all_combos) <= max_combinations:
        yield from all_combos
        return
    rng = random.Random(seed)
    yield from rng.sample(all_combos, max_combinations)


def cscv_probability_of_backtest_overfitting(
    returns_matrix: Sequence[Sequence[float]],
    n_subsets: int = 16,
    max_combinations: Optional[int] = 2000,
    seed: int = 0,
    performance: str = "sharpe",
) -> dict:
    """Return PBO and logit diagnostics for a T×N return matrix (rows=time)."""
    # Normalize to N strategy series of equal length T.
    series = [list(col) for col in returns_matrix]
    n_configs = len(series)
    if n_configs < 2:
        return {"status": "NOT_APPLICABLE",
                "reason": "PBO requires >= 2 configurations (no selection with one)"}
    lengths = {len(s) for s in series}
    if len(lengths) != 1:
        return {"status": "UNAVAILABLE", "reason": "configurations have unequal lengths"}
    t_obs = lengths.pop()
    if n_subsets % 2 != 0:
        return {"status": "UNAVAILABLE", "reason": "n_subsets must be even"}
    if t_obs % n_subsets != 0:
        return {"status": "UNAVAILABLE",
                "reason": f"T={t_obs} not divisible by S={n_subsets}"}
    sub_len = t_obs // n_subsets
    if sub_len < 1:
        return {"status": "UNAVAILABLE", "reason": "empty submatrices"}

    def perf(vals: Sequence[float]) -> float:
        if performance == "sharpe":
            return _sharpe(vals)
        if performance == "mean":
            return sum(vals) / len(vals)
        raise ValueError(f"unknown performance metric: {performance}")

    def is_oos_scores(is_idx: Sequence[int]) -> tuple[int, float, float]:
        oos_idx = [i for i in range(n_subsets) if i not in set(is_idx)]
        is_perf = []
        oos_perf = []
        for col in series:
            is_vals = [col[i * sub_len:(i + 1) * sub_len] for i in is_idx]
            oos_vals = [col[i * sub_len:(i + 1) * sub_len] for i in oos_idx]
            flat_is = [v for seg in is_vals for v in seg]
            flat_oos = [v for seg in oos_vals for v in seg]
            is_perf.append(perf(flat_is))
            oos_perf.append(perf(flat_oos))
        best = max(range(n_configs), key=lambda k: is_perf[k])
        # OOS rank of best among all configs (1 = worst, N = best).
        rank = 1 + sum(1 for k in range(n_configs) if oos_perf[k] > oos_perf[best])
        relative_rank = rank / (n_configs + 1)
        logit = math.log(relative_rank / (1.0 - relative_rank))
        return best, relative_rank, logit

    combos = list(_cscv_combinations(n_subsets, n_subsets // 2, max_combinations, seed))
    if not combos:
        return {"status": "UNAVAILABLE", "reason": "no combinations generated"}

    logits = []
    for combo in combos:
        _, _, logit = is_oos_scores(combo)
        logits.append(logit)

    pbo = sum(1 for l in logits if l < 0) / len(logits)
    return {
        "status": "OK",
        "pbo": pbo,
        "n_configs": n_configs,
        "n_observations": t_obs,
        "n_subsets": n_subsets,
        "n_combinations_evaluated": len(logits),
        "logit_mean": sum(logits) / len(logits),
        "approx": (max_combinations is not None) and (len(combos) <
                    math.comb(n_subsets, n_subsets // 2)),
    }
