"""Research governance — governed receipts + canonical promotion bundle (PR-R1).

The single most important architectural invariant of this subsystem:

    A typed, self-hashed result is NOT evidence provenance.
    A receipt is NOT provenance because it is named "receipt".

Three independent trust properties are enforced here:

  1. **A result is governed only when a trusted producer computes it.** A bare
     typed result (even with a valid self-digest) is rejected. A caller must not
     be able to submit a finished statistical answer for certification — the
     sanctioned paths are method-specific producers that invoke the actual
     statistical implementation from raw inputs (see `producers.py`).

  2. **Producer code identity represents CODE, not a version label.**
     ``producer_code_sha`` is ``sha256(actual producer module source bytes)``, so
     changing an implementation while keeping the same module/version string
     necessarily changes the producer identity.

  3. **Receipts are ISSUED, not self-certified.** Every receipt is HMAC-signed by
     an in-process trusted ``ReceiptAuthority`` that owns an opaque key. A caller
     can recompute the public payload digest but cannot produce a valid signature,
     so recomputing public fields cannot forge issuer provenance.

Durable append-only persistence remains deferred; R1 keeps the issuer boundary
in-process and injectable.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .enums import VerificationStatus
from .models import FrozenDict, canonical_json, _stable_hash
from .results import (
    DSRResult,
    MethodApplicability,
    MethodRequirement,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    RobustnessResult,
)

# ---------------------------------------------------------------------------
# Trusted issuer boundary (P0-3)
# ---------------------------------------------------------------------------

DEFAULT_ISSUER_ID = "r1-receipt-authority"


class ReceiptAuthority:
    """In-process trusted issuer/verifier boundary for receipts.

    Owns an opaque HMAC key. ``sign`` is the issuing capability; ``verify`` is the
    public check. Receipt authenticity therefore depends on the authority, not on
    recomputing a public payload digest. A caller that recreates the public fields
    cannot recreate a valid ``signature``.
    """

    def __init__(self, key: Optional[bytes] = None, issuer_id: str = DEFAULT_ISSUER_ID) -> None:
        self._key = key if key is not None else secrets.token_bytes(32)
        self.issuer_id = issuer_id

    def sign(self, payload: dict) -> str:
        """HMAC-SHA256 signature over a canonical payload dict."""
        return hmac.new(self._key, canonical_json(payload).encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def verify(self, payload: dict, signature: Optional[str],
               issuer_id: Optional[str] = None) -> bool:
        if not signature or not isinstance(signature, str):
            return False
        if issuer_id is not None and issuer_id != self.issuer_id:
            return False
        expected = self.sign(payload)
        return hmac.compare_digest(expected, signature)


# The single trusted issuer used by producers and the registry. Test code may
# replace it via `set_authority()` for isolated fixtures.
AUTHORITY = ReceiptAuthority()


def set_authority(authority: ReceiptAuthority) -> None:
    """Replace the module-level trusted authority (test injection only)."""
    global AUTHORITY
    AUTHORITY = authority


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sha256(value: Optional[str]) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


# ---------------------------------------------------------------------------
# Producer code identity (P0-2) — the SOURCE, not a label
# ---------------------------------------------------------------------------

# Canonical producer identity per statistical method. `producer_code_sha` is the
# sha256 of the ACTUAL producer module source bytes (never a module/version label).
PRODUCER_REGISTRY: dict[str, str] = {
    "deflated_sharpe": "deflated_sharpe.py",
    "cscv_pbo": "pbo.py",
    "white_reality_check": "bootstrap_reality_check.py",
    "bonferroni": "multiple_testing.py",
    "holm": "multiple_testing.py",
    "bh_fdr": "multiple_testing.py",
    "robustness": "robustness.py",
}

PRODUCER_MODULE_NAMES: dict[str, str] = {
    "deflated_sharpe": "research_governance.deflated_sharpe",
    "cscv_pbo": "research_governance.pbo",
    "white_reality_check": "research_governance.bootstrap_reality_check",
    "bonferroni": "research_governance.multiple_testing",
    "holm": "research_governance.multiple_testing",
    "bh_fdr": "research_governance.multiple_testing",
    "robustness": "research_governance.robustness",
}


def producer_source_digest(method: str) -> str:
    """sha256 of the actual producer module SOURCE BYTES (P0-2).

    This binds receipts to the implementation content, not to a metadata label. A
    code change with an unchanged version string therefore changes the digest.
    """
    if method not in PRODUCER_REGISTRY:
        raise ValueError(f"unknown governed method: {method!r}")
    fname = PRODUCER_REGISTRY[method]
    path = Path(__file__).resolve().parent / fname
    return hashlib.sha256(path.read_bytes()).hexdigest()


def producer_module_name(method: str) -> str:
    if method not in PRODUCER_REGISTRY:
        raise ValueError(f"unknown governed method: {method!r}")
    return PRODUCER_MODULE_NAMES[method]


def producer_code_sha(method: str) -> str:
    """Canonical producer-code identity for a method (raises if unknown).

    Backward-compatible alias for :func:`producer_source_digest` — the value is the
    source-bytes digest, NOT a module/version label hash.
    """
    return producer_source_digest(method)


# ---------------------------------------------------------------------------
# Governed result receipt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GovernedResultReceipt:
    """Immutable receipt binding a governed function output to exact inputs.

    ``result_payload_hash`` == the typed result's canonical ``result_digest``.
    ``output_artifact_hash`` == the hash of the governed function's output bytes.
    ``input_artifact_hash`` == the canonical digest of the governed inputs.
    ``signature`` == the trusted issuer's HMAC over ``payload()``.
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
    producer_code_sha: str
    input_artifact_hash: str
    output_artifact_hash: str
    result_payload_hash: str
    generated_at: str
    producer_version: str = "1.0"
    producer_git_sha: Optional[str] = None
    verification_status: str = VerificationStatus.VERIFIED.value
    verifier_id: str = "governed-producer"
    issuer_id: Optional[str] = None
    signature: Optional[str] = None
    receipt_digest: Optional[str] = None

    def payload(self) -> dict:
        """Canonical payload that is signed and self-digested (no meta fields)."""
        return {
            "receipt_id": self.receipt_id, "method": self.method,
            "hypothesis_id": self.hypothesis_id, "protocol_hash": self.protocol_hash,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash, "code_sha": self.code_sha,
            "producer_module": self.producer_module,
            "producer_version": self.producer_version,
            "producer_git_sha": self.producer_git_sha,
            "producer_code_sha": self.producer_code_sha,
            "input_artifact_hash": self.input_artifact_hash,
            "output_artifact_hash": self.output_artifact_hash,
            "result_payload_hash": self.result_payload_hash,
            "generated_at": self.generated_at,
            "verification_status": self.verification_status,
            "verifier_id": self.verifier_id,
            "issuer_id": self.issuer_id,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.payload())

    def verify(self) -> bool:
        """True only if self-digest matches AND the trusted issuer's signature is valid."""
        if self.receipt_digest is None or self.receipt_digest != self.compute_digest():
            return False
        return AUTHORITY.verify(self.payload(), self.signature, self.issuer_id)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.verification_status != VerificationStatus.VERIFIED.value:
            problems.append(f"verification_status != VERIFIED: {self.verification_status!r}")
        if self.method not in PRODUCER_REGISTRY:
            problems.append(f"unknown governed method: {self.method!r}")
        else:
            if self.producer_module != producer_module_name(self.method):
                problems.append(
                    f"producer_module {self.producer_module!r} != expected "
                    f"{producer_module_name(self.method)!r}")
            if self.producer_code_sha != producer_source_digest(self.method):
                problems.append(
                    "producer_code_sha does not match the actual producer source bytes")
        if self.output_artifact_hash != self.result_payload_hash:
            problems.append("output_artifact_hash != result_payload_hash")
        # The input artifact is the FULL raw canonical input the producer consumed
        # (identity + statistical raw inputs). It must be a present, well-formed
        # sha256 digest; the producer computes it from a single frozen input
        # dataclass, so a caller cannot bind a result to one identity while
        # hashing different inputs.
        if not _is_sha256(self.input_artifact_hash):
            problems.append("input_artifact_hash is not a valid sha256 digest")
        if not self.receipt_digest:
            problems.append("missing receipt_digest")
        if self.issuer_id != AUTHORITY.issuer_id:
            problems.append("issuer_id does not match the trusted authority")
        if not AUTHORITY.verify(self.payload(), self.signature, self.issuer_id):
            problems.append("receipt signature is not valid for the trusted issuer")
        return problems

    def binds_result(self, result: Any) -> bool:
        """True if this receipt's payload hash matches the typed result digest."""
        return result.result_digest == self.result_payload_hash


