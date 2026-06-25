"""Tests for hermes_research_curator tick rotation."""
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "hermes_research_curator", ROOT / "scripts" / "hermes_research_curator.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tick_depth_baseline():
    mod = _load()
    d = mod.tick_depth(datetime(2026, 6, 24, 10, 30, tzinfo=timezone.utc))
    assert d["skip_web"] is True
    assert d["skip_llm"] is True
    assert d["skip_sites"] is False
    assert d["skip_watchlist_drain"] is True
    assert d["max_themes"] == 2
    assert d["max_prospects_stage"] == 6


def test_tick_depth_hourly_web():
    mod = _load()
    d = mod.tick_depth(datetime(2026, 6, 24, 10, 5, tzinfo=timezone.utc))
    assert d["skip_web"] is False
    assert d["skip_watchlist_drain"] is False
    assert d["mode"] in ("web", "llm", "prospects", "baseline")


def test_tick_depth_force_deep():
    mod = _load()
    d = mod.tick_depth(force_deep=True)
    assert d["skip_web"] is False
    assert d["skip_llm"] is False
    assert d["skip_drain"] is False
    assert d["max_themes"] == 8


def test_attention_summary_nonempty():
    mod = _load()
    report = {
        "signals": {
            "rs_rsi": {"weekly_rs_leaders": [{"symbol": "NVDA", "perf_week_pct": 12.5}]},
            "hermes_research": [{"theme": "Defense spending", "count": 5}],
            "news_feeds": {"themes": [{"theme": "Nuclear", "feed": "pattern_match", "count": 4}]},
        },
        "themes_upserted": [{"label": "trend Defense"}],
        "site_registration": {"registered": 1, "sample": ["example.com"]},
    }
    lines = mod._attention_summary(report, {"mode": "baseline"})
    assert any("NVDA" in l for l in lines)
    assert any("Defense" in l for l in lines)


def test_attention_summary_scalp_leads():
    mod = _load()
    report = {
        "prospect_pipeline": {
            "scalp_leads": {"mined": 5, "incubator": {"staged": 3}},
        },
    }
    lines = mod._attention_summary(report, {"mode": "baseline"})
    assert any("Scalp leads beyond Finviz" in l for l in lines)