"""Tests for think_tank_prospect_discovery."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "think_tank_prospect_discovery", ROOT / "scripts" / "think_tank_prospect_discovery.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mine_signal_prospects_rs_leaders(monkeypatch):
    mod = _load()

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        mod,
        "load_portfolio_priority",
        lambda conn: {
            "held": set(),
            "watchlist_active": {"AAPL"},
            "watchlist_directive": set(),
            "watchlist_buy": set(),
            "known_watchlist": {"AAPL"},
        },
        raising=False,
    )
    # import is inside mine_signal_prospects — patch source module
    import momentum_scalp_lead_miner as mslm
    monkeypatch.setattr(mslm, "load_portfolio_priority", lambda conn: {
        "held": set(),
        "watchlist_active": {"AAPL"},
        "watchlist_directive": set(),
        "watchlist_buy": set(),
        "known_watchlist": {"AAPL"},
    })

    prospects = mod.mine_signal_prospects(
        FakeConn(),
        {
            "rs_rsi": {
                "weekly_rs_leaders": [
                    {"symbol": "NVDA", "perf_week_pct": 12.5, "rsi": 62, "sector": "Technology"},
                    {"symbol": "AAPL", "perf_week_pct": 8.0, "rsi": 55, "sector": "Technology"},
                ],
                "rsi_momentum": [],
                "rsi_oversold_bounce": [],
                "sector_rs": [],
            },
            "hermes_research": [],
        },
        max_prospects=10,
    )
    syms = [p["symbol"] for p in prospects]
    assert "NVDA" in syms
    aapl = next(p for p in prospects if p["symbol"] == "AAPL")
    assert aapl["refresh"] is True
    assert "active_watchlist" in aapl["priority_tags"]


def test_pick_directive_sector_match():
    mod = _load()
    directives = [
        {"id": 1, "kind": "sector", "label": "sector Healthcare leadership", "spec": {"gics_sector": "Healthcare"}},
        {"id": 2, "kind": "trend", "label": "trend Weekly RS momentum leaders", "spec": {"keywords": ["relative strength"]}},
    ]
    did = mod._pick_directive(directives, {"symbol": "X", "source": "sector_rs_cluster", "sector": "Healthcare", "thesis": ""})
    assert did == 1


def test_pick_directive_rs_fallback():
    mod = _load()
    directives = [
        {"id": 2, "kind": "trend", "label": "trend Weekly RS momentum leaders", "spec": {"keywords": ["relative strength"]}},
    ]
    did = mod._pick_directive(directives, {"symbol": "FTH", "source": "rs_weekly_leader", "sector": "", "thesis": ""})
    assert did == 2