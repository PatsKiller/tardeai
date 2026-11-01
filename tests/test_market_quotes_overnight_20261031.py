"""ANCHOR MARKET_QUOTES_OVERNIGHT_20261031 -- overnight (20:00-04:00 ET, Sunday night to Friday 04:00) and Sunday
18:00 futures-open sessions in ``market_quotes_extended`` (operator 2026-10-31: "No excuses").

Proves the session definition (DST weekends, the Sunday futures open, holiday trading dates, no Friday-night session,
04:00:00 is pre-market), the next-trading-day trading date on the market_day_gate.sh calendar, the reference rule
(the last regular close before the night, or level-only and never invented), the writer, the Schwab producer
(fixture dry run, no network, no DB), the engine reader and category (stale overnight -> UNKNOWN naming session and
age, never CALM), and the additive migration on a throwaway socket-only Postgres cluster (never the live DB).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import market_session  # noqa: E402
from lib import offhours_quotes as oq  # noqa: E402
from scripts.lib import overnight_session as ovn  # noqa: E402
from scripts.lib.market_risk.categories import _overnight, extended_hours  # noqa: E402
from scripts.lib.market_risk.contract import EvalContext  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402
from scripts.lib.writers import market_quotes_extended_writer as w  # noqa: E402

import market_quotes_extended as mqe  # noqa: E402

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
CFG = mqe.load_config()
FX = ROOT / "tests" / "fixtures" / "offhours_quotes" / "schwab_quotes_overnight_20261102.json"
UP = ROOT / "migrations" / "2026_10_31_market_quotes_extended_overnight.sql"
DOWN = ROOT / "migrations" / "2026_10_31_market_quotes_extended_overnight.down.sql"
BASE_UP = ROOT / "migrations" / "2026_10_31_market_quotes_extended.sql"
ENTRY = ROOT / "scripts" / "market_quotes_offhours_schwab.py"


def _et(*a) -> datetime:
    return datetime(*a, tzinfo=ET)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ── session definition ──────────────────────────────────────────────────────────────────────────────


def test_calendar_is_the_market_day_gate_calendar():
    """market_day_gate.sh asks scripts/market_session.py; overnight_session uses its market_holidays, and the engine's
    cio_market_session calendar agrees with it for every year this can run in."""
    assert "from market_session import" in (ROOT / "scripts" / "market_day_gate.sh").read_text()
    import inspect

    # same function from the same file (it may be imported as scripts.market_session or market_session)
    assert inspect.getsourcefile(ovn.market_holidays) == inspect.getsourcefile(market_session.market_holidays)
    assert ovn.market_holidays.__name__ == "market_holidays"
    assert Path(inspect.getsourcefile(ovn.market_holidays)).resolve() == (ROOT / "scripts" / "market_session.py").resolve()
    from scripts.lib.cio_market_session import nyse_holidays

    for y in range(2026, 2031):
        assert set(market_session.market_holidays(y)) == {d.isoformat() for d in nyse_holidays(y)}


@pytest.mark.parametrize(
    "instant,asset,want",
    [
        # DST fall-back weekend (2026-11-01 02:00 EDT -> 01:00 EST): the Sunday futures open is 23:00 UTC
        (datetime(2026, 11, 1, 23, 0, tzinfo=UTC), "FUTURE", ("futures_open", date(2026, 11, 2))),
        (datetime(2026, 11, 1, 22, 59, tzinfo=UTC), "FUTURE", None),  # 17:59 EST
        (datetime(2026, 11, 2, 1, 0, tzinfo=UTC), "FUTURE", ("overnight", date(2026, 11, 2))),  # 20:00 EST
        (datetime(2026, 11, 2, 8, 59, tzinfo=UTC), "EQUITY", ("overnight", date(2026, 11, 2))),  # 03:59 EST
        (datetime(2026, 11, 2, 9, 0, tzinfo=UTC), "EQUITY", None),  # 04:00 EST: pre-market, not overnight
        # the same UTC minute a week earlier was 04:59 EDT: pre-market, not overnight
        (datetime(2026, 10, 30, 8, 59, tzinfo=UTC), "EQUITY", None),
        (datetime(2026, 10, 30, 7, 59, tzinfo=UTC), "EQUITY", ("overnight", date(2026, 10, 30))),  # 03:59 EDT
        # DST spring-forward weekend (2027-03-14 02:00 EST -> 03:00 EDT): the futures open is 22:00 UTC
        (datetime(2027, 3, 14, 22, 0, tzinfo=UTC), "FUTURE", ("futures_open", date(2027, 3, 15))),
        (datetime(2027, 3, 14, 21, 59, tzinfo=UTC), "FUTURE", None),
        (datetime(2027, 3, 15, 7, 59, tzinfo=UTC), "FUTURE", ("overnight", date(2027, 3, 15))),  # 03:59 EDT
        (datetime(2027, 3, 14, 7, 30, tzinfo=UTC), "FUTURE", None),  # Sunday 03:30 EDT: weekend, no session
    ],
)
def test_dst_weekends_and_the_sunday_futures_open(instant, asset, want):
    assert ovn.label(instant, CFG, asset_type=asset) == want


def test_sunday_futures_open_is_futures_only_and_sunday_only():
    assert ovn.label(_et(2026, 11, 1, 18, 0), CFG, "FUTURE") == ("futures_open", date(2026, 11, 2))
    assert ovn.label(_et(2026, 11, 1, 19, 59, 59), CFG, "FUTURE") == ("futures_open", date(2026, 11, 2))
    assert ovn.label(_et(2026, 11, 1, 18, 30), CFG, "EQUITY") is None  # equities do not trade Sunday 18:00-20:00
    assert ovn.label(_et(2026, 11, 1, 18, 30), CFG, "INDEX") is None
    assert ovn.label(_et(2026, 11, 2, 18, 30), CFG, "FUTURE") is None  # Monday 18:30 is after-hours, not this
    assert ovn.label(_et(2026, 11, 1, 20, 0), CFG, "EQUITY") == ("overnight", date(2026, 11, 2))


def test_holiday_monday_trading_date_is_tuesday():
    """MLK Day 2027-01-18: the Sunday open and Sunday night lead into Tuesday; the reference is Friday's close."""
    assert "2027-01-18" in market_session.market_holidays(2027)
    for t, asset, sess in [
        (_et(2027, 1, 17, 18, 30), "FUTURE", "futures_open"),
        (_et(2027, 1, 17, 21, 0), "EQUITY", "overnight"),
        (_et(2027, 1, 18, 2, 0), "FUTURE", "overnight"),
        (_et(2027, 1, 18, 21, 0), "FUTURE", "overnight"),
    ]:
        assert ovn.label(t, CFG, asset) == (sess, date(2027, 1, 19))
    assert ovn.reference_date(date(2027, 1, 19)) == date(2027, 1, 15)
    assert mqe.session_of(_et(2027, 1, 18, 4, 0), CFG) is None  # the holiday itself has no pre-market
    assert ovn.label(_et(2027, 1, 18, 4, 0), CFG, "FUTURE") is None


