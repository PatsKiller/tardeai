"""L3 model policy — DeepSeek Flash author, separated critic, off-peak rails.

Operator campaign policy:
  - DeepSeek V4.1 Flash (`deepseek-flash`) is the preferred judgment author.
  - Prefer off-peak unless a deterministic urgent-materiality rule fires.
  - No local model may silently substitute as the L3 author.
  - Returned provider/model identity must match the approved registry entry.
  - Critic must use a different provider from the author.

Off-peak schedule is loaded from an operator-readable config when present.
Default proposal (America/New_York, DST-safe) lives beside this module's
tests and in EVIDENCE; Claude Lane A decides/applies production config via SFR.
config/** is Lane A exclusive — this module never writes it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from scripts.lib.deepseek_offpeak import (
    ET,
    is_bulk_deepseek_window,
    is_deepseek_peak_utc,
)
from scripts.lib.llm_model_registry import (
    EXACT_DEEPSEEK_MODELS,
    RegistryError,
    deepseek_model_id,
    reject_legacy_model_id,
)

AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

# Proposed operator-readable config path (Lane A applies to production).
PROPOSED_OFFPEAK_CONFIG_REL = "config/l3_judgment_offpeak.json"

# Default proposal — documented, tested, not buried only in opaque constants.
DEFAULT_OFFPEAK_PROPOSAL: dict[str, Any] = {
    "schema": "L3OffPeakPolicy@v1",
    "timezone": "America/New_York",
    "bulk_window_et": {"start_hour": 10, "end_hour_exclusive": 21},
    "deepseek_official_peak_utc_weekdays": [["01:00", "04:00"], ["06:00", "10:00"]],
    "weekend_official_peak": False,
    "urgent_exception": {
        "requires_trigger": "urgent",
        "deterministic_rules": [
            "material_residual_present",
            "resolution_confidence_gte_0.8",
            "selected_memory_facts_gte_1",
            "free_first_exhausted",
            "materiality_basis_in_allowlist",
        ],
        "materiality_basis_allowlist": [
            "price_move_gt_threshold",
            "earnings_within_horizon",
            "operator_escalation_flag",
            "commitment_falsifier_imminent",
        ],
        "note": "Caller prose alone is never sufficient for urgent exception.",
    },
    "author": {
        "provider": "deepseek",
        "logical_policy": "FAST",
        "exact_model_id": "deepseek-flash",
        "local_substitute_forbidden": True,
    },
    "critic": {
        "preferred_providers": ["grok", "chatgpt", "anthropic"],
        "forbidden_same_as_author": True,
        "default_provider": "grok",
        "default_model": "grok-3-mini",
    },
}


@dataclass(frozen=True)
class L3ModelPolicy:
    author_provider: str = "deepseek"
    author_logical_policy: str = "FAST"
    author_model_id: str = "deepseek-flash"
    critic_provider: str = "grok"
    critic_model: str = "grok-3-mini"
    local_substitute_forbidden: bool = True
    min_resolution_confidence: float = 0.5
    allowed_subject_kinds: frozenset[str] = frozenset({"security", "thesis", "portfolio", "operator_topic"})
    research_only_question_classes: frozenset[str] = frozenset({"research_only_v1"})
    min_selected_facts: int = 1
    min_decay_weight_for_selection: float = 0.01
    min_evidence_freshness_decay: float = 0.01
    max_fact_age_hours: float = 24.0 * 90
    # Lane B may emit digest-only facts (include_fact_text=False). Model authoring
    # requires fact_text on at least one selected fact unless research_only.
    require_fact_text_for_model: bool = True
    memory_policy_version: str = "memory_policy@v1"
    prompt_template_version: str = "l3_judgment_author@v1"
    model_registry_version: str = "llm_model_registry@v1"
    urgent_materiality_bases: frozenset[str] = frozenset(
        {
            "price_move_gt_threshold",
            "earnings_within_horizon",
            "operator_escalation_flag",
            "commitment_falsifier_imminent",
        }
    )
    offpeak_config: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_OFFPEAK_PROPOSAL))


@dataclass
class OffPeakDecision:
    eligible: bool
    reason: str
    in_bulk_et: bool
    in_official_peak_utc: bool
    timezone: str = "America/New_York"

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "in_bulk_et": self.in_bulk_et,
            "in_official_peak_utc": self.in_official_peak_utc,
            "timezone": self.timezone,
        }


def load_offpeak_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load operator config if present; else return the governed proposal default."""
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    env = (os.environ.get("TRADEAI_L3_OFFPEAK_CONFIG") or "").strip()
    if env:
        candidates.append(Path(env))
    # Repo-relative proposal path (may not exist until Lane A applies).
    root = Path(__file__).resolve().parents[2]
    candidates.append(root / PROPOSED_OFFPEAK_CONFIG_REL)

    for cand in candidates:
        try:
            if cand.is_file():
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("schema") == "L3OffPeakPolicy@v1":
                    return data
        except (OSError, json.JSONDecodeError):
            continue
    return dict(DEFAULT_OFFPEAK_PROPOSAL)


