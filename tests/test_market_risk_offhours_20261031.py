"""Market Risk Engine off-hours (after-hours, overnight 24/5, weekend, Sunday futures/Asia open, premarket).

Measured 2026-10-31 on live data (read-only) before this change:
* decay aged Friday's close in wall-clock hours, so the same market facts read YELLOW 59.7 on Friday 18:30 ET,
  BLUE 39 on Saturday 19:50 and BLUE 27 (breadth UNKNOWN) on Monday 08:00 premarket, with no new information;
* ``PgReader.quotes`` returned no ``session`` field, so the extended_hours category ignored every production quote;
* an Alpaca quote fetched after Friday's close carries Thursday's close as ``prev_close``: QQQ 690.80 vs 715.42 read
  -3.4%, the regular-session move, as if it were an after-hours move;
* there was no way to write the snapshot Home reads without the alert path (``--apply`` sends, ``--dry-run`` writes
  nothing).

Hermetic: fake DB connection, temp state root, telegram import tripwired, no network.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib.market_risk import contract as c, reader as rd, scoring, sessions  # noqa: E402
from scripts.lib.market_risk.categories import extended_hours as xh  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")
P = load_policy()


def et(y, m, d, hh, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


# ── session labels ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "t,want",
    [
        (et(2026, 10, 30, 8, 0), "premarket"),
        (et(2026, 10, 30, 12, 0), "regular"),
        (et(2026, 10, 30, 17, 0), "afterhours"),
        (et(2026, 10, 30, 21, 0), "closed"),  # Friday night: no 24/5 session until Sunday 20:00
        (et(2026, 10, 29, 21, 0), "overnight"),  # Thursday night -> Friday
        (et(2026, 10, 30, 2, 0), "overnight"),
        (et(2026, 10, 31, 19, 50), "closed"),  # Saturday
        (et(2026, 11, 1, 18, 30), "closed"),  # Sunday futures open, equities overnight not yet
        (et(2026, 11, 1, 20, 30), "overnight"),  # Sunday 20:00 the 24/5 session opens
        (et(2026, 11, 25, 21, 0), "closed"),  # night before Thanksgiving: no session follows
        (et(2026, 11, 27, 14, 0), "afterhours"),  # early close 13:00
    ],
)
def test_session_label(t, want):
    assert sessions.session_label(t) == want


# ── market-hours clock ───────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "a,b,reopen,want",
    [
        (et(2026, 10, 30, 16), et(2026, 10, 31, 19, 50), "18:00", 8.0),  # Saturday: only Friday 16:00-24:00
        (et(2026, 10, 30, 16), et(2026, 11, 1, 18, 30), "18:00", 8.5),  # Sunday: + 18:00-18:30
        (et(2026, 10, 30, 16), et(2026, 11, 1, 18, 30), None, 8.0),
        (et(2026, 10, 30, 16), et(2026, 11, 2, 8, 0), "18:00", 8.0 + 6.0 + 8.0),  # Mon 08:00 EST (DST ended)
        (et(2026, 10, 29, 16), et(2026, 10, 30, 8, 0), "18:00", 16.0),  # an ordinary weeknight is all counted
        (et(2026, 11, 25, 16), et(2026, 11, 27, 9, 0), None, 8.0 + 9.0),  # Thanksgiving does not count
        (et(2026, 10, 31, 12), et(2026, 10, 31, 13), "18:00", 0.0),  # inside a weekend: nothing elapses
        (et(2026, 10, 31, 13), et(2026, 10, 31, 12), None, 0.0),  # reversed: never negative
    ],
)
def test_market_hours_between(a, b, reopen, want):
    ro = None if reopen is None else datetime.strptime(reopen, "%H:%M").time()
    assert sessions.market_hours_between(a, b, reopen=ro) == pytest.approx(want, abs=1e-6)


def test_dst_day_counts_25_hours_on_a_trading_calendar():
    # 2026-11-01 (Sunday) is 25 hours long; a weekday DST change would be too. Prove UTC arithmetic on a span that
    # crosses the change with the whole Sunday counted (reopen 00:00).
    got = sessions.market_hours_between(et(2026, 10, 31, 23), et(2026, 11, 2, 0), reopen=datetime.min.time())
    assert got == pytest.approx(25.0)  # Sunday 00:00 -> Monday 00:00 is 25 real hours; Saturday 23:00-24:00 not


def _obs(at, state="STRESS", score=80.0, stale=96.0, cat="technical"):
    return c.CategoryObservation(
        category=cat, state=state, score=score, observed_at=at.isoformat(), headline="x", stale_after_hours=stale
    )


def test_weekend_does_not_decay_fridays_close():
    o = _obs(et(2026, 10, 30, 16))
    w_sat, age_sat = scoring.decay_weight(o, et(2026, 10, 31, 19, 50), P)
    w_mon, age_mon = scoring.decay_weight(o, et(2026, 11, 2, 8, 0), P)
    assert (w_sat, age_sat) == (1.0, pytest.approx(8.0))
    assert w_mon == 0.8 and age_mon == pytest.approx(22.0)  # 0.8 >= confirm_min_weight: it still confirms a tier


def test_wall_clock_is_still_available_and_was_the_defect():
    wall = dict(P, decay=dict(P["decay"], clock="wall"))
    o = _obs(et(2026, 10, 30, 16))
    assert scoring.decay_weight(o, et(2026, 11, 2, 8, 0), wall)[0] == 0.4  # Friday's STRESS no longer confirms
    br = _obs(et(2026, 10, 30, 17, 25), state="WARN", score=40, stale=30.0, cat="breadth")
    assert scoring.decay_weight(br, et(2026, 11, 1, 18, 30), wall)[0] == 0.0  # breadth UNKNOWN by Sunday
    assert scoring.decay_weight(br, et(2026, 11, 1, 18, 30), P)[0] == 1.0


def test_stale_is_still_stale_on_a_weekday():
    # a collector that stops on Tuesday is not hidden by the market clock
    o = _obs(et(2026, 11, 3, 16), stale=30.0)
    assert scoring.decay_weight(o, et(2026, 11, 5, 9), P)[0] == 0.0


def test_composite_holds_its_tier_over_the_weekend():
    obs = [
        _obs(et(2026, 10, 30, 16), cat="technical"),
        _obs(et(2026, 10, 30, 17, 35), cat="options_flow", score=85),
    ]
    fri = scoring.compose(obs, P, prior=None, now=et(2026, 10, 30, 18, 30))
    mon = scoring.compose(obs, P, prior=None, now=et(2026, 11, 2, 8, 0))
    assert fri.score == pytest.approx(mon.score, rel=0.25) and mon.tier == fri.tier


# ── extended prints: market_quotes_extended rows (#2384 reader shape); market_quotes is never an extended print ─────
class _Cur:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, [], []

    def execute(self, sql, params=None):
        self.conn.log.append((sql, params))
        if "FROM market_quotes" in sql and "market_quotes_extended" not in sql:
            cols = ["symbol", "source", "price", "prev_close", "day_change_pct", "volume", "fetched_at"]
            rows = [
                r for r in self.conn.quotes if r["symbol"] in params[0] and params[1] <= r["fetched_at"] <= params[2]
            ]
        else:
            cols, rows = [], []
        self.description = [(x,) for x in cols]
        self._rows = [tuple(r.get(x) for x in cols) for r in rows]

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, quotes):
        self.quotes, self.log = quotes, []

    def set_session(self, readonly=False):
        self.readonly = readonly

    def cursor(self):
        return _Cur(self)

    def close(self):
        pass


def _q(sym, price, prev, at, source="alpaca"):
    return {
        "symbol": sym,
        "source": source,
        "price": price,
        "prev_close": prev,
        "day_change_pct": None,
        "volume": None,
        "fetched_at": at.astimezone(timezone.utc),
    }


def test_f4_market_quotes_rows_are_never_an_after_hours_move():
    # review of #2415, F4: a 10:00 quote and a 17:00 quote in market_quotes (fetch times, not trades) must not make
    # a -1.6% "after-hours" move. Through the production reader they are not extended prints at all.
    rows = [_q("QQQ", 700.0, 715.42, et(2026, 10, 30, 10)), _q("QQQ", 689.0, 715.42, et(2026, 10, 30, 17))]
    ctx = c.EvalContext(
        now=et(2026, 10, 30, 17, 5), reader=rd.PgReader(lambda: _Conn(rows)), policy=P, session="afterhours"
    )
    ctx.reader.session_opens = lambda *a, **k: []
    o = xh.evaluate(ctx)
    assert o.state == "UNKNOWN" and "no proven extended-session print" in o.reason_unknown


# ── extended_hours category over production-shaped rows ──────────────────────────────────────────────────────────
class _R:
    def __init__(self, rows, filt=True):
        self.rows, self.calls, self.filt = rows, [], filt

    def quotes(self, symbols, *, start, end):
        self.calls.append((start, end))
        return [
            r
            for r in self.rows
            if r["symbol"] in symbols and (not self.filt or start <= datetime.fromisoformat(r["as_of"]) <= end)
        ]

    def session_opens(self, symbols, *, sessions, end):
        return []

    def daily_bars(self, symbols, *, sessions, end):
        return []


def _row(sym, price, prev, at, session, source="market_quotes_extended:sip", ref_date=None):
    """A row as #2384's PgReader.extended_quotes returns it (bar_end -> as_of, reference_close -> prev_close)."""
    return {
        "symbol": sym,
        "price": price,
        "prev_close": prev,
        "as_of": at.isoformat(),
        "session": session,
        "source": source,
        "reference_date": ref_date or sessions.last_closed_session(at).isoformat(),
    }


