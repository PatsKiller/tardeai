"""Controls for monotonic bounded decay — no 168h deletion cliff."""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.memory_decay import (  # noqa: E402
    DecayPolicy,
    age_seconds,
    annotate_age,
    decay_weight,
    freshness_class,
    load_decay_policy,
    meets_min_influence,
)

NOW = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)


def test_age_seconds_non_negative():
    past = NOW - timedelta(hours=10)
    assert age_seconds(past, now=NOW) == pytest.approx(10 * 3600)
    # Future clamped to 0 at age layer (caller flags future separately)
    future = NOW + timedelta(hours=1)
    assert age_seconds(future, now=NOW) == 0.0


def test_monotonic_decay_never_increases_with_age():
    policy = DecayPolicy(half_life_hours=336.0, min_influence=0.05)
    ages = [0, 1, 24, 167, 168, 169, 336, 432, 720, 2000]
    weights = [decay_weight(a * 3600, policy=policy, confidence=1.0) for a in ages]
    for i in range(1, len(weights)):
        assert weights[i] <= weights[i - 1] + 1e-15


def test_no_discontinuous_disappearance_around_168h():
    """Former cliff boundary: weight is continuous; both sides remain > 0."""
    policy = DecayPolicy(half_life_hours=336.0, min_influence=0.01)
    w167 = decay_weight(167 * 3600, policy=policy)
    w168 = decay_weight(168 * 3600, policy=policy)
    w169 = decay_weight(169 * 3600, policy=policy)
    assert w167 > 0 and w168 > 0 and w169 > 0
    assert abs(w167 - w168) < 0.01
    assert abs(w168 - w169) < 0.01
    # Not a step to zero
    assert w169 > 0.5 ** (169 / 336) * 0.99


def test_decay_never_exact_zero_from_age_alone():
    policy = DecayPolicy(half_life_hours=336.0)
    w = decay_weight(10_000 * 3600, policy=policy, confidence=1.0)
    assert w > 0.0
    assert w < 1e-6


def test_confidence_only_reduces_weight():
    policy = DecayPolicy(half_life_hours=336.0)
    base = decay_weight(100 * 3600, policy=policy, confidence=1.0)
    low = decay_weight(100 * 3600, policy=policy, confidence=0.5)
    assert low < base
    assert low == pytest.approx(base * 0.5)


def test_freshness_class_labels_not_gates():
    policy = load_decay_policy()
    assert freshness_class(0, policy) == "fresh"
    assert freshness_class(50 * 3600, policy) == "aging"
    assert freshness_class(200 * 3600, policy) == "stale_but_usable"
    assert freshness_class(800 * 3600, policy) == "ancient"


def test_min_influence_threshold_explicit():
    policy = DecayPolicy(half_life_hours=336.0, min_influence=0.2)
    # Solve age where weight ~= 0.2: 0.5**(h/336)=0.2 → h = 336*log2(1/0.2)
    h = 336 * math.log(1 / 0.2, 2)
    just_above = decay_weight((h - 1) * 3600, policy=policy)
    just_below = decay_weight((h + 10) * 3600, policy=policy)
    assert meets_min_influence(just_above, policy)
    assert not meets_min_influence(just_below, policy)


def test_policy_cache_token_changes_on_revision():
    a = DecayPolicy(half_life_hours=336.0, min_influence=0.05)
    b = DecayPolicy(half_life_hours=400.0, min_influence=0.05)
    assert a.cache_token() != b.cache_token()


def test_annotate_age_cliff_applied_always_false():
    ann = annotate_age(NOW - timedelta(hours=500), now=NOW)
    assert ann["cliff_applied"] is False
    assert ann["age_seconds"] == pytest.approx(500 * 3600)
    assert ann["decay_weight"] > 0


def test_env_policy_override(monkeypatch):
    monkeypatch.setenv("WAKE_MEMORY_DECAY_HALFLIFE_HOURS", "100")
    monkeypatch.setenv("WAKE_MEMORY_MIN_INFLUENCE", "0.1")
    p = load_decay_policy()
    assert p.half_life_hours == 100.0
    assert p.min_influence == 0.1
