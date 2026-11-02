"""ANCHOR MARKET_QUOTES_OVERNIGHT_20261031 -- overnight (20:00-04:00 ET, Sunday night to Friday 04:00) and Sunday
18:00 futures-open sessions in ``market_quotes_extended`` (operator 2026-10-31: "No excuses").

Proves the session definition (DST weekends, the Sunday futures open, holiday trading dates, no Friday-night session,
04:00:00 is pre-market), the next-trading-day trading date on the market_day_gate.sh calendar, the reference rule
(the last regular close before the night, or level-only and never invented), the writer, the Schwab producer
(fixture dry run, no network, no DB), the engine reader and category (stale overnight -> UNKNOWN naming session and
age, never CALM), and the additive migration on a throwaway socket-only Postgres cluster (never the live DB).

Review round 1 (2026-10-31) fixes, each with the reviewer's exact failing input: F1 a level-only print never erases a
real after-hours selloff (tied to the close through an earlier referenced print, else UNKNOWN); F2/F4 an undated or
wrong-day reference is never trusted, in any session; F3 a stale print never rides on a fresh one (per-symbol aging,
#2425); F5 every Schwab batch failing is http_error with a non-zero exit; F6 weekday futures after-hours have a
reference rule; F7 the Alpaca dry run is fixture-only.
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
    assert es["reference_basis"] == "schwab_quote_close_price_settle_dated"
    assert es["change_pct"] == round(100 * (6698.25 - 6800.0) / 6800.0, 4)
    assert qqq["price"] == 690.5 and qqq["reference_close"] == 700.0 and qqq["reference_date"] == date(2026, 10, 30)
    assert qqq["reference_basis"] == "schwab_regular_market_last_price_dated"
    # settle dated Thursday, no closePrice, no regular block: the level is stored, the reference is NOT invented
    for sym in ("/NQ", "/YM", "SPY"):
        r = by[sym]
        assert r["reference_close"] is None and r["reference_date"] is None and r["change_pct"] is None
        assert r["reference_basis"] == "none_level_only_no_dated_reference_in_payload" and r["level_only_reason"]
    assert "2026-10-29" in by["/NQ"]["level_only_reason"]
    # 'not entitled' is Schwab's provider-error block, named as such (never silently a symbol that returned no quote)
    assert skipped["$SPX"]["reason"] == "stale_trade" and skipped["/RTY"]["reason"] == "provider_error"


def test_undated_reference_is_never_trusted(ocfg):
    """Review of #2423 F2: /ES Tue 02:30 with closePrice 6800 and NO settleTime, and NVDA with a regular close but no
    regularMarketTradeTime, are stored as levels -- not as a -1.47% move against an unproven close."""
    t = _et(2026, 11, 3, 2, 30)
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6700.0, "closePrice": 6800.0, "tradeTime": _ms(t)}},
         "NVDA": {"assetMainType": "EQUITY", "quote": {"lastPrice": 190.0, "tradeTime": _ms(t)},
                  "regular": {"regularMarketLastPrice": 200.0}}}
    rows, skipped = oq.schwab_rows(p, t + timedelta(minutes=1), ocfg)
    assert skipped == [] and {r["symbol"] for r in rows} == {"/ES", "NVDA"}
    for r in rows:
        assert r["session"] == "overnight" and r["reference_close"] is None and r["change_pct"] is None
        assert "undated" in r["level_only_reason"] and w.validate(r) is None


def test_afterhours_and_premarket_references_need_date_proof(ocfg):
    """Review of #2416 F4: AAPL Mon 11-02 17:00 with a regular block dated Fri 10-30 must NOT be stamped +5.26% vs
    11-02; undated premarket/after-hours closes are refused (those sessions cannot store a level)."""
    t = _et(2026, 11, 2, 17, 0)
    p = {"AAPL": {"assetMainType": "EQUITY", "quote": {"lastPrice": 210.5, "tradeTime": _ms(t)},
                  "regular": {"regularMarketLastPrice": 200.0, "regularMarketTradeTime": _ms(_et(2026, 10, 30, 16))}},
         "MSFT": {"assetMainType": "EQUITY", "quote": {"lastPrice": 500.0, "tradeTime": _ms(t)},
                  "regular": {"regularMarketLastPrice": 505.0}}}
    rows, skipped = oq.schwab_rows(p, t + timedelta(minutes=1), ocfg)
    assert rows == []
    why = {x["symbol"]: (x["reason"], x["detail"]) for x in skipped}
    assert why["AAPL"][0] == "no_dated_reference_for_afterhours" and "dated 2026-10-30, not 2026-11-02" in why["AAPL"][1]
    assert why["MSFT"][0] == "no_dated_reference_for_afterhours" and "undated" in why["MSFT"][1]
    pm = _et(2026, 11, 3, 8, 0)
    q = {"AAPL": {"assetMainType": "EQUITY", "quote": {"lastPrice": 199.0, "tradeTime": _ms(pm)},
                  "regular": {"regularMarketLastPrice": 200.0, "regularMarketTradeTime": _ms(_et(2026, 11, 2, 16))}}}
    rows, _ = oq.schwab_rows(q, pm + timedelta(minutes=1), ocfg)
    assert rows[0]["session"] == "premarket" and rows[0]["reference_date"] == date(2026, 11, 2)


def test_weekday_futures_after_hours_have_a_reference_rule(ocfg):
    """Review of #2423 F6: /NQ Thu 18:15 is after-hours; it is measured from Thursday's settlement when Schwab dates
    it, and refused (never assumed) when it does not."""
    t = _et(2026, 10, 29, 18, 15)
    dated = {"/NQ": {"assetMainType": "FUTURE", "quote": {"lastPrice": 25300.0, "closePrice": 25700.0,
                                                          "tradeTime": _ms(t), "settleTime": _ms(_et(2026, 10, 29, 16))}}}
    rows, _ = oq.schwab_rows(dated, t + timedelta(minutes=1), ocfg)
    assert (rows[0]["session"], rows[0]["reference_date"], rows[0]["change_pct"]) == (
        "afterhours", date(2026, 10, 29), round(100 * (25300 - 25700) / 25700, 4))
    assert w.validate(rows[0]) is None
    stale_settle = {"/NQ": {**dated["/NQ"], "quote": {**dated["/NQ"]["quote"], "settleTime": _ms(_et(2026, 10, 28, 16))}}}
    rows, skipped = oq.schwab_rows(stale_settle, t + timedelta(minutes=1), ocfg)
    assert rows == [] and skipped[0]["reason"] == "no_dated_reference_for_afterhours"


def test_sunday_futures_open_row(ocfg):
    t = _et(2026, 11, 1, 18, 0, 5)
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0, "tradeTime": _ms(t),
                                                      "settleTime": _ms(_et(2026, 10, 30, 16, 0))}},
         "/NQ": {"assetMainType": "FUTURE", "quote": {"lastPrice": 25000.0, "closePrice": 25500.0, "tradeTime": _ms(t)}},
         "QQQ": {"assetMainType": "EQUITY", "quote": {"lastPrice": 699.0, "tradeTime": _ms(t)}}}
    rows, skipped = oq.schwab_rows(p, _et(2026, 11, 1, 18, 1), ocfg)
    by = {r["symbol"]: r for r in rows}
    assert (by["/ES"]["session"], by["/ES"]["session_date"], by["/ES"]["reference_date"]) == (
        "futures_open", date(2026, 11, 2), date(2026, 10, 30))
    assert by["/NQ"]["session"] == "futures_open" and by["/NQ"]["reference_close"] is None  # undated: level only
    assert all(w.validate(r) is None for r in rows)
    assert [(x["symbol"], x["reason"]) for x in skipped] == [("QQQ", "session_not_in_store_contract")]


def test_friday_20_00_print_is_refused(ocfg):
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0,
                                                      "tradeTime": _ms(_et(2026, 10, 30, 20, 0))}}}
    rows, skipped = oq.schwab_rows(p, _et(2026, 10, 30, 20, 1), ocfg)
    assert rows == [] and skipped[0]["reason"] == "session_not_in_store_contract"


def test_04_00_00_print_is_stored_as_premarket(ocfg):
    p = {"/ES": {"assetMainType": "FUTURE", "quote": {"lastPrice": 6750.0, "closePrice": 6800.0,
                                                      "tradeTime": _ms(_et(2026, 11, 2, 4, 0, 0)),
                                                      "settleTime": _ms(_et(2026, 10, 30, 16, 0))}}}
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


def _fake_fetch_env(monkeypatch, statuses):
    """live_fetch with fake requests + token manager (never the real token store, never the network)."""
    import types

    import market_quotes_offhours_schwab as ent
    from lib import schwab_access_mode as sam

    monkeypatch.setattr(sam, "reads_allowed", lambda: True)
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, "{}" if code == 200 else "server error"

        def json(self):
            return {"/ES": {"quote": {"lastPrice": 1.0}}}

    req = types.ModuleType("requests")
    req.get = lambda *a, **k: (calls.append(k["params"]["symbols"]), Resp(statuses[len(calls) - 1]))[1]
    tm = types.ModuleType("schwab_token_manager")
    tm.canonical_token_key = lambda: "k"
    tm.health = lambda key: {"access_fresh": True}
    tm.get_access_token = lambda key: "fake-token"
    tm.is_auth_failure = lambda text: False
    tm.record_auth_failure = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "requests", req)
    monkeypatch.setitem(sys.modules, "schwab_token_manager", tm)
    return ent, calls


def test_stale_access_token_fails_closed_without_refresh(ocfg, monkeypatch):
    """The lane never refreshes: a stale access token stops before get_access_token (which can refresh) and before
    any Schwab request."""
    ent, calls = _fake_fetch_env(monkeypatch, [200])
    tm = sys.modules["schwab_token_manager"]
    monkeypatch.setattr(tm, "health", lambda key: {"access_fresh": False, "refresh_valid": True})
    monkeypatch.setattr(tm, "get_access_token", lambda key: (_ for _ in ()).throw(AssertionError("refresh path")))
    out = ent.live_fetch(["/ES"], ocfg)
    assert out["_status"] == "no_token" and "never refreshes" in out["_detail"] and calls == []


def test_all_schwab_batches_failing_is_an_error_not_ok(ocfg, monkeypatch, capsys):
    """Review of #2416 F5: every batch failing returned status ok, 0 rows, exit 0."""
    cfg = {**ocfg, "schwab": {**ocfg["schwab"], "batch_size": 2}}
    ent, calls = _fake_fetch_env(monkeypatch, [500, 503])
    out = ent.live_fetch(["/ES", "/NQ", "QQQ"], cfg)
    assert len(calls) == 2 and out["_status"] == "http_error" and len(out["_failed"]) == 2
    r = oq.run(cfg={**cfg, "schwab": {**cfg["schwab"], "enabled": True}}, now=_et(2026, 11, 2, 2, 30),
               fetch=lambda s: out, write=lambda rows: {}, dry_run=False, promoted=lambda: True, force_window=True)
    assert r["status"] == "http_error" and r["inserted"] == 0 and len(r["failed_batches"]) == 2
    monkeypatch.setattr(ent.oq, "run", lambda **k: r)
    monkeypatch.setattr(ent.oq, "load_config", lambda *_a: cfg)
    assert ent.main(["--apply"]) == 1  # non-zero exit