@dataclass(frozen=True)
class GovernedResult:
    """A typed statistical result paired with its governed receipt."""

    receipt: GovernedResultReceipt
    result: Any  # a frozen typed result object (DSR/PBO/MT/RC/Robustness)


def _build_receipt(method: str, result: Any, *, input_artifact: Any,
                   authority: Optional[ReceiptAuthority] = None,
                   generated_at: Optional[str] = None) -> GovernedResultReceipt:
    authority = authority or AUTHORITY
    receipt = GovernedResultReceipt(
        receipt_id=f"rcpt-{method}-{result.result_id}",
        method=method,
        hypothesis_id=result.hypothesis_id,
        protocol_hash=result.protocol_hash,
        trial_family_id=result.trial_family_id,
        family_definition_hash=result.family_definition_hash,
        dataset_hash=result.dataset_hash or "",
        code_sha=result.code_sha or "",
        producer_module=producer_module_name(method),
        producer_code_sha=producer_source_digest(method),
        input_artifact_hash=_stable_hash(input_artifact),
        output_artifact_hash=result.result_digest,
        result_payload_hash=result.result_digest,
        generated_at=generated_at or _now_iso(),
        issuer_id=authority.issuer_id,
    )
    receipt = replace(receipt, signature=authority.sign(receipt.payload()))
    receipt = replace(receipt, receipt_digest=receipt.compute_digest())
    return receipt


