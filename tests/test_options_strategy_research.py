#!/usr/bin/env python3
"""White-Space Stage 3 — read-only options-chain research (spec Part D).

Covers: parsing the options desk's normalized Schwab chain shape from a
synthetic fixture (mid / spread% / liquidity / feasibility), deep-ITM call
selection on the greeks path AND the ITM%-depth proxy path, extrinsic /
breakeven / max-loss / capital-vs-100-shares arithmetic, earnings-before-
expiry flagging, the honest-degrade contract (weekend / no auth / thin chain
→ available:false, never fabricated numbers), the forced EDUCATIONAL_ONLY
banner, and the read-only guarantee on the schwab_transport surface.

    .venv/bin/python -m pytest tests/test_options_strategy_research.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.strategy_research import options_chain as oc  # noqa: E402

SPOT = 200.0


def _row(side, strike, bid, ask, *, delta=None, iv=0.35, oi=500, vol=50, dte=33):
    return {"exp": "x", "strike": strike, "side": side, "bid": bid, "ask": ask,
            "last": (bid + ask) / 2 if bid and ask else None, "iv": iv,
            "delta": delta, "oi": oi, "volume": vol, "dte": dte}


def _fixture(with_greeks: bool = True) -> dict:
    """Synthetic chain in schwab_transport.normalize_option_chain's shape."""
    def d(v):  # greeks path vs proxy path (delta stripped)
        return v if with_greeks else None
    near_calls = [
        _row("call", 140.0, 60.6, 61.4, delta=d(0.93), oi=800, vol=20),
        _row("call", 160.0, 42.0, 43.0, delta=d(0.88), oi=1500, vol=120),
        _row("call", 170.0, 33.1, 33.9, delta=d(0.84), oi=300, vol=40),
        _row("call", 180.0, 24.0, 26.0, delta=d(0.75), oi=900, vol=200),
        _row("call", 200.0, 12.0, 12.6, delta=d(0.52), oi=2500, vol=900),
        _row("call", 210.0, 7.0, 7.4, delta=d(0.40), oi=1800, vol=400),
    ]
    near_puts = [
        _row("put", 180.0, 3.8, 4.2, delta=d(-0.22), oi=1000, vol=150),
        _row("put", 200.0, 11.5, 12.1, delta=d(-0.48), oi=2000, vol=600),
    ]
    leaps_calls = [
        _row("call", 140.0, 72.0, 76.0, delta=d(0.90), oi=60, vol=0, dte=370),
        _row("call", 160.0, 58.0, 61.0, delta=d(0.83), oi=250, vol=5, dte=370),
        _row("call", 200.0, 33.0, 35.0, delta=d(0.60), oi=900, vol=30, dte=370),
    ]
    return {
        "status": "ok", "symbol": "TEAM", "underlying_price": SPOT,
        "expirations": [
            {"exp": "2026-08-07", "dte": 33, "contracts": 8,
             "total_call_oi": 7800, "total_put_oi": 3000,
             "strikes": near_calls + near_puts},
            {"exp": "2027-07-09", "dte": 370, "contracts": 3,
             "total_call_oi": 1210, "total_put_oi": 0,
             "strikes": leaps_calls},
        ],
    }


# ── chain adapter parses the synthetic fixture ───────────────────────────────

def test_parse_chain_snapshot():
    snap = oc.parse_chain(_fixture(), "TEAM")
    assert snap["available"] is True
    assert snap["symbol"] == "TEAM"
    assert snap["underlying_price"] == SPOT
    assert snap["educational_only"] is True and snap["banner"] == oc.EDUCATIONAL_BANNER
    assert len(snap["expirations"]) == 2
    c160 = next(c for c in snap["expirations"][0]["contracts"]
                if c["side"] == "call" and c["strike"] == 160.0)
    assert c160["mid"] == 42.5
    assert abs(c160["spread_pct"] - (1.0 / 42.5 * 100)) < 0.01
    assert 0 <= c160["liquidity_score"] <= 100
    assert isinstance(snap["liquidity_score"], int)


