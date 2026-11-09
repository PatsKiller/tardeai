"""LQ-20261107-1293: every swept reader takes the row shape the database layer really answers.

The served 500 was `_extended_batch` unpacking a `_db_query` row: `a, b, c = row` over a DICT binds its KEYS, so
`float("price")` raised and `/api/v2/sectors/monitor` failed. `_db_query` and every `RealDictCursor` reader answer
dict rows; only plain cursors answer tuples. Each test below drives a swept function with dict rows — the REAL shape —
and at least one keeps the tuple shape working, because a plain-cursor caller must not regress.

Synthetic fixtures only (public repo). No database, no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import news_risk_raise as nrr
from scripts.lib import market_risk_book_join as bj
from scripts.lib import offhours_quotes as oq
from scripts.lib.market_risk.policy import load_policy

ET = ZoneInfo("America/New_York")
POLICY = load_policy()
#: Sunday 2026-11-08 16:45 ET — nothing is open, the last close was Friday 16:00.
SUNDAY = datetime(2026, 11, 8, 16, 45, tzinfo=ET)


class _Cur:
    """A cursor that answers the rows it was given, in the given shape (dict rows by default)."""

    def __init__(self, rows):
        self._rows, self._out = rows, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._out = self._rows

    def fetchall(self):
        return list(self._out)

    def fetchone(self):
        return self._out[0] if self._out else None

    def close(self):
        pass


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cur(self._rows)

    def rollback(self):
        pass


# ── market_risk_book_join.material_news ───────────────────────────────────────────────────────────────────────────
def test_material_news_reads_dict_rows_by_column():
    rows = [
        {"symbol": "SPCX", "catalyst_type": "contract_win", "severity": "high", "at": "2026-11-07 10:01:00+00"},
        {"symbol": "SPCX", "catalyst_type": "analyst_upgrade", "severity": "high", "at": "2026-11-08 09:00:00+00"},
        {"symbol": "V", "catalyst_type": "earnings_beat", "severity": "critical", "at": "2026-11-06 18:38:00+00"},
    ]
    news = bj.material_news(_Conn(rows), POLICY, SUNDAY, ["SPCX", "V", "nvda"])
    assert set(news) == {"SPCX", "V"}  # not {"symbol", "catalyst_type", "severity", "at"}
    assert news["SPCX"]["count"] == 2 and news["SPCX"]["latest"].startswith("2026-11-08")
    # equal severity: the first type stands, the timestamp still advances (rank is strict)
    assert news["SPCX"]["catalyst_type"] == "contract_win"
    assert news["V"]["severity"] == "critical"


def test_material_news_still_reads_tuple_rows_from_a_plain_cursor():
    rows = [("V", "earnings_beat", "critical", "2026-11-06 18:38:00+00")]
    news = bj.material_news(_Conn(rows), POLICY, SUNDAY, ["V"])
    assert news == {"V": {"count": 1, "catalyst_type": "earnings_beat", "severity": "critical",
                          "latest": "2026-11-06 18:38:00+00"}}


# ── market_risk_book_join.overnight_markets ───────────────────────────────────────────────────────────────────────
_OVERNIGHT = {"home_review": {"overnight_markets": {"enabled": True, "stale_after_hours": 12, "max_items": 11}}}


def test_overnight_markets_reads_dict_rows_by_column():
    bar_end = datetime(2026, 11, 6, 19, 45, tzinfo=ET)
    rows = [{"symbol": "/ES", "session": "afterhours", "session_date": None, "price": 6810.25, "change_pct": 0.45,
             "reference_basis": "schwab_quote_close_price_settle_dated", "reference_date": None, "bar_end": bar_end}]
    out = bj.overnight_markets(_Conn(rows), SUNDAY, _OVERNIGHT)
    # the other configured symbols have no print and are NAMED there; /ES is not one of them
    assert not any("/ES" in str(g.get("reason") or "") for g in out["gaps"])
    item = out["items"][0]
    assert item["symbol"] == "/ES" and item["price"] == 6810.25 and item["change_pct"] == 0.45
    assert item["as_of"].startswith("2026-11-06 19:45") and item["stale"] is True


def test_overnight_markets_still_reads_tuple_rows():
    bar_end = datetime(2026, 11, 6, 19, 45, tzinfo=ET)
    rows = [("/ES", "afterhours", None, 6810.25, 0.45, "basis", None, bar_end)]
    item = bj.overnight_markets(_Conn(rows), SUNDAY, _OVERNIGHT)["items"][0]
    assert item["symbol"] == "/ES" and item["price"] == 6810.25


# ── news_risk_raise readers ───────────────────────────────────────────────────────────────────────────────────────
def test_catalyst_by_news_reads_dict_rows_by_column():
    rows = [{"nid": "17", "catalyst_type": "earnings_beat", "severity": "high"},
            {"nid": "17", "catalyst_type": "contract_win", "severity": "critical"}]
    out = nrr._catalyst_by_news(_Cur(rows), SUNDAY - timedelta(days=2))
    assert out == {"17": {"catalyst_type": "earnings_beat", "severity": "high"}}  # the first row per article wins


def test_catalyst_by_news_still_reads_tuple_rows():
    out = nrr._catalyst_by_news(_Cur([("17", "contract_win", "critical")]), SUNDAY - timedelta(days=2))
    assert out == {"17": {"catalyst_type": "contract_win", "severity": "critical"}}


def test_open_market_episode_reads_a_dict_row():
    assert nrr._open_market_episode(_Cur([{"episode_id": "ep-2026-11-08"}])) == "ep-2026-11-08"


def test_open_market_episode_still_reads_a_tuple_row():
    assert nrr._open_market_episode(_Cur([("ep-2026-11-08",)])) == "ep-2026-11-08"


def test_articles_keep_dict_rows_as_mappings_instead_of_zipping_their_keys():
    row = {"id": 7, "symbol": "V", "title": "Acme wins contract", "summary": "…",
           "published_at": "2026-11-07T10:00:00+00:00", "created_at": "2026-11-07T10:01:00+00:00"}
    out = nrr._articles(_Cur([row]), SUNDAY - timedelta(days=2), 10)
    assert out == [row]  # not {"id": "id", "symbol": "symbol", ...}


def test_articles_still_map_tuple_rows_to_their_columns():
    out = nrr._articles(_Cur([(7, "V", "Acme wins contract", "…", "2026-11-07T10:00:00+00:00", None)]),
                        SUNDAY - timedelta(days=2), 10)
    assert out[0]["id"] == 7 and out[0]["symbol"] == "V" and out[0]["created_at"] is None


# ── offhours_quotes.resolve_universe ─────────────────────────────────────────────────────────────────────────────
def _universe_cfg():
    return {"universe": {"sources": [{"name": "positions_current", "sql": "SELECT upper(symbol) FROM x"}]}}


def test_resolve_universe_reads_dict_rows_by_their_one_column():
    merged, prov = oq.resolve_universe(_universe_cfg(), db_query=lambda _s: [{"symbol": "v"}, {"symbol": "mu"}])
    assert merged == ["V", "MU"]
    assert prov["counts"] == {"sql:positions_current": {"kept": 2}}


def test_resolve_universe_never_turns_a_whole_dict_row_into_a_symbol():
    # the old fall-through stringified the row: "V" became "{'symbol': 'V'}" and reached the Schwab request as a name
    merged, _prov = oq.resolve_universe(_universe_cfg(), db_query=lambda _s: [{"symbol": "V"}])
    assert merged == ["V"]
    assert not any("{" in s or "'" in s for s in merged)


def test_resolve_universe_still_reads_tuple_rows_and_skips_null():
    merged, _prov = oq.resolve_universe(_universe_cfg(), db_query=lambda _s: [("V",), (None,), ("",)])
    assert merged == ["V"]
