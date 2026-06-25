"""Tests for hermes_think_tank and think_tank_signal_miner."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_think_tank():
    return _load("hermes_think_tank", "hermes_think_tank.py")


def _load_miner():
    return _load("think_tank_signal_miner", "think_tank_signal_miner.py")


def test_rule_themes_sector_leader():
    mod = _load_think_tank()
    snap = {
        "snapshot_date": "2026-06-24",
        "leaders": [{"name": "Consumer Cyclical", "change_pct": 1.29}],
        "laggards": [],
    }
    themes = mod._rule_themes(snap, {"signal": None})
    assert any(t["kind"] == "sector" and "Consumer Cyclical" in t["label"] for t in themes)


def test_rule_themes_small_cap_rotation():
    mod = _load_think_tank()
    themes = mod._rule_themes({"leaders": [], "laggards": []}, {
        "signal": "small_cap_outperform",
        "explain": "IWM vs SPY 1d RS +0.84%",
    })
    assert any("small" in t["label"].lower() for t in themes)
    assert any("IWM" in (t.get("spec") or {}).get("seed_symbols", []) for t in themes)


def test_norm_label_dedup():
    mod = _load_think_tank()
    assert mod._norm_label("trend AI Datacenter") == mod._norm_label("TREND  AI   datacenter")


def test_merge_themes_priority():
    mod = _load_think_tank()
    a = [{"kind": "trend", "label": "trend AI datacenter", "spec": {"think_tank_source": "llm"}}]
    b = [{"kind": "trend", "label": "TREND  AI datacenter", "spec": {"think_tank_source": "rules"}}]
    merged = mod._merge_themes(a, b)
    assert len(merged) == 1
    assert merged[0]["spec"]["think_tank_source"] == "llm"


def test_themes_from_signals_research_cluster():
    miner = _load_miner()
    signals = {
        "hermes_research": [
            {"theme": "Nuclear / SMR power", "count": 5, "symbols": ["CCJ", "SMR"], "example": "SMR contract win"},
        ],
        "news_feeds": {"themes": [], "sector_rotation_mentions": 0, "articles_scanned": 0},
        "catalysts": [],
    }
    themes = miner.themes_from_signals(signals)
    assert any("Nuclear" in t["label"] for t in themes)
    assert any("CCJ" in (t.get("spec") or {}).get("seed_symbols", []) for t in themes)


def test_themes_from_signals_news_rotation():
    miner = _load_miner()
    signals = {
        "hermes_research": [],
        "news_feeds": {
            "themes": [{"theme": "Semiconductor supply chain", "count": 12, "feed": "pattern_match"}],
            "sector_rotation_mentions": 8,
            "articles_scanned": 400,
        },
        "catalysts": [{"theme": "earnings_beat", "count": 15}],
    }
    themes = miner.themes_from_signals(signals)
    labels = [t["label"] for t in themes]
    assert any("Semiconductor" in l for l in labels)
    assert any("rotation" in l.lower() for l in labels)
    assert any("earnings" in l.lower() for l in labels)


def test_themes_from_rs_rsi_weekly_leaders():
    miner = _load_miner()
    rs = {
        "weekly_rs_leaders": [
            {"symbol": "NVDA", "perf_week_pct": 12.5, "rsi": 62},
            {"symbol": "SMCI", "perf_week_pct": 10.2, "rsi": 58},
            {"symbol": "ARM", "perf_week_pct": 9.1, "rsi": 55},
            {"symbol": "PLTR", "perf_week_pct": 8.4, "rsi": 60},
        ],
        "sector_rs": [{"sector": "Technology", "avg_perf_week_pct": 4.2, "leaders": ["NVDA", "AMD"], "count": 120}],
        "rsi_momentum": [],
        "rsi_oversold_bounce": [],
    }
    themes = miner.themes_from_rs_rsi(rs)
    assert any("RS momentum" in t["label"] for t in themes)
    assert any("Technology" in t["label"] for t in themes)
    assert "NVDA" in (themes[0].get("spec") or {}).get("seed_symbols", [])


def test_domain_from_url_blocks_aggregators():
    miner = _load_miner()
    assert miner._is_blocked_domain("finance.yahoo.com")
    assert not miner._is_blocked_domain("fintel.io")
    assert miner._domain_from_url("https://www.example.com/path") == "example.com"


def test_mine_all_signals_skip_web():
    miner = _load_miner()

    class FakeCursor:
        def execute(self, *args, **kwargs):
            self._sql = args[0] if args else ""

        def fetchone(self):
            if "max(snapshot_date)" in getattr(self, "_sql", ""):
                return (None,)
            return (None,)

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    out = miner.mine_all_signals(FakeConn(), skip_web=True)
    assert out["web_probe"] == []
    assert "hermes_research" in out
    assert "news_feeds" in out