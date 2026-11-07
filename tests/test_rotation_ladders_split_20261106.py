"""Rotation ladders: unadjusted share splits must not read as sector crashes (2026-11-06).

Synthetic prices only (public repo)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.data_broker import rotation_ladders as rl  # noqa: E402

NOW = datetime.now(timezone.utc)


def _rows(sym, prices):
    """prices: list oldest->newest, one per day ending ~1h ago."""
    n = len(prices)
    return [{"symbol": sym, "price": p, "fetched_at": NOW - timedelta(days=n - 1 - i, hours=1)}
            for i, p in enumerate(prices)]


def _db(rows):
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append(sql)
        return rows
    q.calls = calls
    return q


def test_forward_split_is_back_adjusted():
    # 140 daily closes rising 100 -> ~114, then a 3:1 split 10 days ago.
    prices = [100 + i * 0.1 for i in range(140)]
    for i in range(130, 140):
        prices[i] = prices[i] / 3
    q = {}
    out = rl._sector_momentum_returns(_db(_rows("ITA", prices)), ["ITA"], q)
    r1, r3, r6 = out["ITA"]
    assert all(r is not None for r in (r1, r3, r6))
    assert all(0 < r < 15 for r in (r1, r3, r6)), out
    assert q["ITA"]["split_adjusted"] == 1


def test_reverse_split_is_back_adjusted():
    prices = [50.0] * 140
    for i in range(100, 140):
        prices[i] = 500.0  # 1:10 reverse split, flat otherwise
    out = rl._sector_momentum_returns(_db(_rows("SOXX", prices)), ["SOXX"])
    assert out["SOXX"] == [0.0, 0.0, 0.0]


def test_unexplained_jump_marks_unknown_not_crash():
    prices = [100.0] * 140
    for i in range(135, 140):
        prices[i] = 42.0  # -58%: not an integer split ratio
    q = {}
    out = rl._sector_momentum_returns(_db(_rows("XLK", prices)), ["XLK"], q)
    assert out["XLK"] == [None, None, None]
    assert q["XLK"]["reason"] == "unexplained_price_jump"


def test_normal_moves_unchanged():
    prices = [100.0] * 100 + [100.0 + i for i in range(40)]  # +39% over 40 days, small steps
    out = rl._sector_momentum_returns(_db(_rows("XLE", prices)), ["XLE"])
    assert out["XLE"][2] == 39.0


def test_stale_quotes_and_db_errors_are_unknown_with_reason():
    stale = [{"symbol": "XLU", "price": 70.0, "fetched_at": NOW - timedelta(days=3)}]
    q = {}
    assert rl._sector_momentum_returns(_db(stale), ["XLU"], q)["XLU"] == [None, None, None]
    assert q["XLU"]["reason"] == "no_quote_in_24h"

    def boom(*a, **k):
        raise RuntimeError("db down")
    q2 = {}
    assert rl._sector_momentum_returns(boom, ["XLU"], q2)["XLU"] == [None, None, None]
    assert q2["XLU"]["reason"] == "market_quotes_read_failed"


def test_build_carries_price_quality():
    rows = _rows("XLK", [100.0] * 140)
    out = rl._build(_db(rows))
    xlk = next(s for s in out["sectors"] if s["etf"] == "XLK")
    assert xlk["price_quality"]["status"] == "OK"
    assert xlk["return_6m"] == 0.0
