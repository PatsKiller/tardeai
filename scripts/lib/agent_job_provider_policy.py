"""Canonical provider lane for queued agent intelligence.

Automatic queue work is DeepSeek Flash FIRST via existing llm_router.
OAuth (Grok/ChatGPT) is explicit fallback / manual / challenge — it must not
preempt Flash because a symbol is a holding or top-N WAIT.

Do not invent a second DeepSeek router. Do not print secrets.
READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import os
from typing import Any

POLICY_FLASH_FIRST_AUTO_QUEUE = "FLASH_FIRST_AUTO_QUEUE"
POLICY_OAUTH_MANUAL = "OAUTH_MANUAL_OPERATOR"
POLICY_OAUTH_CHALLENGE = "OAUTH_CHALLENGE"
POLICY_OAUTH_SOFT_FALLBACK = "OAUTH_SOFT_FALLBACK_AFTER_FLASH"

LANE_AUTO_QUEUE = "AUTO_QUEUE"
LANE_MANUAL_OPERATOR = "MANUAL_OPERATOR"
LANE_CHALLENGE = "CHALLENGE"

CHALLENGE_REQUEST_TYPES = frozenset({
    "challenge",
    "oauth_challenge",
    "cross_check",
    "high_quality_challenge",
})

# Explicit operator/manual enqueue sources. Overnight batch historically used
# submitted_from='command_center' for automatic holdings refresh — that is AUTO_QUEUE.
EXPLICIT_MANUAL_SOURCES = frozenset({
    "watchlist_requeue",
    "api",
    "operator_telegram",
    "cio_telegram",
    "operator",
})

HARD_FAILURE_MARKERS = (
    "COST_CONFIGURATION_INVALID",
    "POLICY_NOT_ALLOWED",
    "BUDGET_EXHAUSTED",
    "GLOBAL_CAP",
    "missing global",
    "credential governance",
    "HARD_POLICY_FAILURE",
)

TRUTHY = {"1", "true", "yes", "on"}


def _truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in TRUTHY


def classify_job_lane(
    *,
    submitted_from: str | None = None,
    request_type: str | None = None,
    priority: int | None = None,
    payload: dict[str, Any] | None = None,
    explicit_lane: str | None = None,
) -> str:
    """Return AUTO_QUEUE | MANUAL_OPERATOR | CHALLENGE. Encoded in code, not prompt prose."""
    payload = payload or {}
    lane = str(
        explicit_lane
        or payload.get("provider_lane")
        or os.environ.get("AGENT_JOB_PROVIDER_LANE")
        or ""
    ).strip().upper()
    if lane in {LANE_CHALLENGE, "OAUTH_CHALLENGE"}:
        return LANE_CHALLENGE
    if lane in {LANE_MANUAL_OPERATOR, "OAUTH", "OAUTH_MANUAL"}:
        return LANE_MANUAL_OPERATOR
    rt = str(request_type or "").strip().lower()
    if rt in CHALLENGE_REQUEST_TYPES:
        return LANE_CHALLENGE
    src = str(submitted_from or "").strip().lower()
    if src in EXPLICIT_MANUAL_SOURCES:
        return LANE_MANUAL_OPERATOR
    if src == "command_center":
        # High-priority time-sensitive CC clicks can be manual; scheduled CC dumps are auto.
        try:
            p = int(priority) if priority is not None else 99
        except (TypeError, ValueError):
            p = 99
        if p <= 0 or rt in CHALLENGE_REQUEST_TYPES:
            return LANE_MANUAL_OPERATOR
        return LANE_AUTO_QUEUE
    return LANE_AUTO_QUEUE


def requested_provider_policy(lane: str) -> str:
    if lane == LANE_CHALLENGE:
        return POLICY_OAUTH_CHALLENGE
    if lane == LANE_MANUAL_OPERATOR:
        # Manual remains configurable; default Flash-first unless operator asks for OAuth.
        if _truthy("AGENT_JOB_MANUAL_OAUTH_FIRST", "0"):
            return POLICY_OAUTH_MANUAL
        return POLICY_FLASH_FIRST_AUTO_QUEUE
    return POLICY_FLASH_FIRST_AUTO_QUEUE


def oauth_may_preempt_flash(lane: str) -> bool:
    """OAuth runs before llm_router only for explicit challenge, or manual-OAuth-first."""
    if lane == LANE_CHALLENGE:
        return True
    if lane == LANE_MANUAL_OPERATOR and _truthy("AGENT_JOB_MANUAL_OAUTH_FIRST", "0"):
        return True
    if _truthy("AGENT_JOB_OAUTH_LANE", "0"):
        return True
    return False


def is_hard_policy_failure(error: str | None) -> bool:
    text = str(error or "")
    up = text.upper()
    return any(m.upper() in up or m in text for m in HARD_FAILURE_MARKERS)


def oauth_soft_fallback_permitted(lane: str, error: str | None) -> bool:
    """Temporary network/provider failure may use OAuth; hard policy failures must not."""
    if is_hard_policy_failure(error):
        return False
    if lane == LANE_CHALLENGE:
        return True
    # Default on: free OAuth as explicit SOFT fallback after Flash failure.
    return _truthy("AGENT_JOB_OAUTH_SOFT_FALLBACK", "1")


def first_provider_attempt(lane: str) -> str:
    if oauth_may_preempt_flash(lane):
        return "grok-oauth"
    return "deepseek-v4-flash"
