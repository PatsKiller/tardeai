"""Research governance — multiple-testing corrections (PR-R1).

Bonferroni and Holm are confirmatory / high-consequence family controls;
Benjamini-Hochberg controls the false-discovery rate and is suited to
exploratory discovery screens. Usage must be classified, not chosen blindly.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

from typing import Sequence


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def bonferroni(pvalues: Sequence[float], alpha: float = 0.05) -> dict:
    """Bonferroni: adjusted p = min(1, m * p_i). Controls family-wise error."""
    p = list(pvalues)
    m = len(p)
    if m == 0:
        return {"method": "bonferroni", "adjusted": [], "rejected": [], "alpha": alpha}
    adjusted = [_clamp01(m * pi) for pi in p]
    rejected = [ap <= alpha for ap in adjusted]
    return {"method": "bonferroni", "adjusted": adjusted, "rejected": rejected, "alpha": alpha}


def holm(pvalues: Sequence[float], alpha: float = 0.05) -> dict:
    """Holm-Bonferroni step-down. More powerful than Bonferroni, still FWER."""
    p = list(pvalues)
    m = len(p)
    if m == 0:
        return {"method": "holm", "adjusted": [], "rejected": [], "alpha": alpha}
    order = sorted(range(m), key=lambda i: p[i])
    adjusted = [0.0] * m
    for rank, idx in enumerate(order):
        # step-down: adjust by (m - rank); enforce monotonicity
        candidate = (m - rank) * p[idx]
        if rank > 0:
            candidate = max(candidate, adjusted[order[rank - 1]])
        adjusted[idx] = _clamp01(candidate)
    rejected = [adjusted[i] <= alpha for i in range(m)]
    return {"method": "holm", "adjusted": adjusted, "rejected": rejected, "alpha": alpha}


def benjamini_hochberg(pvalues: Sequence[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR step-up. Controls false-discovery rate."""
    p = list(pvalues)
    m = len(p)
    if m == 0:
        return {"method": "bh_fdr", "adjusted": [], "rejected": [], "alpha": alpha}
    order = sorted(range(m), key=lambda i: p[i])
    # q-values (step-up)
    qvals = [0.0] * m
    running_min = 1.0
    for rank in range(m - 1, -1, -1):
        idx = order[rank]
        candidate = (m / (rank + 1)) * p[idx]
        running_min = min(running_min, candidate)
        qvals[idx] = _clamp01(running_min)
    rejected = [qvals[i] <= alpha for i in range(m)]
    return {"method": "bh_fdr", "adjusted": qvals, "rejected": rejected, "alpha": alpha}


MULTIPLE_TESTING_METHODS = {
    "bonferroni": bonferroni,
    "holm": holm,
    "bh_fdr": benjamini_hochberg,
}