def default_l3_policy(*, config_path: str | Path | None = None) -> L3ModelPolicy:
    cfg = load_offpeak_config(config_path)
    author = cfg.get("author") if isinstance(cfg.get("author"), Mapping) else {}
    critic = cfg.get("critic") if isinstance(cfg.get("critic"), Mapping) else {}
    urgent = cfg.get("urgent_exception") if isinstance(cfg.get("urgent_exception"), Mapping) else {}
    allow = urgent.get("materiality_basis_allowlist") or list(
        DEFAULT_OFFPEAK_PROPOSAL["urgent_exception"]["materiality_basis_allowlist"]
    )
    try:
        flash_id = deepseek_model_id("FAST")
    except RegistryError:
        flash_id = "deepseek-flash"
    return L3ModelPolicy(
        author_provider=str(author.get("provider") or "deepseek"),
        author_logical_policy=str(author.get("logical_policy") or "FAST"),
        author_model_id=str(author.get("exact_model_id") or flash_id),
        critic_provider=str(critic.get("default_provider") or "grok"),
        critic_model=str(critic.get("default_model") or "grok-3-mini"),
        local_substitute_forbidden=bool(author.get("local_substitute_forbidden", True)),
        urgent_materiality_bases=frozenset(str(x) for x in allow),
        offpeak_config=cfg,
    )


def evaluate_offpeak_eligibility(
    when: datetime | None = None,
    *,
    policy: L3ModelPolicy | None = None,
) -> OffPeakDecision:
    """Eligible when inside operator bulk ET window and outside official UTC peak."""
    policy = policy or default_l3_policy()
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Prefer shared deepseek_offpeak helpers (DST-safe via zoneinfo).
    in_bulk = is_bulk_deepseek_window(dt)
    # is_bulk already excludes official peak; expose components for evidence.
    in_peak = is_deepseek_peak_utc(dt)
    in_bulk_et_only = False
    et = dt.astimezone(ET)
    cfg = policy.offpeak_config or DEFAULT_OFFPEAK_PROPOSAL
    bulk = cfg.get("bulk_window_et") or {}
    start = int(bulk.get("start_hour", 10))
    end = int(bulk.get("end_hour_exclusive", 21))
    hour = et.hour + et.minute / 60.0 + et.second / 3600.0
    in_bulk_et_only = start <= hour < end

    if in_bulk:
        return OffPeakDecision(
            eligible=True,
            reason="offpeak_bulk_window",
            in_bulk_et=in_bulk_et_only,
            in_official_peak_utc=in_peak,
        )
    if in_peak:
        reason = "official_deepseek_peak_utc"
    elif not in_bulk_et_only:
        reason = "outside_operator_bulk_et"
    else:
        reason = "not_bulk_eligible"
    return OffPeakDecision(
        eligible=False,
        reason=reason,
        in_bulk_et=in_bulk_et_only,
        in_official_peak_utc=in_peak,
    )


