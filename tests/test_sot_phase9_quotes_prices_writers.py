"""One Source of Truth, Phase 9: one write module per store for ``market_quotes``
(domain quote_price) and ``ticker_prices`` (domain technicals).

Before: three files carried their own INSERT for market_quotes and four for
ticker_prices (config/data_source_authority_baseline.json records the ceilings
3 and 4). Each path had its own column list, conflict rule and coercions -- the
same shape as the Finviz column shift, where a 1-5 rating column carried
ten-year performance for five months because two parsers each owned a write.

After: scripts/lib/writers/market_quotes_writer.py and
scripts/lib/writers/ticker_prices_writer.py are the only files whose text
contains the INSERT for their table; the registry's writer_target modules
(external_market_data_ingest, portfolio_repricer) re-export them; every legacy
producer calls them.

These tests are offline: a fake cursor records SQL + params; nothing touches a
database; the identity registry is pinned to a temp file (autouse) so no test
reads the production registry. For each legacy writer there is a golden test
that feeds the input the legacy code fed and asserts the module issues the
equivalent statement -- same target columns, same conflict clause, same values
after coercion.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import types
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_data_source_authority as gate  # noqa: E402
from lib.writers import market_quotes_writer as mq  # noqa: E402
from lib.writers import ticker_prices_writer as tp  # noqa: E402
from lib.writers.receipt import DERIVED_ALIAS, NOT_APPLICABLE, RESOLVED, WriteReceipt  # noqa: E402
from scripts.lib import identity_registry as reg  # noqa: E402
from scripts.lib.security_identity import resolve_identity_spine  # noqa: E402

AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
BASELINE = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())
WRITER_RE = r"\b(INSERT\s+INTO|UPDATE|COPY)\s+{table}\b"


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """No test here may read the production identity registry."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))
    reg._CACHE.clear()


# ── fakes ────────────────────────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, rowcount: int = 1, fetchone=None, fetchall=None):
        self.calls: list[tuple[str, object]] = []
        self.rowcount = rowcount
        self._one = fetchone
        self._all = fetchall or []
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        self.closed = True

    @property
    def sqls(self) -> list[str]:
        return [norm(s) for s, _ in self.calls]


class FakeConn:
    def __init__(self, cur: FakeCursor | None = None):
        self.cur = cur or FakeCursor()
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


def norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def columns_of(sql: str) -> list[str]:
    m = re.search(r"INSERT INTO \w+ \(([^)]*)\)", norm(sql))
    assert m, sql
    return [c.strip() for c in m.group(1).split(",")]


class _TS:
    """pandas.Timestamp stand-in: the yfinance index type both backfills iterate."""

    def __init__(self, d: date):
        self._d = d

    def date(self) -> date:
        return self._d


# ── market_quotes: golden tests, one per legacy writer ───────────────────────


def test_golden_watchlist_sweep_yfinance_backfill():
    """Legacy (watchlist_enrichment_sweep._price):
    INSERT INTO market_quotes (symbol, price, day_change_pct, source, fetched_at)
    VALUES (%s,%s,%s,'yfinance',NOW()).  fetched_at=NOW() is the column's DB default,
    so the module leaves it to the default; the other four columns and values match."""
    cur = FakeCursor()
    rc = mq.write_market_quotes(cur, [{"symbol": "SPCX", "price": 24.5, "day_change_pct": 2.08}],
                                source="yfinance")
    assert len(cur.calls) == 1
    sql, params = cur.calls[0]
    assert set(columns_of(sql)) == {"symbol", "source", "price", "day_change_pct"}
    assert dict(zip(columns_of(sql), params)) == {"symbol": "SPCX", "source": "yfinance",
                                                  "price": 24.5, "day_change_pct": 2.08}
    assert "ON CONFLICT" not in norm(sql)
    assert rc.rows_in == rc.rows_accepted == rc.rows_written == 1 and rc.rows_rejected == []
    assert rc.table == "market_quotes" and rc.source == "yfinance"