def _ctx(now, rows, filt=True):
    return c.EvalContext(now=now, reader=_R(rows, filt), policy=P, session=sessions.session_label(now))


@pytest.mark.parametrize(
    "t,want",
    [
        (et(2026, 10, 30, 16, 5), "2026-10-30"),  # after-hours on D -> D
        (et(2026, 10, 30, 16, 0, 30), "2026-10-29"),  # inside the closing-snapshot minute: D not closed yet
        (et(2026, 11, 1, 20, 30), "2026-10-30"),  # Sunday overnight -> Friday
        (et(2026, 11, 2, 8), "2026-10-30"),  # Monday pre-market -> Friday
        (et(2026, 11, 27, 8), "2026-11-25"),  # the day after Thanksgiving -> Wednesday
        (et(2026, 11, 27, 13, 5), "2026-11-27"),  # early close 13:00
    ],
)
def test_last_closed_session(t, want):
    assert sessions.last_closed_session(t).isoformat() == want


def test_after_hours_print_is_read_with_its_age_and_reference():
    rows = [_row("QQQ", 675.0, 690.0, et(2026, 10, 30, 17, 0), "afterhours")]  # -2.2%
    o = xh.evaluate(_ctx(et(2026, 10, 30, 18, 0), rows))
    assert o.state == "STRESS" and "afterhours" in o.evidence[0].label
    d = o.evidence[0].detail
    assert "vs 2026-10-30 close" in d and "1.0h old" in d and "17:00 ET" in d
    assert o.evidence[0].source == "market_quotes_extended:sip"