def test_feasibility_scores_from_fixture():
    feas = oc.parse_chain(_fixture(), "TEAM")["strategy_feasibility"]
    for key in ("deep_itm_call", "covered_call", "cash_secured_put",
                "leaps_long_call", "collar", "protective_put",
                "call_spread", "diagonal_spread", "synthetic_long"):
        assert key in feas
        assert set(feas[key]) == {"feasible", "score", "reason"}
    assert feas["deep_itm_call"]["feasible"] is True
    assert feas["leaps_long_call"]["feasible"] is True  # 370-DTE calls exist


def test_sentinel_greeks_are_discarded():
    raw = _fixture()
    raw["expirations"][0]["strikes"][0]["delta"] = -999.0  # Schwab dead pad
    snap = oc.parse_chain(raw, "TEAM")
    c140 = next(c for c in snap["expirations"][0]["contracts"]
                if c["side"] == "call" and c["strike"] == 140.0)
    assert c140["delta"] is None


# ── deep ITM selection: greeks path ──────────────────────────────────────────

def test_deep_itm_delta_selection_and_arithmetic():
    out = oc.deep_itm_call_analysis("TEAM", snapshot=oc.parse_chain(_fixture(), "TEAM"),
                                    dte_buckets=[30, 60, 365],
                                    earnings_date="2026-07-20")
    assert out["available"] is True
    assert out["selection_modes_used"] == ["delta"]
    assert out["educational_only"] is True and out["banner"] == oc.EDUCATIONAL_BANNER

    b30 = next(b for b in out["dte_buckets"] if b["target_dte"] == 30)
    assert b30["available"] and b30["exp"] == "2026-08-07"
    strikes = {c["strike"] for c in b30["candidates"]}
    assert strikes <= {140.0, 160.0, 170.0}          # delta in [0.80, 0.95] only
    assert 180.0 not in strikes and 200.0 not in strikes

    sel = b30["selected"]
    assert sel["strike"] == 160.0                     # highest liquidity in band
    assert sel["mid"] == 42.5
    assert sel["intrinsic_value"] == 40.0             # S - K
    assert sel["extrinsic_value"] == 2.5              # mid - intrinsic
    assert sel["breakeven"] == 202.5                  # K + mid
    assert sel["max_loss"] == 4250.0                  # mid * 100
    ratio = sel["capital_vs_100_shares"]
    assert ratio["contract_debit"] == 4250.0
    assert ratio["100_shares"] == 20000.0
    assert abs(ratio["capital_ratio_pct"] - 21.25) < 0.01
    assert sel["flags"]["wide_spread"] is False
    assert sel["flags"]["low_oi"] is False
    assert sel["flags"]["earnings_before_expiry"] is True   # 07-20 <= 08-07

    b60 = next(b for b in out["dte_buckets"] if b["target_dte"] == 60)
    assert b60["available"] is False                  # nothing near 60 DTE
    b365 = next(b for b in out["dte_buckets"] if b["target_dte"] == 365)
    assert b365["available"] and b365["exp"] == "2027-07-09"
    assert b365["selected"]["flags"]["earnings_before_expiry"] is True


def test_deep_itm_flags_wide_spread_low_oi_no_volume():
    out = oc.deep_itm_call_analysis("TEAM", snapshot=oc.parse_chain(_fixture(), "TEAM"),
                                    dte_buckets=[365], earnings_date=None)
    sel_pool = {c["strike"]: c for c in out["dte_buckets"][0]["candidates"]}
    c140 = sel_pool[140.0]                            # 72/76 quote, OI 60, vol 0
    assert c140["flags"]["low_oi"] is True
    assert c140["flags"]["no_volume"] is True
    assert c140["flags"]["earnings_before_expiry"] is None  # honestly unknown


# ── deep ITM selection: ITM%-depth proxy path (no greeks) ────────────────────