def test_golden_api_v2_protective_stop_refresh():
    """Legacy (api_v2._protective_stop_refresh_quote):
    INSERT INTO market_quotes (symbol, source, price, fetched_at) VALUES (%s,%s,%s,%s)
    with source 'refresh:<provider>' and fetched_at = the quote's own UTC event time."""
    ts = datetime(2026, 9, 11, 14, 30, 5, tzinfo=timezone.utc)
    cur = FakeCursor()
    mq.write_market_quotes(cur, [{"symbol": "NVDA", "price": 182.31, "fetched_at": ts}],
                           source="refresh:schwab")
    sql, params = cur.calls[0]
    assert columns_of(sql) == ["symbol", "source", "price", "fetched_at"]
    assert params == ("NVDA", "refresh:schwab", 182.31, ts)


def test_golden_ingest_yfinance_thirteen_columns():
    """Legacy (external_market_data_ingest.ingest_yfinance_quotes): thirteen columns in
    this order, with None for any yfinance field the info dict lacked."""
    info = {"currentPrice": 101.5, "previousClose": 100.0, "regularMarketChangePercent": 1.5,
            "volume": 1234567, "averageVolume": 2000000, "marketCap": 50_000_000_000,
            "trailingPE": 21.7, "forwardPE": None, "dividendYield": 0.012,
            "fiftyTwoWeekHigh": 120.0}  # fiftyTwoWeekLow absent -> None, as before
    cur = FakeCursor()
    mq.write_market_quotes(cur, [{
        "symbol": "AAPL", "price": info["currentPrice"],
        "prev_close": info.get("previousClose"), "day_change_pct": info.get("regularMarketChangePercent"),
        "volume": info.get("volume"), "avg_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"), "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"), "dividend_yield": info.get("dividendYield"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"), "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
    }], source="yfinance")
    sql, params = cur.calls[0]
    assert columns_of(sql) == ["symbol", "source", "price", "prev_close", "day_change_pct",
                               "volume", "avg_volume", "market_cap", "pe_ratio", "forward_pe",
                               "dividend_yield", "fifty_two_week_high", "fifty_two_week_low"]
    assert params == ("AAPL", "yfinance", 101.5, 100.0, 1.5, 1234567, 2000000, 50_000_000_000,
                      21.7, None, 0.012, 120.0, None)


@pytest.mark.parametrize("source", ["alpaca", "finviz"])
def test_golden_ingest_alpaca_and_finviz_six_columns(source):
    """Legacy: INSERT INTO market_quotes (symbol, source, price, prev_close, day_change_pct, volume)
    VALUES (%s, '<source>', %s, %s, %s, %s)."""
    cur = FakeCursor()
    mq.write_market_quotes(cur, [{"symbol": "TMHC", "price": 61.2, "prev_close": 60.0,
                                  "day_change_pct": 2.0, "volume": 555}], source=source)
    sql, params = cur.calls[0]
    assert columns_of(sql) == ["symbol", "source", "price", "prev_close", "day_change_pct", "volume"]
    assert params == ("TMHC", source, 61.2, 60.0, 2.0, 555)


def test_market_quotes_is_an_append_only_ledger_no_conflict_clause():
    """No legacy writer declared ON CONFLICT; the module must not invent one."""
    cur = FakeCursor()
    mq.write_market_quotes(cur, [{"symbol": "A", "price": 1.0}], source="alpaca")
    assert "conflict" not in cur.sqls[0].lower()
    assert mq.CONFLICT_RULE.startswith("none")


# ── ticker_prices: golden tests, one per legacy writer ───────────────────────


