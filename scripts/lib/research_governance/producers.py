"""Research governance — method-specific governed producers (PR-R1, P0-1).

THE trust boundary of the statistical-governance layer.

A bare, self-hashed typed result is NOT evidence provenance: any caller can build
a ``DSRResult(status="OK", psr_z=999, ...)``, finalize it, and hold a digest-valid
object. That only proves the object did not change after hashing itself.

The ONLY sanctioned way to obtain a promotable ``GovernedResult`` is through one
of the producers in this module. Each producer:

  1. accepts an IMMUTABLE raw-input dataclass (no prebuilt statistical result);
  2. computes the canonical input digest over those raw inputs;
  3. INVOKES the actual governed statistical implementation;
  4. constructs the typed result from the ACTUAL returned output;
  5. validates the typed result (numeric self-consistency);
  6. binds the actual producer-source digest (sha256 of the module source bytes);
  7. issues an issuer-authenticated (HMAC-signed) receipt;
  8. verifies the receipt before returning.

No producer accepts a caller-populated statistical result object. The generic
``receipts.governed_result()`` wrapper is UNSIGNED and therefore non-promotable.

Pure stdlib, deterministic, no provider/broker/DB calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import deflated_sharpe, multiple_testing, pbo, bootstrap_reality_check, robustness
from .models import FrozenDict, _stable_hash
from .receipts import GovernedResult, issue_governed_receipt
from .results import (
    DSRResult,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    RobustnessItem,
    RobustnessResult,
    finalize,
)

# ---------------------------------------------------------------------------
# Immutable raw-input contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultipleTestingInput:
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    tested_hypothesis_id: str
    method: str  # "bonferroni" | "holm"
    alpha: float
    tested_trial_ids: tuple
    tested_config_hashes: tuple
    raw_pvalues: tuple
    focal_trial_id: str


@dataclass(frozen=True)
class DSRInput:
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    observed_sharpe: float
    n_observations: int
    skewness: float
    kurtosis: float
    trial_sharpes: tuple
    n_trials: int
    sharpe_frequency: str
    trial_sharpe_frequency: str
    return_frequency: str
    confirmatory: bool = True
    periods_per_year: Optional[int] = None


@dataclass(frozen=True)
class PBOInput:
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    config_returns: tuple  # tuple[tuple[float, ...], ...] (N x T matrix)
    n_subsets: int
    max_combinations: Optional[int] = None
    seed: int = 0
    performance: str = "sharpe"


@dataclass(frozen=True)
class RealityCheckInput:
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    family_id: str
    differentials: tuple  # tuple[tuple[float, ...], ...]
    n_bootstrap: int
    mean_block_length: float
    seed: int = 0
    confirmatory: bool = True


@dataclass(frozen=True)
class RobustnessInput:
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    items: FrozenDict  # field name -> RobustnessItem


# ---------------------------------------------------------------------------
# Shared identity helpers
# ---------------------------------------------------------------------------

_IDENTITY_FIELDS = ("hypothesis_id", "protocol_hash", "trial_family_id",
                    "family_definition_hash", "dataset_hash", "code_sha")


def _identity(inp) -> dict:
    """The six-field identity common to every research-generation child."""
    return {f: getattr(inp, f) for f in _IDENTITY_FIELDS}


def _input_digest(inp) -> str:
    """Canonical digest over the FULL raw input (identity + statistical inputs)."""
    return _stable_hash(inp)


def _assert_clean(result, method: str) -> None:
    """Fail-closed guard: a producer never returns a receipt it cannot verify."""
    if not result.receipt.verify():
        raise RuntimeError(f"{method} producer issued a receipt that does not verify")


def _frozen_tuple(values) -> tuple:
    return tuple(float(v) for v in values)


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------

def run_governed_multiple_testing(inp: MultipleTestingInput) -> GovernedResult:
    """Bonferroni/Holm over the EXACT frozen trial family, from raw p-values."""
    if inp.method not in ("bonferroni", "holm"):
        raise ValueError(f"confirmatory multiple-testing method must be bonferroni/holm: {inp.method!r}")
    alpha = float(inp.alpha)
    if not (0.0 < alpha < 1.0) or not math.isfinite(alpha):
        raise ValueError(f"alpha must be in (0,1): {alpha!r}")
    trial_ids = tuple(inp.tested_trial_ids)
    config_hashes = tuple(inp.tested_config_hashes)
    pvalues = _frozen_tuple(inp.raw_pvalues)
    if not trial_ids or len(trial_ids) != len(config_hashes) or len(trial_ids) != len(pvalues):
        raise ValueError("tested_trial_ids / tested_config_hashes / raw_pvalues must align and be non-empty")
    if inp.focal_trial_id not in trial_ids:
        raise ValueError(f"focal_trial_id {inp.focal_trial_id!r} not in tested_trial_ids")

    fn = multiple_testing.bonferroni if inp.method == "bonferroni" else multiple_testing.holm
    out = fn(pvalues, alpha)  # INVOKE the actual implementation.

    focal_idx = trial_ids.index(inp.focal_trial_id)
    family_input_digest = _stable_hash({
        "family": inp.trial_family_id,
        "trial_ids": trial_ids,
        "config_hashes": config_hashes,
        "pvalues": pvalues,
    })

    result = MultipleTestingResult(
        result_id=f"mt-{_input_digest(inp)[:12]}",
        method=inp.method, status="OK", alpha=alpha,
        family_id=inp.trial_family_id, family_definition_hash=inp.family_definition_hash,
        trial_family_id=inp.trial_family_id, tested_hypothesis_id=inp.tested_hypothesis_id,
        raw_pvalue=pvalues[focal_idx], adjusted_pvalue=out["adjusted"][focal_idx],
        rejected=out["rejected"][focal_idx], complete_family=True,
        protocol_hash=inp.protocol_hash, hypothesis_id=inp.hypothesis_id,
        dataset_hash=inp.dataset_hash, code_sha=inp.code_sha,
        tested_hypothesis_ids=(inp.tested_hypothesis_id,),
        raw_pvalues=pvalues, family_input_digest=family_input_digest,
        tested_trial_ids=trial_ids, tested_config_hashes=config_hashes,
        focal_trial_id=inp.focal_trial_id,
    )
    result = finalize(result)
    if result.validate():
        raise RuntimeError(f"multiple-testing producer produced an invalid result: {result.validate()}")
    governed = issue_governed_receipt("bonferroni" if inp.method == "bonferroni" else "holm",
                                      result, input_artifact=inp)
    _assert_clean(governed, "multiple_testing")
    return governed


def run_governed_dsr(inp: DSRInput) -> GovernedResult:
    """Deflated Sharpe Ratio from raw Sharpe/moments/trial-distribution."""
    out = deflated_sharpe.deflated_sharpe(  # INVOKE the actual implementation.
        observed_sharpe=float(inp.observed_sharpe),
        n_observations=int(inp.n_observations),
        skewness=float(inp.skewness),
        kurtosis=float(inp.kurtosis),
        trial_sharpes=_frozen_tuple(inp.trial_sharpes),
        n_trials=int(inp.n_trials),
        sharpe_frequency=inp.sharpe_frequency,
        trial_sharpe_frequency=inp.trial_sharpe_frequency,
        return_frequency=inp.return_frequency,
        confirmatory=inp.confirmatory,
        periods_per_year=inp.periods_per_year,
    )
    if out.get("status") != "OK":
        raise RuntimeError(f"DSR producer got non-OK status: {out}")

    result = DSRResult(
        result_id=f"dsr-{_input_digest(inp)[:12]}", status="OK",
        observed_sharpe=float(inp.observed_sharpe), n_observations=int(inp.n_observations),
        skewness=float(inp.skewness), kurtosis=float(inp.kurtosis),
        n_trials=int(inp.n_trials),
        deflated_benchmark_sr=out["deflated_benchmark_sr"],
        psr_z=out["psr_z"],
        probability_sr_exceeds_deflated_benchmark=out["probability_sr_exceeds_deflated_benchmark"],
        sharpe_frequency=inp.sharpe_frequency, trial_sharpe_frequency=inp.trial_sharpe_frequency,
        return_frequency=inp.return_frequency, confirmatory=inp.confirmatory,
        protocol_hash=inp.protocol_hash, hypothesis_id=inp.hypothesis_id,
        trial_family_id=inp.trial_family_id, family_definition_hash=inp.family_definition_hash,
        dataset_hash=inp.dataset_hash, code_sha=inp.code_sha,
    )
    result = finalize(result)
    if result.validate():
        raise RuntimeError(f"DSR producer produced an invalid result: {result.validate()}")
    governed = issue_governed_receipt("deflated_sharpe", result, input_artifact=inp)
    _assert_clean(governed, "dsr")
    return governed


def run_governed_pbo(inp: PBOInput) -> GovernedResult:
    """CSCV probability of backtest overfitting from a raw config-return matrix."""
    matrix = tuple(tuple(float(v) for v in col) for col in inp.config_returns)
    out = pbo.cscv_probability_of_backtest_overfitting(  # INVOKE the actual implementation.
        matrix, n_subsets=int(inp.n_subsets),
        max_combinations=inp.max_combinations, seed=int(inp.seed),
        performance=inp.performance,
    )
    if out.get("status") != "OK":
        raise RuntimeError(f"PBO producer got non-OK status: {out}")

    result = PBOResult(
        result_id=f"pbo-{_input_digest(inp)[:12]}", status="OK",
        pbo=out["pbo"], n_configs=out["n_configs"], n_observations=out["n_observations"],
        n_subsets=out["n_subsets"], total_combinations=out["total_combinations"],
        combinations_evaluated=out["combinations_evaluated"],
        sampling_fraction=out["sampling_fraction"], approx=out["approx"],
        sampling_method=out["sampling_method"], sampling_seed=out["sampling_seed"],
        tie_policy=out["tie_policy"], is_tie_split_count=out["is_tie_split_count"],
        tie_fraction=out["tie_fraction"], lambda_zero_policy=out["lambda_zero_policy"],
        protocol_hash=inp.protocol_hash, hypothesis_id=inp.hypothesis_id,
        trial_family_id=inp.trial_family_id, family_definition_hash=inp.family_definition_hash,
        dataset_hash=inp.dataset_hash, code_sha=inp.code_sha,
    )
    result = finalize(result)
    if result.validate():
        raise RuntimeError(f"PBO producer produced an invalid result: {result.validate()}")
    governed = issue_governed_receipt("cscv_pbo", result, input_artifact=inp)
    _assert_clean(governed, "pbo")
    return governed


def run_governed_reality_check(inp: RealityCheckInput) -> GovernedResult:
    """White Reality Check over a raw differential matrix (confirmatory family)."""
    differentials = tuple(tuple(float(v) for v in d) for d in inp.differentials)
    out = bootstrap_reality_check.reality_check_pvalue(  # INVOKE the actual implementation.
        differentials, n_bootstrap=int(inp.n_bootstrap),
        mean_block_length=float(inp.mean_block_length), seed=int(inp.seed),
        family_id=inp.family_id, family_definition_hash=inp.family_definition_hash,
        trial_family_id=inp.trial_family_id, confirmatory=inp.confirmatory,
    )
    if out.get("status") != "OK":
        raise RuntimeError(f"Reality Check producer got non-OK status: {out}")

    result = RealityCheckResult(
        result_id=f"rc-{_input_digest(inp)[:12]}", status="OK",
        bootstrap_pvalue=out["bootstrap_pvalue"], n_rules=out["n_rules"],
        n_observations=out["n_observations"], n_bootstrap=out["n_bootstrap"],
        bootstrap_method=out["bootstrap_method"], mean_block_length=out["mean_block_length"],
        bootstrap_seed=out["bootstrap_seed"], alpha=0.05,
        pvalue_resolution=out["pvalue_resolution"],
        protocol_hash=inp.protocol_hash, hypothesis_id=inp.hypothesis_id,
        trial_family_id=inp.trial_family_id, family_definition_hash=inp.family_definition_hash,
        family_id=inp.family_id, dataset_hash=inp.dataset_hash, code_sha=inp.code_sha,
    )
    result = finalize(result)
    if result.validate():
        raise RuntimeError(f"Reality Check producer produced an invalid result: {result.validate()}")
    governed = issue_governed_receipt("white_reality_check", result,
                                      input_artifact=inp)
    _assert_clean(governed, "reality_check")
    return governed


def run_governed_robustness(inp: RobustnessInput) -> GovernedResult:
    """Governed robustness checklist (the canonical evaluator is invoked)."""
    items = FrozenDict({k: v for k, v in inp.items.items()})
    for k, v in items.items():
        if not isinstance(v, RobustnessItem):
            raise ValueError(f"robustness item {k!r} must be a RobustnessItem, got {type(v)!r}")
    # INVOKE the canonical evaluator (same function the promotion gate RG-8 uses,
    # so a governed robustness result cannot diverge from what the gate checks).
    problems = robustness.evaluate_robustness(items)
    if problems:
        raise RuntimeError(f"robustness producer checklist has unresolved problems: {problems}")

    result = RobustnessResult(
        result_id=f"rob-{_input_digest(inp)[:12]}",
        items=items,
        protocol_hash=inp.protocol_hash, hypothesis_id=inp.hypothesis_id,
        trial_family_id=inp.trial_family_id, family_definition_hash=inp.family_definition_hash,
        dataset_hash=inp.dataset_hash, code_sha=inp.code_sha,
    )
    result = finalize(result)
    governed = issue_governed_receipt("robustness", result, input_artifact=inp)
    _assert_clean(governed, "robustness")
    return governed
