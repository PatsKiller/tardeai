"""Phase 7 / 8 — advisory desk provenance on expanded rows."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_advisory_provenance import (  # noqa: E402
    ADVISORY_PROVENANCE_VERSION,
    DATA_CONFLICT_ACTION_SUPPRESSED,
    attach_expand_provenance,
    build_analyst_provenance_fields,
    build_canonical_financial_facts,
    build_expanded_row_provenance,
    synthesize_specialist_opinions,
)


def test_version():
    assert ADVISORY_PROVENANCE_VERSION.startswith("advisory_provenance_")


def test_clean_row_facts():
    row = {
        "symbol": "AAA",
        "shares": 10.0,
        "current_price": 100.0,
        "price": 100.0,
        "market_value": 1000.0,
        "cost_basis": 800.0,
        "analyst_target": 120.0,
    }
    p = build_expanded_row_provenance(row)
    assert p["symbol"] == "AAA"
    assert p["authority"] == "READ_ONLY_ADVISORY"
    labels = [f["label"] for f in p["current_financial_facts"]]
    assert "Current price" in labels
    assert "Position value" in labels
    assert p["conflicts"] == []
    facts = p["canonical_financial_facts"]
    assert facts["current_mark"] == 100.0
    assert facts["shares"] == 10.0
    assert facts["market_value"] == 1000.0
    assert facts["quality"] != "CONFLICTED"
    an = p["analyst"]
    assert an["target"] == 120.0
    assert an["denominator_is_canonical_current"] is True
    assert an["target_upside_vs_current"] == 20.0
    assert an["target_vs_current_pct"] == 20.0


def test_dual_price_conflict_surfaced():
    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 91.26,
        "price": 90.98,
        "market_value": 20470.50,
        "cost_basis": 15985.13,
    }
    p = build_expanded_row_provenance(row)
    assert p["conflicts"]  # mark vs implied-from-MV and/or shares×px ≠ MV
    assert any("implied-from-MV" in c or "shares×price" in c or "market_value" in c for c in p["conflicts"])
    assert "order" in p
    assert p["order"][0] == "decision"
    assert DATA_CONFLICT_ACTION_SUPPRESSED in p["conflicts"]
    assert p["action_suppressed"] is True
    facts = p["canonical_financial_facts"]
    assert facts["current_mark"] == 91.26
    assert facts["quality"] == "CONFLICTED"
    assert abs(facts["avg_cost_per_share"] - (15985.13 / 225.0)) < 1e-3


def test_trim_vs_hold_synthesis():
    row = {
        "symbol": "SCHD",
        "shares": 100.0,
        "current_price": 80.0,
        "market_value": 8000.0,
        "cost_basis": 7000.0,
        "deterministic_stance": "TRIM",
        "maria_stance": "HOLD",
        "guardian_stance": "HOLD",
    }
    p = build_expanded_row_provenance(row)
    assert p["opinion_synthesis"]
    assert "portfolio-risk" in p["opinion_synthesis"].lower() or "HOLD" in p["opinion_synthesis"]
    assert "remain HOLD" in p["opinion_synthesis"]


def test_missing_desk_opinion_is_not_hold():
    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 91.26,
        "market_value": 20470.50,
        "cost_basis": 15985.13,
        "deterministic_stance": "TRIM",
        # maria / guardian omitted — must not be inferred as HOLD
    }
    p = build_expanded_row_provenance(row)
    assert p["opinion_synthesis"]
    assert "remain HOLD" not in p["opinion_synthesis"]
    assert "not HOLD" in p["opinion_synthesis"]
    assert p["specialist_opinions"]["missing_is_not_hold"] is True
    assert synthesize_specialist_opinions(row) == p["opinion_synthesis"]


def test_empty_string_stance_is_not_hold():
    text = synthesize_specialist_opinions({
        "deterministic_stance": "TRIM",
        "maria_stance": "",
        "guardian_stance": "",
    })
    assert text
    assert "remain HOLD" not in text
    assert "not HOLD" in text


def test_dxcm_stale_analyst_denominator_not_vs_current():
    """Yahoo ~$70 snapshot must not be labeled vs current against a ~$91 mark."""
    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 91.26,
        "price": 90.98,
        "market_value": 20470.50,
        "cost_basis": 15985.13,
        "analyst_target": 119.0,
        "analyst_snapshot_price": 70.0,
        "analyst_as_of": "2025-11-01",
        "as_of": "2026-08-14",
        "price_source": "holdings.json",
    }
    p = build_expanded_row_provenance(row)
    facts = p["canonical_financial_facts"]
    assert facts["current_mark"] == 91.26
    assert facts["as_of"] == "2026-08-14"
    assert facts["source"] == "holdings.json"
    assert facts["quality"] == "CONFLICTED"
    an = p["analyst"]
    assert an["target"] == 119.0
    assert an["target_as_of"] == "2025-11-01"
    assert an["denominator_is_canonical_current"] is False
    assert an["target_vs_current_pct"] is None
    assert an["target_upside_vs_current"] == round((119.0 - 91.26) / 91.26 * 100.0, 2)
    assert an["target_upside_vs_provider_snapshot"] == round((119.0 - 70.0) / 70.0 * 100.0, 2)
    assert an["denominator_price"] == 70.0
    assert "vs current" not in str(an.get("upside_label") or "").lower()
    assert an["upside_label"] == "upside_vs_provider_snapshot"
    fields = build_analyst_provenance_fields(row, facts)
    assert fields["target_vs_current_pct"] is None


def test_advisory_desk_attach_includes_canonical_financial_facts():
    from scripts.lib.data_broker.advisory_desk import attach_advisory_row_provenance

    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 91.26,
        "price": 90.98,
        "market_value": 20470.50,
        "cost_basis": 15985.13,
        "as_of": "2026-08-14",
        "price_source": "holdings.json",
        "analyst": {
            "target": 119.0,
            "price_target_mean": 119.0,
            "target_as_of": "2025-11-01",
            "provider_snapshot_price": 70.0,
            "provider_snapshot_as_of": "2025-11-01",
            "consensus_rating": "Buy",
        },
    }
    out = attach_advisory_row_provenance(row)
    assert "canonical_financial_facts" in out
    facts = out["canonical_financial_facts"]
    assert facts["current_mark"] == 91.26
    assert facts["shares"] == 225.0
    expand = out["expand"]
    assert expand["canonical_financial_facts"]["current_mark"] == 91.26
    assert expand["advisory_provenance"]["symbol"] == "DXCM"
    analyst = expand["analyst"]
    assert analyst["target"] == 119.0
    assert analyst["target_upside_vs_current"] is not None
    assert analyst["target_upside_vs_provider_snapshot"] is not None
    assert analyst["denominator_is_canonical_current"] is False
    assert analyst["target_vs_current_pct"] is None
    assert out["data_quality"]["action_suppressed"] is True
    assert DATA_CONFLICT_ACTION_SUPPRESSED in (out["data_quality"].get("banner") or "")


def test_stamp_conflicted_verdict_suppression():
    from scripts.lib.data_broker.advisory_desk import (
        AdvisoryVerdict,
        stamp_conflicted_verdict_suppression,
    )

    rows = [
        {
            "symbol": "SCHD", "verdict": AdvisoryVerdict.TRIM,
            "canonical_financial_facts": {"conflicts": ["dual price fields disagree"]},
            "data_quality": {"action_suppressed": True},
        },
        {
            "symbol": "V", "verdict": AdvisoryVerdict.TRIM,
            "canonical_financial_facts": {"conflicts": []},
            "data_quality": {"action_suppressed": False},
        },
        {
            "symbol": "MSFT", "verdict": AdvisoryVerdict.WAIT,
            "data_quality": {"action_suppressed": True},
        },
        {
            "symbol": "BND", "verdict": AdvisoryVerdict.HOLD,
            "canonical_financial_facts": {"conflicts": ["x"]},
        },
    ]
    stamp_conflicted_verdict_suppression(rows)
    assert rows[0]["verdict_suppressed"] is True
    assert rows[0]["verdict_suppressed_reason"] == "DATA CONFLICT — ACTION SUPPRESSED"
    assert "verdict_suppressed" not in rows[1]  # clean TRIM stays actionable
    assert "verdict_suppressed" not in rows[2]  # WAIT is not an actionable verdict
    assert "verdict_suppressed" not in rows[3]  # HOLD is not actionable


def test_attach_does_not_let_yahoo_snapshot_overwrite_mark():
    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 91.26,
        "market_value": 20470.50,
        "cost_basis": 15985.13,
    }
    analyst = {
        "current_price": 70.0,  # Yahoo snapshot column — must not become the mark
        "provider_snapshot_price": 70.0,
        "target": 119.0,
    }
    out = attach_expand_provenance(row, analyst=analyst)
    assert out["canonical_financial_facts"]["current_mark"] == 91.26
    assert out["expand"]["analyst"]["provider_snapshot_price"] == 70.0


def test_canonical_financial_facts_keys():
    facts = build_canonical_financial_facts({
        "symbol": "AAA",
        "shares": 10,
        "current_price": 50,
        "market_value": 500,
        "cost_basis": 400,
        "as_of": "2026-08-14T15:00:00+00:00",
        "price_source": "holdings.json",
    })
    for key in (
        "current_mark", "as_of", "source", "shares", "market_value",
        "total_cost_basis", "avg_cost_per_share", "unrealized_pl", "quality",
    ):
        assert key in facts
    assert facts["current_mark"] == 50.0
    assert facts["as_of"].startswith("2026-08-14")
    assert facts["source"] == "holdings.json"