def test_golden_portfolio_repricer_today_row_overwrite():
    """Legacy (portfolio_repricer._sync_ticker_prices):
      UPDATE ... SET close_price=%s, source='portfolio_repricer' WHERE symbol=%s AND price_date=CURRENT_DATE
      if rowcount == 0: INSERT (symbol, price_date, close_price, source, created_at)
                        VALUES (%s, CURRENT_DATE, %s, 'portfolio_repricer', now())
    Under the (symbol, price_date) unique index that is exactly an upsert that overwrites
    close_price and source. The holdings price is written as given (no rounding)."""
    cur = FakeCursor()
    rc = tp.write_ticker_prices(cur, [{"symbol": "NVDA", "price_date": None, "close_price": 182.3456789}],
                                source="portfolio_repricer", on_conflict="overwrite",
                                round_to=None, stamp_created_at=True)
    assert cur.sqls == [
        "INSERT INTO ticker_prices (symbol, price_date, close_price, source, created_at) "
        "VALUES (%s, CURRENT_DATE, %s, %s, now()) "
        "ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price, source = EXCLUDED.source"
    ]
    assert cur.calls[0][1] == ("NVDA", 182.3456789, "portfolio_repricer")
    assert rc.rows_accepted == 1 and rc.rows_rejected == []


def test_golden_price_db_sync_finviz_overwrite():
    """Legacy: INSERT (symbol, price_date, close_price, source) VALUES (%s, %s, %s, 'finviz')
    ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price, source = 'finviz'
    with today as an ISO string and round(price, 4)."""
    cur = FakeCursor()
    tp.write_ticker_prices(cur, [{"symbol": "SCHD", "price_date": "2026-09-11", "close_price": 27.123456}],
                           source="finviz", on_conflict="overwrite", round_to=4)
    sql, params = cur.calls[0]
    assert columns_of(sql) == ["symbol", "price_date", "close_price", "source"]
    assert "ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price, source = EXCLUDED.source" in norm(sql)
    assert params == ("SCHD", date(2026, 9, 11), 27.1235, "finviz")


def test_golden_price_db_sync_holdings_do_nothing():
    cur = FakeCursor()
    tp.write_ticker_prices(cur, [{"symbol": "FCNTX", "price_date": "2026-09-11", "close_price": 19.00001}],
                           source="holdings", on_conflict="nothing", round_to=4)
    sql, params = cur.calls[0]
    assert norm(sql).endswith("ON CONFLICT (symbol, price_date) DO NOTHING")
    assert "DO UPDATE" not in norm(sql)
    assert params == ("FCNTX", date(2026, 9, 11), 19.0, "holdings")


def test_golden_yfinance_backfill_shared_by_redeploy_and_price_db_sync():
    """Legacy (lib/redeploy_price_history.backfill_symbol_history and
    price_db_sync.backfill_yfinance_history, identical SQL):
    INSERT (symbol, price_date, close_price, source) VALUES (%s,%s,%s,'yfinance')
    ON CONFLICT (symbol, price_date) DO NOTHING with idx.date() and round(px, 4);
    the count returned is the sum of rowcount (0 on a conflict)."""
    cur = FakeCursor(rowcount=1)
    rows = [{"symbol": "SCHD", "price_date": _TS(date(2021, 9, 10)), "close_price": 75.123456},
            {"symbol": "SCHD", "price_date": _TS(date(2021, 9, 13)), "close_price": 75.5}]
    rc = tp.write_ticker_prices(cur, rows, source="yfinance", on_conflict="nothing", round_to=4)
    assert len(cur.calls) == 2
    for (sql, params), want in zip(cur.calls, [("SCHD", date(2021, 9, 10), 75.1235, "yfinance"),
                                               ("SCHD", date(2021, 9, 13), 75.5, "yfinance")]):
        assert columns_of(sql) == ["symbol", "price_date", "close_price", "source"]
        assert norm(sql).endswith("ON CONFLICT (symbol, price_date) DO NOTHING")
        assert params == want
    assert rc.rows_written == 2
    cur0 = FakeCursor(rowcount=0)  # every row already present
    assert tp.write_ticker_prices(cur0, rows, source="yfinance").rows_written == 0


