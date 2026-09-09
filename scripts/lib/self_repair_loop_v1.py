"""Lane J — human-governed bounded self-repair loop (non-financial).

detect → diagnose → propose → isolated branch → tests → PR → native approval →
deploy → verify → close|rollback

Recommendation ≠ mutation. No autonomous bypass of guard / branch protection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib
import json


NO_CONSUMER_REASON = (
    "maturity-gap-closure-20260909 hermetic lane helpers; serving-SHA producers/"
    "consumers await merge+promote+operator grants (telegram/service/drive). "
    "Zero live consumers is correct until then — not a silent dark contract "
    "(MBI_BEHAVIOR=0; recommendation≠mutation)."
)

SCHEMA = "SelfRepairLoop@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MAX_SCOPE = "non_financial_ops_only"


@dataclass
class RepairProposal:
    proposal_id: str
    signal: str
    diagnosis: str
    recommended_action: str
    scope: str = MAX_SCOPE
    executable: bool = False
    requires_native_grant: str | None = None
    financial_surface_reachable: bool = False
    source_sha: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "proposal_id": self.proposal_id,
            "signal": self.signal,
            "diagnosis": self.diagnosis,
            "recommended_action": self.recommended_action,
            "scope": self.scope,
            "executable": self.executable,
            "requires_native_grant": self.requires_native_grant,
            "financial_surface_reachable": self.financial_surface_reachable,
            "production_mutation": False,
            "authority": AUTHORITY,
            "source_sha": self.source_sha,
            "evidence": dict(self.evidence),
            "produced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def detect_poller_identity_drift(report: dict[str, Any]) -> RepairProposal | None:
    """Real runtime signal: poller cwd ≠ CURRENT or deleted interpreter class."""
    if report.get("matches_current") is True:
        return None
    digest = hashlib.sha256(json.dumps(report, sort_keys=True, default=str).encode()).hexdigest()
    return RepairProposal(
        proposal_id=f"sr_{digest[:20]}",
        signal="poller_identity_mismatch",
        diagnosis=str(report.get("mismatch_reason") or "cwd_ne_current"),
        recommended_action="run recycle_telegram_poller.sh after service/process-recycle grant; verify /proc/cwd",
        requires_native_grant="service",
        executable=False,
        source_sha=str(report.get("current_source_commit") or ""),
        evidence=dict(report),
    )


def verify_effect(*, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Effect verify for a completed recycle — no mutation here."""
    passed = after.get("matches_current") is True and before.get("matches_current") is False
    return {
        "schema_version": "SelfRepairVerify@v1",
        "passed": passed,
        "rollback_recommended": not passed,
        "before_matches": before.get("matches_current"),
        "after_matches": after.get("matches_current"),
    }
