"""Journal auto-tag — regime mapping and enrich helpers."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import journal_trade_in_view as tiv


def test_map_regime_label():
    assert tiv._map_regime_label("risk_on_trend") == "Risk-On"
    assert tiv._map_regime_label("choppy_range") == "Choppy"
    assert tiv._map_regime_label("unknown") == "Ranging"
    assert tiv._map_regime_label("Bullish") == "Bullish"


def test_regime_fields_for_trade_same_day():
    fields = tiv._regime_fields_for_trade({"open_date": "2026-01-22", "close_date": "2026-01-22"})
    assert "market_regime" in fields
    assert "market_regime_entry" in fields
    assert "market_regime_exit" in fields
    assert fields["market_regime_display"] == fields["market_regime_entry"]


def test_score_trade_tags_skips_ai_critique_by_default():
    policy = tiv._load_tagging_policy()
    assert policy.get("queue_requires_ai_critique") is False
    rev = {
        "setup_family": "Scalp",
        "setup_types": ["day_scalp"],
        "market_regime": "Choppy",
        "emotion_before": "Calm",
        "payload": {"operator_confirmed": True, "tagging_complete": True, "industry": "Software"},
    }
    score = tiv.score_trade_tags(rev, policy)
    assert "ai_critique" not in score["missing"]
    assert "operator_review" not in score["missing"]


def test_stale_ai_critique_does_not_block_queue():
    policy = dict(tiv._load_tagging_policy())
    policy["queue_requires_ai_critique"] = True
    rev = {
        "setup_family": "Scalp",
        "setup_types": ["day_scalp"],
        "market_regime": "Risk-On",
        "emotion_before": "Calm",
        "payload": {
            "operator_confirmed": True,
            "operator_reviewed": True,
            "tagging_complete": True,
            "ai_critique": {"narrative": {"summary": "ok"}},
            "ai_critique_meta": {"status": "ok", "stale": True, "tag_fingerprint": "abc"},
        },
    }
    score = tiv.score_trade_tags(rev, policy)
    assert score["complete"] is True
    assert "ai_critique_stale" not in score["missing"]
    assert "ai_critique_stale" in score["critique_gaps"]


def test_stop_context_invalid_key():
    ctx = tiv.stop_context_for_trade("BADKEY")
    assert ctx.get("ok") is False


def test_stop_context_schwab_trade():
    ctx = tiv.stop_context_for_trade("ELAB:schwab_rollover_ira:2026-07-10")
    assert ctx.get("ok") is True
    assert ctx.get("symbol") == "ELAB"
    assert "notes" in ctx


if __name__ == "__main__":
    test_map_regime_label()
    test_regime_fields_for_trade_same_day()
    test_score_trade_tags_skips_ai_critique_by_default()
    test_stale_ai_critique_does_not_block_queue()
    test_stop_context_invalid_key()
    test_stop_context_schwab_trade()
    print("ok")