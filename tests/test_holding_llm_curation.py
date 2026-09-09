"""Unit tests for holding intel freshness + CIO multi-consensus reconciliation."""
from datetime import datetime, timedelta, timezone

from lib.holding_intel_freshness import (
    annotate_external_row,
    classify_freshness,
    is_refusal_narrative,
    synthesis_status_from_narrative,
)
from process_watchlist_agent_jobs import _normalize_cio_lanes, _reconcile_cio_votes


def test_freshness_current_stale_expired():
    now = datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)
    assert classify_freshness(now - timedelta(hours=2), now=now) == "CURRENT"
    assert classify_freshness(now - timedelta(hours=48), now=now) == "STALE"
    assert classify_freshness(now - timedelta(days=10), now=now) == "EXPIRED"
    assert classify_freshness(None, now=now) == "UNDATED"


def test_annotate_external_row():
    now = datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)
    row = annotate_external_row({"lane": "deepseek", "at": now - timedelta(hours=30)}, now=now)
    assert row["freshness_class"] == "STALE"
    assert row["age_hours"] is not None and 29 < row["age_hours"] < 31


def test_refusal_narrative_detection():
    assert is_refusal_narrative("LLM error: model refused the synthesis prompt (refusal suppressed)")
    assert is_refusal_narrative("**I cannot fulfill this request.**")
    assert not is_refusal_narrative("HOLD — thesis intact with stop defined.")
    assert synthesis_status_from_narrative("LLM error: boom") == "error"
    assert synthesis_status_from_narrative("LLM error: model refused the synthesis prompt") == "refused"
    assert synthesis_status_from_narrative("Solid HOLD narrative") == "ok"


def test_normalize_cio_lanes_includes_flash():
    assert _normalize_cio_lanes(None) == ("grok", "chatgpt", "deepseek-flash")
    assert "deepseek-flash" in _normalize_cio_lanes(("grok", "deepseek"))


def test_reconcile_majority_and_cautious():
    votes = [
        {"lane": "grok", "rec": "HOLD", "conf": 0.6},
        {"lane": "chatgpt", "rec": "IGNORE", "conf": 0.5},
        {"lane": "deepseek-flash", "rec": "HOLD", "conf": 0.7},
    ]
    r = _reconcile_cio_votes(votes)
    assert r["consensus"] == "HOLD"
    assert r["majority"] is True
    assert r["agree"] is False

    full_disagree = [
        {"lane": "grok", "rec": "BUY", "conf": 0.8},
        {"lane": "chatgpt", "rec": "HOLD", "conf": 0.6},
        {"lane": "deepseek-flash", "rec": "IGNORE", "conf": 0.5},
    ]
    r2 = _reconcile_cio_votes(full_disagree)
    assert r2["consensus"] == "IGNORE"  # most cautious
    assert r2["majority"] is False


def test_reconcile_no_invented_vote_when_empty():
    assert _reconcile_cio_votes([])["consensus"] is None


def test_curation_lineage_guid_and_grounding():
    from lib.curation_lineage import (
        grounding_instruction_text,
        new_research_guid,
        prior_grounding_context,
    )

    g1, g2 = new_research_guid(), new_research_guid()
    assert g1 != g2

    block = prior_grounding_context(None)
    assert block is None

    prior = {
        "research_guid": g1,
        "model": "deepseek-v4-flash",
        "created_at": "2026-09-09T12:00:00Z",
        "recommendation": "HOLD — prior thesis.",
    }
    block = prior_grounding_context(prior)
    assert block["guid"] == g1
    assert "do not repeat it verbatim" in grounding_instruction_text(block).lower()
    assert "prior recommendation: HOLD" in grounding_instruction_text(block)


def test_redact_struct_preserves_numbers():
    """canonical_prompt_context must redact string values without corrupting numeric literals."""
    from hermes_external_researcher import _redact_struct

    d = {
        "market_value": 1267430.0,
        "price_str": "$1,267,430",
        "account": "123456789",
        "nested": [1.5, "sk-abcdefghijklmnop123456"],
        "email": "a@b.com",
    }
    out = _redact_struct(d)
    assert out["market_value"] == 1267430.0
    assert "REDACTED" in out["price_str"]
    assert "REDACTED" in out["account"]
    assert out["nested"][0] == 1.5
    assert "REDACTED" in out["nested"][1]
    assert "REDACTED" in out["email"]
