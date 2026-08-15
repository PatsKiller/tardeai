"""Research governance — governed result receipts + canonical promotion bundle (PR-R1).

The single most important architectural invariant of this subsystem:

    A typed, self-hashed result is NOT evidence provenance.

A caller can build a ``DSRResult(status="OK", ...)`` and call ``finalize()`` to
give it a valid self-digest; that only proves the object did not change after it
hashed itself. It does NOT prove the governed statistical function produced the
result from the governed dataset/family.

This module introduces the two pieces that close that gap:

  * ``GovernedResultReceipt`` — an immutable receipt binding the governed
    function's output to its exact inputs, dataset, code, hypothesis, and family.
    It carries ``producer_module`` / ``producer_code_sha`` / ``input_artifact_hash``
    / ``output_artifact_hash`` / ``result_payload_hash`` and a
    ``verification_status``. A Grade A/B promotion REQUIRES a verified receipt;
    a bare typed result (even digest-valid) fails.
  * ``PromotionEvidenceBundle`` — the single immutable canonical input to a Grade
    A/B empirical promotion. It binds every statistical result to ONE identity
    (hypothesis / protocol / trial family / family definition / dataset / code)
    plus the frozen-family receipt, registry-completeness receipt, and OOS
    receipt, with the method applicability folded into the bundle digest.

R1 keeps all of this pure/in-memory and injectable. Durable persistence and a
real (non-fake) verifier are deferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional

from .enums import VerificationStatus
from .models import FrozenDict, _stable_hash
from .results import (
    DSRResult,
    MethodApplicability,
    MethodRequirement,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    RobustnessResult,
)

# Canonical producer identity per statistical method. `producer_code_sha` is a
# stable hash of (module, version) so a hand-built receipt with an arbitrary
# producer cannot satisfy verification.
PRODUCER_REGISTRY: dict[str, tuple[str, str]] = {
    "deflated_sharpe": ("research_governance.deflated_sharpe", "1.0"),
    "cscv_pbo": ("research_governance.pbo", "1.0"),
    "white_reality_check": ("research_governance.bootstrap_reality_check", "1.0"),
    "bonferroni": ("research_governance.multiple_testing", "1.0"),
    "holm": ("research_governance.multiple_testing", "1.0"),
    "bh_fdr": ("research_governance.multiple_testing", "1.0"),
    "robustness": ("research_governance.results", "1.0"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def producer_code_sha(method: str) -> str:
    """Canonical producer-code identity for a method (raises if unknown)."""
    if method not in PRODUCER_REGISTRY:
        raise ValueError(f"unknown governed method: {method!r}")
    module, version = PRODUCER_REGISTRY[method]
    return _stable_hash({"module": module, "version": version})


# ---------------------------------------------------------------------------
# Governed result receipt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GovernedResultReceipt:
    """Immutable receipt binding a governed function output to exact inputs.

    ``result_payload_hash`` == the typed result's canonical ``result_digest``.
    ``output_artifact_hash`` == the hash of the governed function's output bytes
    (which, for these in-memory results, is the same payload). ``input_artifact_hash``
    == the canonical digest of the governed inputs (dataset + family + parameters).
    """

    receipt_id: str
    method: str
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    producer_module: str
    producer_version: str
    producer_code_sha: str
    input_artifact_hash: str
    output_artifact_hash: str
    result_payload_hash: str
    generated_at: str
    verification_status: str = VerificationStatus.VERIFIED.value
    verifier_id: str = "governed-producer"
    receipt_digest: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "receipt_id": self.receipt_id, "method": self.method,
            "hypothesis_id": self.hypothesis_id, "protocol_hash": self.protocol_hash,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
            "producer_module": self.producer_module,
            "producer_version": self.producer_version,
            "producer_code_sha": self.producer_code_sha,
            "input_artifact_hash": self.input_artifact_hash,
            "output_artifact_hash": self.output_artifact_hash,
            "result_payload_hash": self.result_payload_hash,
            "generated_at": self.generated_at,
            "verification_status": self.verification_status,
            "verifier_id": self.verifier_id,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.to_payload())

    def verify(self) -> bool:
        return self.receipt_digest is not None and self.receipt_digest == self.compute_digest()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.verification_status != VerificationStatus.VERIFIED.value:
            problems.append(f"verification_status != VERIFIED: {self.verification_status!r}")
        if self.method not in PRODUCER_REGISTRY:
            problems.append(f"unknown governed method: {self.method!r}")
        else:
            module, version = PRODUCER_REGISTRY[self.method]
            if self.producer_module != module:
                problems.append(f"producer_module {self.producer_module!r} != expected {module!r}")
            if self.producer_version != version:
                problems.append(f"producer_version {self.producer_version!r} != expected {version!r}")
            if self.producer_code_sha != _stable_hash({"module": module, "version": version}):
                problems.append("producer_code_sha does not match the canonical producer")
        if self.output_artifact_hash != self.result_payload_hash:
            problems.append("output_artifact_hash != result_payload_hash")
        # The input artifact's identity portion must equal the receipt's own identity
        # fields, so a caller cannot bind a result to one identity while hashing a
        # different dataset/family/code as its input.
        expected_input = _stable_hash({
            "hypothesis_id": self.hypothesis_id, "protocol_hash": self.protocol_hash,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
        })
        if self.input_artifact_hash != expected_input:
            problems.append("input_artifact_hash does not match the receipt identity fields")
        if not self.receipt_digest:
            problems.append("missing receipt_digest")
        return problems

    def binds_result(self, result: Any) -> bool:
        """True if this receipt's payload hash matches the typed result digest."""
        return result.result_digest == self.result_payload_hash


