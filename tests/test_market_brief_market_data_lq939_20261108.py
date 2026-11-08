"""Market-data block for the market-event brief (LQ-20261107-939 part 4, design WU-1 scope).

The Sunday 20:00 ET market-event brief rendered the MarketEvent@v1 payload only: episode, market gate, candidates,
accounts. It had no market data at all -- no futures, no cash-index levels, no movers, no sectors, no international
exposure. `scripts/lib/market_brief_inputs.py` supplies that block (reached only with ``?market_data=1``, which the
brief asks for via ``config/market_event_brief_policy.json`` ``market_data``) and `scripts/market_event_brief.py`
renders it.

Proves:
  * the four sections read exactly the tables the lead named: market_quotes_extended (off-hours futures and cash
    indices, with the carried cash-index level shown as level-only and labelled with its print), market_movers
    (newest capture, gainers high-to-low, losers low-to-high, limited), sector_rs_daily + sector_momentum_state
    (newest RS date joined to the newest state), market_quotes (international ETFs, labelled ``etf_derived``);
  * the block is OPT-IN: build_active omits it unless asked, so the Command Center's poll of the route does not pay
    for the extra reads;
  * honesty: a section whose read failed is ``unavailable`` with the reason, an empty table is ``empty`` with a note,
    and neither is ever rendered as zeros; every section carries its own as-of;
  * the renderers print the section (email: one line per instrument plus each section's as-of; Telegram: a compact
    market line) and never invent a number for a missing section.

Hermetic: fake db_query only, no DB, no network, no state. Schedules nothing.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import market_brief_inputs as bi  # noqa: E402
import market_event_brief as brief  # noqa: E402

NOW = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)


def _db(rows_by_marker: dict[str, object], calls: list | None = None):
    """A fake db_query: the first marker found in the SQL decides the answer.

    An answer is a list of dicts, None, an exception, or a callable ``f(sql, params)`` for the queries whose answer
    depends on a bound parameter (the two movers signals share one statement).
    """
    def q(sql: str, params=None):
        if calls is not None:
            calls.append((sql, params))
        for marker, rows in rows_by_marker.items():
            if marker in sql:
                if callable(rows) and not isinstance(rows, type):
                    return rows(sql, params)
                if isinstance(rows, Exception):
                    raise rows
                return rows
        return []
    return q


def _movers_rows():
    def f(sql, params):
        at = datetime(2026, 11, 6, 16, 45, tzinfo=timezone.utc)
        if params and params[0] == "top_gainers":
            return [{"signal": "top_gainers", "symbol": "AAA", "company": "A Co", "sector": "Tech", "last": 10.0,
                     "change_pct": 12.5, "volume": 1, "captured_at": at}]
        return [{"signal": "top_losers", "symbol": "ZZZ", "company": "Z Co", "sector": "Energy", "last": 9.0,
                 "change_pct": -11.0, "volume": 2, "captured_at": at}]
    return f


def _good() -> dict[str, object]:
    end = datetime(2026, 11, 6, 9, 15, tzinfo=timezone(timedelta(hours=-5)))
    return {
        "DISTINCT ON (symbol) symbol, session": [
            {"symbol": "/ES", "session": "premarket", "session_date": date(2026, 11, 6), "bar_end": end,
             "price": 7391.0, "reference_close": 7502.0, "reference_date": date(2026, 11, 5), "change_pct": -1.4796,
             "reference_basis": "schwab_quote_close_price_settle_dated"},
            {"symbol": "$SPX", "session": "overnight", "session_date": date(2026, 11, 9), "bar_end": end,
             "price": 6720.5, "reference_close": None, "reference_date": None, "change_pct": None,
             "reference_basis": "schwab_index_level_carried_print_2026-11-06"},
        ],
        "max(captured_at) AS at": [{"signal": "top_gainers", "at": datetime(2026, 11, 6, 16, 45, tzinfo=timezone.utc)},
                                   {"signal": "top_losers", "at": datetime(2026, 11, 6, 16, 45, tzinfo=timezone.utc)}],
        "signal = %s AND captured_at = %s": _movers_rows(),
        "FROM sector_rs_daily s": [
            {"etf": "XLK", "rs_date": date(2026, 11, 6), "rs": 0.224, "close": 164.8, "state_as_of": date(2026, 11, 6),
             "sector": "Technology", "state": "LEADING", "rs5": 1.0, "rs20": 2.0},
            {"etf": "XLP", "rs_date": date(2026, 11, 6), "rs": 0.12, "close": 84.1, "state_as_of": date(2026, 11, 5),
             "sector": "Consumer Defensive", "state": "IMPROVING", "rs5": 0.5, "rs20": 0.7},
            {"etf": "XLE", "rs_date": date(2026, 11, 6), "rs": 0.084, "close": 61.64, "state_as_of": None,
             "sector": None, "state": None, "rs5": None, "rs20": None},
        ],
        "DISTINCT ON (symbol) symbol, source, price": [
            {"symbol": "EWJ", "source": "alpaca", "price": 78.5, "day_change_pct": 0.4,
             "fetched_at": datetime(2026, 11, 6, 21, 45, tzinfo=timezone.utc)},
        ],
    }


# ── the four sections ─────────────────────────────────────────────────────────────────────────────


def test_gather_reads_the_four_sections_with_their_own_as_of():
    md = bi.gather(_db(_good()), now=NOW)
    assert md["schema"] == "MarketBriefData@v1"
    q = md["quotes"]
    assert q["state"] == "ok" and q["as_of"].startswith("2026-11-06T09:15")
    by = {r["symbol"]: r for r in q["rows"]}
    assert list(by) == ["/ES", "$SPX"]  # futures first, then cash indices, config order
    assert by["/ES"]["change_pct"] == -1.4796 and by["/ES"]["level_only"] is False
    # A carried cash-index level: no invented move, and the basis names the print it came from.
    assert by["$SPX"]["level_only"] is True and by["$SPX"]["change_pct"] is None
    assert by["$SPX"]["reference_basis"] == "schwab_index_level_carried_print_2026-11-06"
    assert by["$SPX"]["age_hours"] > 0 and by["$SPX"]["session"] == "overnight"  # the row keeps its own session
    mv = md["movers"]
    assert mv["state"] == "ok" and mv["as_of"] == "2026-11-06T16:45:00+00:00"
    assert [(r["signal"], r["symbol"]) for r in mv["rows"]] == [("top_gainers", "AAA"), ("top_losers", "ZZZ")]
    sec = md["sectors"]
    assert sec["state"] == "ok" and sec["as_of"] == "2026-11-06"
    assert [r["state"] for r in sec["rows"]] == ["LEADING", "IMPROVING", None]  # LEFT JOIN, never invented
    # Each ETF's state is its OWN newest one, so a state one session older than the RS date still appears, dated.
    assert sec["rows"][1]["state_as_of"] == "2026-11-05" and sec["rows"][1]["rs"] == 0.12
    it = md["international"]
    assert it["state"] == "ok" and it["rows"][0]["basis"] == "etf_derived"
    assert it["rows"][0]["symbol"] == "EWJ" and it["rows"][0]["change_pct"] == 0.4


def test_a_failed_read_is_unavailable_never_zero():
    rows = _good()
    rows["max(captured_at) AS at"] = RuntimeError("connection reset")
    md = bi.gather(_db(rows), now=NOW)
    assert md["movers"] == {"state": "unavailable", "as_of": None, "rows": [],
                            "note": "market_movers unreadable"}
    assert md["quotes"]["state"] == "ok" and md["sectors"]["state"] == "ok"  # one failure never hides another


def test_a_none_answer_is_unavailable_too():
    rows = _good()
    rows["FROM sector_rs_daily s"] = None
    md = bi.gather(_db(rows), now=NOW)
    assert md["sectors"]["state"] == "unavailable" and md["sectors"]["rows"] == []


def test_an_empty_table_is_empty_with_its_reason():
    md = bi.gather(_db({}), now=NOW)
    for key in ("quotes", "movers", "sectors", "international"):
        assert md[key]["state"] == "empty" and md[key]["rows"] == [] and md[key]["note"], key


def test_movers_take_the_newest_capture_per_signal_with_a_limit():
    calls: list = []
    bi.gather(_db(_good(), calls), now=NOW)
    mover_calls = [(s, p) for s, p in calls if "signal = %s AND captured_at = %s" in s]
    assert len(mover_calls) == 2
    (g_sql, g_params), (l_sql, l_params) = mover_calls
    assert "ORDER BY change_pct DESC" in g_sql and g_params[0] == "top_gainers" and g_params[2] == bi.MOVERS_LIMIT
    assert "ORDER BY change_pct ASC" in l_sql and l_params[0] == "top_losers"
    assert g_params[1].isoformat() == "2026-11-06T16:45:00+00:00"  # the snapshot's own stamp, not "now"


def test_the_sector_state_is_joined_per_etf_not_on_the_tables_newest_date():
    """2026-11-06 held only STYLE rows in ``sector_momentum_state``; a join on the table's ``max(as_of)`` would have
    shown 'no state' for all eleven sectors even though each has its own newest state the session before."""
    assert "m2.etf = s.symbol" in bi.SECTORS_SQL, bi.SECTORS_SQL
    assert "m.as_of = (SELECT max(as_of) FROM sector_momentum_state)" not in bi.SECTORS_SQL
    assert "max(as_of) FROM sector_momentum_state m2 WHERE" in bi.SECTORS_SQL


def test_a_configured_instrument_with_no_row_is_named_not_dropped():
    """INDA and EWZ had no quote in the 14-day window; a proxy that was not read is named, never silently absent."""
    md = bi.gather(_db(_good()), now=NOW)
    assert md["quotes"]["missing"] == ["/NQ", "/YM", "/RTY", "$COMPX", "$DJI", "$RUT", "$NDX"]
    # Derived from the universe rather than re-pinned: the fixture quotes EWJ and nothing else, so every other
    # configured proxy (now including the LQ-972 Europe proxies EWG EWU EZU VGK) is named.
    expected = [s for s in bi.INTERNATIONAL_ETFS if s != "EWJ"]
    assert md["international"]["missing"] == expected
    _, body = brief.render_email(_payload(md), slot="s", changes=[], top_n=5, stale=False)
    assert "no stored row: /NQ, /YM, /RTY, $COMPX, $DJI, $RUT, $NDX" in body
    assert "no quote: " + ", ".join(expected) in body


def test_reads_are_bounded_and_named():
    calls: list = []
    bi.gather(_db({}, calls), now=NOW)
    joined = " ".join(s for s, _ in calls)
    assert "market_quotes_extended" in joined and "market_movers" in joined
    assert "sector_rs_daily" in joined and "sector_momentum_state" in joined
    assert "FROM market_quotes " in joined
    assert "market_ohlcv_bars" not in joined  # never the yfinance-only bar table


# ── opt-in wiring: the payload carries it only when asked ─────────────────────────────────────────


def test_build_active_includes_the_block_only_on_request(monkeypatch):
    from lib import market_event_api as api

    seen: list = []
    monkeypatch.setattr(api.brief_inputs, "gather", lambda db, feed, now: seen.append(feed) or {"schema": "x"})
    kw = dict(db_query=_db({}), snapshot=None, holdings_rows=[], label=lambda k: str(k),
              facts=lambda h: {}, taxable=lambda k: False)

    class _Doc(dict):  # plan.build's document, without running the planner
        pass

    monkeypatch.setattr(api.plan, "build", lambda **k: {"episode": None, "market_gate": {}, "candidates": [],
                                                        "accounts": [], "policy": {}})
    plain = api.build_active(**kw, now=NOW)
    assert "market_data" not in plain and seen == []
    asked = api.build_active(**kw, now=NOW, include_market_data=True)
    assert asked["market_data"] == {"schema": "x"} and seen == ["schwab"]


def test_the_brief_asks_for_the_block():
    pol = brief.load_policy()
    assert pol["market_data"] is True


# ── rendering ─────────────────────────────────────────────────────────────────────────────────────


def _payload(md) -> dict:
    return {"episode": {"kind": "selloff", "state": "OPEN"}, "market_gate": {"tier": 2, "score": 40, "checks": {}},
            "candidates": [], "accounts": [], "market_data": md}


def test_email_prints_each_section_with_its_as_of_and_no_invented_move():
    subject, body = brief.render_email(_payload(bi.gather(_db(_good()), now=NOW)), slot="2026-11-08T20:00",
                                       changes=["x"], top_n=5, stale=False)
    assert "MARKET DATA" in body
    assert "FUTURES & CASH INDICES: as of 2026-11-06 09:15 ET" in body  # the row's own as-of, on the operator's clock
    assert "-1.48% vs 2026-11-05" in body
    assert "level only (schwab_index_level_carried_print_2026-11-06)" in body
    assert "gainers: AAA +12.5%" in body and "losers: ZZZ -11.0%" in body
    assert "XLK LEADING" in body and "XLE no state" in body
    assert "XLP IMPROVING (11-05)" in body  # a state older than the RS day carries its own date
    assert "EWJ 78.50 +0.4%" in body and "ETF proxies, not index levels" in body


def test_email_never_renders_a_failed_section_as_zero():
    rows = _good()
    rows["max(captured_at) AS at"] = RuntimeError("boom")
    _, body = brief.render_email(_payload(bi.gather(_db(rows), now=NOW)), slot="2026-11-08T20:00", changes=[],
                                 top_n=5, stale=False)
    assert "MOVERS: unavailable (market_movers unreadable)" in body


def test_telegram_gets_a_compact_market_line():
    text = brief.render_telegram(_payload(bi.gather(_db(_good()), now=NOW)), slot="2026-11-08T20:00", changes=[],
                                 top_n=5, stale=False)
    assert "Mkt: /ES -1.5%" in text and "Movers: +AAA / -ZZZ" in text
    assert "level only" not in text  # the text stays short; the email carries the detail


def test_renderers_are_unchanged_without_the_block():
    """A payload that has no market_data (any older caller) renders exactly as before."""
    subject, body = brief.render_email({"episode": {}, "market_gate": {}, "candidates": []}, slot="s", changes=[],
                                       top_n=5, stale=False)
    assert "MARKET DATA" not in body
    assert "Mkt:" not in brief.render_telegram({"episode": {}, "market_gate": {}, "candidates": []}, slot="s",
                                               changes=[], top_n=5, stale=False)
