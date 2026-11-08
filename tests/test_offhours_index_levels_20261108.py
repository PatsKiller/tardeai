"""Cash-index levels off-hours (LQ-20261107-939, operator 2026-11-08): the Sunday 20:00 ET weekly-outlook brief.

The lane `market-quotes-offhours-schwab` could not store $SPX/$COMPX/$DJI/$RUT at all: a cash index has no
off-hours print, so Schwab's last trade is frozen at the Friday regular close and ``max_trade_age_minutes``
refuses it as a stale quote -- correctly, for a QUOTE. A LEVEL is not a quote: ``schwab.index_levels`` in
config/market_risk_offhours_quotes.yaml lets a configured ``$`` index, older than that age but no older than
``carry_max_age_hours``, be stored LEVEL ONLY in the night session the lane observes (scripts/lib/offhours_quotes.py
``index_level_row``). The store's own writer accepts it (overnight rows may carry a level with no dated reference).

Proves:
  * the four cash indices are configured and are carried as level-only OVERNIGHT rows: reference_close /
    reference_date / change_pct all None (never a guessed close), reference_basis names the basis AND the print's
    ET date, ``carried_from`` holds the exact print the level came from, and validate() accepts each row unchanged;
  * the carry is anchored on the session's 20:00 ET start, so the 20:01 Sunday fire and the 03:45 Monday fire
    produce the SAME (symbol, bar_start, feed) key -- one row per index per night, never a synthetic stream;
  * never widened: a stale EQUITY (SPY) is still refused as ``stale_trade``; a fresh index takes the normal
    referenced path, not the carry; the carry is refused outside an overnight session (the Sunday 18:00
    futures_open window, a weekday regular session) and past ``carry_max_age_hours``; removing the block or
    setting the age to 0 goes back to refusing every stale index;
  * the run receipt carries the rows, ``carried_from`` and the config's symbol list, and a dry run writes nothing;
  * a bad ``index_levels`` block fails loud at config load (a quoted number, a non-positive or non-finite age, a
    missing prefix, or a prefix that would be read as the futures same-day settlement exception).

Hermetic: fixture only, no network, no DB, no credential, no live state. Schedules nothing.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import offhours_quotes as oq  # noqa: E402
from lib.writers.market_quotes_extended_writer import validate  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "offhours_quotes" / "schwab_quotes_weekend_20261108.json"
CASH = ["$SPX", "$COMPX", "$DJI", "$RUT", "$NDX"]
CARRIED_BASIS = "schwab_index_level_carried_print_2026-11-06"
NIGHT_OPEN = datetime(2026, 11, 8, 20, 0, tzinfo=oq.ET)


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _doc() -> dict:
    return json.loads(FX.read_text())


def _cfg(**schwab) -> dict:
    cfg = copy.deepcopy(oq.load_config())
    cfg["schwab"].update(schwab)
    return cfg


def _rows(now: str, cfg: dict | None = None):
    doc = _doc()
    return oq.schwab_rows(doc["quotes"], _t(now), cfg or oq.load_config())


def _index_rows(now: str, cfg: dict | None = None) -> dict[str, dict]:
    rows, _ = _rows(now, cfg)
    return {r["symbol"]: r for r in rows if str(r["symbol"]).startswith("$")}


# ── the four cash indices are carried ───────────────────────────────────────────────────────────────


def test_the_four_cash_indices_are_configured():
    s = oq.load_config()["schwab"]
    # Design WU-1 (ADDENDUM 2026-11-08): exactly this list, $NDX next to the others, $VIX kept.
    assert s["indices"] == ["$SPX", "$COMPX", "$DJI", "$RUT", "$NDX", "$VIX"]
    assert set(CASH) <= {str(x).strip().upper() for x in s["indices"]}
    assert s["index_levels"]["basis_prefix"] == "schwab_index_level_carried_print"
    assert float(s["index_levels"]["carry_max_age_hours"]) >= 113  # Fri close -> Tue 09:30 ET after a holiday


def test_sunday_2001_fire_carries_each_cash_index_level():
    doc = _doc()
    rows, skipped = oq.schwab_rows(doc["quotes"], _t(doc["now"]), oq.load_config())
    by = {r["symbol"]: r for r in rows}
    assert set(by) == {"/ES", *CASH}  # /ES still flows beside them; SPY is refused (below)
    for sym in CASH:
        r = by[sym]
        assert validate(r) is None, (sym, validate(r))  # the store's own writer accepts it unchanged
        assert r["session"] == "overnight" and str(r["session_date"]) == "2026-11-09"  # next NYSE trading day
        assert r["bar_end"] == NIGHT_OPEN and r["bar_start"] < r["bar_end"]
        assert r["bar_end"] - r["bar_start"] == timedelta(milliseconds=1)
        assert r["price"] == doc["quotes"][sym]["quote"]["lastPrice"]
        # A LEVEL, never a measured move: no reference and no change_pct, because the print is 51 h old.
        assert r["reference_close"] is None and r["reference_date"] is None and r["change_pct"] is None
        # The basis names the basis AND the print's ET date: a level is never displayed as a fresh print.
        assert r["reference_basis"] == CARRIED_BASIS
        assert r["carried_from"] == "2026-11-06T21:47:00+00:00"  # Friday 16:47 ET, the last cash print
        assert "2026-11-06" in r["level_only_reason"]
        assert r["feed"] == "schwab"
    assert skipped == [{"symbol": "SPY", "reason": "stale_trade", "as_of": "2026-11-06T21:47:00+00:00",
                        "age_minutes": 3074.0}]


def test_carried_row_is_one_key_for_the_whole_night():
    """(symbol, bar_start, feed) is the store's idempotency key: the 20:01 Sunday fire and a 03:45 Monday fire
    (same overnight session, whose trade date is still Monday 2026-11-09) must not write a second row."""
    first = _index_rows("2026-11-08T20:01:00-05:00")
    later = _index_rows("2026-11-09T03:45:00-05:00")
    assert set(first) == set(later) == set(CASH)
    for sym in CASH:
        assert first[sym]["bar_start"] == later[sym]["bar_start"] == NIGHT_OPEN - timedelta(milliseconds=1)
        assert str(first[sym]["session_date"]) == str(later[sym]["session_date"]) == "2026-11-09"
        assert first[sym]["price"] == later[sym]["price"]  # same print, same level
    # A LATER print (Monday premarket, 04:30 ET) is a different night session: it is not carried at all.
    assert _index_rows("2026-11-09T04:30:00-05:00") == {}


# ── what the carry must never widen ────────────────────────────────────────────────────────────────


def test_stale_equity_is_never_carried():
    _, skipped = _rows("2026-11-08T20:01:00-05:00")
    assert {s["symbol"]: s["reason"] for s in skipped} == {"SPY": "stale_trade"}


def test_a_configured_index_must_come_back_as_an_index():
    """Design WU-1: verify Schwab returns each symbol as INDEX; any refusal is NAMED, never a silent substitution."""
    t = int(_t("2026-11-08T20:00:40-05:00").timestamp() * 1000)
    for typ, reason in (("FUND", "index_asset_type_fund"), ("EQUITY", "index_asset_type_equity"),
                        ("", "index_asset_type_missing")):
        blk = {"quote": {"lastPrice": 25610.0, "tradeTime": t}}
        if typ:
            blk["assetMainType"] = typ
        rows, skipped = oq.schwab_rows({"$NDX": blk}, _t("2026-11-08T20:01:00-05:00"), oq.load_config())
        assert rows == [] and skipped == [{"symbol": "$NDX", "reason": reason}], typ
    # A non-index symbol is not subject to this check: a fresh SPY overnight print is stored on its own rules.
    rows, skipped = oq.schwab_rows({"SPY": {"assetMainType": "EQUITY", "quote": {"lastPrice": 671.0, "tradeTime": t}}},
                                   _t("2026-11-08T20:01:00-05:00"), oq.load_config())
    assert skipped == [] and rows[0]["symbol"] == "SPY" and validate(rows[0]) is None


def test_fresh_index_takes_the_normal_referenced_path():
    """A stale print is carried; a fresh one is not -- it keeps its own bar_end and a real settled reference."""
    p = {"$SPX": {"assetMainType": "INDEX",
                  "quote": {"lastPrice": 6731.0, "closePrice": 6720.5,
                            "tradeTime": int(_t("2026-11-08T20:00:40-05:00").timestamp() * 1000),
                            "settleTime": 1794001620000}}}
    rows, skipped = oq.schwab_rows(p, _t("2026-11-08T20:01:00-05:00"), oq.load_config())
    assert skipped == [] and len(rows) == 1
    r = rows[0]
    assert validate(r) is None
    assert r["bar_end"] == _t("2026-11-08T20:00:40-05:00")  # the print instant, not the night anchor
    assert r["reference_close"] == 6720.5 and str(r["reference_date"]) == "2026-11-06"
    assert r["reference_basis"] == "schwab_quote_close_price_settle_dated"  # never the carried-print label
    assert "carried_from" not in r


def test_carry_is_refused_outside_the_overnight_session():
    # Sunday 18:30 ET is the futures_open window: the store takes futures there, never a cash index level.
    assert set(_index_rows("2026-11-08T18:30:00-05:00")) == set()
    assert {s["symbol"]: s["reason"] for s in _rows("2026-11-08T18:30:00-05:00")[1]
            if str(s["symbol"]).startswith("$")} == {sym: "stale_trade" for sym in CASH}
    # A weekday regular session is not a night session either.
    assert set(_index_rows("2026-11-10T14:00:00-05:00")) == set()


def test_carry_is_refused_past_the_configured_age():
    cfg = _cfg(index_levels={"carry_max_age_hours": 10, "basis_prefix": "schwab_index_level_carried_print"})
    rows, skipped = _rows("2026-11-08T20:01:00-05:00", cfg)
    assert [r["symbol"] for r in rows] == ["/ES"]  # 51 h old print, 10 h ceiling
    assert {s["symbol"]: s["reason"] for s in skipped} == {**{sym: "stale_trade" for sym in CASH},
                                                          "SPY": "stale_trade"}


def test_removing_the_block_restores_the_refusal():
    cfg = copy.deepcopy(oq.load_config())
    cfg["schwab"].pop("index_levels")
    rows, skipped = _rows("2026-11-08T20:01:00-05:00", cfg)
    assert [r["symbol"] for r in rows] == ["/ES"]
    assert {s["symbol"] for s in skipped} == {*CASH, "SPY"}


# ── receipt and dry run ────────────────────────────────────────────────────────────────────────────


def test_receipt_carries_the_levels_and_the_dry_run_writes_nothing():
    doc = _doc()
    seen: list[list[str]] = []

    def fetch(symbols):
        seen.append(list(symbols))
        return doc["quotes"]

    rec = oq.run(cfg=oq.load_config(), now=_t(doc["now"]), fetch=fetch, write=None, dry_run=True,
                 force_window=True)
    assert rec["status"] == "dry_run" and rec["inserted"] == 0
    assert isinstance(rec["now"], str) and rec["dry_run"] is True
    assert set(CASH) <= set(seen[0])  # the indices are actually requested from Schwab
    by = {r["symbol"]: r for r in rec["rows"]}
    assert set(by) == {"/ES", *CASH} and len(rec["rows"]) == 1 + len(CASH)  # NON-ZERO rows on the receipt
    for sym in CASH:
        assert by[sym]["reference_basis"] == CARRIED_BASIS
        assert by[sym]["carried_from"] == "2026-11-06T21:47:00+00:00"  # JSON-safe, the exact print
        assert by[sym]["session"] == "overnight" and by[sym]["price"] > 0
    assert rec["skipped"] == [{"symbol": "SPY", "reason": "stale_trade", "as_of": "2026-11-06T21:47:00+00:00",
                               "age_minutes": 3074.0}]


# ── config validation: fail loud, never silently disable the carry ─────────────────────────────────


_BAD_AGES = {"zero_age": 0, "negative_age": -1, "bool_age": True, "nan_age": float("nan"),
             "inf_age": float("inf"), "quoted_age": "120"}


def _mut(name: str):
    def apply(s: dict) -> None:
        lv = s.setdefault("index_levels", {})
        if name == "not_a_mapping":
            s["index_levels"] = "carry"
        elif name == "missing_age":
            lv.pop("carry_max_age_hours", None)
        elif name == "missing_prefix":
            lv["basis_prefix"] = " "
        else:
            lv["carry_max_age_hours"] = _BAD_AGES[name]
    return apply


@pytest.mark.parametrize("name", ["not_a_mapping", "missing_age", "missing_prefix", "zero_age", "negative_age",
                                  "bool_age", "nan_age", "inf_age", "quoted_age"])
def test_config_refuses_a_bad_carry_block(tmp_path, name):
    doc = copy.deepcopy(oq.load_config())
    _mut(name)(doc["schwab"])
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(oq.ConfigError):
        oq.load_config(p)


def test_config_refuses_a_prefix_read_as_the_same_day_exception(tmp_path):
    """extended_hours.py treats any reference_basis containing 'settle_same_day' as the futures settlement
    exception. A carried level is not a settlement, so the prefix may never carry that token."""
    doc = copy.deepcopy(oq.load_config())
    doc["schwab"]["index_levels"]["basis_prefix"] = "schwab_index_level_settle_same_day"
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(oq.ConfigError):
        oq.load_config(p)


def test_shipped_config_loads():
    cfg = oq.load_config()
    assert cfg["schwab"]["enabled"] is True and cfg["schwab"]["feed"] == "schwab"


# ── settle reference: the lane's own stored settle, never yfinance-named bars (design WU-1) ─────────


def test_settle_reference_is_lane_internal_and_the_yfinance_map_is_retired(tmp_path):
    s = oq.load_config()["schwab"]
    assert s["settle_reference_source"] == "market_quotes_extended_own_feed"
    assert s["settle_reference_feed"] == "schwab"
    assert "reference_symbols" not in s  # ES=F, NQ=F, RTY=F, YM=F are gone (LQ-20261107-455 bans the source)
    for mutate in (lambda d: d["schwab"].update(reference_symbols={"/ES": "ES=F"}),
                   lambda d: d["schwab"].update(settle_reference_source="market_ohlcv_bars"),
                   lambda d: d["schwab"].update(settle_reference_feed=" ")):
        doc = copy.deepcopy(oq.load_config())
        mutate(doc)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(oq.ConfigError):
            oq.load_config(p)


def test_stored_reference_reads_the_lanes_own_stored_settle(monkeypatch):
    import types

    import market_quotes_offhours_schwab as ent

    calls: list[tuple] = []

    class Cur:
        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchone(self):
            return (6820.0,)

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            calls.append(("closed", None))

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=Conn))
    cfg = oq.load_config()
    assert ent.stored_reference("/ES", _t("2026-11-06").date(), cfg) == 6820.0
    sql, params = calls[0]
    assert "market_quotes_extended" in sql and "reference_close" in sql
    assert "market_ohlcv_bars" not in sql  # the yfinance-named path is gone, not merely unused
    assert params == ["/ES", "schwab", _t("2026-11-06").date()]
    assert calls[-1] == ("closed", None)
    # A config that does not name the lane-internal source never reaches the database.
    calls.clear()
    assert ent.stored_reference("/ES", _t("2026-11-06").date(), {"schwab": {}}) is None
    assert calls == []