LEGACY_RESTORE_SQL = """INSERT INTO ticker_prices (symbol, price_date, close_price, source, created_at)
           SELECT symbol, price_date, close_price, source, created_at
             FROM ticker_prices_quarantine WHERE symbol = %s
           ON CONFLICT DO NOTHING"""


def test_golden_scrub_restore_sql_is_verbatim_and_symbol_passes_through():
    cur = FakeCursor(rowcount=3)
    rc = tp.restore_ticker_prices_from_quarantine(cur, "NVDA")
    assert cur.calls == [(tp.RESTORE_SQL, ("NVDA",))]
    assert norm(tp.RESTORE_SQL) == norm(LEGACY_RESTORE_SQL)
    assert rc.rows_written == 3 and rc.conflict_rule == "ON CONFLICT DO NOTHING"
    # not normalised: the scrub's DELETE of the quarantine copies uses the same argument
    cur2 = FakeCursor()
    tp.restore_ticker_prices_from_quarantine(cur2, "nvda")
    assert cur2.calls[0][1] == ("nvda",)


def _legacy_quotes_sync_sql(symbol_filter: str) -> str:
    return f"""WITH candidates AS (
               SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                      UPPER(symbol) AS symbol, fetched_at::date AS price_date, price
               FROM market_quotes
               WHERE price IS NOT NULL AND price > 0
                 {symbol_filter}
               ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
           ),
           bounded AS (
               SELECT c.symbol, c.price_date, c.price, prior.close_price AS prior_price
               FROM candidates c
               LEFT JOIN LATERAL (
                   SELECT tp.close_price FROM ticker_prices tp
                   WHERE tp.symbol = c.symbol AND tp.price_date < c.price_date
                   ORDER BY tp.price_date DESC LIMIT 1
               ) prior ON true
           )
           INSERT INTO ticker_prices (symbol, price_date, close_price, source)
           SELECT symbol, price_date, price, 'market_quotes'
           FROM bounded
           WHERE prior_price IS NULL
              OR price BETWEEN prior_price * %(min_ratio)s AND prior_price * %(max_ratio)s
           ON CONFLICT (symbol, price_date) DO UPDATE SET
             close_price = EXCLUDED.close_price,
             source = CASE
               WHEN ticker_prices.source IN ('finviz', 'holdings', 'portfolio_repricer')
               THEN ticker_prices.source
               ELSE EXCLUDED.source
             END"""


@pytest.mark.parametrize("symbols,flt", [
    (["nvda", "SCHD"], "AND UPPER(symbol) = ANY(%(syms)s)"),
    (None, ""),
])
def test_golden_price_db_sync_quotes_to_closes_is_verbatim(symbols, flt):
    cur = FakeCursor(rowcount=7)
    rc = tp.sync_ticker_prices_from_market_quotes(cur, symbols, min_ratio=0.1, max_ratio=10.0)
    sql, params = cur.calls[0]
    assert norm(sql) == norm(_legacy_quotes_sync_sql(flt))
    assert params == {"syms": [s.upper() for s in (symbols or [])], "min_ratio": 0.1, "max_ratio": 10.0}
    assert rc.rows_written == 7 and rc.source == "market_quotes"


def test_only_two_conflict_rules_exist_for_ticker_prices():
    assert set(tp.CONFLICT_RULES) == {"nothing", "overwrite"}
    with pytest.raises(ValueError):
        tp.write_ticker_prices(FakeCursor(), [], source="x", on_conflict="merge")


# ── through the migrated producers (fakes injected, no DB) ───────────────────