def test_thanksgiving_night_leads_into_the_early_close_friday():
    assert ovn.label(_et(2026, 11, 25, 21, 0), CFG, "FUTURE") == ("overnight", date(2026, 11, 27))
    assert ovn.label(_et(2026, 11, 26, 21, 0), CFG, "FUTURE") == ("overnight", date(2026, 11, 27))
    assert ovn.reference_date(date(2026, 11, 27)) == date(2026, 11, 25)


@pytest.mark.parametrize(
    "t",
    [
        _et(2026, 10, 30, 20, 0),  # Friday 20:00: no overnight session into the weekend
        _et(2026, 11, 6, 20, 0),
        _et(2026, 11, 6, 23, 59),
        _et(2026, 10, 31, 2, 0),  # Saturday small hours
        _et(2026, 10, 31, 21, 0),  # Saturday night
        _et(2026, 11, 1, 3, 0),  # Sunday small hours (the DST-ambiguous night)
    ],
)
def test_friday_night_and_weekend_have_no_session(t):
    assert ovn.label(t, CFG, "FUTURE") is None and ovn.label(t, CFG, "EQUITY") is None


def test_row_at_04_00_00_is_premarket_never_overnight():
    t = _et(2026, 11, 2, 4, 0, 0)
    assert ovn.label(t, CFG, "FUTURE") is None and mqe.session_of(t, CFG) == "premarket"
    just_before = t - timedelta(microseconds=1)
    assert ovn.label(just_before, CFG, "FUTURE") == ("overnight", date(2026, 11, 2))
    assert mqe.session_of(just_before, CFG) is None
    # 20:00:00 is the first overnight instant; 19:59:59 is still after-hours
    assert ovn.label(_et(2026, 11, 2, 20, 0, 0), CFG, "EQUITY") == ("overnight", date(2026, 11, 3))
    assert mqe.session_of(_et(2026, 11, 2, 19, 59, 59), CFG) == "afterhours"


