"""Research governance — typed, digested statistical result contracts (PR-R1).

The promotion gate must consume GOVERNED evidence, not arbitrary caller-built
dicts and not even self-digested typed objects. Each statistical result is an
immutable dataclass carrying:

  * a canonical `result_digest` (hash of the full payload), and
  * a `verify()` method that recomputes the digest, and
  * a `validate()` method that checks NUMERIC self-consistency (P0-9).

The governed provenance wrapper (``receipts.GovernedResultReceipt``) binds these
results to exact inputs, dataset, code and family. A bare typed result — even
with a valid self-digest — is NOT evidence provenance and is rejected for a
Grade A/B promotion. See `receipts.py` and `promotion_gate.py`.

Nested collections are DEEP-FROZEN in `__post_init__`: `@dataclass(frozen=True)`
alone does not freeze a nested plain dict, so canonical constructors convert any
mapping/list into `FrozenDict`/tuple.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .enums import (
    InfluenceClass,
)
from .models import FrozenDict, _deep_freeze, _stable_hash


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x))


def _pvalue_ok(p: Any) -> bool:
    return _is_finite(p) and 0.0 <= float(p) <= 1.0


def _alpha_ok(a: Any) -> bool:
    return _is_finite(a) and 0.0 < float(a) < 1.0


def _digest(payload: dict) -> str:
    return _stable_hash(payload)


def finalize(result: Any) -> Any:
    """Return a copy of a typed result with its canonical `result_digest` set."""
    return replace(result, result_digest=result.compute_digest())


# ---------------------------------------------------------------------------
# Method applicability (P0-7)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MethodRequirement:
    state: str  # REQUIRED | NOT_APPLICABLE | UNAVAILABLE
    reason: str = ""


@dataclass(frozen=True)
class MethodApplicability:
    dsr: MethodRequirement = MethodRequirement("NOT_APPLICABLE")
    pbo: MethodRequirement = MethodRequirement("NOT_APPLICABLE")
    reality_check: MethodRequirement = MethodRequirement("NOT_APPLICABLE")
    purged_cv: MethodRequirement = MethodRequirement("NOT_APPLICABLE")


# ---------------------------------------------------------------------------
# Multiple testing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MultipleTestingResult:
    result_id: str
    method: str
    status: str
    alpha: float
    family_id: str
    family_definition_hash: str
    trial_family_id: str
    tested_hypothesis_id: str
    raw_pvalue: float
    adjusted_pvalue: float
    rejected: bool
    complete_family: bool
    protocol_hash: str
    hypothesis_id: str
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    parameters: FrozenDict = field(default_factory=FrozenDict)
    approx: bool = False
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None
    # P0-8: the COMPLETE tested family, so Bonferroni/Holm is recomputable.
    tested_hypothesis_ids: tuple = ()
    raw_pvalues: tuple = ()
    family_input_digest: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _deep_freeze(self.parameters))
        object.__setattr__(self, "tested_hypothesis_ids",
                           tuple(self.tested_hypothesis_ids))
        object.__setattr__(self, "raw_pvalues", tuple(float(p) for p in self.raw_pvalues))

    def to_payload(self) -> dict:
        return {
            "result_id": self.result_id, "method": self.method, "status": self.status,
            "alpha": self.alpha, "family_id": self.family_id,
            "family_definition_hash": self.family_definition_hash,
            "trial_family_id": self.trial_family_id,
            "tested_hypothesis_id": self.tested_hypothesis_id,
            "raw_pvalue": self.raw_pvalue, "adjusted_pvalue": self.adjusted_pvalue,
            "rejected": self.rejected, "complete_family": self.complete_family,
            "protocol_hash": self.protocol_hash, "hypothesis_id": self.hypothesis_id,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
            "parameters": self.parameters.to_dict(), "approx": self.approx,
            "generated_at": self.generated_at,
            "tested_hypothesis_ids": list(self.tested_hypothesis_ids),
            "raw_pvalues": list(self.raw_pvalues),
            "family_input_digest": self.family_input_digest,
        }

    def compute_digest(self) -> str:
        return _digest(self.to_payload())

    def verify(self) -> bool:
        return self.result_digest is not None and self.result_digest == self.compute_digest()

    def recompute(self) -> Optional[dict]:
        """Recompute Bonferroni/Holm over the complete family (None if unsupported)."""
        from . import multiple_testing
        if not self.tested_hypothesis_ids or not self.raw_pvalues:
            return None
        if len(self.tested_hypothesis_ids) != len(self.raw_pvalues):
            return None
        if self.method == "bonferroni":
            return multiple_testing.bonferroni(self.raw_pvalues, self.alpha)
        if self.method == "holm":
            return multiple_testing.holm(self.raw_pvalues, self.alpha)
        return None

    def family_consistency_problems(self) -> list[str]:
        """P0-8: the complete family must reproduce the claimed focal result."""
        problems: list[str] = []
        if self.complete_family:
            if not self.tested_hypothesis_ids:
                problems.append("complete_family=True but no tested_hypothesis_ids")
            if not self.raw_pvalues:
                problems.append("complete_family=True but no raw_pvalues")
            if self.tested_hypothesis_id not in self.tested_hypothesis_ids:
                problems.append("focal tested_hypothesis_id not in tested_hypothesis_ids")
            if not _alpha_ok(self.alpha):
                # alpha invalid — already reported by validate(); cannot recompute.
                return problems
            # The family_input_digest binds the EXACT complete family. If a trial is
            # silently omitted (file-drawer) without updating this binding digest, the
            # result no longer matches the governed family and must fail.
            if self.family_input_digest is None:
                problems.append("complete_family=True but no family_input_digest")
            else:
                want_digest = _stable_hash({
                    "family": self.family_id, "ids": self.tested_hypothesis_ids,
                    "pvalues": self.raw_pvalues,
                })
                if self.family_input_digest != want_digest:
                    problems.append(
                        "family_input_digest does not match tested_hypothesis_ids + "
                        "raw_pvalues (omitted/altered trial)")
            out = self.recompute()
            if out is None:
                problems.append("complete_family=True but method not recomputable (Bonferroni/Holm only)")
            else:
                idx = self.tested_hypothesis_ids.index(self.tested_hypothesis_id) \
                    if self.tested_hypothesis_id in self.tested_hypothesis_ids else -1
                if idx >= 0:
                    want_adj = out["adjusted"][idx]
                    want_rej = out["rejected"][idx]
                    if abs(float(want_adj) - float(self.adjusted_pvalue)) > 1e-12:
                        problems.append(
                            f"adjusted_pvalue {self.adjusted_pvalue!r} != recomputed {want_adj!r}")
                    if bool(want_rej) != bool(self.rejected):
                        problems.append(
                            f"rejected {self.rejected!r} != recomputed {want_rej!r}")
        return problems

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not _alpha_ok(self.alpha):
            problems.append("alpha must be in (0,1)")
        if not _pvalue_ok(self.raw_pvalue):
            problems.append("raw_pvalue must be in [0,1] and finite")
        if not _pvalue_ok(self.adjusted_pvalue):
            problems.append("adjusted_pvalue must be in [0,1] and finite")
        if _pvalue_ok(self.adjusted_pvalue) and _alpha_ok(self.alpha):
            expected = self.adjusted_pvalue <= self.alpha
            if self.rejected != expected:
                problems.append(
                    f"rejection inconsistency: adjusted_pvalue={self.adjusted_pvalue}, "
                    f"alpha={self.alpha}, rejected={self.rejected}")
        problems.extend(self.family_consistency_problems())
        return problems


# ---------------------------------------------------------------------------
# DSR
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DSRResult:
    result_id: str
    method: str = "deflated_sharpe"
    status: str = "OK"
    observed_sharpe: float = 0.0
    n_observations: int = 0
    skewness: float = 0.0
    kurtosis: float = 3.0
    n_trials: Optional[int] = None
    deflated_benchmark_sr: Optional[float] = None
    psr_z: Optional[float] = None
    probability_sr_exceeds_deflated_benchmark: Optional[float] = None
    sharpe_frequency: Optional[str] = None
    trial_sharpe_frequency: Optional[str] = None
    return_frequency: Optional[str] = None
    confirmatory: bool = False
    protocol_hash: str = ""
    hypothesis_id: str = ""
    trial_family_id: str = ""
    family_definition_hash: str = ""
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def to_payload(self) -> dict:
        return {k: getattr(self, k) for k in (
            "result_id", "method", "status", "observed_sharpe", "n_observations",
            "skewness", "kurtosis", "n_trials", "deflated_benchmark_sr", "psr_z",
            "probability_sr_exceeds_deflated_benchmark", "sharpe_frequency",
            "trial_sharpe_frequency", "return_frequency", "confirmatory",
            "protocol_hash", "hypothesis_id", "trial_family_id",
            "family_definition_hash", "dataset_hash", "code_sha", "generated_at")}

    def compute_digest(self) -> str:
        return _digest(self.to_payload())

    def verify(self) -> bool:
        return self.result_digest is not None and self.result_digest == self.compute_digest()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.status != "OK":
            return problems  # unavailable results carry their own reason
        if not _is_finite(self.observed_sharpe):
            problems.append("observed_sharpe non-finite")
        if not _is_finite(self.skewness):
            problems.append("skewness non-finite")
        if not _is_finite(self.kurtosis):
            problems.append("kurtosis non-finite")
        if not isinstance(self.n_observations, int) or self.n_observations < 2:
            problems.append("n_observations must be >= 2")
        if self.n_trials is None or not isinstance(self.n_trials, int) or self.n_trials < 2:
            problems.append("n_trials must be an integer >= 2 for a confirmatory family")
        if self.deflated_benchmark_sr is not None and not _is_finite(self.deflated_benchmark_sr):
            problems.append("deflated_benchmark_sr non-finite")
        if self.psr_z is not None and not _is_finite(self.psr_z):
            problems.append("psr_z non-finite")
        if (self.probability_sr_exceeds_deflated_benchmark is not None
                and not _pvalue_ok(self.probability_sr_exceeds_deflated_benchmark)):
            problems.append("probability out of [0,1]")
        # Confirmatory frequency contract (P0-10): per-period Sharpe only.
        if self.confirmatory:
            if not self.sharpe_frequency:
                problems.append("confirmatory DSR missing sharpe_frequency")
            if not self.trial_sharpe_frequency:
                problems.append("confirmatory DSR missing trial_sharpe_frequency")
            if not self.return_frequency:
                problems.append("confirmatory DSR missing return_frequency")
            if self.sharpe_frequency and self.sharpe_frequency != "PER_PERIOD":
                problems.append(
                    f"confirmatory DSR requires PER_PERIOD Sharpe, got {self.sharpe_frequency!r}")
            if self.trial_sharpe_frequency and self.trial_sharpe_frequency != "PER_PERIOD":
                problems.append(
                    f"confirmatory DSR requires PER_PERIOD trial Sharpe, got "
                    f"{self.trial_sharpe_frequency!r}")
            if (self.sharpe_frequency and self.trial_sharpe_frequency
                    and self.sharpe_frequency != self.trial_sharpe_frequency):
                problems.append("sharpe frequency mismatch")
        return problems


# ---------------------------------------------------------------------------
# PBO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PBOResult:
    result_id: str
    method: str = "cscv_pbo"
    status: str = "OK"
    pbo: float = 0.0
    n_configs: int = 0
    n_observations: int = 0
    n_subsets: int = 0
    total_combinations: int = 0
    combinations_evaluated: int = 0
    sampling_fraction: float = 1.0
    approx: bool = False
    sampling_method: Optional[str] = None
    sampling_seed: Optional[int] = None
    tie_policy: str = "average_rank"
    is_tie_split_count: int = 0
    tie_fraction: float = 0.0
    lambda_zero_policy: str = "counts_as_not_overfit"
    protocol_hash: str = ""
    hypothesis_id: str = ""
    trial_family_id: str = ""
    family_definition_hash: str = ""
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def to_payload(self) -> dict:
        return {k: getattr(self, k) for k in (
            "result_id", "method", "status", "pbo", "n_configs", "n_observations",
            "n_subsets", "total_combinations", "combinations_evaluated",
            "sampling_fraction", "approx", "sampling_method", "sampling_seed",
            "tie_policy", "is_tie_split_count", "tie_fraction", "lambda_zero_policy",
            "protocol_hash", "hypothesis_id", "trial_family_id", "family_definition_hash",
            "dataset_hash", "code_sha", "generated_at")}

    def compute_digest(self) -> str:
        return _digest(self.to_payload())

    def verify(self) -> bool:
        return self.result_digest is not None and self.result_digest == self.compute_digest()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.status != "OK":
            return problems
        if not _is_finite(self.pbo) or not (0.0 <= self.pbo <= 1.0):
            problems.append("pbo must be in [0,1] and finite")
        if not isinstance(self.n_configs, int) or self.n_configs < 2:
            problems.append("n_configs must be >= 2")
        if not isinstance(self.n_subsets, int) or self.n_subsets < 2 or self.n_subsets % 2 != 0:
            problems.append("n_subsets must be even and >= 2")
        if self.n_subsets > self.n_observations:
            problems.append("n_subsets must be <= n_observations")
        expect_total = math.comb(self.n_subsets, self.n_subsets // 2) if self.n_subsets >= 2 else 0
        if self.total_combinations != expect_total:
            problems.append(
                f"total_combinations {self.total_combinations} != C(S,S/2)={expect_total}")
        if not (0 < self.combinations_evaluated <= self.total_combinations):
            problems.append(
                f"combinations_evaluated {self.combinations_evaluated} out of range")
        if self.approx and self.sampling_method is None:
            problems.append("approximate PBO missing sampling_method")
        if self.approx and self.sampling_method == "full_enumeration":
            problems.append("approx=True but sampling_method=full_enumeration")
        if not self.approx and self.sampling_method != "full_enumeration":
            problems.append("approx=False but sampling_method != full_enumeration")
        if self.total_combinations > 0:
            frac = self.combinations_evaluated / self.total_combinations
            if abs(frac - self.sampling_fraction) > 1e-12:
                problems.append(
                    f"sampling_fraction {self.sampling_fraction} != evaluated/total {frac}")
        if self.combinations_evaluated > 0:
            tf = self.is_tie_split_count / self.combinations_evaluated
            if abs(tf - self.tie_fraction) > 1e-12:
                problems.append(
                    f"tie_fraction {self.tie_fraction} != is_tie_split_count/evaluated {tf}")
        return problems


# ---------------------------------------------------------------------------
# Reality Check
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RealityCheckResult:
    result_id: str
    method: str = "white_reality_check"
    status: str = "OK"
    bootstrap_pvalue: float = 1.0
    n_rules: int = 0
    n_observations: int = 0
    n_bootstrap: int = 0
    bootstrap_method: str = "stationary"
    mean_block_length: float = 1.0
    bootstrap_seed: Optional[int] = None
    alpha: float = 0.05
    pvalue_resolution: Optional[float] = None
    protocol_hash: str = ""
    hypothesis_id: str = ""
    trial_family_id: str = ""
    family_definition_hash: str = ""
    family_id: str = ""
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def to_payload(self) -> dict:
        return {k: getattr(self, k) for k in (
            "result_id", "method", "status", "bootstrap_pvalue", "n_rules",
            "n_observations", "n_bootstrap", "bootstrap_method", "mean_block_length",
            "bootstrap_seed", "alpha", "pvalue_resolution", "protocol_hash",
            "hypothesis_id", "trial_family_id", "family_definition_hash",
            "family_id", "dataset_hash", "code_sha", "generated_at")}

    def compute_digest(self) -> str:
        return _digest(self.to_payload())

    def verify(self) -> bool:
        return self.result_digest is not None and self.result_digest == self.compute_digest()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.status != "OK":
            return problems
        if not _pvalue_ok(self.bootstrap_pvalue):
            problems.append("bootstrap_pvalue must be in [0,1] and finite")
        if not _alpha_ok(self.alpha):
            problems.append("alpha must be in (0,1)")
        if self.n_rules < 2:
            problems.append("n_rules must be >= 2 for a searched family")
        if self.n_observations <= 1:
            problems.append("n_observations must be > 1")
        if not isinstance(self.n_bootstrap, int) or self.n_bootstrap < 1:
            problems.append("n_bootstrap must be an integer >= 1")
        if self.mean_block_length < 1:
            problems.append("mean_block_length must be >= 1")
        if self.bootstrap_method != "stationary":
            problems.append("bootstrap_method must be 'stationary' for this implementation")
        if self.pvalue_resolution is not None and not _is_finite(self.pvalue_resolution):
            problems.append("pvalue_resolution non-finite")
        # P0-9: resolution must equal 1/(n_bootstrap+1) under this implementation.
        if isinstance(self.n_bootstrap, int) and self.n_bootstrap >= 1:
            want = 1.0 / (self.n_bootstrap + 1)
            if self.pvalue_resolution is not None and abs(self.pvalue_resolution - want) > 1e-12:
                problems.append(
                    f"pvalue_resolution {self.pvalue_resolution!r} != 1/(n_bootstrap+1)={want!r}")
        if (self.pvalue_resolution is not None and _alpha_ok(self.alpha)
                and self.pvalue_resolution >= self.alpha):
            problems.append(
                f"bootstrap resolution {self.pvalue_resolution:.4f} too coarse for alpha={self.alpha}")
        return problems


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RobustnessItem:
    state: str  # PASS | FAIL | NOT_APPLICABLE
    reason: str = ""
    evidence_ref: str = ""


@dataclass(frozen=True)
class RobustnessResult:
    result_id: str
    method: str = "robustness"
    items: FrozenDict = field(default_factory=FrozenDict)  # field -> RobustnessItem
    protocol_hash: str = ""
    hypothesis_id: str = ""
    trial_family_id: str = ""
    family_definition_hash: str = ""
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", _deep_freeze(self.items))

    def to_payload(self) -> dict:
        items = {k: {"state": v.state, "reason": v.reason, "evidence_ref": v.evidence_ref}
                 for k, v in self.items.items()}
        return {
            "result_id": self.result_id, "method": self.method, "items": items,
            "protocol_hash": self.protocol_hash, "hypothesis_id": self.hypothesis_id,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
            "generated_at": self.generated_at,
        }

    def compute_digest(self) -> str:
        return _digest(self.to_payload())

    def verify(self) -> bool:
        return self.result_digest is not None and self.result_digest == self.compute_digest()


# -- Influence class compatibility matrix (P1-6) -----------------------------

_INFLUENCE_MATRIX = {
    "SEASONALITY": {InfluenceClass.CONTEXT_MODIFIER.value},
    "POLICY_OR_REGULATORY": {InfluenceClass.RISK_VETO.value,
                             InfluenceClass.DETERMINISTIC_MECHANICS.value},
    "DETERMINISTIC_MECHANICS": {InfluenceClass.DETERMINISTIC_MECHANICS.value},
    "VALUATION_MODEL": {InfluenceClass.VALUATION_INPUT.value},
    "EMPIRICAL_STRATEGY": {InfluenceClass.CONTEXT_MODIFIER.value,
                           InfluenceClass.PORTFOLIO_CONSTRUCTION.value},
    "EMPIRICAL_FACTOR": {InfluenceClass.CONTEXT_MODIFIER.value,
                         InfluenceClass.PORTFOLIO_CONSTRUCTION.value},
    "SOURCE_NARRATIVE": {InfluenceClass.CONTEXT_MODIFIER.value},
    "BEHAVIORAL_FRAMEWORK": {InfluenceClass.CONTEXT_MODIFIER.value},
}


def influence_allowed(evidence_type: str, influence_class: str) -> bool:
    allowed = _INFLUENCE_MATRIX.get(evidence_type)
    if allowed is None:
        return False
    return influence_class in allowed


def make_typed_empirical_context() -> dict:
    """Backward-compatible alias for the governed bundle-backed promotion context.

    The canonical builder lives in ``governed_bundle``; this re-export keeps older
    import sites working while the promotion gate consumes ``evidence_bundle``.
    """
    from . import governed_bundle
    return governed_bundle.make_typed_empirical_context()