def test_producer_scrub_restore_calls_module_then_deletes_quarantine_copy():
    from scripts import scrub_ticker_price_outliers as scrub

    conn = FakeConn(FakeCursor(rowcount=2))
    assert scrub.restore(conn, "NVDA") == 2
    assert conn.cur.sqls == [norm(tp.RESTORE_SQL), "DELETE FROM ticker_prices_quarantine WHERE symbol = %s"]
    assert conn.cur.calls[1][1] == ("NVDA",)
    assert conn.committed == 1
    # the detector is untouched: the quarantine INSERT still precedes the live DELETE
    src = inspect.getsource(scrub.apply_quarantine)
    assert 0 <= src.find("INSERT INTO ticker_prices_quarantine") < src.find("DELETE FROM ticker_prices WHERE id")


def test_producer_portfolio_repricer_sync_uses_module_with_legacy_contract(monkeypatch, tmp_path):
    import portfolio_repricer as pr

    conn = FakeConn()
    fake_pg = types.SimpleNamespace(connect=lambda **kw: conn)
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    portfolio = {"holdings": [
        {"symbol": "NVDA", "price": 182.5},
        {"symbol": "NVDA", "price": 1.0},                    # duplicate symbol: skipped, as before
        {"symbol": "CASH", "price": 1.0, "is_cash": True},   # cash: skipped, as before
        {"symbol": "BAD", "price": -3.0},                    # px <= 0: producer skips, as before
    ]}
    pr._sync_ticker_prices(portfolio, tmp_path)
    assert len(conn.cur.calls) == 1
    sql, params = conn.cur.calls[0]
    assert "VALUES (%s, CURRENT_DATE, %s, %s, now())" in norm(sql)
    assert "DO UPDATE SET close_price = EXCLUDED.close_price, source = EXCLUDED.source" in norm(sql)
    assert params == ("NVDA", 182.5, "portfolio_repricer")
    assert conn.committed == 1 and conn.closed
    assert pr.write_ticker_prices is tp.write_ticker_prices  # writer_target re-exports the module


def test_producer_watchlist_sweep_backfills_through_module(monkeypatch):
    import watchlist_enrichment_sweep as wes

    class _Ticker:
        def __init__(self, sym):
            self.info = {"regularMarketPrice": 24.5, "regularMarketPreviousClose": 24.0}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))
    conn = FakeConn(FakeCursor(fetchone=None))  # no fresh market_quotes row -> yfinance fallback
    assert wes._price(conn, "SPCX") == (24.5, 2.08)
    assert conn.cur.sqls[0].startswith("SELECT price, day_change_pct FROM market_quotes")
    sql, params = conn.cur.calls[1]
    assert columns_of(sql) == ["symbol", "source", "price", "day_change_pct"]
    assert params == ("SPCX", "yfinance", 24.5, 2.08)
    assert conn.committed == 1


def test_producer_ingest_alpaca_writes_through_module_and_rail_rejects_negative(monkeypatch, capsys):
    import external_market_data_ingest as emdi

    assert emdi.write_market_quotes is mq.write_market_quotes  # writer_target re-exports the module
    snaps = {
        "AAPL": {"latestTrade": {"p": 190.5}, "prevDailyBar": {"c": 189.0}, "dailyBar": {"v": 1000}},
        "ZERO": {"latestTrade": {"p": 0}, "dailyBar": {"c": 0}},          # producer skips falsy price
        "NEG": {"latestTrade": {"p": -5.0}, "prevDailyBar": {"c": 5.0}, "dailyBar": {"v": 10}},  # rail
    }

    class _Resp:
        status_code = 200

        def json(self):
            return snaps

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda *a, **k: _Resp()))
    conn = FakeConn()
    monkeypatch.setattr(emdi, "_get_conn", lambda: conn)
    monkeypatch.setattr(emdi, "_alpaca_creds", lambda: ("k", "s"))
    out = emdi.ingest_alpaca_quotes(["AAPL", "ZERO", "NEG"])
    assert out["fetched"] == 1 and sorted(out["missing"]) == ["NEG", "ZERO"]
    assert len(conn.cur.calls) == 1  # NEG never reached the table
    sql, params = conn.cur.calls[0]
    assert columns_of(sql) == ["symbol", "source", "price", "prev_close", "day_change_pct", "volume"]
    assert params == ("AAPL", "alpaca", 190.5, 189.0, 0.7937, 1000)
    assert conn.committed == 1


