"""Option spot must be the freshest price, and the chain's own when present (2026-09-26).

DELL's options card used $524.14 from a trade_ai_scans row dated 2026-09-05 while
market_quotes had $563.28 at the 09-25 close: strike distance, POP, breakeven and
edge were all computed on a three-week-old price. No DB or network: stubbed.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import options_engine as oe  # noqa: E402

NOW = datetime.now(timezone.utc)


def _db(monkeypatch, scan, quote):
    def ex(sql, params=None, fetch="one"):
        if "trade_ai_scans" in sql:
            return scan
        if "market_quotes" in sql:
            return quote
        return None
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(USE_DB=True, _execute=ex))
    monkeypatch.setattr(oe, "_DESK_CFG", {"price_max_age_hours": 96})
    oe._PRICE_SOURCE.clear()


def test_newer_quote_beats_a_stale_scan(monkeypatch):
    _db(monkeypatch, {"price": 524.14, "at": NOW - timedelta(days=21)}, {"price": 563.28, "at": NOW - timedelta(hours=20)})
    assert oe._resolve_symbol_price("DELL", {}, []) == 563.28
    assert oe._PRICE_SOURCE["DELL"]["source"] == "market_quotes"


def test_newer_scan_still_wins_when_it_is_fresher(monkeypatch):
    _db(monkeypatch, {"price": 119.40, "at": NOW - timedelta(hours=10)}, {"price": 119.395, "at": NOW - timedelta(hours=20)})
    assert oe._resolve_symbol_price("HOOD", {}, []) == 119.40


def test_every_price_too_old_is_refused(monkeypatch):
    _db(monkeypatch, {"price": 524.14, "at": NOW - timedelta(days=21)}, None)
    monkeypatch.setitem(sys.modules, "market_quote_provider",
                        types.SimpleNamespace(check_fresh_quote=lambda s: {"ok": False}))
    assert oe._resolve_symbol_price("DELL", {}, []) == 0.0


def test_chain_underlying_is_the_option_spot(monkeypatch):
    oe._PRICE_SOURCE.clear()
    monkeypatch.setattr(oe, "_schwab_chain", lambda sym, strikes=12: {"status": "ok", "underlying_price": 563.28})
    assert oe._spot_for("DELL", 524.14) == 563.28
    assert oe._PRICE_SOURCE["DELL"] == {**oe._PRICE_SOURCE["DELL"], "source": "schwab_chain_underlying", "replaced": 524.14}
    monkeypatch.setattr(oe, "_schwab_chain", lambda sym, strikes=12: {"status": "error"})
    assert oe._spot_for("DELL", 563.0) == 563.0