def test_deep_itm_proxy_selection_without_greeks():
    out = oc.deep_itm_call_analysis("TEAM",
                                    snapshot=oc.parse_chain(_fixture(False), "TEAM"),
                                    dte_buckets=[30], earnings_date=None)
    assert out["available"] is True
    assert out["selection_modes_used"] == ["itm_pct_proxy"]
    b = out["dte_buckets"][0]
    assert b["selection_mode"] == "itm_pct_proxy"
    strikes = {c["strike"] for c in b["candidates"]}
    # depth (S-K)/S must sit in [0.10, 0.35] → K in [130, 180]
    assert strikes <= {140.0, 160.0, 170.0, 180.0}
    assert 200.0 not in strikes


# ── honest degrade: unavailable chain data is NEVER faked ────────────────────

def test_degrade_on_needs_account_link():
    out = oc.parse_chain({"status": "needs_account_link"}, "TEAM")
    assert out["available"] is False
    assert "needs_account_link" in out["reason"]
    assert out["educational_only"] is True and out["banner"] == oc.EDUCATIONAL_BANNER
    assert "expirations" not in out and "underlying_price" not in out


def test_degrade_on_empty_or_garbage_chain():
    assert oc.parse_chain(None, "TEAM")["available"] is False
    assert oc.parse_chain({"status": "ok", "expirations": []}, "TEAM")["available"] is False
    assert oc.parse_chain({"status": "error", "error": "boom"}, "TEAM")["available"] is False


def test_deep_itm_degrades_with_unavailable_snapshot():
    out = oc.deep_itm_call_analysis(
        "TEAM", snapshot={"available": False, "reason": "weekend — no chain"})
    assert out["available"] is False
    assert out["reason"] == "weekend — no chain"
    assert "dte_buckets" not in out and "underlying_price" not in out
    assert out["banner"] == oc.EDUCATIONAL_BANNER


def test_deep_itm_refuses_missing_underlying_price():
    raw = _fixture()
    raw["underlying_price"] = None
    out = oc.deep_itm_call_analysis("TEAM", snapshot=oc.parse_chain(raw, "TEAM"))
    assert out["available"] is False
    assert "underlying price" in out["reason"]


def test_fetch_degrades_when_transport_raises(monkeypatch):
    import types
    stub = types.ModuleType("schwab_transport")
    stub.get_option_chain = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no auth"))
    monkeypatch.setitem(sys.modules, "schwab_transport", stub)
    out = oc.fetch_chain_snapshot("TEAM")
    assert out["available"] is False
    assert "chain read failed" in out["reason"]


def test_fetch_uses_desk_read_path(monkeypatch):
    import types
    calls = {}
    stub = types.ModuleType("schwab_transport")

    def fake_chain(symbol, strike_count=8, **kw):
        calls["symbol"], calls["strike_count"] = symbol, strike_count
        return _fixture()

    stub.get_option_chain = fake_chain
    monkeypatch.setitem(sys.modules, "schwab_transport", stub)
    out = oc.fetch_chain_snapshot("team", strike_count=24)
    assert out["available"] is True
    assert calls == {"symbol": "TEAM", "strike_count": 24}
    assert "get_option_chain" in out["source"]


# ── read-only guarantee on the transport surface ─────────────────────────────

def test_only_get_option_chain_is_touched_on_schwab_transport():
    src = (ROOT / "scripts" / "lib" / "strategy_research" / "options_chain.py"
           ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    touched = {node.attr for node in ast.walk(tree)
               if isinstance(node, ast.Attribute)
               and isinstance(node.value, ast.Name)
               and node.value.id == "schwab_transport"}
    assert touched == {"get_option_chain"}


def test_banner_forced_on_every_entry_point():
    for out in (oc.parse_chain(_fixture(), "TEAM"),
                oc.parse_chain(None, "TEAM"),
                oc.deep_itm_call_analysis(
                    "TEAM", snapshot=oc.parse_chain(_fixture(), "TEAM"),
                    dte_buckets=[30], earnings_date=None)):
        assert out["educational_only"] is True
        assert out.get("banner") == oc.EDUCATIONAL_BANNER
