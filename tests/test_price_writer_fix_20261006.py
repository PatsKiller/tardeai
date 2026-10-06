"""Stale-price overwrites of holdings.json (2026-10-06, 12:01 / 13:01 / 14:00 ET).

portfolio_live_monitor.py loaded the book once and, every hour, repriced its in-memory copy and saved it back;
when its Finviz fetch came back empty the fallback marked 22 of 25 held rows at 10-02 cached closes with 0% day
change. Fixes: the monitor no longer writes holdings.json; the repricer refuses a near-empty live fetch in market
hours; the health agent raises portfolio_stale_marks (critical) and auto-reruns the repricer.
Fakes only: no network, no database, no broker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_live_monitor_never_writes_holdings():
    src = (ROOT / "scripts" / "portfolio_live_monitor.py").read_text()
    assert "save_state(" not in src and "reprice_portfolio" not in src


def _book():
    return {"holdings": [
        {"symbol": "SCHD", "account": "schwab_rollover_ira", "shares": 4000.0, "price": 32.9,
         "price_source": "finviz_elite", "day_change": 660.0, "day_change_pct": 0.61},
        {"symbol": "SPCX", "account": "schwab_rollover_ira", "shares": 300.0, "price": 174.0,
         "price_source": "finviz_elite", "day_change": 819.0, "day_change_pct": 1.6},
    ], "portfolio_totals": {"total_value": 1.0, "day_change": 1479.0}}


def test_repricer_refuses_an_empty_live_fetch_in_market_hours(tmp_path, monkeypatch):
    import portfolio_repricer as pr
    monkeypatch.setattr(pr, "_get_all_symbols", lambda p, r: {"finviz": ["SCHD", "SPCX"], "fidelity": [],
                                                              "schwab": ["SCHD", "SPCX"], "watchlist": []})
    monkeypatch.setattr(pr, "_fetch_finviz", lambda syms, root: {})
    monkeypatch.setattr(pr, "_is_market_hours", lambda now=None: True)
    monkeypatch.setattr(pr, "_fetch_fidelity_from_cache",
                        lambda syms, root: {s: {"price": 1.0, "source": "price_cache_nav"} for s in syms})
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    book = _book()
    before = json.dumps(book["holdings"], sort_keys=True)
    out = pr.reprice_portfolio(book, state)
    assert out.get("_reprice_refused")
    assert json.dumps(out["holdings"], sort_keys=True) == before      # last good marks stand


def test_repricer_main_does_not_rewrite_the_file_when_refused():
    src = (ROOT / "scripts" / "portfolio_repricer.py").read_text()
    blk = src[src.index("portfolio = reprice_portfolio(portfolio, state_dir)\n    if portfolio.pop"):]
    assert blk.index("raise SystemExit(3)") < blk.index("_payload = json.dumps")


def test_min_live_coverage_is_config():
    import yaml
    pos = yaml.safe_load((ROOT / "config" / "portfolio_positions.yaml").read_text())["positions"]
    assert pos["reprice_min_live_coverage"] == 0.5


def test_stale_marks_finding_is_critical_and_auto_remediated():
    import health_agent as ha
    hp = {"holdings": [{"symbol": f"S{i}", "market_value": 1000, "price_source": "price_cache_nav"} for i in range(5)]
          + [{"symbol": "CASH", "is_cash": True, "market_value": 9, "price_source": "price_cache_nav"}]}
    f = ha._check_portfolio_stale_marks(hp, {}, market_open=True, max_rows=3)
    assert len(f) == 1 and f[0]["type"] == "portfolio_stale_marks" and f[0]["severity"] == "critical"
    assert f[0]["count"] == 5                                         # cash rows are not counted
    assert ha._check_portfolio_stale_marks(hp, {}, market_open=False, max_rows=3) == []
    assert ha._check_portfolio_stale_marks(hp, {}, market_open=True, max_rows=5) == []
    pol = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())
    assert "portfolio_stale_marks" in pol["auto_remediate"]["finding_types"]
    assert pol["remediation_map"]["portfolio_stale_marks"].endswith("scripts/portfolio_repricer.py")