def test_overnight_print_from_an_overnight_feed_counts():
    rows = [_row("SPY", 740.0, 750.0, et(2026, 11, 2, 1, 0), "overnight", source="schwab")]
    o = xh.evaluate(_ctx(et(2026, 11, 2, 1, 30), rows))
    assert o.state == "WARN"


@pytest.mark.parametrize("source", ["yfinance", "alpaca", "market_quotes"])
def test_market_quotes_feeds_are_not_extended_prints(source):
    rows = [_row("SPY", 740.0, 750.0, et(2026, 10, 30, 17, 54), "afterhours", source=source)]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 18, 0), rows))
    assert o.state == "UNKNOWN"


def test_f1_price_equal_to_the_close_is_not_a_calm_print():
    # live shape, Wed 10-28 16:45: IEX latestTrade still the closing print
    rows = [
        _row("QQQ", 725.59, 725.59, et(2026, 10, 28, 16, 45), "afterhours"),
        _row("SPY", 680.0, 680.0, et(2026, 10, 28, 16, 45), "afterhours"),
    ]
    o = xh.evaluate(_ctx(et(2026, 10, 28, 16, 50), rows))
    assert o.state == "UNKNOWN" and "no extended-session trade proven" in o.reason_unknown
    assert "QQQ" in o.reason_unknown and "SPY" in o.reason_unknown


