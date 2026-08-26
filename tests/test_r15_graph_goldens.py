"""100 graph-propagation goldens: membership, exposure, freshness, isolation."""
from __future__ import annotations

import pytest

from scripts.lib.cio_intelligence_fabric import build_delta_receipt, resolve_impact
from tests.r15_goldens import UNIVERSE, graph_goldens

pytestmark = pytest.mark.tier0
CASES = graph_goldens()


def _profiles(case: dict) -> list[dict]:
    overrides = case.get("profile_overrides") or {}
    out = []
    for profile in UNIVERSE:
        row = dict(profile)
        extra = overrides.get(row["symbol"])
        if extra:
            row.update(extra)
        out.append(row)
    return out


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_graph_propagation_golden(case: dict) -> None:
    delta = build_delta_receipt(
        source_domain="graph_golden",
        source_ref=case["id"],
        source_version="1",
        entity_guid_value=case["delta"]["entity_guid"],
        entity_type=case["delta"]["entity_type"],
        change_type="EVENT",
        before_hash="0",
        after_hash=case["id"],
        materiality=case["delta"]["materiality"],
        freshness=case["delta"]["freshness"],
        reason=case["kind"],
    )
    impact = resolve_impact(delta, _profiles(case))
    wake = set(impact["wake_symbols"])
    for sym in case.get("expect_wake") or []:
        assert sym in wake, f"{case['id']} missing {sym} in {sorted(wake)} rejected={impact['rejected'][:4]}"
    for sym in case.get("forbid_wake") or []:
        assert sym not in wake, f"{case['id']} falsely woke {sym}"
    for sym in case.get("expect_wake_not") or []:
        assert sym not in wake
    if case.get("peer_not_thesis"):
        for hit in impact["affected"]:
            if hit.get("hit_kind") == "peer":
                assert hit["thesis_evidence"] is False
                assert hit["wake_research"] is False
                assert hit["context_only"] is True
        for sym in case.get("expect_context") or []:
            assert sym in set(impact["context_only"]) or sym in wake
    assert impact["inferred_from_shared_industry_text"] is False
    assert impact["financial_action"] is False