def test_window_comes_from_config_not_code():
    cfg = json.loads(json.dumps(CFG))
    cfg["overnight"]["futures_open_et"] = "17:00"
    assert ovn.label(_et(2026, 11, 1, 17, 30), cfg, "FUTURE") == ("futures_open", date(2026, 11, 2))
    cfg["overnight"]["last_close_day"] = "sat"  # a hypothetical Friday-night session now exists
    assert ovn.label(_et(2026, 11, 6, 21, 0), cfg, "FUTURE") == ("overnight", date(2026, 11, 9))
    with pytest.raises(ValueError):
        ovn.label(datetime(2026, 11, 2, 2, 0), CFG)  # naive time refused, never guessed


# ── Schwab producer (fixture only: no network, no DB) ───────────────────────────────────────────────


@pytest.fixture()
def ocfg():
    return oq.load_config()


def _fx_rows(ocfg):
    doc = json.loads(FX.read_text())
    rows, skipped = oq.schwab_rows(doc["quotes"], datetime.fromisoformat(doc["now"]), ocfg)
    return doc, {r["symbol"]: r for r in rows}, {s["symbol"]: s for s in skipped}


def test_overnight_rows_carry_the_next_trading_date_and_a_proven_reference_or_none(ocfg):
    _, by, skipped = _fx_rows(ocfg)
    assert set(by) == {"/ES", "/NQ", "/YM", "QQQ", "SPY"}
    for r in by.values():
        assert r["session"] == "overnight" and r["session_date"] == date(2026, 11, 2)
        assert w.validate(r) is None, (r["symbol"], w.validate(r))
    es, qqq = by["/ES"], by["QQQ"]
    assert es["reference_close"] == 6800.0 and es["reference_date"] == date(2026, 10, 30)
    assert es["reference_basis"] == "schwab_quote_close_price_previous_settle"
    assert es["change_pct"] == round(100 * (6698.25 - 6800.0) / 6800.0, 4)
    assert qqq["price"] == 690.5 and qqq["reference_close"] == 700.0 and qqq["reference_date"] == date(2026, 10, 30)
    assert qqq["reference_basis"] == "schwab_regular_market_last_price_last_session"
    # settle dated Thursday, no closePrice, no regular block: the level is stored, the reference is NOT invented
    for sym in ("/NQ", "/YM", "SPY"):
        r = by[sym]
        assert r["reference_close"] is None and r["reference_date"] is None and r["change_pct"] is None
        assert r["reference_basis"] == "none_level_only_no_reference_in_payload" and r["level_only_reason"]
    assert "2026-10-29" in by["/NQ"]["level_only_reason"]
    assert skipped["$SPX"]["reason"] == "stale_trade" and skipped["/RTY"]["reason"] == "not_a_quote"


def test_sunday_futures_open_row(ocfg):
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0,
                                                      "tradeTime": _ms(_et(2026, 11, 1, 18, 0, 5))}},
         "QQQ": {"assetMainType": "EQUITY", "quote": {"lastPrice": 699.0, "tradeTime": _ms(_et(2026, 11, 1, 18, 0, 5))}}}
    rows, skipped = oq.schwab_rows(p, _et(2026, 11, 1, 18, 1), ocfg)
    assert [(r["symbol"], r["session"], r["session_date"], r["reference_date"]) for r in rows] == [
        ("/ES", "futures_open", date(2026, 11, 2), date(2026, 10, 30))
    ]
    assert w.validate(rows[0]) is None
    assert skipped == [{"symbol": "QQQ", "reason": "session_not_in_store_contract", "as_of": skipped[0]["as_of"],
                        "detail": skipped[0]["detail"]}]