@dataclass(frozen=True)
class GovernedResult:
    """A typed statistical result paired with its governed receipt."""

    receipt: GovernedResultReceipt
    result: Any  # a frozen typed result object (DSR/PBO/MT/RC/Robustness)


def governed_result(result: Any, *, input_artifact: Any,
                    generated_at: Optional[str] = None) -> GovernedResult:
    """Wrap a typed result in a governed receipt (the only sanctioned path).

    Raises if the result has no method, no digest, or an unknown producer method.
    """
    if getattr(result, "result_digest", None) is None:
        from .results import finalize
        result = finalize(result)
    method = getattr(result, "method", "robustness")
    module, version = PRODUCER_REGISTRY[method]  # raises if unknown
    receipt = GovernedResultReceipt(
        receipt_id=f"rcpt-{method}-{result.result_id}",
        method=method,
        hypothesis_id=result.hypothesis_id,
        protocol_hash=result.protocol_hash,
        trial_family_id=result.trial_family_id,
        family_definition_hash=result.family_definition_hash,
        dataset_hash=result.dataset_hash,
        code_sha=result.code_sha,
        producer_module=module,
        producer_version=version,
        producer_code_sha=_stable_hash({"module": module, "version": version}),
        input_artifact_hash=_stable_hash(input_artifact),
        output_artifact_hash=result.result_digest,
        result_payload_hash=result.result_digest,
        generated_at=generated_at or _now_iso(),
    )
    receipt = replace(receipt, receipt_digest=receipt.compute_digest())
    return GovernedResult(receipt=receipt, result=result)


# ---------------------------------------------------------------------------
# Frozen trial family receipt (immutable definition)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrozenTrialFamilyReceipt:
    """Deeply immutable snapshot of a frozen trial family DEFINITION.

    The registry's mutable runtime state (recorded trials, selections, OOS
    windows) is kept private; this receipt is the only canonical definition that
    leaves the registry, and it cannot be mutated in place.
    """

    family_id: str
    hypothesis_id: str
    protocol_hash: str
    family_definition_hash: str
    confirmatory: bool
    planned_trial_ids: tuple
    planned_config_hashes: FrozenDict
    frozen_at: str
    definition_digest: str

    def to_payload(self) -> dict:
        return {
            "family_id": self.family_id, "hypothesis_id": self.hypothesis_id,
            "protocol_hash": self.protocol_hash,
            "family_definition_hash": self.family_definition_hash,
            "confirmatory": self.confirmatory,
            "planned_trial_ids": list(self.planned_trial_ids),
            "planned_config_hashes": self.planned_config_hashes.to_dict(),
            "frozen_at": self.frozen_at,
        }

    def compute_definition_digest(self) -> str:
        return _stable_hash(self.to_payload())

    def verify(self) -> bool:
        return self.definition_digest == self.compute_definition_digest()


