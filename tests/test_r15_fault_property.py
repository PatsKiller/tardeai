"""Fault campaign + property invariants for the intelligence fabric."""
from __future__ import annotations

import random

import pytest

from scripts.lib.cio_intelligence_fabric import (
    FORBIDDEN_TRUTH_KEYS,
    fault_response,
    process_observation,
)
from scripts.lib.cio_model_learning import RoutingPromotionForbidden, apply_routing_candidate
from scripts.lib.ticker_knowledge_graph import entity_guid
from tests.r15_goldens import UNIVERSE, fault_goldens, property_seeds

pytestmark = pytest.mark.tier0
FAULTS = fault_goldens()


@pytest.mark.parametrize("case", FAULTS, ids=[c["id"] for c in FAULTS])
def test_fault_campaign_golden(case: dict) -> None:
    row = fault_response(case["kind"])
    assert row["status"] == case["expect_status"]
    assert row["silent_loss"] is False
    assert row["fabricated_certainty"] is False
    assert row["memory_behavior_influence"] == 0
    assert row["financial_action"] is False


@pytest.mark.parametrize("seed", property_seeds())
def test_property_invariants(seed: int, tmp_path) -> None:
    rng = random.Random(seed)
    sym = rng.choice([p["symbol"] for p in UNIVERSE])
    profile = next(p for p in UNIVERSE if p["symbol"] == sym)
    material = rng.choice(["NO_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE", "CONFLICT", "STALE", "DATA_UNAVAILABLE"])
    observation = {
        "source_domain": rng.choice(["holdings", "catalysts", "hermes_research", "news"]),
        "source_ref": f"{sym}:{seed}",
        "source_version": str(seed),
        "entity_guid": profile["ticker_guid"],
        "entity_type": "ticker",
        "change_type": "PROP",
        "before_hash": "0",
        "after_hash": "0" if material == "NO_CHANGE" else f"h{seed}",
        "materiality": material,
        "material_fields_changed": material == "MATERIAL_CHANGE",
        "stale": material == "STALE",
        "conflict": material == "CONFLICT",
        "available": material != "DATA_UNAVAILABLE",
        "freshness": "STALE" if material == "STALE" else "FRESH",
        "hermes_resolved": rng.random() > 0.5,
        "reason": f"property-{seed}",
    }
    receipt = process_observation(tmp_path, observation, profiles=UNIVERSE)
    assert receipt["authority"] == "READ_ONLY_ADVISORY"
    assert receipt["memory_behavior_influence"] == 0
    assert receipt["financial_action"] is False
    assert receipt["llm_calls"] == 0
    assert receipt["model_policy_auto_changed"] is False
    blob = str(receipt)
    for key in FORBIDDEN_TRUTH_KEYS:
        assert f'"{key}"' not in blob or key not in (receipt.get("delta") or {})
    replay = process_observation(tmp_path, observation, profiles=UNIVERSE)
    assert replay["duplicate_delta"] is True
    with pytest.raises(RoutingPromotionForbidden):
        apply_routing_candidate(tmp_path, {"task_class": "extraction"})
