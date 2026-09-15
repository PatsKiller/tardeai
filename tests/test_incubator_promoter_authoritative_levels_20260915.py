"""2026-09-15: the incubator promoter proposes from the symbol's real plan, not 2R geometry."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _stub_missing():
    """CI's source-only runner has no psycopg2 / python-dotenv; the functions under test use neither."""
    import types
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
    except ImportError:
        pg = types.ModuleType("psycopg2")
        pg.extras = types.ModuleType("psycopg2.extras")
        pg.extras.RealDictCursor = object
        pg.connect = lambda *a, **k: None
        sys.modules["psycopg2"], sys.modules["psycopg2.extras"] = pg, pg.extras
    try:
        import dotenv  # noqa: F401
    except ImportError:
        dm = types.ModuleType("dotenv")
        dm.load_dotenv = lambda *a, **k: False
        sys.modules["dotenv"] = dm


def _promoter():
    _stub_missing()
    spec = importlib.util.spec_from_file_location("inc_promoter_t", ROOT / "scripts" / "incubator_proposal_promoter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self, rows):
        self.rows = list(rows)
    def execute(self, sql, params=None):
        self.last = sql
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class _Conn:
    def __init__(self, rows):
        self.c = _Cur(rows)
    def cursor(self, *a, **k):
        return self.c
    def rollback(self):
        pass


def test_uses_resolved_card_levels_and_keeps_the_source(monkeypatch):
    mod = _promoter()
    import broker_trade_plan_gate as btpg
    seen = {}
    def fake_resolve(conn, sym, candidate=None, quote_cache=None):
        seen.update(candidate=candidate, quote_cache=quote_cache)
        return {"entry": 50.0, "stop": 46.0, "target": 60.0, "plan_source": "watchlist_card",
                "exit_rationale": {"sources": ["stop from watchlist strategy card", "target from watchlist strategy card"]}}
    monkeypatch.setattr(btpg, "resolve_authoritative_levels", fake_resolve)
    conn = _Conn([(49.5, 46.0, 60.0, 45.0, 62.0, "swing_trade"), (50.0, 49.0, 50.5)])
    out = mod.authoritative_levels_for(conn, "abc", 50.2)
    assert out["entry"] == 50.0 and out["stop"] == 46.0 and out["target"] == 60.0
    assert out["plan_source"] == "watchlist_card" and "strategy card" in out["exit_rationale"]["sources"][0]
    assert seen["candidate"]["card_stop"] == 46.0 and seen["candidate"]["entry_zone_high"] == 50.5
    assert seen["quote_cache"] == {"ABC": 50.2}


def test_no_plan_falls_back_to_none(monkeypatch):
    mod = _promoter()
    import broker_trade_plan_gate as btpg
    monkeypatch.setattr(btpg, "resolve_authoritative_levels", lambda *a, **k: None)
    assert mod.authoritative_levels_for(_Conn([None, None]), "XYZ", 10.0) is None


def test_invalid_resolved_geometry_is_rejected(monkeypatch):
    mod = _promoter()
    import broker_trade_plan_gate as btpg
    monkeypatch.setattr(btpg, "resolve_authoritative_levels",
                        lambda *a, **k: {"entry": 10.0, "stop": 11.0, "target": 12.0, "plan_source": "x"})
    assert mod.authoritative_levels_for(_Conn([None, None]), "XYZ", 10.0) is None


def test_gate_accepts_card_sourced_levels_and_blocks_geometry():
    import pre_promotion_readiness_policy as ppr
    base = {"symbol": "ABC", "strategy_id": "swing_trade", "catalyst": "contract win", "catalyst_verified": True,
            "scan_age_hours": 1.0, "quote_age_hours": 0.5}
    geometry = dict(base, proposed_entry=50.0, proposed_stop=47.5, proposed_target1=55.0, proposed_rr=2.0)
    assert any("no_authoritative_trade_plan" in b for b in ppr.evaluate_pre_promotion_readiness(geometry)["blockers"])
    card = dict(base, proposed_entry=50.0, proposed_stop=46.0, proposed_target1=60.0, proposed_rr=2.5,
                sizing_basis={"plan_source": "watchlist_card", "exit_rationale": {
                    "sources": ["stop from watchlist strategy card", "target from watchlist strategy card"]}})
    assert not any("no_authoritative_trade_plan" in b for b in ppr.evaluate_pre_promotion_readiness(card)["blockers"])


def test_run_prefers_authoritative_levels_and_persists_sizing_basis():
    src = (ROOT / "scripts" / "incubator_proposal_promoter.py").read_text(encoding="utf-8")
    i_auth = src.index("_auth = authoritative_levels_for(conn, symbol, scan_price)")
    i_geo = src.index("entry, stop, target, shares = compute_levels(scan_price)", i_auth)
    assert i_auth < i_geo
    assert '"sizing_basis": _sizing_basis,' in src
    assert "llm_review_status, agent_review_status, sizing_basis)" in src
    assert "json.dumps(_sizing_basis) if _sizing_basis else None," in src