def test_partial_batch_failure_is_reported(ocfg, monkeypatch):
    cfg = {**ocfg, "schwab": {**ocfg["schwab"], "batch_size": 2}}
    ent, _ = _fake_fetch_env(monkeypatch, [200, 500])
    out = ent.live_fetch(["/ES", "/NQ", "QQQ"], cfg)
    assert "_status" not in out and out["_failed"] == [{"batch": 1, "http_status": 500}]
    got = []
    r = oq.run(cfg={**cfg, "schwab": {**cfg["schwab"], "enabled": True}}, now=_et(2026, 11, 2, 2, 30),
               fetch=lambda s: out, write=lambda rows: got.extend(rows) or {"inserted": len(rows)}, dry_run=False,
               promoted=lambda: True, force_window=True)
    assert r["status"] == "partial" and r["failed_batches"] == [{"batch": 1, "http_status": 500}]
    assert all(x["symbol"] != "_FAILED" for x in r["skipped"])


def test_alpaca_dry_run_is_fixture_only(monkeypatch, capsys):
    """Review of #2384 F7: the default dry run without --bars-json called Alpaca live."""
    def boom(*_a, **_k):
        raise AssertionError("dry run reached the live Alpaca fetch")

    monkeypatch.setattr(mqe, "fetch", boom)
    assert mqe.main([]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "fixture-only" in out["detail"] and out["source"] is None
    monkeypatch.setattr(mqe, "fetch", lambda cfg, now: ({}, {}))
    assert mqe.main(["--live-read"]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "alpaca_live"

def test_dry_run_entry_on_the_fixture_writes_nothing(tmp_path):
    env = {**os.environ, "TRADE_AI_CI": "1"}
    for k in ("DATABASE_URL", "PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, str(ENTRY), "--dry-run", "--fixture", str(FX), "--now",
                        "2026-11-02T02:30:00-05:00"], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["status"] == "dry_run" and out["dry_run"] is True and out["inserted"] == 0
    assert out["config_enabled"] is True and out["window"] == "futures_overnight"
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


def _q(sym, at, price, prev=None, session="overnight", sdate="2026-11-02", ref_date="2026-10-30", feed="schwab"):
    return {"symbol": sym, "session": session, "session_date": sdate, "price": price, "prev_close": prev,
            "reference_date": ref_date if prev is not None else None, "as_of": at.isoformat(),
            "reference_basis": "x" if prev is not None else "none_level_only", "source": f"market_quotes_extended:{feed}"}


POLICY = load_policy()


def _eval(rows, now):
    return extended_hours.evaluate(EvalContext(now=now, reader=_Reader(rows), policy=POLICY, session="closed"))


def test_fresh_overnight_futures_drop_is_measured():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("/NQ", now - timedelta(minutes=2), 25300.0, 25700.0)], now)
    assert obs.state == "STRESS" and "/NQ" in obs.headline  # a real fresh STRESS stands without QQQ/SPY
    assert obs.evidence[0].label.startswith("/NQ overnight move")
    assert obs.stale_after_hours == pytest.approx(45 / 60)