def governed_result(result: Any, *, input_artifact: Any,
                    generated_at: Optional[str] = None) -> GovernedResult:
    """Wrap a typed result in an UNSIGNED receipt (NON-PROMOTABLE / test-only).

    This generic wrapper does NOT invoke any governed statistical implementation and
    does NOT produce issuer-authenticated provenance. It exists only so negative
    tests can construct a "self-digested typed result" that the promotion gate MUST
    reject. A Grade A/B promotion requires a signed, producer-issued receipt.
    """
    if getattr(result, "result_digest", None) is None:
        from .results import finalize
        result = finalize(result)
    method = getattr(result, "method", "robustness")
    if method not in PRODUCER_REGISTRY:
        raise ValueError(f"unknown governed method: {method!r}")
    receipt = GovernedResultReceipt(
        receipt_id=f"rcpt-{method}-{result.result_id}",
        method=method,
        hypothesis_id=result.hypothesis_id,
        protocol_hash=result.protocol_hash,
        trial_family_id=result.trial_family_id,
        family_definition_hash=result.family_definition_hash,
        dataset_hash=result.dataset_hash or "",
        code_sha=result.code_sha or "",
        producer_module=producer_module_name(method),
        producer_code_sha=producer_source_digest(method),
        input_artifact_hash=_stable_hash(input_artifact),
        output_artifact_hash=result.result_digest,
        result_payload_hash=result.result_digest,
        generated_at=generated_at or _now_iso(),
        # Deliberately UNSIGNED and issued by "caller" — not the trusted authority.
        issuer_id="caller-unsigned",
        signature=None,
    )
    receipt = replace(receipt, receipt_digest=receipt.compute_digest())
    return GovernedResult(receipt=receipt, result=result)


def issue_governed_receipt(method: str, result: Any, *, input_artifact: Any,
                           authority: Optional[ReceiptAuthority] = None) -> GovernedResult:
    """Issue a SIGNED governed receipt for a producer-computed typed result.

    This is the sanctioned path used by method-specific producers. It signs the
    receipt through the trusted authority so it carries real issuer provenance.
    """
    if getattr(result, "result_digest", None) is None:
        from .results import finalize
        result = finalize(result)
    receipt = _build_receipt(method, result, input_artifact=input_artifact,
                             authority=authority)
    return GovernedResult(receipt=receipt, result=result)