def test_f1_alpaca_overnight_row_is_not_a_calm_print():
    rows = [_row("QQQ", 690.8, 690.54, et(2026, 11, 2, 2, 0), "overnight")]
    o = xh.evaluate(_ctx(et(2026, 11, 2, 2, 10), rows))
    assert o.state == "UNKNOWN" and "no overnight trades" in o.reason_unknown


def test_f1_newest_unproven_row_hides_an_older_print_for_that_symbol():
    rows = [
        _row("QQQ", 689.0, 690.54, et(2026, 10, 30, 16, 20), "afterhours"),
        _row("QQQ", 690.54, 690.54, et(2026, 10, 30, 16, 40), "afterhours"),
    ]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 16, 45), rows))
    assert o.state == "UNKNOWN"


def test_f4_reference_from_another_session_is_not_proven():
    # a Friday after-hours print against Thursday's close is the regular-session move (-3.4%), not an extended one
    rows = [_row("QQQ", 690.80, 715.42, et(2026, 10, 30, 16, 10), "afterhours", ref_date="2026-10-29")]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 16, 15), rows))
    assert o.state == "UNKNOWN" and "is not the 2026-10-30 session close" in o.reason_unknown


def test_f4_monday_premarket_against_fridays_close_counts():
    rows = [_row("QQQ", 680.0, 690.80, et(2026, 11, 2, 8, 0), "premarket", ref_date="2026-10-30")]
    o = xh.evaluate(_ctx(et(2026, 11, 2, 8, 30), rows))
    assert o.state == "STRESS"


def test_f5_future_quote_is_invalid():
    rows = [_row("QQQ", 670.0, 690.54, et(2026, 10, 30, 19, 0), "afterhours")]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 17, 0), rows, filt=False))
    assert o.state == "UNKNOWN" and "stamped in the future" in o.reason_unknown


def test_f5_stale_proxy_is_named_beside_a_fresh_one():
    rows = [
        _row("QQQ", 670.0, 690.54, et(2026, 10, 30, 16, 30), "afterhours"),
        _row("SPY", 681.0, 680.0, et(2026, 10, 30, 19, 0), "afterhours"),
    ]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 19, 30), rows))
    assert o.state == "CALM"
    assert "not measured: QQQ -3.0%" in o.headline and "3.0 market hours old" in o.headline
    assert any(e.label == "index proxy not measured" and "QQQ" in e.detail for e in o.evidence)


def test_weekend_names_the_last_after_hours_print_and_its_age():
    rows = [_row("QQQ", 690.80, 690.54, et(2026, 10, 30, 16, 9, 35), "afterhours")]
    ctx = _ctx(et(2026, 10, 31, 19, 50), rows)
    o = xh.evaluate(ctx)
    assert o.state == "UNKNOWN"
    assert "QQQ +0.0% at Fri 10-30 16:09 ET is 7.8 market hours old" in o.reason_unknown
    assert ctx.reader.calls[0][0] <= et(2026, 10, 30, 16, 0)  # the query reached back to Friday's close