def test_api_v2_hunk_routes_through_module_with_refresh_source_and_event_time():
    """api_v2 is not importable offline; the hunk is pinned by source text."""
    text = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    hunk_at = text.find("persist the refreshed quote (advisory record")
    hunk = text[hunk_at:hunk_at + 1400]
    assert "write_market_quotes" in hunk
    assert 'source=f"refresh:{source}"' in hunk
    assert '"fetched_at": parsed.astimezone(_dt.timezone.utc)' in hunk
    assert not re.search(WRITER_RE.format(table="market_quotes"), text, re.I)


# ── rails: rejected rows are returned with a reason, never written ───────────


@pytest.mark.parametrize("row,reason", [
    ({"symbol": "X", "price": -1.0}, "price: must be > 0"),
    ({"symbol": "X", "price": 0, "volume": 5000}, "price: must be > 0"),       # zero-with-volume
    ({"symbol": "X", "price": float("nan")}, "not finite"),
    ({"symbol": "X", "price": "n/a"}, "non-numeric"),
    ({"symbol": "", "price": 1.0}, "missing ['symbol']"),
    ({"symbol": "X", "price": 1.0, "rating": 3}, "unknown column(s) ['rating']"),
    ({"symbol": "X", "price": 1.0, "source": "finviz"}, "disagrees with writer source"),
    ({"symbol": "X", "price": 1.0, "fetched_at": "yesterday"}, "fetched_at: unparseable"),
])
def test_market_quotes_rejects_off_rail_rows(row, reason):
    cur = FakeCursor()
    rc = mq.write_market_quotes(cur, [row, {"symbol": "OK", "price": 2.0}], source="alpaca")
    assert cur.calls and cur.calls[0][1][0] == "OK", "the good row still goes in"
    assert len(cur.calls) == 1
    assert rc.rows_in == 2 and rc.rows_accepted == 1 and len(rc.rows_rejected) == 1
    assert reason in rc.rows_rejected[0]["reason"]
    assert rc.rows_rejected[0]["row"]["symbol"] == row["symbol"]


@pytest.mark.parametrize("row,reason", [
    ({"symbol": "X", "price_date": "2026-09-11", "close_price": -1.0}, "close_price: must be > 0"),
    ({"symbol": "X", "price_date": "2026-09-11", "close_price": 0}, "close_price: must be > 0"),
    ({"symbol": "X", "price_date": "2026-09-11", "close_price": float("nan")}, "not finite"),
    ({"symbol": "X", "price_date": "2026-09-11", "close_price": "abc"}, "non-numeric"),
    ({"symbol": " ", "price_date": "2026-09-11", "close_price": 1.0}, "symbol: empty"),
    ({"symbol": "X", "price_date": "not-a-date", "close_price": 1.0}, "price_date: unparseable"),
    ({"symbol": "X", "price_date": "2026-09-11", "close_price": 1.0, "volume": 1}, "unknown column(s) ['volume']"),
])
def test_ticker_prices_rejects_off_rail_rows(row, reason):
    cur = FakeCursor()
    rc = tp.write_ticker_prices(cur, [row, {"symbol": "OK", "price_date": "2026-09-11", "close_price": 2.0}],
                                source="finviz")
    assert len(cur.calls) == 1 and cur.calls[0][1][0] == "OK"
    assert rc.rows_in == 2 and rc.rows_accepted == 1 and len(rc.rows_rejected) == 1
    assert reason in rc.rows_rejected[0]["reason"]


def test_rejections_are_logged_not_silent(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="tradeai.writers"):
        mq.write_market_quotes(FakeCursor(), [{"symbol": "X", "price": -1}], source="alpaca")
    assert any("rejected row" in r.getMessage() and "market_quotes" in r.getMessage() for r in caplog.records)