# ---------------------------------------------------------------------------
# Frozen trial family receipt (immutable definition)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrozenTrialFamilyReceipt:
    """Deeply immutable snapshot of a frozen trial family DEFINITION.

    Issuer-authenticated: ``verify()`` requires both a matching definition digest
    and a valid trusted-issuer signature.
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
    issuer_id: Optional[str] = None
    signature: Optional[str] = None

    def definition_payload(self) -> dict:
        """The pure definition fields (issuer-independent) that ``definition_digest`` covers."""
        return {
            "family_id": self.family_id, "hypothesis_id": self.hypothesis_id,
            "protocol_hash": self.protocol_hash,
            "family_definition_hash": self.family_definition_hash,
            "confirmatory": self.confirmatory,
            "planned_trial_ids": list(self.planned_trial_ids),
            "planned_config_hashes": self.planned_config_hashes.to_dict(),
            "frozen_at": self.frozen_at,
        }

    def payload(self) -> dict:
        """Signing payload: the definition fields PLUS the issuer identity."""
        p = self.definition_payload()
        p["issuer_id"] = self.issuer_id
        return p

    def compute_definition_digest(self) -> str:
        return _stable_hash(self.definition_payload())

    def verify(self) -> bool:
        if self.definition_digest != self.compute_definition_digest():
            return False
        return AUTHORITY.verify(self.payload(), self.signature, self.issuer_id)


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
    issuer_id: Optional[str] = None
    signature: Optional[str] = None
    receipt_digest: Optional[str] = None

    def payload(self) -> dict:
        return {
            "family_id": self.family_id, "complete": self.complete,
            "planned_trial_count": self.planned_trial_count,
            "recorded_trial_count": self.recorded_trial_count,
            "terminal_counts": self.terminal_counts.to_dict(),
            "definition_digest": self.definition_digest,
            "generated_at": self.generated_at,
            "issuer_id": self.issuer_id,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.payload())

    def verify(self) -> bool:
        if self.receipt_digest is None or self.receipt_digest != self.compute_digest():
            return False
        return AUTHORITY.verify(self.payload(), self.signature, self.issuer_id)


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
    issuer_id: Optional[str] = None
    signature: Optional[str] = None
    receipt_digest: Optional[str] = None

    def payload(self) -> dict:
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
            "issuer_id": self.issuer_id,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.payload())

    def verify(self) -> bool:
        if self.receipt_digest is None or self.receipt_digest != self.compute_digest():
            return False
        return AUTHORITY.verify(self.payload(), self.signature, self.issuer_id)


def sign_receipt(receipt: Any, authority: Optional[ReceiptAuthority] = None) -> Any:
    """Return a copy of a receipt signed by the trusted authority."""
    authority = authority or AUTHORITY
    signed = replace(receipt, issuer_id=authority.issuer_id)
    signed = replace(signed, signature=authority.sign(signed.payload()))
    if hasattr(signed, "receipt_digest"):
        signed = replace(signed, receipt_digest=signed.compute_digest())
    return signed


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
                problems.append("frozen_family_receipt does not verify (digest or issuer signature)")
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

        # Registry completeness receipt (P0-4: binds the EXACT frozen definition).
        if not self.registry_completeness_receipt:
            problems.append("missing registry_completeness_receipt")
        else:
            rc = self.registry_completeness_receipt
            if not rc.verify():
                problems.append("registry_completeness_receipt does not verify (digest or issuer signature)")
            if rc.complete is not True:
                problems.append("registry_completeness_receipt.complete is not True")
            if rc.family_id != self.trial_family_id:
                problems.append("completeness receipt family_id != bundle trial_family_id")
            if self.frozen_family_receipt:
                if rc.definition_digest != self.frozen_family_receipt.definition_digest:
                    problems.append(
                        "completeness receipt definition_digest != frozen family definition_digest")
                if rc.planned_trial_count != len(self.frozen_family_receipt.planned_trial_ids):
                    problems.append(
                        "completeness receipt planned_trial_count != len(frozen planned_trial_ids)")
                if rc.complete is True and rc.recorded_trial_count != rc.planned_trial_count:
                    problems.append(
                        "completeness receipt recorded_trial_count != planned_trial_count when complete")
                if sum(rc.terminal_counts.values()) != rc.recorded_trial_count:
                    problems.append(
                        "completeness receipt terminal_counts sum != recorded_trial_count")

        # OOS receipt (P0-6: binds the exact bundle dataset + confirmatory fields).
        if not self.oos_receipt:
            problems.append("missing oos_receipt")
        else:
            o = self.oos_receipt
            if not o.verify():
                problems.append("oos_receipt does not verify (digest or issuer signature)")
            if o.untouched is not True:
                problems.append("oos_receipt.untouched is not True (consumed/rerun)")
            if o.trial_family_id != self.trial_family_id:
                problems.append("oos receipt trial_family_id != bundle")
            if o.protocol_hash != self.protocol_hash:
                problems.append("oos receipt protocol_hash != bundle")
            if o.family_definition_hash != self.family_definition_hash:
                problems.append("oos receipt family_definition_hash != bundle")
            if o.dataset_hash != self.dataset_hash:
                problems.append("oos receipt dataset_hash != bundle dataset_hash")
            for field in ("dataset_id", "dataset_hash", "segment_start", "segment_end"):
                if not getattr(o, field, ""):
                    problems.append(f"oos receipt has blank {field} (confirmatory OOS requires it)")

        # Cross-result identity: every child receipt + result must match the bundle.
        for name, gr in self._child_entries():
            if gr is None:
                continue
            if not isinstance(gr, GovernedResult):
                problems.append(f"{name} must be a governed result (bare typed/dict rejected)")
                continue
            r = gr.receipt
            if not r.verify():
                problems.append(f"{name} receipt does not verify (digest or issuer signature)")
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
            # P0-5: multiple-testing must bind the EXACT frozen trial/config family.
            if name == "multiple_testing" and self.frozen_family_receipt:
                fr = self.frozen_family_receipt
                mt = res
                if tuple(getattr(mt, "tested_trial_ids", ())) != tuple(fr.planned_trial_ids):
                    problems.append(
                        "multiple_testing tested_trial_ids != frozen planned_trial_ids")
                want_hashes = tuple(fr.planned_config_hashes[tid]
                                    for tid in fr.planned_trial_ids)
                if tuple(getattr(mt, "tested_config_hashes", ())) != want_hashes:
                    problems.append(
                        "multiple_testing tested_config_hashes != frozen planned_config_hashes")
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