def test_friday_20_00_print_is_refused(ocfg):
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0,
                                                      "tradeTime": _ms(_et(2026, 10, 30, 20, 0))}}}
    rows, skipped = oq.schwab_rows(p, _et(2026, 10, 30, 20, 1), ocfg)
    assert rows == [] and skipped[0]["reason"] == "session_not_in_store_contract"


def test_04_00_00_print_is_stored_as_premarket(ocfg):
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0,
                                                      "tradeTime": _ms(_et(2026, 11, 2, 4, 0, 0))}}}
    rows, _ = oq.schwab_rows(p, _et(2026, 11, 2, 4, 1), ocfg)
    assert rows[0]["session"] == "premarket" and rows[0]["session_date"] == date(2026, 11, 2)
    assert w.validate(rows[0]) is None


def test_holiday_monday_producer_row(ocfg):
    t = _et(2027, 1, 17, 21, 0)
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0, "tradeTime": _ms(t),
                                                      "settleTime": _ms(_et(2027, 1, 15, 16, 0))}}}
    rows, _ = oq.schwab_rows(p, t + timedelta(minutes=1), ocfg)
    assert (rows[0]["session"], rows[0]["session_date"], rows[0]["reference_date"]) == (
        "overnight", date(2027, 1, 19), date(2027, 1, 15))
    assert w.validate(rows[0]) is None


def test_dry_run_entry_on_the_fixture_writes_nothing(tmp_path):
    env = {**os.environ, "TRADE_AI_CI": "1"}
    for k in ("DATABASE_URL", "PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, str(ENTRY), "--dry-run", "--fixture", str(FX), "--now",
                        "2026-11-02T02:30:00-05:00"], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["status"] == "dry_run" and out["dry_run"] is True and out["inserted"] == 0
    assert out["config_enabled"] is False and out["window"] == "futures_overnight"
    assert sorted((r["symbol"], r["session"]) for r in out["rows"]) == sorted(
        (s, "overnight") for s in ("/ES", "/NQ", "/YM", "QQQ", "SPY"))
    assert list(tmp_path.iterdir()) == []


# ── writer ──────────────────────────────────────────────────────────────────────────────────────────


def _row(**kw):
    end = _et(2026, 11, 2, 2, 0)
    r = {"symbol": "/ES", "session": "overnight", "session_date": date(2026, 11, 2), "bar_start": end - timedelta(
        milliseconds=1), "bar_end": end, "price": 6700.0, "volume": None, "reference_close": 6800.0,
         "reference_date": date(2026, 10, 30), "reference_basis": "x", "change_pct": -1.47, "feed": "schwab"}
    r.update(kw)
    return r


def test_writer_overnight_contract():
    assert w.validate(_row()) is None
    assert w.validate(_row(reference_close=None, reference_date=None, change_pct=None)) is None  # level only
    assert "missing" in w.validate(_row(reference_close=None))  # partial reference
    assert "missing" in w.validate(_row(change_pct=None))
    assert "missing" in w.validate(_row(reference_basis=None, reference_close=None, reference_date=None,
                                        change_pct=None))
    assert "reference_date" in w.validate(_row(reference_date=date(2026, 10, 29)))  # not the last session
    assert "session_date" in w.validate(_row(session_date=date(2026, 11, 3)))
    assert "does not contain" in w.validate(_row(bar_end=_et(2026, 11, 2, 4, 0), bar_start=_et(2026, 11, 2, 3, 59)))
    assert "does not contain" in w.validate(_row(bar_end=_et(2026, 10, 30, 21, 0), bar_start=_et(2026, 10, 30, 20, 59),
                                                 session_date=date(2026, 11, 2)))  # Friday night
    assert "does not contain" in w.validate(_row(session="futures_open"))  # Monday 02:00 is not the Sunday open
    fo = _row(session="futures_open", bar_end=_et(2026, 11, 1, 18, 30), bar_start=_et(2026, 11, 1, 18, 29))
    assert w.validate(fo) is None
    assert "timezone" in w.validate(_row(bar_end=datetime(2026, 11, 2, 2, 0), bar_start=datetime(2026, 11, 2, 1, 59)))