def test_receipt_shape():
    rc = mq.write_market_quotes(FakeCursor(), [{"symbol": "A", "price": 1}], source="alpaca", run_id="r1")
    d = rc.as_dict()
    assert d["schema"] == "WriteReceipt@v1" and d["run_id"] == "r1"
    assert d["written_by"] == "scripts/lib/writers/market_quotes_writer.py"
    assert set(d) >= {"table", "source", "rows_in", "rows_accepted", "rows_written", "rows_rejected",
                      "identity", "identity_lookup", "conflict_rule"}
    assert isinstance(rc, WriteReceipt)


# ── identity: registry-first, never recomputed, never NULL where it resolved ─


def test_identity_symbol_only_row_round_trips_to_the_registry_guid():
    """A bare ticker resolves to the same GUID identity_registry.register() would mint
    for it (the ticker alias defined once in memory_fact), and to what resolve_guid
    returns for the registry's by_symbol entry once it is minted."""
    rc = mq.write_market_quotes(FakeCursor(), [{"symbol": "aapl", "price": 1.0}], source="alpaca")
    guid = rc.identity["AAPL"]
    assert guid and rc.identity_lookup["AAPL"] == DERIVED_ALIAS
    assert guid == reg.ticker_alias_guid("AAPL")
    doc = reg.register(reg.empty_registry(), {"symbol": "AAPL"})
    assert reg.resolve_guid(doc, doc["by_symbol"]["AAPL"]) == guid
    # ticker_prices resolves through the same path -> same GUID for the same symbol
    rc2 = tp.write_ticker_prices(FakeCursor(), [{"symbol": "AAPL", "price_date": "2026-09-11", "close_price": 1}],
                                 source="finviz")
    assert rc2.identity["AAPL"] == guid


def test_identity_row_with_cik_and_company_is_issuer_derived():
    row = {"symbol": "NVDA", "price": 182.0, "cik": "0001045810", "company": "NVIDIA Corp"}
    # cik/company are not market_quotes columns; they ride on the row for identity only
    # and must be rejected as columns -> resolve identity via the module's resolver directly.
    from lib.writers.receipt import resolve_subject_identity

    guid, verdict = resolve_subject_identity(row)
    spine = resolve_identity_spine({"symbol": "NVDA", "cik": "0001045810", "company": "NVIDIA Corp"})
    assert verdict == DERIVED_ALIAS
    assert guid == reg.subject_guid_of(spine, "NVDA") == spine["security_guid"]
    assert guid != reg.ticker_alias_guid("NVDA"), "issuer-derived, not the bare alias"
    doc = reg.register(reg.empty_registry(), {"symbol": "NVDA", "cik": "0001045810", "company": "NVIDIA Corp"})
    assert doc["by_symbol"]["NVDA"] == guid


def test_identity_registry_first_follows_supersede_chain(tmp_path, monkeypatch):
    """When the registry has an entity, its (chain-resolved) GUID wins over any derivation.
    Here NVDA's by_symbol still points at the historical alias GUID; the write module
    must report the active, superseded_by target -- identity_registry.resolve_guid's answer."""
    doc = reg.empty_registry()
    reg.register(doc, {"symbol": "NVDA"})
    alias = doc["by_symbol"]["NVDA"]
    reg.register(doc, {"symbol": "NVDA", "cik": "0001045810", "company": "NVIDIA Corp"})
    upgraded = doc["by_symbol"]["NVDA"]
    assert upgraded != alias and doc["entities"][alias]["superseded_by"] == upgraded
    doc["by_symbol"]["NVDA"] = alias  # a historical pointer, as a stale row would carry
    path = tmp_path / "minted.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(path))
    reg.save(doc)  # honours TRADEAI_IDENTITY_REGISTRY, so this is the temp file
    reg._CACHE.clear()

    rc = tp.write_ticker_prices(FakeCursor(), [{"symbol": "NVDA", "price_date": "2026-09-11", "close_price": 1}],
                                source="finviz")
    assert rc.identity_lookup["NVDA"] == RESOLVED
    assert rc.identity["NVDA"] == upgraded == reg.resolve_guid(doc, alias)


