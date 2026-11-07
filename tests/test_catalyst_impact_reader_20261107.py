"""LQ-20261107-135 — `catalyst_symbol_impact` gets the operator-facing reader it never had.

ANCHOR: CATALYST_SYMBOL_IMPACT_READER_20261107

The lane writes accurate rows (126 on 2026-11-06, 10,306 since 2026-09-15) and no surface showed
them: the only readers were the purge guard and `lib/catalyst_graph`. These tests pin the reader's
contract — typed rows, every user value travelling as a driver parameter, bounded inputs, and the
distinction between "nothing recorded for this symbol" and "nothing in this window".

Hermetic: a fake DB callable records every statement; no database, no network.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import api_v3_catalyst as API  # noqa: E402
from lib import catalyst_impact_reader as R  # noqa: E402

NOW = datetime(2026, 11, 6, 22, 20, 4, tzinfo=timezone.utc)


def _row(**kw):
    base = {
        "id": 9412,
        "symbol": "ANET",
        "strategy_type": "held",
        "expected_direction": "up",
        "expected_magnitude": Decimal("3.7"),
        "price_at_event": Decimal("170.80"),
        "portfolio_impact_pct": Decimal("11.6"),
        "created_at": NOW,
        "catalyst_type": "news_momentum",
        "headline": "Arista Networks Going From Strength To Strength",
        "severity": "medium",
        "impact_score": Decimal("3.7"),
        "source_url": "https://example.invalid/anet",
        "event_at": NOW - timedelta(hours=3),
    }
    base.update(kw)
    return base


class FakeDb:
    def __init__(self, rows=None, last=None):
        self.rows = list(rows or [])
        self.last = last
        self.calls: list[tuple[str, object, str]] = []

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append((str(sql), params, fetch))
        return self.last if fetch == "one" else list(self.rows)


# --- rows -------------------------------------------------------------------------------------------

def test_rows_are_typed_for_the_page():
    db = FakeDb(rows=[_row()], last={"last_row_at": NOW, "rows_written": 42})
    out = R.build(symbol="anet", db=db)
    assert out["status"] == "ok" and out["count"] == 1
    r = out["rows"][0]
    assert r["symbol"] == "ANET"
    assert r["expected_direction"] == "UP"                      # normalised, not the stored lower case
    assert r["expected_magnitude"] == 3.7 and isinstance(r["expected_magnitude"], float)
    assert r["price_at_event"] == 170.8 and r["portfolio_impact_pct"] == 11.6
    assert r["event_at"].startswith("2026-11-06T")              # ISO, not a driver timestamp object
    assert out["authority"]["mutation"] is False


def test_every_user_value_travels_as_a_parameter():
    db = FakeDb(rows=[_row()], last={"last_row_at": NOW, "rows_written": 1})
    R.build(symbol="anet", days=30, limit=7, db=db)
    sql, params, _ = db.calls[0]
    assert "anet" not in sql.lower().replace("catalyst", "")     # the symbol is not spliced into SQL
    assert params == ("ANET", "ANET", 30, 7)
    assert sql.count("%s") == len(params)
    assert sql.lstrip().upper().startswith("SELECT") and "INSERT" not in sql.upper()


def test_the_reader_is_select_only_on_both_statements():
    db = FakeDb(rows=[], last={"last_row_at": NOW, "rows_written": 3})
    R.build(symbol="ANET", db=db)
    for sql, _, _ in db.calls:
        body = sql.strip().upper()
        assert body.startswith("SELECT")
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALTER", "DROP"):
            assert verb not in body


# --- inputs -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["X'; DROP TABLE t;--", "TOOLONGSYMBOL123", "AB CD", "ANET;--"])
def test_a_value_that_is_not_a_ticker_is_refused_not_defaulted(bad):
    db = FakeDb(rows=[_row()])
    with pytest.raises(R.BadRequest):
        R.build(symbol=bad, db=db)
    assert db.calls == []                                        # refused before any SQL ran


def test_an_empty_symbol_means_every_symbol_not_a_refusal():
    db = FakeDb(rows=[])
    out = R.build(symbol="   ", db=db)
    assert out["symbol"] is None
    assert db.calls[0][1] == (None, None, R.DEFAULT_DAYS, R.DEFAULT_LIMIT)


@pytest.mark.parametrize("kw", [{"days": 0}, {"days": 4000}, {"days": "abc"}, {"limit": 0}, {"limit": 999}])
def test_window_and_limit_are_bounded(kw):
    db = FakeDb()
    with pytest.raises(R.BadRequest):
        R.build(symbol="ANET", db=db, **kw)
    assert db.calls == []


def test_defaults_are_named_not_hidden():
    db = FakeDb(rows=[])
    R.build(db=db)
    assert (R.DEFAULT_DAYS, R.DEFAULT_LIMIT) == (90, 25)
    _, params, _ = db.calls[0]
    assert params == (None, None, R.DEFAULT_DAYS, R.DEFAULT_LIMIT)


# --- empty is a statement, not a zero ---------------------------------------------------------------

def test_empty_window_names_when_the_writer_last_recorded():
    db = FakeDb(rows=[], last={"last_row_at": NOW - timedelta(days=120), "rows_written": 9})
    out = R.build(symbol="fcx", db=db)
    assert out["status"] == "no_rows_in_window"
    assert out["count"] == 0
    assert out["rows_written_total"] == 9
    assert out["last_row_at"].startswith("2026-07-09")
    assert "FCX" in out["note"] and "90 days" in out["note"]


def test_a_symbol_the_writer_never_saw_says_so():
    # What count(*) really returns for a symbol with no rows: one row, count 0, max(created_at) NULL.
    db = FakeDb(rows=[], last={"last_row_at": None, "rows_written": 0})
    out = R.build(symbol="ZZZZ", db=db)
    assert out["status"] == "no_rows"
    assert out["rows_written_total"] == 0
    assert "no catalyst impact for ZZZZ" in out["note"]


def test_an_unreadable_count_is_not_a_zero():
    # The count query returned nothing at all: the symbol's history is unknown, so the note must not
    # claim "no catalyst impact" and rows_written_total must stay None rather than become 0.
    db = FakeDb(rows=[], last=None)
    out = R.build(symbol="ZZZZ", db=db)
    assert out["status"] == "no_rows"
    assert out["rows_written_total"] is None
    assert "could not be read" in out["note"] and "not a count of zero" in out["note"]


def test_a_timestamp_without_a_readable_count_still_means_the_symbol_was_seen():
    db = FakeDb(rows=[], last={"last_row_at": NOW - timedelta(days=200), "rows_written": None})
    out = R.build(symbol="FCX", db=db)
    assert out["status"] == "no_rows_in_window"
    assert out["rows_written_total"] is None
    assert "could not be read" in out["note"]


# --- the handler -----------------------------------------------------------------------------------

def test_handler_serves_the_route_and_the_root(monkeypatch):
    monkeypatch.setattr(R, "_db_callable", lambda: FakeDb(rows=[_row()], last={"last_row_at": NOW, "rows_written": 1}))
    for path in ("", "symbol-impact", "/symbol-impact/"):
        status, body = API.handle_get(path, {"symbol": "anet"})
        assert status == 200 and body["ok"] is True
        assert body["schema"] == R.SCHEMA and body["rows"][0]["symbol"] == "ANET"


def test_handler_returns_400_for_a_bad_symbol(monkeypatch):
    monkeypatch.setattr(R, "_db_callable", lambda: FakeDb())
    status, body = API.handle_get("symbol-impact", {"symbol": "bad symbol"})
    assert status == 400 and body["error"] == "bad_request"


def test_handler_says_500_rather_than_an_empty_200(monkeypatch):
    def boom(sql=None, params=None, fetch="all"):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(R, "_db_callable", lambda: boom)
    status, body = API.handle_get("symbol-impact", {"symbol": "ANET"})
    assert status == 500 and body["error"] == "RuntimeError" and "rows" not in body


def test_handler_unknown_path_is_404():
    status, body = API.handle_get("something-else", {})
    assert status == 404 and body["error"] == "not_found"
