"""Tests for momentum_scalp_lead_miner."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "momentum_scalp_lead_miner", ROOT / "scripts" / "momentum_scalp_lead_miner.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_merge_lead_keeps_higher_score():
    mod = _load()
    leads = {}
    mod._merge_lead(leads, "NVDA", score=55, thesis="social", source="scalp_scan_results")
    mod._merge_lead(leads, "NVDA", score=48, thesis="quote", source="market_quotes")
    assert leads["NVDA"]["score"] == 55
    assert leads["NVDA"]["source"] == "scalp_scan_results"


def test_merge_lead_accumulates_sources_on_lower_score():
    mod = _load()
    leads = {}
    mod._merge_lead(leads, "SMCI", score=60, thesis="go", source="scalp_scan_results")
    mod._merge_lead(leads, "SMCI", score=50, thesis="news", source="news:feed")
    assert "news:feed" in leads["SMCI"]["sources"]
    assert "scalp_scan_results" in leads["SMCI"]["sources"]


def test_merge_lead_rejects_invalid_symbols():
    mod = _load()
    leads = {}
    mod._merge_lead(leads, "TOOLONG", score=70, thesis="x", source="test")
    mod._merge_lead(leads, "", score=70, thesis="x", source="test")
    assert leads == {}


def test_mine_scalp_leads_rs_adjunct_from_signals(monkeypatch):
    mod = _load()

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(mod, "load_portfolio_priority", lambda conn: {
        "held": set(),
        "watchlist_active": set(),
        "watchlist_directive": set(),
        "watchlist_buy": set(),
        "known_watchlist": set(),
    })

    leads = mod.mine_scalp_leads(
        FakeConn(),
        {
            "catalysts": [],
            "rs_rsi": {
                "rsi_momentum": [
                    {"symbol": "PLTR", "perf_week_pct": 9.5, "rsi": 58},
                ],
            },
        },
        max_leads=10,
    )
    assert len(leads) == 1
    assert leads[0]["symbol"] == "PLTR"
    assert leads[0]["source"] == "rs_rsi_adjunct"


def test_stage_scalp_leads_dry_run_no_db_writes():
    mod = _load()

    class FakeCursor:
        def execute(self, *args, **kwargs):
            raise AssertionError("execute should not run when apply=False")

    class FakeConn:
        def commit(self):
            raise AssertionError("commit should not run when apply=False")

        def cursor(self):
            return FakeCursor()

    result = mod.stage_scalp_leads_to_incubator(
        FakeConn(),
        [{"symbol": "AAPL", "score": 72, "source": "scalp_scan_results", "thesis": "GO"}],
        apply=False,
    )
    assert result["staged"] == 1
    assert result["detail"][0]["symbol"] == "AAPL"


def test_priority_boost_for_held_and_active():
    mod = _load()
    priority = {
        "held": {"TSLA"},
        "watchlist_active": {"AAPL"},
        "watchlist_directive": set(),
        "watchlist_buy": set(),
    }
    boost, tags = mod._priority_boost_for_symbol("TSLA", priority)
    assert boost == mod.HELD_SCORE_BOOST
    assert tags == ["held"]

    boost, tags = mod._priority_boost_for_symbol("AAPL", priority)
    assert boost == mod.ACTIVE_WATCHLIST_BOOST
    assert tags == ["active_watchlist"]

    boost, tags = mod._priority_boost_for_symbol("XYZ", priority)
    assert boost == 0.0
    assert tags == []


def test_apply_priority_boosts():
    mod = _load()
    leads = {
        "TSLA": {"symbol": "TSLA", "score": 50.0, "source": "market_quotes"},
        "RAND": {"symbol": "RAND", "score": 60.0, "source": "market_quotes"},
    }
    priority = {
        "held": {"TSLA"},
        "watchlist_active": set(),
        "watchlist_directive": set(),
        "watchlist_buy": set(),
    }
    boosted = mod._apply_priority_boosts(leads, priority)
    assert boosted == 1
    assert leads["TSLA"]["score"] == 60.0
    assert leads["TSLA"]["priority_tags"] == ["held"]
    assert "priority_boost" not in leads["RAND"]


def test_run_scalp_lead_pipeline_shape():
    mod = _load()

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    import momentum_scalp_lead_miner as mslm
    mslm.load_portfolio_priority = lambda conn: {
        "held": set(),
        "watchlist_active": set(),
        "watchlist_directive": set(),
        "watchlist_buy": set(),
        "known_watchlist": set(),
    }

    report = mod.run_scalp_lead_pipeline(FakeConn(), {"rs_rsi": {"rsi_momentum": []}}, apply=False)
    assert "mined" in report
    assert "priority_boosted" in report
    assert "portfolio_refresh" in report
    assert "incubator" in report
    assert "updated_at" in report
    assert report["incubator"]["staged"] == 0