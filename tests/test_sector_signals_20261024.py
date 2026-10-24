"""Approved W3: cross-reader sector truth, exact horizons and honest gaps."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.sector_signals import relative_strength, sector_posture
from lib.data_broker import sector_momentum as projection

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def price_rows():
    """Technology rises today while losing strength over both longer horizons."""
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(115)]
    days = [d for d in days if d.weekday() < 5][-71:]
    rows = []
    for i, day in enumerate(days):
        for symbol, price in (("SPY", 100 + i * .1), ("XLK", 130 - i * .3),
                              ("XLP", 80 + i * .4), ("ABT", 50 + i * .2),
                              ("MSFT", 130 - i * .3), ("PG", 80 + i * .4)):
            rows.append({"symbol": symbol, "price_date": day, "close_price": price})
    return rows


def database(rows=None):
    rows = price_rows() if rows is None else rows

    def query(sql, params=None, fetch=None):
        assert sql.lstrip().upper().startswith("SELECT"), "projection must be read-only"
        if "ticker_prices" in sql:
            return [r for r in rows if r["symbol"] in params[0]]
        if "watch_directives" in sql:
            return []
        if "count(DISTINCT symbol)" in sql:
            return {"n": 1}
        if "watchlist_items wi" in sql:
            symbol = {"Technology": "MSFT", "Healthcare": "ABT", "Consumer Defensive": "PG"}.get((params or [None])[0])
            return [{"symbol": symbol, "score": 80, "analyst_opinions": 5}] if symbol else []
        if "sector_momentum_state" in sql:
            return [{"sector": "Technology", "etf": "XLK", "state": "LEADING",
                     "rs20": 9, "rs60": 12, "book_pct": 4}]
        return []
    return query


def pairs(rows, symbol):
    return [(r["price_date"], r["close_price"]) for r in rows if r["symbol"] == symbol]


@pytest.mark.parametrize("mid,long,state,posture", [
    (2, 4, "LEADING", "Favoured"), (-2, -4, "LAGGING", "Review"),
    (2, -4, "IMPROVING", "Research watch"), (-2, 4, "WEAKENING", "Neutral"),
    (None, 4, None, "Not measured"), (4, None, None, "Not measured"),
    (float("nan"), 1, None, "Not measured"), (1, float("inf"), None, "Not measured"),
])
def test_posture_requires_both_named_horizons(mid, long, state, posture):
    out = sector_posture(mid, long)
    assert out["state"] == state
    assert out["cio_posture"] == posture


def test_exact_return_difference_and_old_snapshot_does_not_win():
    from lib.cio_sector_opportunity import normalize_sector_row
    rows = price_rows()
    sector, spy = pairs(rows, "XLK"), pairs(rows, "SPY")
    result = relative_strength(sector, spy)
    expected = ((sector[-1][1] / sector[-21][1] - 1) - (spy[-1][1] / spy[-21][1] - 1)) * 100
    assert result["rs20"] == round(expected, 2)
    assert result["state"] == "LAGGING"
    normalized = normalize_sector_row({"sector": "Technology", "state": "LEADING", **result})
    assert normalized["state"] == "LAGGING"


def test_missing_history_never_becomes_a_shorter_twenty_day_return():
    rows = price_rows()
    result = relative_strength(pairs(rows, "XLK")[-10:], pairs(rows, "SPY"))
    assert result["rs5"] is not None
    assert result["rs20"] is None and result["rs60"] is None
    assert result["cio_posture"] == "Not measured"


def test_missing_session_and_stale_etf_do_not_compress_benchmark_window():
    rows = price_rows()
    s, spy = pairs(rows, "XLK"), pairs(rows, "SPY")
    assert relative_strength(s[:-10] + s[-9:], spy)["rs20"] is None
    stale = relative_strength(s[:-1], spy)
    assert stale["rs5"] is None and stale["rs20"] is None
    assert stale["as_of"] == str(spy[-1][0])


def test_engine_projection_cio_and_defense_use_identical_sector_values(tmp_path):
    import sector_momentum_engine as writer
    from lib.cio_sector_opportunity import fetch_sector_opportunity_inputs

    rows = price_rows()

    class Cursor:
        def execute(self, sql, params):
            self.symbols = params[0]

        def fetchall(self):
            return [(r["symbol"], r["price_date"], r["close_price"]) for r in rows if r["symbol"] in self.symbols]

    written = next(r for r in writer.compute_states(Cursor()) if r["etf"] == "XLK")
    canonical = projection.get_sector_signals(database())["sectors"]["XLK"]
    cio = fetch_sector_opportunity_inputs(database())["sector_rows"][0]
    (tmp_path / "sector_momentum_latest.json").write_text(json.dumps({
        "generated_at": NOW.isoformat(), "rows": [written]
    }))
    defense = projection.get_sector_momentum_snapshot(runtime_dir=tmp_path, now=NOW)["snapshot"]["rows"][0]
    for field in ("rs5", "rs20", "rs60", "state", "cio_posture", "as_of"):
        assert written[field] == canonical[field] == defense[field] == cio[field]
    assert written["as_of"] == str(max(r["price_date"] for r in rows))


def test_monitor_one_day_opposition_and_missing_spy_are_context_only(tmp_path, monkeypatch):
    from lib.sectors_monitor import monitor
    from lib.data_broker import market_quote
    quotes = {"XLK": {"chg_pct": 5, "as_of": NOW.isoformat()},
              "XLP": {"chg_pct": -5, "as_of": NOW.isoformat()}}
    monkeypatch.setattr(market_quote, "get_price_batch", lambda *a, **kw: quotes)
    (tmp_path / "holdings.json").write_text(json.dumps({"resolved_sectors": [
        {"sector": "Technology", "value": 2000, "pct": 4.25}]}))
    result = monitor(database(), tmp_path, sector_map={"Technology": "XLK", "Consumer Defensive": "XLP"}, now=NOW)
    tech = next(r for r in result["sectors"] if r["etf"] == "XLK")
    staples = next(r for r in result["sectors"] if r["etf"] == "XLP")
    assert tech["etf_change_pct"] == 5 and tech["momentum"] == "lagging"
    assert tech["cio_posture"] == "Review" and staples["cio_posture"] == "Favoured"
    assert tech["rel_strength"] is None and result["spy_change_pct"] is None
    assert tech["book_weight_pct"] == 4.25  # the owner's pct, never recomputed
    assert tech["book_dollars"] == 2000
    assert tech["leaders"][0]["symbol"] == "MSFT"
    assert tech["leaders"][0]["rs20"] is not None


def test_one_day_cache_is_never_served_as_multi_horizon_truth(tmp_path, monkeypatch):
    cache = tmp_path / "sector_momentum.json"
    cache.write_text(json.dumps({"computed_at": NOW.isoformat(), "sectors": {"XLK": {"label": "leading"}}}))
    monkeypatch.setattr(projection, "SNAPSHOT_PATH", cache)
    monkeypatch.setattr(projection.time, "time", lambda: NOW.timestamp())
    assert projection.get_sector_momentum()["sectors"] == {}


def test_defense_refreshes_signal_fields_without_fabricating_evidence_time(tmp_path):
    (tmp_path / "sector_momentum_latest.json").write_text(json.dumps({
        "generated_at": "2026-10-20T21:00:00Z", "rows": [{
            "etf": "XLK", "sector": "Technology", "state": "LEADING", "rs20": 9,
            "rs60": 10, "as_of": "2026-10-20", "breadth_pct": 60}]}))
    response = projection.get_sector_momentum_snapshot(runtime_dir=tmp_path, now=NOW, db_query=database())
    row = response["snapshot"]["rows"][0]
    assert row["state"] == "LAGGING"
    assert row["breadth_pct"] == 60
    assert response["snapshot"]["generated_at"] == "2026-10-20T21:00:00Z"
    assert row["as_of"] == projection.get_sector_signals(database())["as_of"]


def test_monitor_reads_candidate_stance_only_through_w1(tmp_path, monkeypatch):
    import types
    from lib.sectors_monitor import monitor
    from lib.data_broker import market_quote
    called = []
    def canonical(symbols, **kwargs):
        called.append(symbols)
        return {"ABT": {"stance": "HOLD", "gap": None}}
    monkeypatch.setitem(sys.modules, "lib.cio_truth", types.SimpleNamespace(stances_for_symbols=canonical))
    monkeypatch.setattr(market_quote, "get_price_batch", lambda *a, **kw: {})
    result = monitor(database(), tmp_path, sector_map={"Healthcare": "XLV"}, now=NOW)
    assert called == [["ABT"]]
    assert result["sectors"][0]["candidates"][0]["cio_view"] == "HOLD"


def test_favoured_names_format_canonical_posture_without_another_rule():
    out = projection.get_sector_signals(database())
    assert out["favoured"] == ["Consumer Staples"]
    assert out["sectors"]["XLP"]["sector"] == "Consumer Staples"
    missing = projection.get_sector_signals(database([]))
    assert missing["favoured"] is None
    assert missing["favoured_gap"]
