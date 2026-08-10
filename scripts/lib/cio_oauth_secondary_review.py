"""
Gate-B: OAuth Secondary Review Process Registration.

The legacy Grok+ChatGPT dual-consensus path is converted into a separately
registered secondary-review process. This review may challenge Alex.
It does not become Alex, and it is never invoked merely because DeepSeek failed.

Required trigger reasons:
  - MATERIAL_SPECIALIST_DISAGREEMENT
  - HERMES_CONTRADICTION
  - HIGH_CONSEQUENCE_RECOMMENDATION
  - WEEKLY_QA_SAMPLE
  - OPERATOR_REQUESTED_SECOND_OPINION

Required artifact:
  - secondary_review_id
  - parent_run_id
  - trigger_reason
  - primary_artifact_id
  - snapshot_hash
  - provider/model provenance
  - agree | disagree | inconclusive
  - analysis
  - limitations
  - cost/accounting provenance
  - artifact_hash
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class SecondaryReviewTrigger(Enum):
    """Authorized trigger reasons for OAuth secondary review."""
    MATERIAL_SPECIALIST_DISAGREEMENT = "MATERIAL_SPECIALIST_DISAGREEMENT"
    HERMES_CONTRADICTION = "HERMES_CONTRADICTION"
    HIGH_CONSEQUENCE_RECOMMENDATION = "HIGH_CONSEQUENCE_RECOMMENDATION"
    WEEKLY_QA_SAMPLE = "WEEKLY_QA_SAMPLE"
    OPERATOR_REQUESTED_SECOND_OPINION = "OPERATOR_REQUESTED_SECOND_OPINION"


class ReviewDisposition(Enum):
    """Possible dispositions of a secondary review."""
    AGREE = "agree"
    DISAGREE = "disagree"
    INCONCLUSIVE = "inconclusive"


def create_secondary_review_artifact(
    *,
    parent_run_id: str,
    trigger_reason: SecondaryReviewTrigger,
    primary_artifact_id: str,
    snapshot_hash: str,
    disposition: ReviewDisposition,
    analysis: str,
    limitations: list[str],
    provider: str,
    model: str,
    cost_usd: float,
    process_id: str = "oauth_secondary_review",
) -> dict[str, Any]:
    """Create a secondary review artifact with full provenance.

    Must NOT be invoked merely because DeepSeek failed.
    Must be explicitly triggered by registered trigger reasons only.
    """
    artifact_id = f"sec-review-{hashlib.md5(f'{parent_run_id}:{trigger_reason.value}'.encode()).hexdigest()[:12]}"

    artifact = {
        "secondary_review_id": artifact_id,
        "parent_run_id": parent_run_id,
        "trigger_reason": trigger_reason.value,
        "primary_artifact_id": primary_artifact_id,
        "snapshot_hash": snapshot_hash,
        "disposition": disposition.value,
        "analysis": analysis,
        "limitations": limitations,
        "provenance": {
            "process_id": process_id,
            "provider": provider,
            "model": model,
            "not_automatic_fallback": True,
            "trigger_required": True,
        },
        "cost": {
            "usd": round(cost_usd, 6),
            "accounted_via": "llm_consumption",
        },
        "artifact_hash": hashlib.sha256(
            f"{artifact_id}:{parent_run_id}:{disposition.value}:{analysis[:100]}".encode()
        ).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return artifact


def validate_trigger_reason(reason: str) -> bool:
    """Validate that a trigger reason is authorized for secondary review.
    
    Secondary review is NEVER triggered by DeepSeek failure.
    """
    try:
        SecondaryReviewTrigger(reason)
        return True
    except ValueError:
        return False