def test_sunday_futures_open_print_is_measured_from_friday_close():
    now = _et(2026, 11, 1, 18, 10)
    obs = _eval([_q("/NQ", _et(2026, 11, 1, 18, 5), 25200.0, 25700.0, "futures_open")], now)
    assert obs.state == "STRESS" and obs.evidence[0].label.startswith("/NQ futures_open move")
    assert "2026-10-30 close" in obs.evidence[0].detail


def test_stale_overnight_is_unknown_naming_session_and_age_never_calm():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("QQQ", now - timedelta(minutes=60), 700.5, 700.0),
                 _q("SPY", now - timedelta(minutes=50), 671.0, 670.0),
                 _q("/ES", now - timedelta(minutes=95), 6801.0, 6800.0)], now)
    assert obs.state == "UNKNOWN" and obs.score is None
    r = obs.reason_unknown
    assert "QQQ +0.1% overnight (trading date 2026-11-02)" in r and "60 min old" in r and "50 min old" in r
    assert "limit 45 min; never CALM" in r
    # the same rows, fresh, are CALM: staleness alone made it UNKNOWN
    fresh = [_q("QQQ", now - timedelta(minutes=5), 700.5, 700.0), _q("SPY", now - timedelta(minutes=5), 671.0, 670.0)]
    assert _eval(fresh, now).state == "CALM"