def test_identity_is_never_null_for_a_real_symbol_and_not_applicable_for_cash():
    rc = tp.write_ticker_prices(FakeCursor(), [
        {"symbol": "SCHD", "price_date": "2026-09-11", "close_price": 27.0},
        {"symbol": "CASH", "price_date": "2026-09-11", "close_price": 1.0},
    ], source="holdings")
    assert rc.identity["SCHD"] is not None and rc.identity_lookup["SCHD"] in (RESOLVED, DERIVED_ALIAS)
    assert rc.identity["CASH"] is None and rc.identity_lookup["CASH"] == NOT_APPLICABLE


def test_neither_table_has_an_identity_column_so_none_is_written():
    """Rule (e): the tables carry no subject/security/issuer GUID column, so the module
    neither adds one nor writes one. Identity rides on the receipt (proposed migration in
    docs/implementation/sot/phase9_quotes_prices_notes.md)."""
    for cols in (mq.COLUMNS, tp.COLUMNS):
        assert not any(c.endswith("_guid") for c in cols)
    cur = FakeCursor()
    mq.write_market_quotes(cur, [{"symbol": "A", "price": 1}], source="alpaca")
    tp.write_ticker_prices(cur, [{"symbol": "A", "price_date": "2026-09-11", "close_price": 1}], source="finviz")
    assert not any("guid" in s.lower() for s in cur.sqls)


def test_identity_resolution_can_be_switched_off_for_hot_loops():
    rc = mq.write_market_quotes(FakeCursor(), [{"symbol": "A", "price": 1}], source="alpaca", resolve_identity=False)
    assert rc.identity == {} and rc.rows_written == 1


# ── negative control: the writer count fell from the baseline to exactly 1 ──


def _writer_files(table: str) -> set[str]:
    pat = re.compile(WRITER_RE.format(table=re.escape(table)), re.I)
    return {p.relative_to(ROOT).as_posix() for p in gate._files()
            if pat.search(p.read_text(encoding="utf-8", errors="replace"))}


@pytest.mark.parametrize("table,module", [
    ("market_quotes", "scripts/lib/writers/market_quotes_writer.py"),
    ("ticker_prices", "scripts/lib/writers/ticker_prices_writer.py"),
])
def test_negative_control_writer_count_fell_from_baseline_to_one(table, module):
    assert BASELINE["history"]["2026-09-13_pre_phase9"]["writers"][table] > 1, "history records the pre-Phase-9 plurality"
    assert BASELINE["writers"][table] == 1, "the enforced ceiling is now one"
    now = gate.count_writers(AUTH, gate._files())[table]
    assert now == 1, f"{table}: {now} writer files"
    assert _writer_files(table) == {module}
    assert gate.compare_baseline("WRITER_COUNT_ROSE", {table: now}, {table: BASELINE["writers"][table]}) == []


def test_registry_writer_targets_re_export_the_module():
    q = next(d for d in AUTH["domains"] if d["domain"] == "quote_price")
    t = next(d for d in AUTH["domains"] if d["domain"] == "technicals")
    # Integrated 2026-09-13: the lib module is the declared writer; the producer is its facade.
    assert q["writer"] == "scripts/lib/writers/market_quotes_writer.py"
    assert t["writer"] == "scripts/lib/writers/ticker_prices_writer.py"
    assert q["writer_facade"] == "scripts/external_market_data_ingest.py"
    assert t["writer_facade"] == "scripts/portfolio_repricer.py"
    assert "write_market_quotes" in (ROOT / q["writer_facade"]).read_text(encoding="utf-8")
    assert "write_ticker_prices" in (ROOT / t["writer_facade"]).read_text(encoding="utf-8")
