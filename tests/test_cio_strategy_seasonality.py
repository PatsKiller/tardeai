"""Phases 12–13 — strategy knowledge + seasonality (context only)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_seasonality_engine import (  # noqa: E402
    SEASONALITY_VERSION,
    build_seasonality_context,
    presidential_cycle_year,
    month_context,
)
from scripts.lib.cio_strategy_knowledge import (  # noqa: E402
    STRATEGY_KNOWLEDGE_VERSION,
    INFLUENCE_POLICY,
    load_strategy_store,
    compose_strategy_context,
    make_research_fact,
    default_seed_facts,
)


def test_versions():
    assert SEASONALITY_VERSION.startswith("seasonality_engine_")
    assert STRATEGY_KNOWLEDGE_VERSION.startswith("strategy_knowledge_")


def test_presidential_cycle_mechanical_non_partisan():
    # 2024 election year, 2025 post, 2026 midterm, 2027 pre
    assert presidential_cycle_year(2024)["cycle_label"] == "election_year"
    assert presidential_cycle_year(2025)["cycle_label"] == "post_election_year"
    assert presidential_cycle_year(2026)["cycle_label"] == "midterm_year"
    assert presidential_cycle_year(2027)["cycle_label"] == "pre_election_year"
    for y in (2020, 2024, 2026, 2028):
        c = presidential_cycle_year(y)
        assert c["partisan_conclusion"] is None


def test_september_hypothesis_bucket():
    m = month_context(9)
    assert m["month_name"] == "September"
    assert "weaker" in m["hypothesis_bucket"]
    assert m["worst_six_months_window"] is True


def test_influence_policy_never_execution():
    assert INFLUENCE_POLICY["max_role"] == "risk_modifier_or_context"
    assert "autonomous_execution" in INFLUENCE_POLICY["forbidden"]
    assert "collapse_claim_reproduction_application" in INFLUENCE_POLICY["forbidden"]


def test_seed_facts_layered_not_collapsed():
    facts = default_seed_facts()
    assert len(facts) >= 3
    for f in facts:
        assert "layers" in f
        layers = f["layers"]
        assert "source_claim" in layers
        assert "trade_ai_reproduction" in layers
        assert "current_application" in layers
        # STA layers stay distinct. Fixture reproduction may lift unverified →
        # partially_reproduced; do not require seeds to stay unverified.
        if "sta_" in str(f.get("source_id")):
            assert f["internal_validation_status"] in {
                "unverified_source_claim",
                "partially_reproduced",
                "reproduced",
                "reproduced_oos",
            }
            assert layers["source_claim"] != layers["trade_ai_reproduction"]
            assert layers["current_application"] != layers["source_claim"]
            assert "fulltext" not in (f.get("claim") or "").lower()


def test_compose_context_disclaimer():
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    season = build_seasonality_context(now)
    ctx = compose_strategy_context(now=now, store=load_strategy_store(), seasonality=season)
    assert ctx["role"] == "risk_modifier_or_context"
    assert ctx["authority"] == "READ_ONLY_ADVISORY"
    assert season["execution_engine"] is False
    assert any("September" in line or "weaker" in line or "cycle=" in line
               for line in ctx["context_lines"])


def test_make_research_fact_hash_stable_fields():
    f = make_research_fact(
        source_id="unit_test",
        source_type="operator_note",
        title="Unit",
        claim="test claim",
    )
    assert f["research_fact_id"].startswith("rf_")
    assert f["source_hash"]
    assert f["source_type"] == "operator_note"
