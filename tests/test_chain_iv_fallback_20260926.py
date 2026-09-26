"""Watchlist names read IV from their Schwab chain (2026-09-26).

technical_snapshot.json covers holdings only, so after #1248 stopped the constant
12.5 placeholder every watchlist name was refused IV_UNKNOWN (18 of 18). The chain
the engine already reads carries per-contract IV. No network: the chain is stubbed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import options_engine as oe  # noqa: E402


def _chain(price=100.0, iv=32.0):
    rows = [{"side": s, "strike": k, "iv": iv + abs(k - price) / 10, "bid": 1, "ask": 1.1, "oi": 500}
            for k in (90, 95, 100, 105, 110) for s in ("call", "put")]
    return {"status": "ok", "expirations": [{"exp": "2026-10-30", "dte": 34, "strikes": rows},
                                            {"exp": "2026-12-18", "dte": 83, "strikes": rows}]}


def test_atm_iv_is_the_median_near_the_money():
    assert oe._chain_atm_iv_pct(_chain(), 100.0) == 32.5


def test_atm_iv_accepts_decimal_iv_and_ignores_long_dated():
    c = _chain(iv=0.30)
    for e in c["expirations"]:
        for r in e["strikes"]:
            r["iv"] = 0.30
    assert oe._chain_atm_iv_pct(c, 100.0) == 30.0
    assert oe._chain_atm_iv_pct({"expirations": [{"dte": 200, "strikes": []}]}, 100.0) is None


def test_no_technicals_reads_the_chain_when_lookup_is_on(monkeypatch):
    calls = []
    monkeypatch.setattr(oe, "_iv_rank_from_history", lambda *a, **k: None)
    monkeypatch.setattr(oe, "_schwab_chain", lambda sym, strikes=12: calls.append(sym) or _chain())
    assert oe._iv_rank_proxy("AMZN", {}, chain_lookup=True, price=100.0) > oe.MIN_IV_CONVICTION
    assert calls == ["AMZN"]


def test_lookup_off_stays_offline_and_honest(monkeypatch):
    monkeypatch.setattr(oe, "_iv_rank_from_history", lambda *a, **k: None)
    monkeypatch.setattr(oe, "_schwab_chain", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert oe._iv_rank_proxy("AMZN", {}) == 0.0


def test_chain_is_read_once_per_pass(monkeypatch):
    import types
    n = []
    fake = types.SimpleNamespace(get_option_chain=lambda sym, strike_count=12: n.append(sym) or _chain())
    monkeypatch.setitem(sys.modules, "schwab_transport", fake)
    oe._CHAIN_CACHE.clear()
    oe._schwab_chain("AMZN", strikes=16)
    oe._schwab_chain("AMZN", strikes=16)
    assert n == ["AMZN"]
    oe._CHAIN_CACHE.clear()


def test_repair_rerun_writes_no_empty_archive():
    src = (ROOT / "scripts" / "repair_ensemble_jobs.py").read_text(encoding="utf-8")
    assert "if not a.apply or (has_lanes and not ids):" in src