def test_reader_error_is_named():
    ctx = _ctx(et(2026, 10, 30, 18, 0), [])
    ctx.reader.extended_quotes_error = "market_quotes_extended not created (migration not applied)"
    assert "migration not applied" in xh.evaluate(ctx).reason_unknown


# ── F2: every category's staleness on the market clock, with hard caps ───────────────────────────────────────────
def _bars(end_day, n=300):
    """Daily closes for the sector SPDRs + RSP/SPY ending ``end_day`` (weekdays only), each knowable at 16:00 ET."""
    from scripts.lib.market_risk.categories._marketdata import ts as _ts  # noqa: F401

    days, d = [], end_day
    while len(days) < n:
        if sessions.is_trading_day(d):
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    out = []
    for sym in P["breadth"]["proxy"]["universe"] + ["RSP", "SPY"]:
        for i, dd in enumerate(days):
            out.append(
                {
                    "symbol": sym,
                    "date": dd.isoformat(),
                    "close": 100.0 + i * 0.05,
                    "as_of": datetime.combine(dd, datetime.min.time().replace(hour=16), ET).isoformat(),
                }
            )
    return out


class _BreadthReader:
    def __init__(self, bars):
        self.bars = bars

    def sector_states(self, *, end):
        return []

    def daily_bars(self, symbols, *, sessions, end):
        return [b for b in self.bars if b["symbol"] in symbols and datetime.fromisoformat(b["as_of"]) <= end]


@pytest.mark.parametrize(
    "now,known",
    [
        (et(2026, 10, 31, 19, 50), True),  # Saturday
        (et(2026, 11, 1, 18, 30), True),  # Sunday futures open
        (et(2026, 11, 2, 8, 0), True),  # Monday premarket
        (et(2026, 11, 4, 9, 0), False),  # Wednesday morning: Friday's bars are really stale now
    ],
)
def test_f2_breadth_evaluates_over_the_weekend_from_fridays_bars(now, known):
    from datetime import date

    from scripts.lib.market_risk.categories import breadth

    ctx = c.EvalContext(now=now, reader=_BreadthReader(_bars(date(2026, 10, 30))), policy=P, session="closed")
    o = breadth.evaluate(ctx)
    assert (o.state != "UNKNOWN") is known, o.reason_unknown
    if not known:
        assert "stale" in o.reason_unknown and "no sector-ETF daily bars" not in o.reason_unknown


def test_f2_wall_cap_refuses_old_data_the_market_clock_would_keep():
    # 10 days of holidays-free wall time but a policy without a market cap: the wall cap still refuses it
    cfg = dict(P["decay"], max_market_hours=None)
    at = et(2026, 10, 23, 16)
    age, why = scoring.staleness(at, et(2026, 11, 2, 9), cfg, 999)
    assert why and "wall clock" in why
    _, why_m = scoring.staleness(at, et(2026, 11, 2, 9), P["decay"], 999)
    assert why_m and "market hours" in why_m


def test_f2_future_stamped_observation_is_unknown():
    o = _obs(et(2026, 10, 30, 18), cat="technical")
    assert scoring.decay_weight(o, et(2026, 10, 30, 16), P)[0] == 0.0


def test_f2_market_stale_helper_matches_the_scorer():
    from scripts.lib.market_risk.categories import _marketdata as md

    fri = et(2026, 10, 30, 16)
    assert not md.stale(fri, et(2026, 11, 2, 8), 30, P["decay"])  # Monday premarket: 22 market hours
    assert md.stale(fri, et(2026, 11, 2, 8), 30)  # wall clock (no policy): 64h
    assert not md.stale(fri, et(2026, 11, 4, 12), 999, P["decay"])  # 74 market hours: inside the 96h cap
    assert md.stale(fri, et(2026, 11, 5, 12), 999, P["decay"])  # 98 market hours: past the cap


# ── --shadow: snapshot written, alert path never touched; replays write no snapshot ──────────────────────────────
FIXED = datetime(2026, 10, 31, 23, 50, tzinfo=timezone.utc)