def test_writer_still_requires_a_reference_for_premarket_and_afterhours():
    pm = _row(session="premarket", bar_end=_et(2026, 11, 2, 8, 0), bar_start=_et(2026, 11, 2, 7, 55))
    assert w.validate(pm) is None
    assert "missing" in w.validate(dict(pm, reference_close=None, reference_date=None, change_pct=None))
    assert "session" in w.validate(dict(pm, session="regular"))


def test_writer_inserts_level_only_rows_with_nulls():
    class Cur:
        rowcount = 1
        calls: list = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

    cur = Cur()
    res = w.write_extended_quotes(cur, [_row(reference_close=None, reference_date=None, change_pct=None)])
    assert res["inserted"] == 1 and res["rejected"] == []
    params = dict(zip(w.COLUMNS, cur.calls[0][1]))
    assert params["reference_close"] is None and params["change_pct"] is None and params["session"] == "overnight"


# ── engine reader and category ──────────────────────────────────────────────────────────────────────


def test_reader_returns_level_only_rows_as_none_never_zero():
    from scripts.lib.market_risk.reader import EXTENDED_TABLE, PgReader

    class Rd(PgReader):
        def _rows(self, sql, params):
            if "to_regclass" in sql:
                return [{"present": True}]
            if EXTENDED_TABLE in sql:
                return [{"symbol": "/ES", "session": "overnight", "session_date": date(2026, 11, 2), "price": 6700.0,
                         "reference_close": None, "reference_date": None, "change_pct": None, "volume": None,
                         "bar_end": datetime(2026, 11, 2, 7, 0, tzinfo=UTC), "feed": "schwab",
                         "reference_basis": "none_level_only_no_reference_in_payload"}]
            return []

    rows = Rd(conn_factory=lambda: None).extended_quotes(["/ES"], start=_et(2026, 11, 1), end=_et(2026, 11, 2, 3))
    assert rows[0]["prev_close"] is None and rows[0]["day_change_pct"] is None and rows[0]["reference_date"] is None
    assert rows[0]["session"] == "overnight" and rows[0]["session_date"] == "2026-11-02"


class _Reader:
    def __init__(self, rows):
        self.rows = rows

    def quotes(self, symbols, *, start, end):
        return [r for r in self.rows if r["symbol"] in symbols and start <= datetime.fromisoformat(r["as_of"]) <= end]


def _q(sym, at, price, prev=None, session="overnight", sdate="2026-11-02", ref_date="2026-10-30"):
    return {"symbol": sym, "session": session, "session_date": sdate, "price": price, "prev_close": prev,
            "reference_date": ref_date if prev is not None else None, "as_of": at.isoformat(),
            "source": "market_quotes_extended:schwab"}


POLICY = load_policy()


def _eval(rows, now):
    return extended_hours.evaluate(EvalContext(now=now, reader=_Reader(rows), policy=POLICY, session="closed"))


def test_fresh_overnight_futures_drop_is_measured():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("/NQ", now - timedelta(minutes=2), 25300.0, 25700.0)], now)
    assert obs.state == "STRESS" and "/NQ" in obs.headline
    assert "overnight, trading date 2026-11-02" in obs.evidence[0].detail
    assert obs.stale_after_hours == pytest.approx(45 / 60)


def test_stale_overnight_is_unknown_naming_session_and_age_never_calm():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("QQQ", now - timedelta(minutes=60), 700.5, 700.0),
                 _q("/ES", now - timedelta(minutes=95), 6801.0, 6800.0)], now)
    assert obs.state == "UNKNOWN" and obs.score is None
    assert "overnight" in obs.reason_unknown and "60 min old" in obs.reason_unknown
    assert "95 min old" in obs.reason_unknown and "QQQ" in obs.reason_unknown and "/ES" in obs.reason_unknown
    assert "trading date 2026-11-02" in obs.reason_unknown and "never CALM" in obs.reason_unknown
    # the same rows, fresh, are CALM: staleness alone made it UNKNOWN
    assert _eval([_q("QQQ", now - timedelta(minutes=5), 700.5, 700.0)], now).state == "CALM"