def evaluate_urgent_materiality(
    grounded: Mapping[str, Any],
    *,
    policy: L3ModelPolicy | None = None,
) -> tuple[bool, list[str]]:
    """Deterministic urgent exception — never based on free-form caller text alone."""
    policy = policy or default_l3_policy()
    reasons: list[str] = []
    mrq = grounded.get("material_residual_question") or {}
    if not bool(mrq.get("present")):
        return False, ["urgent_missing_material_residual"]
    subject = grounded.get("subject") or {}
    try:
        conf = float(subject.get("resolution_confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < 0.8:
        reasons.append("urgent_resolution_confidence_lt_0.8")
    facts = grounded.get("memory_facts") or []
    if not facts:
        reasons.append("urgent_no_memory_facts")
    research = grounded.get("research") or {}
    if research.get("free_first_exhausted") is not True:
        reasons.append("urgent_free_first_not_exhausted")
    basis = str(mrq.get("materiality_basis") or "").strip()
    if basis not in policy.urgent_materiality_bases:
        reasons.append("urgent_materiality_basis_not_allowlisted")
    # Explicitly ignore narrative-only urgency.
    if mrq.get("urgency_prose") and not basis:
        reasons.append("urgent_prose_without_basis")
    return (not reasons), reasons


def resolve_author_model(policy: L3ModelPolicy | None = None) -> dict[str, str]:
    policy = policy or default_l3_policy()
    mid = policy.author_model_id
    reject_legacy_model_id(mid)
    if mid not in EXACT_DEEPSEEK_MODELS:
        raise RegistryError(f"L3 author model not exact DeepSeek Flash: {mid!r}")
    # Re-check registry binding for FAST.
    bound = deepseek_model_id(policy.author_logical_policy)
    if bound != mid and mid != bound:
        # Prefer registry truth when env override differs — still must be exact Flash.
        reject_legacy_model_id(bound)
        mid = bound
    return {
        "provider": policy.author_provider,
        "logical_policy": policy.author_logical_policy,
        "model_id": mid,
    }


def validate_returned_model(
    *,
    requested_model: str,
    returned_model: str | None,
    provider: str = "deepseek",
) -> None:
    """Mismatch is fail-closed — never accept as judgment."""
    req = (requested_model or "").strip()
    got = (returned_model or "").strip()
    if not got:
        raise RegistryError("returned_model_missing")
    if provider == "deepseek":
        reject_legacy_model_id(got)
        if got not in EXACT_DEEPSEEK_MODELS:
            raise RegistryError(f"returned_model_not_approved: {got!r}")
    if got != req:
        raise RegistryError(f"model_mismatch: requested={req!r} returned={got!r}")


def assert_critic_provider_separated(author_provider: str, critic_provider: str) -> None:
    a = (author_provider or "").strip().lower()
    c = (critic_provider or "").strip().lower()
    if not a or not c:
        raise RegistryError("provider_pair_incomplete")
    if a == c:
        raise RegistryError("author_critic_same_provider")
    # Local models may not substitute for DeepSeek Flash author.
    if a in {"local", "ollama", "llama", "gemma", "hermes_local"}:
        raise RegistryError("local_model_forbidden_as_l3_author")


def forbid_local_author_substitute(provider: str, *, policy: L3ModelPolicy | None = None) -> None:
    policy = policy or default_l3_policy()
    p = (provider or "").strip().lower()
    if policy.local_substitute_forbidden and p in {
        "local",
        "ollama",
        "llama",
        "gemma",
        "hermes_local",
        "mock_local",
    }:
        raise RegistryError("local_model_forbidden_as_l3_author")


def cache_versions(policy: L3ModelPolicy | None = None) -> dict[str, str]:
    policy = policy or default_l3_policy()
    return {
        "memory_policy_version": policy.memory_policy_version,
        "prompt_template_version": policy.prompt_template_version,
        "model_registry_version": policy.model_registry_version,
    }


def et_zone() -> ZoneInfo:
    return ET