def test_one_stale_proxy_is_named_and_blocks_calm():
    now = _et(2026, 11, 2, 2, 30)
    obs = _eval([_q("QQQ", now - timedelta(minutes=60), 600.0, 700.0),  # a stale -14% must not drive it
                 _q("SPY", now - timedelta(minutes=3), 670.1, 670.0),
                 _q("/ES", now - timedelta(minutes=3), 6799.0, 6800.0)], now)
    assert obs.state == "UNKNOWN" and "QQQ" in obs.reason_unknown and "never STRESS" not in obs.reason_unknown


def test_f1_level_only_never_erases_a_real_after_hours_selloff():
    """Review of #2423 F1 (exact input): Thu 10-29 Alpaca 19:55 after-hours SPY 686.7 vs 700 and QQQ 588.6 vs 600
    (-1.9%), then Schwab level-only overnight rows at 20:05 and 20:20. At 20:22 the engine must still see -1.9% vs
    Thursday's close (anchored through the after-hours print), never CALM +0.1% vs its own first print."""
    now = _et(2026, 10, 29, 20, 22)
    rows = [
        _q("SPY", _et(2026, 10, 29, 19, 55), 686.7, 700.0, "afterhours", "2026-10-29", "2026-10-29", "sip"),
        _q("QQQ", _et(2026, 10, 29, 19, 55), 588.6, 600.0, "afterhours", "2026-10-29", "2026-10-29", "sip"),
        _q("SPY", _et(2026, 10, 29, 20, 5), 686.5, sdate="2026-10-30"),
        _q("QQQ", _et(2026, 10, 29, 20, 5), 588.5, sdate="2026-10-30"),
        _q("SPY", _et(2026, 10, 29, 20, 20), 686.9, sdate="2026-10-30"),
        _q("QQQ", _et(2026, 10, 29, 20, 20), 588.9, sdate="2026-10-30"),
    ]
    obs = _eval(rows, now)
    assert obs.state == "STRESS", (obs.state, obs.headline, obs.reason_unknown)
    assert "SPY -1.9% extended" in obs.headline  # SPY -1.87% is the worst proxy; QQQ -1.83%
    ev = {e.label.split()[0]: e for e in obs.evidence if "move vs" in e.label}
    assert "2026-10-29 close (via afterhours market_quotes_extended:sip print Thu 10-29 19:55 ET)" in ev["SPY"].label
    assert ev["SPY"].value == pytest.approx(100 * (686.9 - 700) / 700, abs=0.01)