# ---------------------------------------------------------------------------
# Registry completeness receipt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegistryCompletenessReceipt:
    family_id: str
    complete: bool
    planned_trial_count: int
    recorded_trial_count: int
    terminal_counts: FrozenDict
    definition_digest: str
    generated_at: str
    receipt_digest: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "family_id": self.family_id, "complete": self.complete,
            "planned_trial_count": self.planned_trial_count,
            "recorded_trial_count": self.recorded_trial_count,
            "terminal_counts": self.terminal_counts.to_dict(),
            "definition_digest": self.definition_digest,
            "generated_at": self.generated_at,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.to_payload())

    def verify(self) -> bool:
        return self.receipt_digest is not None and self.receipt_digest == self.compute_digest()


# ---------------------------------------------------------------------------
# OOS receipt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OOSReceipt:
    """Registry-generated immutable OOS window receipt (never caller booleans)."""

    oos_window_id: str
    economic_segment_id: str
    dataset_id: str
    dataset_hash: str
    segment_start: str
    segment_end: str
    oos_generation: int
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    registered_at: str
    consumed_at: Optional[str]
    rerun_classification: Optional[str]
    untouched: bool
    receipt_digest: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "oos_window_id": self.oos_window_id,
            "economic_segment_id": self.economic_segment_id,
            "dataset_id": self.dataset_id, "dataset_hash": self.dataset_hash,
            "segment_start": self.segment_start, "segment_end": self.segment_end,
            "oos_generation": self.oos_generation, "protocol_hash": self.protocol_hash,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "registered_at": self.registered_at, "consumed_at": self.consumed_at,
            "rerun_classification": self.rerun_classification,
            "untouched": self.untouched,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.to_payload())

    def verify(self) -> bool:
        return self.receipt_digest is not None and self.receipt_digest == self.compute_digest()