def test_stale_overnight_row_is_dropped_but_fresh_one_still_measured():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("QQQ", now - timedelta(minutes=60), 600.0, 700.0),  # a stale -14% must not drive it
                 _q("/ES", now - timedelta(minutes=3), 6799.0, 6800.0)], now)
    assert obs.state == "CALM" and any("QQQ overnight quote stale" in e.label for e in obs.evidence)


def test_level_only_futures_compare_with_the_first_stored_level():
    now = _et(2026, 11, 2, 2, 30)
    rows = [_q("/ES", _et(2026, 11, 1, 18, 1), 6800.0, session="futures_open"),
            _q("/ES", _et(2026, 11, 1, 23, 0), 6760.0),
            _q("/ES", now - timedelta(minutes=1), 6680.0)]
    obs = _eval(rows, now)
    assert obs.state == "STRESS"  # -1.76% since the Sunday open
    assert "first stored futures_open level Sun 18:01 ET (no close in payload)" in obs.evidence[0].detail


def test_single_level_only_row_has_no_move_and_is_unknown():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("/ES", now - timedelta(minutes=1), 6680.0)], now)
    assert obs.state == "UNKNOWN" and obs.score is None


def test_baselines_never_cross_trading_dates():
    rows = _overnight.with_baselines([
        _q("/ES", _et(2026, 11, 2, 21, 0), 6900.0, sdate="2026-11-03"),
        _q("/ES", _et(2026, 11, 2, 2, 0), 6800.0),
        _q("/ES", _et(2026, 11, 2, 23, 0), 6850.0, sdate="2026-11-03"),
    ])
    assert rows[1]["prev_close"] is None and rows[2]["prev_close"] == 6900.0


def test_policy_without_overnight_section_fails_loudly_only_when_a_night_row_exists():
    cfg = {k: v for k, v in POLICY["extended_hours"].items() if k != "overnight"}
    fresh, stale = _overnight.split_stale({"QQQ": _q("QQQ", _et(2026, 11, 2, 8), 1.0, 1.0, "premarket")},
                                          _et(2026, 11, 2, 8, 5), cfg)
    assert list(fresh) == ["QQQ"] and stale == []
    with pytest.raises(ValueError):
        _overnight.split_stale({"/ES": _q("/ES", _et(2026, 11, 2, 2), 1.0)}, _et(2026, 11, 2, 2, 5), cfg)


# ── migration (static + throwaway cluster; never the live DB) ───────────────────────────────────────


def _code(path: Path) -> str:
    return "\n".join(line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())


def test_migration_is_additive_and_ordered_after_2384():
    up, down = _code(UP), _code(DOWN)
    assert sorted([BASE_UP.name, UP.name])[-1] == UP.name
    assert not re.search(r"\b(DELETE|UPDATE|TRUNCATE|DROP\s+TABLE|DROP\s+COLUMN|INSERT)\b", up, re.I)
    assert not re.search(r"\b(DELETE|TRUNCATE|DROP\s+TABLE|DROP\s+COLUMN)\b", down, re.I)
    assert "'overnight', 'futures_open'" in up and "RAISE EXCEPTION" in up and "RAISE EXCEPTION" in down


def _bin() -> Path | None:
    for major in ("18", "17", "16", "15"):
        d = Path(f"/usr/lib/postgresql/{major}/bin")
        if (d / "initdb").is_file() and (d / "pg_ctl").is_file() and (d / "psql").is_file():
            return d
    return None


BIN = _bin()


