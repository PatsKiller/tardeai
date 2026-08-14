"""Research governance — White's Reality Check + STW calendar-family test (PR-R1).

White (2000) "A Reality Check for Data Snooping" and Sullivan, Timmermann &
White (1999) "Data-Snooping, Technical Trading Rule Performance, and the
Bootstrap" both answer the same question: when many rules are tried on the same
data, does the BEST rule beat the benchmark by more than pure chance?

This module is a single implementation of that family test, not a separate
"magical" STW statistic. A calendar family (e.g. "September-midterm" variants)
is just a named collection of performance-differential series, evaluated under
the same data-snooping/bootstrap discipline.

Statistic: V = max_l mean(f_l), where f_l is the performance differential of
rule l vs benchmark. The p-value is the bootstrap fraction of resampled max
statistics >= observed V, using a stationary/circular-block bootstrap (seeded).

Applicability: >= 1 rule (with >= 1 => trivially just its own mean test), but
the data-snooping correction is only meaningful with >= 2 rules.

Pure stdlib. Deterministic given a seed.
"""
from __future__ import annotations

import math
import random
from typing import Optional, Sequence


def _stationary_bootstrap_indices(n: int, mean_block_length: float, rng: random.Random) -> list[int]:
    """Politis–Romano stationary bootstrap index sequence (circular)."""
    p = 1.0 / mean_block_length
    idx = [rng.randrange(n)]
    while len(idx) < n:
        if rng.random() < p:
            idx.append(rng.randrange(n))
        else:
            idx.append((idx[-1] + 1) % n)
    return idx


def reality_check_pvalue(
    differentials: Sequence[Sequence[float]],
    n_bootstrap: int = 2000,
    mean_block_length: float = 5.0,
    seed: int = 0,
) -> dict:
    """White Reality Check p-value over a family of performance differentials.

    `differentials[k]` is the time series (f_k,t) of rule k's performance
    relative to the benchmark (e.g. excess returns, or excess Sharpe-normalized
    returns). Positive = rule beats benchmark.
    """
    family = [list(d) for d in differentials]
    n_rules = len(family)
    if n_rules == 0:
        return {"status": "UNAVAILABLE", "reason": "empty rule family"}
    lengths = {len(d) for d in family}
    if len(lengths) != 1:
        return {"status": "UNAVAILABLE", "reason": "rules have unequal lengths"}
    n = lengths.pop()
    if n < 2:
        return {"status": "UNAVAILABLE", "reason": "need >= 2 observations"}

    observed_v = max(sum(d) / n for d in family)
    rng = random.Random(seed)

    count = 0
    for _ in range(n_bootstrap):
        idx = _stationary_bootstrap_indices(n, mean_block_length, rng)
        boot_v = max(sum(d[i] for i in idx) / n for d in family)
        if boot_v >= observed_v:
            count += 1

    p_value = (count + 1) / (n_bootstrap + 1)
    return {
        "status": "OK",
        "n_rules": n_rules,
        "n_observations": n,
        "observed_max_mean": observed_v,
        "bootstrap_pvalue": p_value,
        "n_bootstrap": n_bootstrap,
        "mean_block_length": mean_block_length,
    }


def calendar_family_reality_check(
    family_id: str,
    calendar_differentials: Sequence[Sequence[float]],
    n_bootstrap: int = 2000,
    mean_block_length: float = 5.0,
    seed: int = 0,
) -> dict:
    """Sullivan–Timmermann–White calendar family test.

    `calendar_differentials` is the family of performance differentials for all
    variants of a calendar rule (e.g. every September-midterm variant). This is
    the correct way to test a seasonality claim, not a lone best variant.
    """
    res = reality_check_pvalue(calendar_differentials, n_bootstrap, mean_block_length, seed)
    res["family_id"] = family_id
    return res
