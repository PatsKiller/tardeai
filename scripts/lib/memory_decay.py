"""Monotonic, bounded, inspectable memory decay weights (L2 grounding).

Replaces the former WAKE_MEMORY_STALE_HOURS=168 hard cliff. Age remains visible;
decay never increases with age for equal-quality facts; a fact may be old
without becoming nonexistent.

Policy knobs use env overrides (same convention as WAKE_MEMORY_STALE_HOURS).
config/** is Lane A-owned — do not add governed YAML here without an SFR.

Authority: cognition only. MEMORY_BEHAVIOR_INFLUENCE / MBI_BEHAVIOR stays 0.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "MemoryDecayPolicy@v1"
DECAY_MODEL_DEFAULT = "halflife_exp:336h"

# Env knobs (operator-overridable; defaults are the versioned policy).
ENV_HALFLIFE_HOURS = "WAKE_MEMORY_DECAY_HALFLIFE_HOURS"
ENV_MIN_INFLUENCE = "WAKE_MEMORY_MIN_INFLUENCE"
ENV_FRESH_HOURS = "WAKE_MEMORY_FRESH_HOURS"
ENV_AGING_HOURS = "WAKE_MEMORY_AGING_HOURS"
ENV_STALE_LABEL_HOURS = "WAKE_MEMORY_STALE_LABEL_HOURS"

DEFAULT_HALFLIFE_HOURS = 336.0  # 14d — continuous; NOT a deletion cliff
DEFAULT_MIN_INFLUENCE = 0.05
DEFAULT_FRESH_HOURS = 24.0
DEFAULT_AGING_HOURS = 168.0  # label boundary only; facts remain eligible
DEFAULT_STALE_LABEL_HOURS = 720.0


def _env_float(name: str, default: float, env: Mapping[str, str] | None = None) -> float:
    e = env if env is not None else os.environ
    raw = e.get(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    return float(raw)


@dataclass(frozen=True)
class DecayPolicy:
    """Versioned decay policy. Inspectable; cache-keyable."""

    schema_version: str = SCHEMA_VERSION
    half_life_hours: float = DEFAULT_HALFLIFE_HOURS
    min_influence: float = DEFAULT_MIN_INFLUENCE
    fresh_hours: float = DEFAULT_FRESH_HOURS
    aging_hours: float = DEFAULT_AGING_HOURS
    stale_label_hours: float = DEFAULT_STALE_LABEL_HOURS
    decay_model: str = DECAY_MODEL_DEFAULT

    def cache_token(self) -> str:
        return (
            f"{self.schema_version}|hl={self.half_life_hours}|"
            f"min={self.min_influence}|f={self.fresh_hours}|"
            f"a={self.aging_hours}|s={self.stale_label_hours}|m={self.decay_model}"
        )


def load_decay_policy(env: Mapping[str, str] | None = None) -> DecayPolicy:
    """Load policy from env with versioned defaults. No hardcoded operator secrets."""
    hl = _env_float(ENV_HALFLIFE_HOURS, DEFAULT_HALFLIFE_HOURS, env)
    if hl <= 0:
        raise ValueError(f"{ENV_HALFLIFE_HOURS} must be > 0")
    mn = _env_float(ENV_MIN_INFLUENCE, DEFAULT_MIN_INFLUENCE, env)
    if not (0.0 <= mn <= 1.0):
        raise ValueError(f"{ENV_MIN_INFLUENCE} must be in [0,1]")
    fresh = _env_float(ENV_FRESH_HOURS, DEFAULT_FRESH_HOURS, env)
    aging = _env_float(ENV_AGING_HOURS, DEFAULT_AGING_HOURS, env)
    stale = _env_float(ENV_STALE_LABEL_HOURS, DEFAULT_STALE_LABEL_HOURS, env)
    if not (fresh <= aging <= stale):
        raise ValueError("fresh_hours <= aging_hours <= stale_label_hours required")
    model = f"halflife_exp:{hl:g}h"
    return DecayPolicy(
        half_life_hours=hl,
        min_influence=mn,
        fresh_hours=fresh,
        aging_hours=aging,
        stale_label_hours=stale,
        decay_model=model,
    )


def age_seconds(observed_at: datetime, *, now: datetime | None = None) -> float:
    """Non-negative age in seconds. Future timestamps yield 0 age but are flagged upstream."""
    now = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - observed_at).total_seconds())


def freshness_class(age_sec: float, policy: DecayPolicy | None = None) -> str:
    """Label only — never a deletion gate.

    Classes: fresh | aging | stale_but_usable | ancient
    The former 168h cliff sits inside 'aging'→'stale_but_usable'; facts remain visible.
    """
    policy = policy or load_decay_policy()
    hours = age_sec / 3600.0
    if hours <= policy.fresh_hours:
        return "fresh"
    if hours <= policy.aging_hours:
        return "aging"
    if hours <= policy.stale_label_hours:
        return "stale_but_usable"
    return "ancient"


def decay_weight(
    age_sec: float,
    *,
    policy: DecayPolicy | None = None,
    confidence: float | None = 1.0,
) -> float:
    """Monotonic non-increasing continuous decay in (0, 1], bounded.

    weight = confidence_factor * 0.5 ** (age_hours / half_life)

    - Never reaches exactly 0 solely from age (old ≠ nonexistent).
    - Never increases with age for equal confidence.
    - confidence may only reduce weight (clamped to [0,1]); never amplify above the age curve.
    """
    policy = policy or load_decay_policy()
    age_h = max(0.0, float(age_sec) / 3600.0)
    base = math.pow(0.5, age_h / policy.half_life_hours)
    # Keep a microscopic floor so age-only decay never publishes exact zero.
    base = max(base, math.pow(2.0, -64))
    conf = 1.0 if confidence is None else float(confidence)
    if conf < 0.0:
        conf = 0.0
    if conf > 1.0:
        conf = 1.0
    w = base * conf
    if w > 1.0:
        w = 1.0
    if w < 0.0:
        w = 0.0
    return w


def meets_min_influence(weight: float, policy: DecayPolicy | None = None) -> bool:
    policy = policy or load_decay_policy()
    return float(weight) >= float(policy.min_influence)


def annotate_age(
    observed_at: datetime,
    *,
    now: datetime | None = None,
    policy: DecayPolicy | None = None,
    confidence: float | None = 1.0,
) -> dict[str, Any]:
    """Return inspectable age/decay fields for a single fact."""
    policy = policy or load_decay_policy()
    age_sec = age_seconds(observed_at, now=now)
    weight = decay_weight(age_sec, policy=policy, confidence=confidence)
    return {
        "age_seconds": age_sec,
        "age_hours": age_sec / 3600.0,
        "freshness_class": freshness_class(age_sec, policy),
        "decay_weight": weight,
        "decay_model": policy.decay_model,
        "meets_min_influence": meets_min_influence(weight, policy),
        "policy_version": policy.schema_version,
        "policy_cache_token": policy.cache_token(),
        "cliff_applied": False,
    }