@pytest.fixture(scope="module")
def cluster():
    base = Path(tempfile.mkdtemp(prefix="mqo-pg-", dir=os.environ.get("TMPDIR") or None))
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    env = {**os.environ, "LC_ALL": "C"}
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD", "PGSERVICE", "PGPASSFILE", "DATABASE_URL"):
        env.pop(k, None)
    subprocess.run([str(BIN / "initdb"), "-D", str(data), "-U", "mqo", "--auth=trust", "-E", "UTF8"], check=True,
                   capture_output=True, env=env)
    port = "55441"
    opts = f"-c listen_addresses='' -c unix_socket_directories={sock} -p {port} -c fsync=off"
    subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-o", opts, "-l", str(base / "log"), "-w", "start"],
                   check=True, capture_output=True, env=env)

    def psql(sql=None, file=None):
        argv = [str(BIN / "psql"), "-X", "-h", str(sock), "-p", port, "-U", "mqo", "-d", "postgres", "-v",
                "ON_ERROR_STOP=1", "-tA"] + (["-f", str(file)] if file else ["-c", sql])
        p = subprocess.run(argv, capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    try:
        yield psql
    finally:
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], capture_output=True, env=env)
        shutil.rmtree(base, ignore_errors=True)  # scratch this test created


_INS = ("INSERT INTO market_quotes_extended (symbol, session, session_date, bar_start, bar_end, price, volume, "
        "reference_close, reference_date, reference_basis, change_pct, feed) VALUES ")


@pytest.mark.skipif(BIN is None, reason="no PostgreSQL server binaries on this host")
def test_migration_on_a_throwaway_cluster(cluster):
    psql = cluster
    rc, out = psql(file=UP)
    assert rc != 0 and "apply migrations/2026_10_31_market_quotes_extended.sql first" in out  # refuses before #2384
    assert psql(file=BASE_UP)[0] == 0
    pm = ("('QQQ','premarket','2026-10-30','2026-10-30 08:00-04','2026-10-30 08:05-04',700,1,701,'2026-10-29',"
          "'b',-0.14,'sip')")
    assert psql(_INS + pm)[0] == 0
    _, before = psql("SELECT ctid, xmin, relfilenode FROM market_quotes_extended, pg_class "
                     "WHERE relname='market_quotes_extended'")
    night = ("('/ES','overnight','2026-11-02','2026-11-02 02:00-05','2026-11-02 02:00:00.001-05',6700,NULL,NULL,NULL,"
             "'none_level_only',NULL,'schwab')")
    assert psql(_INS + night)[0] != 0  # #2384's store refuses overnight
    rc, out = psql(file=UP)
    assert rc == 0, out
    assert psql(file=UP)[0] == 0  # idempotent
    _, after = psql("SELECT ctid, xmin, relfilenode FROM market_quotes_extended, pg_class "
                    "WHERE relname='market_quotes_extended'")
    assert after == before  # existing row and table file untouched: nothing rewritten
    assert psql(_INS + night)[0] == 0  # level-only overnight row accepted
    fo = ("('/ES','futures_open','2026-11-02','2026-11-01 18:00-05','2026-11-01 18:00:00.001-05',6750,NULL,6800,"
          "'2026-10-30','settle',-0.74,'schwab')")
    assert psql(_INS + fo)[0] == 0
    bad = [
        ("('QQQ','premarket','2026-11-02','2026-11-02 08:00-05','2026-11-02 08:05-05',700,1,NULL,NULL,'b',NULL,'sip')",
         "market_quotes_extended_reference_ck"),  # premarket still needs a reference
        ("('/NQ','overnight','2026-11-02','2026-11-02 02:00-05','2026-11-02 02:00:01-05',1,NULL,2,NULL,'b',NULL,'s')",
         "market_quotes_extended_reference_ck"),  # partial reference
        ("('/NQ','regular','2026-11-02','2026-11-02 10:00-05','2026-11-02 10:05-05',1,NULL,2,'2026-10-30','b',1,'s')",
         "market_quotes_extended_session_check"),
    ]
    for vals, con in bad:
        rc, out = psql(_INS + vals)
        assert rc != 0 and con in out, out
    rc, out = psql(file=DOWN)
    assert rc != 0 and "refused: 2 overnight/futures_open or reference-less rows" in out
    assert psql("SELECT count(*) FROM market_quotes_extended")[1] == "3"  # the down deleted nothing