def test_f1_unanchored_level_only_reads_unknown():
    now = _et(2026, 10, 29, 20, 22)
    rows = [_q(s, _et(2026, 10, 29, 20, 20), p, sdate="2026-10-30") for s, p in (("SPY", 686.9), ("QQQ", 588.9))]
    obs = _eval(rows, now)
    r = obs.reason_unknown
    assert obs.state == "UNKNOWN" and "QQQ overnight Thu 10-29 20:20 ET" in r
    assert "level-only (no dated close); no earlier referenced QQQ print ties it to the 2026-10-29 close" in r
    assert "no earlier referenced SPY print" in r


def test_f1_anchor_must_measure_against_the_same_close():
    """Wednesday's after-hours print (vs Wednesday's close) cannot anchor Thursday night's level."""
    now = _et(2026, 10, 29, 20, 22)
    rows = [_q("SPY", _et(2026, 10, 28, 19, 55), 690.0, 700.0, "afterhours", "2026-10-28", "2026-10-28", "sip"),
            _q("SPY", _et(2026, 10, 29, 20, 20), 686.9, sdate="2026-10-30")]
    obs = _eval(rows, now)
    assert obs.state == "UNKNOWN"
    assert "no earlier referenced SPY print ties it to the 2026-10-29 close" in obs.reason_unknown


def test_f1_anchor_skips_a_newer_print_measured_against_another_close():
    """The anchor is the newest print measured against the RIGHT close, not just the newest print: a later row whose
    reference is Wednesday's close (a bad writer) must not stop Thursday's 19:30 after-hours print anchoring the night."""
    now = _et(2026, 10, 29, 20, 22)
    rows = [_q("SPY", _et(2026, 10, 29, 19, 30), 686.0, 700.0, "afterhours", "2026-10-29", "2026-10-29", "sip"),
            _q("QQQ", _et(2026, 10, 29, 19, 30), 588.0, 600.0, "afterhours", "2026-10-29", "2026-10-29", "sip"),
            _q("SPY", _et(2026, 10, 29, 19, 55), 686.5, 690.0, "afterhours", "2026-10-29", "2026-10-28", "sip"),
            _q("QQQ", _et(2026, 10, 29, 19, 55), 588.5, 590.0, "afterhours", "2026-10-29", "2026-10-28", "sip"),
            _q("SPY", _et(2026, 10, 29, 20, 20), 686.9, sdate="2026-10-30"),
            _q("QQQ", _et(2026, 10, 29, 20, 20), 588.9, sdate="2026-10-30")]
    obs = _eval(rows, now)
    assert obs.state == "STRESS" and "via afterhours market_quotes_extended:sip print Thu 10-29 19:30 ET" in str(
        obs.evidence)


def test_f3_stale_after_hours_does_not_ride_on_a_fresh_row():
    """Review of #2423 F3 (exact inputs): SPY/QQQ from Mon 19:55 + a fresh NVDA overnight row at Tue 03:00 is not
    CALM; a stale SPY -1.6% + a fresh flat /ES is not STRESS. Each symbol is aged on its own row."""
    now = _et(2026, 11, 3, 3, 0)
    mon = lambda s, p, prev: _q(s, _et(2026, 11, 2, 19, 55), p, prev, "afterhours", "2026-11-02", "2026-11-02", "sip")
    calm = _eval([mon("SPY", 670.0, 670.5), mon("QQQ", 600.0, 600.2),
                  _q("NVDA", now - timedelta(minutes=1), 200.0, 200.5, sdate="2026-11-03", ref_date="2026-11-02")], now)
    assert calm.state == "UNKNOWN" and "market hours old" in calm.reason_unknown
    stress = _eval([mon("SPY", 659.8, 670.5), mon("QQQ", 600.0, 600.2),
                    _q("/ES", now - timedelta(minutes=1), 6801.0, 6800.0, sdate="2026-11-03", ref_date="2026-11-02")],
                   now)
    assert stress.state != "STRESS" and stress.state == "UNKNOWN"
    assert "SPY -1.6% at Mon 11-02 19:55 ET" in stress.reason_unknown


def test_policy_without_overnight_section_fails_loudly_only_when_a_night_row_exists():
    cfg = {k: v for k, v in POLICY["extended_hours"].items() if k != "overnight"}
    now = _et(2026, 11, 2, 8, 5)
    assert _overnight.is_fresh(_q("QQQ", _et(2026, 11, 2, 8), 1.0, 1.0, "premarket"), 0.1, 2.0, now, cfg)
    with pytest.raises(ValueError):
        _overnight.is_fresh(_q("/ES", _et(2026, 11, 2, 2), 1.0), None, 2.0, now, cfg)


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