# ---------------------------------------------------------------------------
# Canonical promotion evidence bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionEvidenceBundle:
    """The single immutable input to a Grade A/B empirical promotion.

    Every child result must agree on ONE identity: hypothesis / protocol / trial
    family / family definition / dataset / code. The bundle digest folds in every
    identity field, method applicability, and every child receipt digest.
    """

    bundle_id: str
    hypothesis_id: str
    protocol_hash: str
    trial_family_id: str
    family_definition_hash: str
    dataset_hash: str
    code_sha: str
    frozen_family_receipt: FrozenTrialFamilyReceipt
    registry_completeness_receipt: RegistryCompletenessReceipt
    oos_receipt: OOSReceipt
    method_applicability: MethodApplicability
    multiple_testing: Optional[GovernedResult] = None
    dsr: Optional[GovernedResult] = None
    pbo: Optional[GovernedResult] = None
    reality_check: Optional[GovernedResult] = None
    robustness: Optional[GovernedResult] = None
    generated_at: Optional[str] = None
    bundle_digest: Optional[str] = None

    _IDENTITY_FIELDS = ("hypothesis_id", "protocol_hash", "trial_family_id",
                        "family_definition_hash", "dataset_hash", "code_sha")

    @staticmethod
    def _child_token(child):
        """Digest token for a child: its governed receipt digest, or a sentinel."""
        if child is None:
            return None
        if isinstance(child, GovernedResult):
            return child.receipt.receipt_digest
        return f"non_governed:{type(child).__name__}:{getattr(child, 'result_digest', None)}"

    def _child_entries(self):
        return (("multiple_testing", self.multiple_testing),
                ("dsr", self.dsr), ("pbo", self.pbo),
                ("reality_check", self.reality_check),
                ("robustness", self.robustness))

    def compute_digest(self) -> str:
        payload = {
            "bundle_id": self.bundle_id,
            "hypothesis_id": self.hypothesis_id, "protocol_hash": self.protocol_hash,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
            "frozen_family_receipt": self.frozen_family_receipt.definition_digest,
            "registry_completeness_receipt": (
                self.registry_completeness_receipt.receipt_digest
                if self.registry_completeness_receipt else None),
            "oos_receipt": self.oos_receipt.receipt_digest if self.oos_receipt else None,
            "method_applicability": {
                "dsr": {"state": self.method_applicability.dsr.state,
                        "reason": self.method_applicability.dsr.reason},
                "pbo": {"state": self.method_applicability.pbo.state,
                        "reason": self.method_applicability.pbo.reason},
                "reality_check": {"state": self.method_applicability.reality_check.state,
                                  "reason": self.method_applicability.reality_check.reason},
                "purged_cv": {"state": self.method_applicability.purged_cv.state,
                              "reason": self.method_applicability.purged_cv.reason},
            },
            "multiple_testing": self._child_token(self.multiple_testing),
            "dsr": self._child_token(self.dsr),
            "pbo": self._child_token(self.pbo),
            "reality_check": self._child_token(self.reality_check),
            "robustness": self._child_token(self.robustness),
            "generated_at": self.generated_at,
        }
        return _stable_hash(payload)

    def verify(self) -> bool:
        return self.bundle_digest is not None and self.bundle_digest == self.compute_digest()

    def validate_bundle(self) -> list[str]:
        """Return all integrity problems ([] == fully coherent)."""
        problems: list[str] = []

        if not self.bundle_digest:
            problems.append("missing bundle_digest")
        elif self.bundle_digest != self.compute_digest():
            problems.append("bundle_digest does not verify")

        # Frozen family receipt.
        if not self.frozen_family_receipt:
            problems.append("missing frozen_family_receipt")
        else:
            fr = self.frozen_family_receipt
            if not fr.verify():
                problems.append("frozen_family_receipt definition_digest does not verify")
            if fr.family_id != self.trial_family_id:
                problems.append("frozen family family_id != bundle trial_family_id")
            if fr.hypothesis_id != self.hypothesis_id:
                problems.append("frozen family hypothesis_id != bundle hypothesis_id")
            if fr.protocol_hash != self.protocol_hash:
                problems.append("frozen family protocol_hash != bundle protocol_hash")
            if fr.family_definition_hash != self.family_definition_hash:
                problems.append("frozen family family_definition_hash != bundle")
            if not fr.confirmatory:
                problems.append("frozen family is not confirmatory (Grade A/B requires confirmatory)")

        # Registry completeness receipt.
        if not self.registry_completeness_receipt:
            problems.append("missing registry_completeness_receipt")
        else:
            rc = self.registry_completeness_receipt
            if not rc.verify():
                problems.append("registry_completeness_receipt does not verify")
            if rc.complete is not True:
                problems.append("registry_completeness_receipt.complete is not True")
            if rc.family_id != self.trial_family_id:
                problems.append("completeness receipt family_id != bundle trial_family_id")

        # OOS receipt.
        if not self.oos_receipt:
            problems.append("missing oos_receipt")
        else:
            o = self.oos_receipt
            if not o.verify():
                problems.append("oos_receipt does not verify")
            if o.untouched is not True:
                problems.append("oos_receipt.untouched is not True (consumed/rerun)")
            if o.trial_family_id != self.trial_family_id:
                problems.append("oos receipt trial_family_id != bundle")
            if o.protocol_hash != self.protocol_hash:
                problems.append("oos receipt protocol_hash != bundle")
            if o.family_definition_hash != self.family_definition_hash:
                problems.append("oos receipt family_definition_hash != bundle")

        # Cross-result identity: every child receipt + result must match the bundle.
        for name, gr in self._child_entries():
            if gr is None:
                continue
            if not isinstance(gr, GovernedResult):
                problems.append(f"{name} must be a governed result (bare typed/dict rejected)")
                continue
            r = gr.receipt
            if not r.verify():
                problems.append(f"{name} receipt does not verify")
            for p in r.validate():
                problems.append(f"{name} receipt: {p}")
            for field in self._IDENTITY_FIELDS:
                if getattr(r, field, None) != getattr(self, field):
                    problems.append(f"{name} receipt {field} mismatch")
            if not r.binds_result(gr.result):
                problems.append(f"{name} receipt does not bind its result digest")
            # Result-level identity (for results that carry identity fields).
            res = gr.result
            for field in self._IDENTITY_FIELDS:
                rv = getattr(res, field, None)
                if rv not in (None, "") and rv != getattr(self, field):
                    problems.append(f"{name} result {field} mismatch")
            validate = getattr(res, "validate", None)
            if callable(validate):
                for p in validate():
                    problems.append(f"{name} numeric/self-consistency: {p}")

        return problems


# ---------------------------------------------------------------------------
# Retrieval freshness / bundle utility (shared)
# ---------------------------------------------------------------------------

def require_governed(bundle: Optional[PromotionEvidenceBundle]) -> bool:
    return bundle is not None and isinstance(bundle, PromotionEvidenceBundle)
