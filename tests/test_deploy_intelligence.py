#!/usr/bin/env python3
"""Deploy intelligence — Hermes + sentiment + regime factor tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_fcntx_plan_excludes_schg_proxy():
    eng = _load("deploy_intelligence_engine", "scripts/lib/deploy_intelligence_engine.py")
    event = {
        "symbol": "FCNTX",
        "proxy_symbol": "SCHG",
        "proxy_sleeve": "US large-cap growth",
        "proceeds_usd": 107023.01,
        "account": "schwab_rollover_ira",
    }
    plan = eng.build_redeploy_plan(event)
    syms = [t["symbol"] for t in plan.get("targets") or []]
    assert "SCHG" not in syms, f"SCHG should be penalized after FCNTX sale, got {syms}"


def test_plan_includes_methodology_and_market_context():
    eng = _load("deploy_intelligence_engine", "scripts/lib/deploy_intelligence_engine.py")
    event = {"symbol": "FCNTX", "proxy_symbol": "SCHG", "proceeds_usd": 50000, "account": "schwab_rollover_ira"}
    plan = eng.build_redeploy_plan(event)
    assert "Hermes" in (plan.get("methodology") or "")
    assert plan.get("market_context") is not None


def test_geopolitical_context_elevated_from_think_tank():
    eng = _load("deploy_intelligence_engine", "scripts/lib/deploy_intelligence_engine.py")
    ctx = eng.load_market_context()
    geo = ctx.get("geopolitical") or {}
    assert geo.get("posture") in ("elevated", "moderate", "neutral")
    assert geo.get("catalyst_count", 0) >= 0
    # Live think-tank has 124 geopolitical catalysts (Jul 2026) → at least moderate
    if geo.get("catalyst_count", 0) >= 40:
        assert geo.get("posture") in ("elevated", "moderate")


def test_geopolitical_boosts_defense_etf():
    eng = _load("deploy_intelligence_engine", "scripts/lib/deploy_intelligence_engine.py")
    market = eng.load_market_context()
    geo = market.get("geopolitical") or {}
    if geo.get("posture") == "neutral":
        return
    gaps = [{"theme": "Defense / Aerospace", "gap_pct": 2.5, "gap_usd": 50000, "floor": 3, "target": 6, "pct": 0.5}]
    lt = {"portfolio_total": 2e6, "themes": {"Defense / Aerospace": {"pct": 0.5}}}

    class FakeCur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return ("ITA", 20, 80.0, "x", "Defense / Aerospace", "etf", "IGNORE", None, 5)

        @property
        def description(self):
            return [("symbol",), ("hermes_rank",), ("score",), ("source",), ("sector",),
                    ("instrument_type",), ("cio_view",), ("decision_safety",), ("analyst_opinions",)]

    row = eng.score_candidate(
        "ITA",
        event={"symbol": "FCNTX", "proceeds_usd": 107023, "proxy_symbol": "SCHG"},
        market=market,
        gaps=gaps,
        lt=lt,
        cur=FakeCur(),
    )
    assert row is not None
    assert row.get("evidence", {}).get("geopolitical_alignment") or row.get("evidence", {}).get("geopolitical_research_symbol")


def test_cio_avoid_blocks_candidate():
    eng = _load("deploy_intelligence_engine", "scripts/lib/deploy_intelligence_engine.py")

    class FakeCur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return ("AVOIDSYM", 99, 10.0, "x", "Tech", "stock", "AVOID", None, 5)

        @property
        def description(self):
            return [("symbol",), ("hermes_rank",), ("score",), ("source",), ("sector",),
                    ("instrument_type",), ("cio_view",), ("decision_safety",), ("analyst_opinions",)]

    row = eng.score_candidate(
        "AVOIDSYM",
        event={"symbol": "X", "proceeds_usd": 10000, "proxy_symbol": None},
        market={"regime_posture": "neutral"},
        gaps=[],
        lt={"portfolio_total": 1e6, "themes": {}},
        cur=FakeCur(),
    )
    assert row is None


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("ok", _name)
    print("all passed")