"""CIO trust bundle unit checks (no DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.cio_trust_bundle import (
    apply_trust_to_qa,
    compute_cio_trust_bundle,
    narrative_conflicts_recommendation,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_high_requires_dual_agree_buy_side():
    dual = {
        "agree": True,
        "grok": {"recommendation": "BUY", "confidence": 0.7},
        "chatgpt": {"recommendation": "BUY", "confidence": 0.8},
        "structured_evidence": [{"tag": "fact", "text": "held income"}],
    }
    out = compute_cio_trust_bundle(
        recommendation="BUY",
        synthesis_updated_at=_now(),
        models_agree=True,
        dual_consensus=dual,
        model_used="grok+chatgpt(agree)",
        decision_quality_status="actionable",
        decision_safety="safe",
        actionable=True,
        street_rec="buy",
        street_n=12,
        street_as_of=_now(),
        evidence=dual["structured_evidence"],
        synthesis_narrative="We recommend a buy on pullback.",
        on_main=True,
    )
    assert out["level"] == "HIGH"
    assert out["dual_mode"] == "AGREE"


def test_dual_disagree_buy_degrades():
    dual = {
        "agree": False,
        "grok": {"recommendation": "BUY"},
        "chatgpt": {"recommendation": "HOLD"},
        "structured_evidence": [{"tag": "fact", "text": "x"}],
    }
    out = compute_cio_trust_bundle(
        recommendation="HOLD",
        synthesis_updated_at=_now(),
        models_agree=False,
        dual_consensus=dual,
        decision_quality_status="actionable",
        street_rec="buy",
        street_n=10,
        street_as_of=_now(),
        evidence=dual["structured_evidence"],
        synthesis_narrative="Cautious hold after disagreement.",
    )
    assert out["level"] == "DEGRADED"
    assert "dual" in out["failed_gates"]


def test_local_fallback_main_degrades():
    out = compute_cio_trust_bundle(
        recommendation="BUY",
        synthesis_updated_at=_now(),
        model_used="gemma3:12b",
        dual_consensus={},
        decision_quality_status="actionable",
        street_rec="buy",
        street_n=10,
        street_as_of=_now(),
        evidence=[{"tag": "fact", "text": "x"}],
        synthesis_narrative="Buy.",
        on_main=True,
    )
    assert out["level"] == "DEGRADED"
    assert "local_fallback" in out["failed_gates"] or "dual" in out["failed_gates"]


def test_street_stale_degrades_equity():
    old = (datetime.now(timezone.utc) - timedelta(hours=120)).isoformat()
    out = compute_cio_trust_bundle(
        recommendation="HOLD",
        synthesis_updated_at=_now(),
        models_agree=True,
        dual_consensus={
            "agree": True,
            "grok": {"recommendation": "HOLD"},
            "chatgpt": {"recommendation": "HOLD"},
        },
        street_rec="buy",
        street_n=10,
        street_as_of=old,
        instrument_type="equity",
        synthesis_narrative="Hold.",
    )
    assert out["level"] == "DEGRADED"
    assert "street" in out["failed_gates"]


def test_fund_street_na_allows_high():
    dual = {
        "agree": True,
        "grok": {"recommendation": "ADD"},
        "chatgpt": {"recommendation": "ADD"},
        "structured_evidence": [{"tag": "fact", "text": "SCHD income"}],
    }
    out = compute_cio_trust_bundle(
        recommendation="ADD",
        synthesis_updated_at=_now(),
        models_agree=True,
        dual_consensus=dual,
        model_used="grok+chatgpt(agree)",
        decision_quality_status="actionable",
        decision_safety="safe",
        street_rec=None,
        street_n=0,
        instrument_type="etf",
        evidence=dual["structured_evidence"],
        synthesis_narrative="Add on weakness for income sleeve.",
    )
    assert out["level"] == "HIGH"


def test_apply_trust_blocks_buy_actionable():
    trust = compute_cio_trust_bundle(
        recommendation="BUY",
        synthesis_updated_at=_now(),
        models_agree=False,
        dual_consensus={
            "agree": False,
            "grok": {"recommendation": "BUY"},
            "chatgpt": {"recommendation": "AVOID"},
        },
        street_rec="sell",
        street_n=8,
        street_as_of=_now(),
        evidence=[{"tag": "risk", "text": "divergent"}],
        synthesis_narrative="Avoid new risk.",
    )
    qa = {"actionable": True, "decision_quality_status": "actionable", "gating_reasons": []}
    out = apply_trust_to_qa(qa, {**trust, "recommendation": "BUY"})
    assert out["actionable"] is False
    assert out["decision_quality_status"] == "cio_trust_degraded"


def test_narrative_conflict():
    assert narrative_conflicts_recommendation("We should sell and avoid", "BUY")
    assert not narrative_conflicts_recommendation("Add on pullback", "ADD_ON_PULLBACK")
