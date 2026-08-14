"""Research governance — typed, digested statistical result contracts (PR-R1).

The promotion gate must consume VERIFIED evidence, not arbitrary caller-built
dicts. Each statistical result is an immutable dataclass carrying:

  * a canonical `result_digest` (hash of the full payload), and
  * a `verify()` method that recomputes the digest, and
  * a `validate()` method that checks NUMERIC self-consistency (P0-6).

A result produced by the governed statistical functions should be wrapped in
these contracts (or serialized and re-verified against their digest) before it
can support a Grade A/B promotion. Arbitrary unverified dicts are rejected.

Cross-result identity is enforced by `ReproductionEvidenceBundle`, which checks
that every bundled result agrees on hypothesis / protocol / trial family /
dataset / code generation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .enums import (
    InfluenceClass,
    ReturnFrequency,
    SharpeFrequency,
)
from .models import FrozenDict, _stable_hash


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
    from dataclasses import replace
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
        }

    def compute_digest(self) -> str:
        return _digest(self.to_payload())

    def verify(self) -> bool:
        return self.result_digest is not None and self.result_digest == self.compute_digest()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not _alpha_ok(self.alpha):
            problems.append("alpha must be in (0,1)")
        if not _pvalue_ok(self.raw_pvalue):
            problems.append("raw_pvalue must be in [0,1] and finite")
        if not _pvalue_ok(self.adjusted_pvalue):
            problems.append("adjusted_pvalue must be in [0,1] and finite")
        # Rejection consistency: rejected must agree with adjusted_pvalue <= alpha.
        if _pvalue_ok(self.adjusted_pvalue) and _alpha_ok(self.alpha):
            expected = self.adjusted_pvalue <= self.alpha
            if self.rejected != expected:
                problems.append(
                    f"rejection inconsistency: adjusted_pvalue={self.adjusted_pvalue}, "
                    f"alpha={self.alpha}, rejected={self.rejected}")
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
        if self.confirmatory:
            if not self.sharpe_frequency:
                problems.append("confirmatory DSR missing sharpe_frequency")
            if not self.trial_sharpe_frequency:
                problems.append("confirmatory DSR missing trial_sharpe_frequency")
            if not self.return_frequency:
                problems.append("confirmatory DSR missing return_frequency")
            if self.sharpe_frequency and self.trial_sharpe_frequency \
                    and self.sharpe_frequency != self.trial_sharpe_frequency:
                problems.append("sharpe frequency mismatch")
        if self.psr_z is not None and not _is_finite(self.psr_z):
            problems.append("psr_z non-finite")
        if self.probability_sr_exceeds_deflated_benchmark is not None \
                and not _pvalue_ok(self.probability_sr_exceeds_deflated_benchmark):
            problems.append("probability out of [0,1]")
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
            "tie_policy", "is_tie_split_count", "tie_fraction", "protocol_hash",
            "hypothesis_id", "trial_family_id", "family_definition_hash",
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
        if self.n_subsets < 2 or self.n_subsets % 2 != 0:
            problems.append("n_subsets must be even and >= 2")
        if self.combinations_evaluated <= 0:
            problems.append("no combinations evaluated")
        if self.approx and self.sampling_method is None:
            problems.append("approximate PBO missing sampling_method")
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
        if self.mean_block_length < 1:
            problems.append("mean_block_length must be >= 1")
        if self.bootstrap_method != "stationary":
            problems.append("bootstrap_method must be 'stationary' for this implementation")
        if self.pvalue_resolution is not None and not _is_finite(self.pvalue_resolution):
            problems.append("pvalue_resolution non-finite")
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
    items: FrozenDict = field(default_factory=FrozenDict)  # field -> RobustnessItem
    protocol_hash: str = ""
    hypothesis_id: str = ""
    trial_family_id: str = ""
    family_definition_hash: str = ""
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def to_payload(self) -> dict:
        items = {k: {"state": v.state, "reason": v.reason, "evidence_ref": v.evidence_ref}
                 for k, v in self.items.items()}
        return {
            "result_id": self.result_id, "items": items,
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


# ---------------------------------------------------------------------------
# Reproduction evidence bundle (cross-result identity)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReproductionEvidenceBundle:
    result_id: str
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: Optional[str] = None
    code_sha: Optional[str] = None
    multiple_testing: Optional[MultipleTestingResult] = None
    dsr: Optional[DSRResult] = None
    pbo: Optional[PBOResult] = None
    reality_check: Optional[RealityCheckResult] = None
    robustness: Optional[RobustnessResult] = None
    applicability: Optional[MethodApplicability] = None
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def cross_result_identity_problems(self) -> list[str]:
        """Verify every bundled result agrees on the shared identity fields."""
        problems: list[str] = []
        for name, res in (("multiple_testing", self.multiple_testing),
                          ("dsr", self.dsr), ("pbo", self.pbo),
                          ("reality_check", self.reality_check),
                          ("robustness", self.robustness)):
            if res is None:
                continue
            if res.hypothesis_id and res.hypothesis_id != self.hypothesis_id:
                problems.append(f"{name} hypothesis_id mismatch")
            if res.protocol_hash and res.protocol_hash != self.protocol_hash:
                problems.append(f"{name} protocol_hash mismatch")
            if res.trial_family_id and res.trial_family_id != self.trial_family_id:
                problems.append(f"{name} trial_family_id mismatch")
            if res.family_definition_hash and res.family_definition_hash != self.family_definition_hash:
                problems.append(f"{name} family_definition_hash mismatch")
            if res.dataset_hash and res.dataset_hash != self.dataset_hash:
                problems.append(f"{name} dataset_hash mismatch")
            if res.code_sha and res.code_sha != self.code_sha:
                problems.append(f"{name} code_sha mismatch")
        return problems

    def verify(self) -> bool:
        if self.result_digest is None:
            return False
        return self.result_digest == self.compute_digest()

    def compute_digest(self) -> str:
        payload = {
            "result_id": self.result_id, "hypothesis_id": self.hypothesis_id,
            "protocol_hash": self.protocol_hash, "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
            "multiple_testing": self.multiple_testing.to_payload() if self.multiple_testing else None,
            "dsr": self.dsr.to_payload() if self.dsr else None,
            "pbo": self.pbo.to_payload() if self.pbo else None,
            "reality_check": self.reality_check.to_payload() if self.reality_check else None,
            "robustness": self.robustness.to_payload() if self.robustness else None,
            "generated_at": self.generated_at,
        }
        return _digest(payload)


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
    """Build a fully valid, typed/digested A-grade empirical promotion context.

    Shared test/acceptance fixture: proves the promotion gate passes ONLY when
    all statistical evidence is typed, digested, numeric-consistent, and bound to
    the frozen family, and when DSR/PBO applicability is satisfied.
    """
    mt = finalize(MultipleTestingResult(
        result_id="mt1", method="bonferroni", status="OK", alpha=0.05,
        family_id="f", family_definition_hash="fdh", trial_family_id="f",
        tested_hypothesis_id="h1", raw_pvalue=0.001, adjusted_pvalue=0.004,
        rejected=True, complete_family=True, protocol_hash="ph", hypothesis_id="h1",
        dataset_hash="d0", code_sha="c0",
    ))
    rc = finalize(RealityCheckResult(
        result_id="rc1", status="OK", bootstrap_pvalue=0.01, n_rules=5,
        n_observations=100, n_bootstrap=1000, bootstrap_method="stationary",
        mean_block_length=5.0, bootstrap_seed=1, alpha=0.05,
        pvalue_resolution=1 / 1001, protocol_hash="ph", hypothesis_id="h1",
        trial_family_id="f", family_definition_hash="fdh", family_id="f",
        dataset_hash="d0", code_sha="c0",
    ))
    rob = finalize(RobustnessResult(
        result_id="rob1",
        items={
            "sample_n": RobustnessItem("PASS", "n=100", "e1"),
            "benchmark": RobustnessItem("PASS", "SPX", "e2"),
            "subperiods": RobustnessItem("PASS", "5y", "e3"),
            "regimes": RobustnessItem("PASS", "bull/bear", "e4"),
            "costs": RobustnessItem("PASS", "bps=5", "e5"),
            "outlier_dependence": RobustnessItem("PASS", "winsorized", "e6"),
            "lookahead_control": RobustnessItem("PASS", "point-in-time", "e7"),
            "survivorship_control": RobustnessItem("PASS", "point-in-time universe", "e8"),
            "limitations": RobustnessItem("PASS", "stated", "e9"),
        },
        protocol_hash="ph", hypothesis_id="h1", trial_family_id="f",
        family_definition_hash="fdh", dataset_hash="d0", code_sha="c0",
    ))
    dsr = finalize(DSRResult(
        result_id="dsr1", status="OK", observed_sharpe=1.2, n_observations=250,
        skewness=-0.2, kurtosis=4.0, n_trials=10, deflated_benchmark_sr=0.5,
        psr_z=2.5, probability_sr_exceeds_deflated_benchmark=0.99,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True, protocol_hash="ph",
        hypothesis_id="h1", trial_family_id="f", family_definition_hash="fdh",
        dataset_hash="d0", code_sha="c0",
    ))
    pbo_res = finalize(PBOResult(
        result_id="pbo1", status="OK", pbo=0.1, n_configs=3, n_observations=16,
        n_subsets=4, total_combinations=6, combinations_evaluated=6,
        sampling_fraction=1.0, approx=False, sampling_method="full_enumeration",
        protocol_hash="ph", hypothesis_id="h1", trial_family_id="f",
        family_definition_hash="fdh", dataset_hash="d0", code_sha="c0",
    ))
    app = MethodApplicability(
        dsr=MethodRequirement("REQUIRED"),
        pbo=MethodRequirement("REQUIRED"),
        reality_check=MethodRequirement("REQUIRED"),
        purged_cv=MethodRequirement("NOT_APPLICABLE", reason="non-overlapping fixed-period"),
    )
    return {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "EMPIRICAL_STRATEGY",
        "protocol_hash": "ph", "trial_family_id": "f", "family_frozen": True,
        "family_definition_hash": "fdh", "hypothesis_id": "h1",
        "code_sha": "c0", "dataset_hash": "d0",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "oos_supported": True, "oos_untouched": True,
        "multiple_testing": mt,
        "reality_check": rc,
        "robustness": rob,
        "dsr_result": dsr,
        "pbo_result": pbo_res,
        "method_applicability": app,
        "purged_cv_applied": False,
        "evidence_grade": "A", "influence_class": "PORTFOLIO_CONSTRUCTION",
    }