def _shadow_env(tmp_path, monkeypatch):
    import importlib

    ev = importlib.import_module("scripts.market_risk_evaluate")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(tmp_path / "ep.json"))
    monkeypatch.setenv("MARKET_RISK_SENT_LEDGER", str(tmp_path / "sk.json"))
    monkeypatch.setattr(ev, "production_reader", lambda: _R([]))

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED

    monkeypatch.setattr(ev, "datetime", _DT)
    return ev


def test_shadow_writes_snapshot_and_never_imports_telegram(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    trip = types.ModuleType("telegram_alert")

    def _boom(*a, **k):
        raise AssertionError("shadow reached send_telegram")

    trip.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", trip)
    monkeypatch.setitem(sys.modules, "scripts.telegram_alert", trip)
    from scripts.lib.market_risk import alerts

    monkeypatch.setattr(alerts, "deliver", _boom)
    monkeypatch.setattr(alerts, "outbox_put", _boom)
    assert ev.main(["--shadow", "--no-portfolio"]) == 0
    snap = json.loads((tmp_path / "data/runtime/market_risk_latest.json").read_text())
    assert snap["tier"] in c.TIERS and snap["mode"] == "shadow" and snap["history"][-1]["mode"] == "shadow"
    d = tmp_path / "data/runtime/market_risk"
    assert (d / "shadow_latest.json").exists() and not (d / "latest.json").exists()
    assert [p.name for p in (d / "receipts").iterdir()] == ["20261031T235000Z-shadow.json"]
    assert json.loads((d / "shadow_latest.json").read_text())["mode"] == "shadow"
    assert not (tmp_path / "ep.json").exists() and not (tmp_path / "sk.json").exists()


def test_f3_projection_carries_the_mode(tmp_path, monkeypatch):
    from scripts.lib import market_risk_projection as proj

    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--no-portfolio"]) == 0
    snap = json.loads((tmp_path / "data/runtime/market_risk_latest.json").read_text())
    assert proj.build(snap, None, now=FIXED)["mode"] == "shadow"
    assert proj.snapshot_from_assessment({"mode": "apply", "tier": "BLUE"})["mode"] == "live"


def test_f3_shadow_replay_never_writes_the_snapshot_or_prior(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--no-portfolio", "--as-of", "2026-10-29T19:00:00Z"]) == 0
    d = tmp_path / "data/runtime/market_risk"
    assert not (tmp_path / "data/runtime/market_risk_latest.json").exists()
    assert not (d / "shadow_latest.json").exists() and not (d / "latest.json").exists()
    assert [p.name for p in (d / "receipts").iterdir()] == ["20261029T190000Z-shadow-replay.json"]


def test_f3_history_stays_in_time_order(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    snap_p = tmp_path / "data/runtime/market_risk_latest.json"
    snap_p.parent.mkdir(parents=True)
    later = {"as_of": "2026-11-01T00:30:00+00:00", "score": 1, "tier": "BLUE", "mode": "live"}
    earlier = {"as_of": "2026-10-31T20:00:00+00:00", "score": 1, "tier": "BLUE", "mode": "live"}
    snap_p.write_text(json.dumps({"history": [later, earlier]}))
    assert ev.main(["--shadow", "--no-portfolio"]) == 0
    hist = [h["as_of"][:16] for h in json.loads(snap_p.read_text())["history"]]
    assert hist == ["2026-10-31T20:00", "2026-10-31T23:50", "2026-11-01T00:30"]


def test_dry_run_beats_shadow(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--dry-run", "--no-portfolio"]) == 0
    assert not (tmp_path / "data").exists()


def test_shadow_reports_the_files_it_wrote(tmp_path, monkeypatch, capsys):
    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--json", "--no-portfolio"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "shadow" and doc["written"].endswith("market_risk/shadow_latest.json")
    assert Path(doc["written"]).exists() and Path(doc["snapshot"]).exists()
