"""ANCHOR: WATCHLIST_SWEEP_KEEPS_PRICE_20261107 — LQ-20261107-56: a failed price lookup never overwrites a known price with NULL."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import watchlist_enrichment_sweep as W  # noqa: E402


class _Cur:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


def _write(price, chg=None):
    cur = _Cur()
    W._write_row(cur, "CXMT", rsi=55.0, trend="neutral", score=60, advisory="RSI 55 · band mid", price=price, chg=chg,
                 floatm=10.0, rvol=1.2, score_kind="technical")
    return cur.calls[0]


def test_failed_lookup_keeps_the_last_good_price_and_marks_the_row_stale():
    sql, params = _write(None)
    assert "price=COALESCE(%s, price)" in sql                       # NULL in -> the stored price stays
    assert "change_pct=CASE WHEN %s::numeric IS NULL THEN change_pct ELSE %s END" in sql
    assert params[4] is None and params[5] is None                  # price and its change% are both "not known"
    assert params[3].endswith(W.STALE_PRICE_NOTE) and "price stale" in params[3]
    assert "last_enriched_at=NOW()" in sql                          # rotation continues: a never-priced symbol cannot hog the queue


def test_fresh_price_replaces_price_and_change_and_is_not_marked_stale():
    sql, params = _write(391.16, 1.5)
    assert params[4] == 391.16 and params[5] == 391.16 and params[6] == 1.5
    assert "stale" not in params[3]


def test_no_unconditional_price_assignment_remains_in_the_sweep():
    src = (ROOT / "scripts" / "watchlist_enrichment_sweep.py").read_text(encoding="utf-8")
    assert "price=%s," not in src.replace("price=COALESCE(%s, price),", "")
    assert src.count("UPDATE watchlist_items SET") == 1             # one writer, so the guarantee holds everywhere
