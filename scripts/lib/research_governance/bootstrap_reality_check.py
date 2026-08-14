"""Research governance — White's Reality Check + STW calendar-family test (PR-R1).

White (2000) "A Reality Check for Data Snooping" and Sullivan, Timmermann &
White (1999) "Data-Snooping, Technical Trading Rule Performance, and the
Bootstrap" answer the same question: when many rules are tried on the same data,
does the BEST rule beat the benchmark by more than chance?

Statistic (canonical scaling):
    V = sqrt(n) * max_k mean(f_k)

where f_k is the performance differential of rule k vs the benchmark over n
observations.

Null construction (the important part): under H0 no rule has predictive
superiority, i.e. E[f_k] <= 0 for all k. To sample under the null we RECENTER
each differential series to zero mean (the least favorable configuration) BEFORE
resampling:

    f*_{k,t} = f_{k,t} - mean(f_k)

The same stationary-bootstrap index sequence is applied to every rule in a
given resample, preserving the cross-rule dependence that the data-snooping
correction exists to model. The bootstrap statistic is

    V* = sqrt(n) * max_k mean( f*_k resampled )

and the p-value is the fraction of resamples with V* >= V.

Simply resampling the RAW differential series is wrong: it keeps each rule's
observed positive mean, so the bootstrap distribution centers near the observed
alternative instead of the null.

Applicability: >= 1 rule; the data-snooping correction is only meaningful with
>= 2 rules (a single rule is a plain one-sided mean test). A calendar family is
a named collection of performance-differential series evaluated under the same
discipline — never a lone best variant.

Pure stdlib. Deterministic given a seed.
"""
from __future__ import annotations

import math
import random
from typing import Optional, Sequence


def _is_finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x))


def _stationary_bootstrap_indices(n: int, mean_block_length: float,
                                  rng: random.Random) -> list[int]:
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
    family_id: Optional[str] = None,
    family_definition_hash: Optional[str] = None,
) -> dict:
    """White Reality Check p-value over a family of performance differentials.

    `differentials[k]` is the time series (f_{k,t}) of rule k's performance
    relative to the benchmark (excess returns). Positive = rule beats benchmark.
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
    for d in family:
        for v in d:
            if not _is_finite(v):
                return {"status": "UNAVAILABLE", "reason": "non-finite differential"}
    if n_bootstrap < 1:
        return {"status": "UNAVAILABLE", "reason": "n_bootstrap must be >= 1"}
    if mean_block_length <= 0:
        return {"status": "UNAVAILABLE", "reason": "mean_block_length must be > 0"}

    means = [sum(d) / n for d in family]
    observed_v = math.sqrt(n) * max(means)

    # Recenter under the null (zero mean) so the bootstrap does not retain each
    # rule's observed mean.
    recentered = [[v - means[k] for v in d] for k, d in enumerate(family)]

    rng = random.Random(seed)
    count = 0
    for _ in range(n_bootstrap):
        idx = _stationary_bootstrap_indices(n, mean_block_length, rng)
        boot_v = math.sqrt(n) * max(
            sum(recentered[k][i] for i in idx) / n for k in range(n_rules)
        )
        if boot_v >= observed_v:
            count += 1

    p_value = (count + 1) / (n_bootstrap + 1)
    result = {
        "status": "OK",
        "n_rules": n_rules,
        "n_observations": n,
        "observed_max_mean": max(means),
        "observed_statistic": observed_v,
        "bootstrap_pvalue": p_value,
        "n_bootstrap": n_bootstrap,
        "mean_block_length": mean_block_length,
    }
    if family_id is not None:
        result["family_id"] = family_id
    if family_definition_hash is not None:
        result["family_definition_hash"] = family_definition_hash
    return result


def calendar_family_reality_check(
    family_id: str,
    calendar_differentials: Sequence[Sequence[float]],
    n_bootstrap: int = 2000,
    mean_block_length: float = 5.0,
    seed: int = 0,
    family_definition_hash: Optional[str] = None,
) -> dict:
    """Sullivan–Timmermann–White calendar-family test.

    Tests the ENTIRE frozen searched family of a calendar rule, never only the
    selected winner. Returns the Reality Check p-value plus family provenance.
    """
    res = reality_check_pvalue(
        calendar_differentials, n_bootstrap, mean_block_length, seed,
        family_id=family_id, family_definition_hash=family_definition_hash,
    )
    return res
