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
    # round 3 (R2-5): the stale proxy is named AND the category cannot read CALM
    assert o.state == "UNKNOWN"
    assert "not measured: QQQ -3.0%" in o.reason_unknown and "3.0 market hours old" in o.reason_unknown


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


def test_shadow_writes_only_shadow_latest_and_never_imports_telegram(tmp_path, monkeypatch):
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
    # review of #2425: a shadow run never writes the snapshot Home/API/CIO read
    assert not (tmp_path / "data/runtime/market_risk_latest.json").exists()
    d = tmp_path / "data/runtime/market_risk"
    assert (d / "shadow_latest.json").exists() and not (d / "latest.json").exists()
    assert [p.name for p in (d / "receipts").iterdir()] == ["20261031T235000Z-shadow.json"]
    assert json.loads((d / "shadow_latest.json").read_text())["mode"] == "shadow"
    assert not (tmp_path / "ep.json").exists() and not (tmp_path / "sk.json").exists()


def test_shadow_never_overwrites_a_live_snapshot(tmp_path, monkeypatch):
    from scripts.lib import market_risk_projection as proj

    ev = _shadow_env(tmp_path, monkeypatch)
    live_p = tmp_path / proj.SNAPSHOT_REL
    live_p.parent.mkdir(parents=True)
    live = proj.snapshot_from_assessment(
        {"schema": c.SCHEMA_ASSESSMENT, "tier": "ORANGE", "score": 66, "as_of": FIXED.isoformat(), "mode": "apply"}
    )
    live_p.write_text(json.dumps(live))
    before = live_p.read_bytes()
    assert ev.main(["--shadow", "--no-portfolio"]) == 0
    assert live_p.read_bytes() == before


def _loader(root):
    def load(rel):
        try:
            return json.loads((root / rel).read_text())
        except FileNotFoundError:
            return None

    return load


def test_api_serves_live_when_present_else_shadow_labelled(tmp_path, monkeypatch):
    from scripts.lib import market_risk_projection as proj

    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--no-portfolio"]) == 0
    snap = proj.load_snapshot(_loader(tmp_path))  # no live snapshot: the shadow one, labelled
    assert snap["mode"] == "shadow" and snap["schema"] == proj.SNAPSHOT_SCHEMA
    p = proj.build(snap, None, now=FIXED, episode={"id": "EP-LIVE", "tier": "RED", "opened_at": FIXED.isoformat()})
    assert p["mode"] == "shadow" and p["episode"] is None  # never a live episode on a shadow tier
    live = proj.snapshot_from_assessment(
        {"schema": c.SCHEMA_ASSESSMENT, "tier": "ORANGE", "score": 66, "as_of": FIXED.isoformat(), "mode": "apply"}
    )
    (tmp_path / proj.SNAPSHOT_REL).write_text(json.dumps(live))
    snap2 = proj.load_snapshot(_loader(tmp_path))
    assert snap2["mode"] == "live" and snap2["tier"] == "ORANGE"
    ep = {"id": "EP-LIVE", "tier": "ORANGE", "opened_at": FIXED.isoformat()}
    assert proj.build(snap2, None, now=FIXED, episode=ep)["episode"]["id"] == "EP-LIVE"
    assert proj.snapshot_from_assessment({"mode": "apply", "tier": "BLUE"})["mode"] == "live"


def test_api_route_uses_the_loader():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    seg = src[src.index('"/api/v2/market-risk/latest" and method == "GET"') :][:1800]
    assert "load_snapshot" in seg and "_MR_REL" not in seg


def test_f3_shadow_replay_never_writes_the_snapshot_or_prior(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--no-portfolio", "--as-of", "2026-10-29T19:00:00Z"]) == 0
    d = tmp_path / "data/runtime/market_risk"
    assert not (tmp_path / "data/runtime/market_risk_latest.json").exists()
    assert not (d / "shadow_latest.json").exists() and not (d / "latest.json").exists()
    assert [p.name for p in (d / "receipts").iterdir()] == ["20261029T190000Z-shadow-replay.json"]


def test_f3_live_history_stays_in_time_order(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    snap_p = tmp_path / "data/runtime/market_risk_latest.json"
    snap_p.parent.mkdir(parents=True)
    later = {"as_of": "2026-11-01T00:30:00+00:00", "score": 1, "tier": "BLUE", "mode": "live"}
    earlier = {"as_of": "2026-10-31T20:00:00+00:00", "score": 1, "tier": "BLUE", "mode": "live"}
    snap_p.write_text(json.dumps({"history": [later, earlier]}))
    doc = {"schema": c.SCHEMA_ASSESSMENT, "as_of": FIXED.isoformat(), "tier": "BLUE", "score": 30, "mode": "apply"}
    ev.persist(doc, FIXED)
    got = json.loads(snap_p.read_text())
    assert [h["as_of"][:16] for h in got["history"]] == ["2026-10-31T20:00", "2026-10-31T23:50", "2026-11-01T00:30"]
    assert got["mode"] == "live"


def test_dry_run_beats_shadow(tmp_path, monkeypatch):
    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--dry-run", "--no-portfolio"]) == 0
    assert not (tmp_path / "data").exists()


def test_shadow_reports_the_files_it_wrote(tmp_path, monkeypatch, capsys):
    ev = _shadow_env(tmp_path, monkeypatch)
    assert ev.main(["--shadow", "--json", "--no-portfolio"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "shadow" and doc["written"].endswith("market_risk/shadow_latest.json")
    assert Path(doc["written"]).exists() and doc["snapshot"] is None


# ── Round 3 (review of #2415 round 2) ────────────────────────────────────────────────────────────────────────────
FIX = ROOT / "tests" / "fixtures" / "market_risk_scenarios"
DAILY_BAR_CATS = ("technical", "volatility", "options_flow", "cross_asset")


def _replay(as_of: str) -> dict:
    import contextlib
    import importlib
    import io

    ev = importlib.import_module("scripts.market_risk_evaluate")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ev.main(
            ["--fixture", str(FIX), "--overlay", str(FIX / "oct2026"), "--as-of", as_of, "--json", "--no-portfolio"]
        )
    d = json.loads(buf.getvalue())
    return {o["category"]: o for o in d["observations"]} | {"_doc": d}


def test_r2_1_daily_bar_limits_are_one_missed_session_in_market_hours():
    for cat in ("technical", "volatility", "options_flow_category", "cross_asset"):
        assert float(P[cat]["stale_after_hours"]) <= 32, cat
    assert float(P["macro_credit"]["stale_after_hours"]) >= 96  # FRED publication lag


@pytest.mark.parametrize(
    "a,b,limit,usable",
    [
        (et(2026, 10, 30, 16), et(2026, 11, 2, 8), 32, True),  # Friday close -> Monday premarket: 22h
        (et(2026, 10, 30, 16), et(2026, 11, 2, 17, 30), 32, True),  # Monday's close not in yet: 31.5h
        (et(2026, 10, 30, 16), et(2026, 11, 4, 10), 32, False),  # review failing input: Fri bars, Wed 10:00
        (et(2026, 10, 28, 16), et(2026, 11, 2, 10), 32, False),  # review failing input: Wed bars, Mon 10:00 (72h)
        (et(2026, 10, 29, 16), et(2026, 11, 3, 9), 32, False),  # Fri and Mon missing
        (et(2027, 1, 15, 16), et(2027, 1, 19, 9, 29), 32, True),  # MLK: nothing missing
        (et(2027, 1, 14, 16), et(2027, 1, 19, 9, 29), 32, False),  # Friday missing before MLK
        (et(2026, 10, 27, 17), et(2026, 10, 30, 18, 30), 120, True),  # FRED Tuesday obs on Friday evening
    ],
)
def test_r2_1_staleness_cases(a, b, limit, usable):
    assert (scoring.staleness(a, b, P["decay"], limit)[1] is None) is usable


def test_r2_1_fixture_replay_fri_bars_wednesday_is_unknown_not_calm():
    got = _replay("2026-11-04T15:00:00Z")  # Wed 10:00 ET; the fixture's bars end Fri 10-30
    for cat in DAILY_BAR_CATS:
        assert got[cat]["state"] == "UNKNOWN", (cat, got[cat].get("headline"))
    mon = _replay("2026-11-02T13:00:00Z")  # Mon 08:00 ET: Friday's close is still current
    assert mon["technical"]["state"] != "UNKNOWN" and mon["volatility"]["state"] != "UNKNOWN"


class _GapReader:
    """The scenario fixture with sessions removed (a data gap): every per-day read drops the gap dates."""

    def __init__(self, base, gap):
        self.base, self.gap = base, {d.isoformat() for d in gap}

    def __getattr__(self, name):
        return getattr(self.base, name)

    def _keep(self, rows):
        out = []
        for r in rows:
            d = str(r.get("date") or r.get("session_date") or r.get("as_of") or "")
            if d[:10] not in self.gap:
                out.append(r)
        return out

    def sessions(self, *, start, end, symbol="SPY"):
        return [d for d in self.base.sessions(start=start, end=end, symbol=symbol) if d.isoformat() not in self.gap]

    def daily_bars(self, symbols, *, sessions, end):
        return self._keep(self.base.daily_bars(symbols, sessions=sessions + len(self.gap), end=end))

    def session_opens(self, symbols, *, sessions, end):
        return self._keep(self.base.session_opens(symbols, sessions=sessions, end=end))

    def option_snapshots(self, symbols, *, sessions, end):
        return self._keep(self.base.option_snapshots(symbols, sessions=sessions, end=end))

    def quotes(self, symbols, *, start, end):
        return self._keep(self.base.quotes(symbols, start=start, end=end))


def test_r2_1_backtest_with_a_data_gap_reads_unknown_not_calm():
    from datetime import date

    from scripts import market_risk_backtest as bt
    from scripts.lib.market_risk.fixture_reader import FixtureReader

    base = FixtureReader(FIX, overlay=FIX / "oct2026")
    gap = [date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)]  # Wed-Fri missing: three sessions
    reader = _GapReader(base, gap)
    s = {"id": "gap_oct2026", "start": "2026-10-19", "end": "2026-10-27", "expect": {}}
    res = bt.run_scenario(s, reader=reader, analogs=False)
    by = {(t["date"], t["session"]): t["states"] for t in res["timeline"]}
    mon_open = by[("2026-10-26", "regular")]  # Monday 09:31: newest bar is Tuesday 10-20's (65.5 market hours)
    for cat in ("technical", "volatility", "cross_asset"):
        assert mon_open[cat] == "UNKNOWN", (cat, mon_open)
    assert by[("2026-10-20", "close")]["technical"] != "UNKNOWN"  # before the gap: measured
    full = bt.run_scenario(s, reader=base, analogs=False)
    assert {(t["date"], t["session"]): t["states"] for t in full["timeline"]}[("2026-10-26", "regular")][
        "technical"
    ] != "UNKNOWN"  # positive control: without the gap Monday is measured


# R2-4: fail closed
def test_r2_4_missing_reference_date_is_unknown_never_stress():
    r = _row("QQQ", 690.8, 715.42, et(2026, 10, 30, 16, 45), "afterhours", source="schwab")
    r.pop("reference_date")
    o = xh.evaluate(_ctx(et(2026, 10, 30, 16, 50), [r]))
    assert o.state == "UNKNOWN" and "no reference_date" in o.reason_unknown


def test_r2_4_row_without_source_fails_the_source_filter():
    r = _row("QQQ", 670.0, 690.54, et(2026, 10, 30, 16, 45), "afterhours")
    r.pop("source")
    assert xh.evaluate(_ctx(et(2026, 10, 30, 16, 50), [r])).state == "UNKNOWN"


# R2-5: CALM needs every proxy proven fresh
def test_r2_5_one_fresh_calm_proxy_with_one_stale_is_unknown():
    rows = [
        _row("QQQ", 670.0, 690.54, et(2026, 10, 30, 16, 30), "afterhours"),  # -3%, 3h old
        _row("SPY", 756.5, 755.72, et(2026, 10, 30, 19, 25), "afterhours"),  # +0.1%, fresh
    ]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 19, 30), rows))
    assert o.state == "UNKNOWN" and "QQQ not proven fresh" in o.reason_unknown


def test_r2_5_fresh_stress_still_stands_beside_an_unproven_proxy():
    rows = [
        _row("QQQ", 670.0, 690.54, et(2026, 10, 30, 19, 25), "afterhours"),  # -3% fresh
        _row("SPY", 755.72, 755.72, et(2026, 10, 30, 19, 25), "afterhours"),  # unproven
    ]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 19, 30), rows))
    assert o.state == "STRESS" and "not measured: SPY" in o.headline


def test_r2_5_both_proxies_fresh_and_flat_is_calm():
    rows = [
        _row("QQQ", 690.9, 690.54, et(2026, 10, 30, 19, 25), "afterhours"),
        _row("SPY", 756.0, 755.72, et(2026, 10, 30, 19, 25), "afterhours"),
    ]
    assert xh.evaluate(_ctx(et(2026, 10, 30, 19, 30), rows)).state == "CALM"


# Seasonal: New York's calendar, not UTC's
@pytest.mark.parametrize(
    "t,month,tag",
    [
        (et(2026, 9, 30, 21, 0), "September", "quarter_end_window"),
        (et(2026, 12, 31, 20, 30), "December", "year_end_window"),
        (et(2026, 11, 20, 20, 30), "November", "options_expiration"),
        (et(2026, 10, 31, 20, 38), "October", None),
    ],
)
def test_seasonal_uses_the_new_york_date(t, month, tag):
    from scripts.lib.market_risk.categories import seasonal

    o = seasonal.evaluate(c.EvalContext(now=t.astimezone(timezone.utc), reader=None, policy=P, session="closed"))
    assert month in o.headline, o.headline
    if tag:
        assert tag in o.headline, o.headline


# R2-2: the CIO sees the shadow marker
def test_r2_2_cio_summary_carries_the_shadow_marker():
    from scripts.lib import cio_market_context_state as cms
    from scripts.lib import market_risk_projection as proj

    now = datetime(2026, 11, 1, 0, 40, tzinfo=timezone.utc)
    snap = proj.snapshot_from_assessment(
        {"schema": c.SCHEMA_ASSESSMENT, "tier": "YELLOW", "score": 59.7, "as_of": now.isoformat(), "mode": "shadow"}
    )
    state = cms.build_market_context_state(
        regime_snapshot={}, evaluated_at=now, market_risk=proj.build(snap, None, now=now)
    )
    s = state["summary"]["market_risk"] if "summary" in state else state["market_risk"]
    assert s["mode"] == "shadow" and "(SHADOW, not alerting)" in s["line"]
    live = proj.build(dict(snap, mode="live"), None, now=now)
    s2 = cms.build_market_context_state(regime_snapshot={}, evaluated_at=now, market_risk=live)
    s2 = s2["summary"]["market_risk"] if "summary" in s2 else s2["market_risk"]
    assert s2["mode"] == "live" and "SHADOW" not in s2["line"]


# ── Round 4 (review of #2425): hold-not-escalate, options-flow slots ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "a,b,want",
    [
        (et(2026, 10, 30, 16), et(2026, 10, 30, 18, 30), False),  # same evening
        (et(2026, 10, 29, 16), et(2026, 10, 30, 9, 31), False),  # weeknight: nothing closed in between
        (et(2026, 10, 30, 16), et(2026, 10, 31, 19, 50), True),  # Saturday
        (et(2026, 10, 30, 16), et(2026, 11, 2, 9, 31), True),  # Monday open
        (et(2026, 11, 25, 16), et(2026, 11, 27, 10), True),  # Thanksgiving
        (et(2026, 11, 2, 16), et(2026, 11, 3, 16), False),
    ],
)
def test_closure_between(a, b, want):
    assert sessions.closure_between(a, b) is want


def _stress(cat, at, score=85.0, stale=96.0):
    return c.CategoryObservation(
        category=cat, state="STRESS", score=score, observed_at=at.isoformat(), headline="x", stale_after_hours=stale
    )


def _carry_case(prior_tier, now):
    fri = et(2026, 10, 30, 16)
    obs = [_stress("technical", fri), _stress("breadth", fri), _stress("volatility", fri), _stress("options_flow", fri)]
    obs += [c.unknown(k, now, "x") for k in c.CATEGORIES if k not in {o.category for o in obs}]
    prior = {"tier": prior_tier, "hysteresis": {}} if prior_tier else None
    return obs, prior


def test_hold_not_escalate_carried_stress_cannot_raise_the_tier():
    now = et(2026, 11, 2, 9, 31)
    obs, prior = _carry_case("YELLOW", now)
    a = scoring.compose(obs, P, prior=prior, now=now)
    assert a.hysteresis["carried"]["capped"] and a.hysteresis["raw_tier"] == "YELLOW" and a.tier == "YELLOW"
    off = scoring.compose(obs, dict(P, decay=dict(P["decay"], carried_escalation="off")), prior=prior, now=now)
    assert scoring.SEVERITY[off.hysteresis["raw_tier"]] > scoring.SEVERITY["YELLOW"]  # the escalation it prevents


def test_hold_not_escalate_carried_data_still_holds_the_tier():
    now = et(2026, 11, 2, 9, 31)
    obs, prior = _carry_case("RED", now)
    a = scoring.compose(obs, P, prior=prior, now=now)
    assert not a.hysteresis["carried"]["capped"]
    assert a.tier == "RED" and a.score > 0  # held, with its weight in the displayed score


def test_hold_not_escalate_fresh_agreement_may_escalate():
    now = et(2026, 11, 2, 16, 0)
    obs, prior = _carry_case("YELLOW", now)
    agree = ("technical", "breadth", "options_flow")
    fresh = [o if o.category not in agree else _stress(o.category, now) for o in obs]
    a = scoring.compose(fresh, P, prior=prior, now=now)
    carried = set(a.hysteresis["carried"]["categories"])
    assert carried.isdisjoint(agree) and carried == {"volatility"}
    assert scoring.SEVERITY[a.hysteresis["raw_tier"]] > scoring.SEVERITY["YELLOW"]


def test_hold_not_escalate_weeknight_is_not_a_closure():
    now = et(2026, 10, 30, 9, 31)
    thu = et(2026, 10, 29, 16)
    obs = [_stress(k, thu) for k in ("technical", "breadth", "volatility", "options_flow")]
    obs += [c.unknown(k, now, "x") for k in c.CATEGORIES if k not in {o.category for o in obs}]
    a = scoring.compose(obs, P, prior={"tier": "YELLOW", "hysteresis": {}}, now=now)
    assert a.hysteresis["carried"]["categories"] == [] and not a.hysteresis["carried"]["capped"]


def test_hold_not_escalate_bootstrap_adopts_the_reconstruction():
    now = et(2026, 10, 31, 19, 50)
    obs, _ = _carry_case(None, now)
    a = scoring.compose(obs, P, prior=None, now=now)
    assert a.hysteresis["bootstrap"] and not a.hysteresis["carried"]["capped"]


def test_hold_not_escalate_is_the_policy_with_the_operator_approval():
    assert P["decay"]["carried_escalation"] == "hold_only"
    txt = (ROOT / "config" / "market_risk_policy.yaml").read_text(encoding="utf-8")
    assert "approve hold-not-escalate" in txt


@pytest.mark.parametrize(
    "obs_at,now,current",
    [
        (et(2026, 10, 30, 17, 35), et(2026, 11, 2, 10, 30), True),  # Fri 17:35 -> late Monday 10:00 run
        (et(2026, 10, 30, 10, 0), et(2026, 11, 2, 10, 30), True),  # Fri 17:35 failed; Mon 10:00 late: one miss
        (et(2026, 10, 30, 10, 0), et(2026, 11, 2, 10, 50), False),  # two slots missed: fail closed
        (et(2026, 10, 30, 17, 35), et(2026, 11, 2, 18, 30), False),  # Monday's both slots missed
        (et(2026, 11, 25, 17, 35), et(2026, 11, 27, 10, 30), True),  # after Thanksgiving
        (et(2027, 1, 15, 17, 35), et(2027, 1, 19, 10, 30), True),  # after MLK
    ],
)
def test_options_flow_staleness_follows_the_snapshot_slots(obs_at, now, current):
    from scripts.lib.market_risk.categories import options_flow as of

    ctx = c.EvalContext(now=now, reader=None, policy=P, session="regular")
    allowance = of._allowance(obs_at, ctx, P["options_flow_category"])
    age, why = scoring.staleness(obs_at, now, P["decay"], allowance)
    assert (why is None) is current, (allowance, age, why)


def test_options_flow_without_slots_falls_back_to_fixed_hours():
    from scripts.lib.market_risk.categories import options_flow as of

    cfg = {k: v for k, v in P["options_flow_category"].items() if k != "expected_slots_et"}
    ctx = c.EvalContext(now=et(2026, 11, 2, 10), reader=None, policy=P, session="regular")
    assert of._allowance(et(2026, 10, 30, 17, 35), ctx, cfg) == float(cfg["stale_after_hours"])


# ── Round 5 (review of PR 2425 round 4) ──────────────────────────────────────────────────────────────────────────
def _ob5(cat, st, sc, at, stale=32.0):
    return c.CategoryObservation(
        category=cat, state=st, score=sc, observed_at=at.isoformat(), headline=f"{cat} {st}", stale_after_hours=stale
    )


def _prior5(tier, now):
    p = scoring.compose([_ob5("technical", "WARN", 45, now)], P, prior=None, now=now).to_dict()
    p["tier"] = p["market_tier"] = tier
    return p


@pytest.mark.parametrize(
    "at,want",
    [
        (et(2027, 1, 18, 10, 0), et(2027, 1, 15, 16, 0)),  # MLK holiday row -> Friday's close
        (et(2026, 9, 7, 10, 43), et(2026, 9, 4, 16, 0)),  # Labor Day sector row -> Friday's close
        (et(2026, 10, 31, 12, 0), et(2026, 10, 30, 16, 0)),  # Saturday -> Friday
        (et(2026, 11, 27, 14, 0), et(2026, 11, 27, 14, 0)),  # an early-close trading day is its own
        (et(2026, 11, 1, 20, 30), et(2026, 11, 1, 20, 30)),  # Sunday overnight session is real trading
        (et(2026, 11, 3, 10, 0), et(2026, 11, 3, 10, 0)),
    ],
)
def test_r5_attributed_instant(at, want):
    assert sessions.attributed_instant(at) == want


def test_r5_holiday_stamped_rows_are_carried_mlk():
    # review failing input: Tue 2027-01-19 08:00 after MLK, prior YELLOW; options_flow + breadth re-captured on the
    # holiday read as fresh and escalated to ORANGE with a P1 "up_from_yellow"
    from scripts.lib.market_risk import alerts

    f2, hol, tue = et(2027, 1, 15, 16), et(2027, 1, 18, 10, 0), et(2027, 1, 19, 8)
    obs = [
        _ob5("technical", "STRESS", 85, f2),
        _ob5("volatility", "STRESS", 80, f2),
        _ob5("cross_asset", "WARN", 45, f2),
        _ob5("options_flow", "STRESS", 85, hol),
        _ob5("breadth", "STRESS", 80, et(2027, 1, 18, 10, 43), 30),
        _ob5("event", "CALM", 5, tue),
        _ob5("seasonal", "CALM", 10, tue, 24),
        _ob5("extended_hours", "CALM", 0, et(2027, 1, 19, 7, 55), 2),
    ]
    prior = _prior5("YELLOW", tue)
    a = scoring.compose(obs, P, prior=prior, now=tue)
    assert {"options_flow", "breadth"} <= set(a.hysteresis["carried"]["categories"])
    assert a.hysteresis["raw_tier"] == "YELLOW" and a.tier == "YELLOW"
    assert alerts.intent_for(a.to_dict(), prior, P) is None


def test_r5_holiday_stamped_rows_are_carried_labor_day():
    tue = et(2026, 9, 8, 8, 0)
    obs = [
        _ob5("options_flow", "STRESS", 85, et(2026, 9, 7, 10, 0)),
        _ob5("breadth", "STRESS", 80, et(2026, 9, 7, 10, 43), 30),
    ]
    a = scoring.compose(obs, P, prior=_prior5("BLUE", tue), now=tue)
    assert set(a.hysteresis["carried"]["categories"]) == {"options_flow", "breadth"}
    assert scoring.SEVERITY[a.tier] <= scoring.SEVERITY["BLUE"]


def test_r5_holiday_snapshot_does_not_extend_slot_currency():
    hol = et(2027, 1, 18, 10, 0)
    assert sessions.slot_deadline(hol, ["10:00", "17:35"], 45) == sessions.slot_deadline(
        et(2027, 1, 15, 16, 0), ["10:00", "17:35"], 45
    )
    assert sessions.slot_deadline(hol, ["10:00", "17:35"], 45) == et(2027, 1, 19, 10, 45)


# Fix 3: an unreadable live snapshot is not replaced by shadow, and keeps the live episode
def test_r5_torn_live_snapshot_reads_not_evaluated_and_keeps_the_episode():
    from scripts.lib import market_risk_projection as proj

    shadow = {
        "schema": proj.ASSESSMENT_SCHEMA,
        "as_of": "2026-10-24T20:00:00+00:00",
        "tier": "GREEN",
        "score": 5,
        "mode": "shadow",
    }
    ep = {"id": "EP-1", "tier": "RED", "status": "OPEN", "opened_at": "2026-10-31T19:00:00+00:00"}
    for live in (None, [], "x"):
        files = {proj.SNAPSHOT_REL: live, proj.SHADOW_REL: shadow}
        snap = proj.load_snapshot(lambda rel: files.get(rel), lambda rel: rel in files)
        p = proj.build(snap, None, episode=ep, now=FIXED)
        assert p["state"] == "not_evaluated" and p["tier"] == "NOT_EVALUATED" and p.get("mode") != "shadow"
        assert "unreadable" in p["reason"] and p["episode"]["id"] == "EP-1"
    absent = {proj.SHADOW_REL: shadow}
    snap = proj.load_snapshot(lambda rel: absent.get(rel), lambda rel: rel in absent)
    assert snap["mode"] == "shadow" and proj.build(snap, None, episode=ep, now=FIXED)["episode"] is None


def test_r5_loaders_pass_an_existence_check():
    api = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert (
        api.count("_mr_load(lambda _rel: _load_json(PROJECT_ROOT / _rel), lambda _rel: (PROJECT_ROOT / _rel).exists())")
        == 2
    )
    ctx = (ROOT / "scripts" / "lib" / "cio_market_context_state.py").read_text(encoding="utf-8")
    assert "load_snapshot(_load, lambda rel: (root / rel).exists())" in ctx


# Bootstrap: policy switch, never P1, torn prior never a bootstrap
def _carried_red(now):
    fri = et(2026, 10, 30, 16)
    obs = [
        _ob5("technical", "STRESS", 85, fri),
        _ob5("breadth", "STRESS", 80, fri, 30),
        _ob5("volatility", "STRESS", 80, fri),
        _ob5("options_flow", "STRESS", 85, et(2026, 10, 30, 17, 35)),
        _ob5("cross_asset", "WARN", 45, fri),
        _ob5("extended_hours", "STRESS", 90, fri, 96),
        _ob5("event", "CALM", 5, now),
        _ob5("seasonal", "CALM", 10, now, 24),
    ]
    return obs + [c.unknown(k, now, "x") for k in c.CATEGORIES if k not in {o.category for o in obs}]


def test_r5_bootstrap_mode_default_is_adopt_carried():
    assert P["decay"]["bootstrap_mode"] == "adopt_carried"
    now = et(2026, 11, 2, 8)
    a = scoring.compose(_carried_red(now), P, prior=None, now=now)
    assert a.hysteresis["bootstrap"] and not a.hysteresis["carried"]["capped"]


def test_r5_bootstrap_fresh_only_no_page_starts_at_the_fresh_tier():
    now = et(2026, 11, 2, 8)
    pol = dict(P, decay=dict(P["decay"], bootstrap_mode="fresh_only_no_page"))
    full = scoring.compose(_carried_red(now), P, prior=None, now=now)
    a = scoring.compose(_carried_red(now), pol, prior=None, now=now)
    car = a.hysteresis["carried"]
    assert car["capped"] and car["carried_tier"] == full.tier and scoring.SEVERITY[a.tier] < scoring.SEVERITY[full.tier]
    assert "first reading after a closure" in car["note"] and a.score == full.score  # carried picture still shown


@pytest.mark.parametrize("mode", ["adopt_carried", "fresh_only_no_page"])
def test_r5_bootstrap_never_pages_p1(tmp_path, monkeypatch, mode):
    import importlib

    from scripts.lib.market_risk import registry

    ev = importlib.import_module("scripts.market_risk_evaluate")
    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda m, **k: sent.append(k) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    now = et(2026, 11, 2, 8)
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _carried_red(now))
    pol = dict(P, decay=dict(P["decay"], bootstrap_mode=mode))
    out = ev.run_cycle(
        now, object(), pol, None, apply=True, episodes_path=tmp_path / "ep.json", ledger_path=tmp_path / "sk.json"
    )
    assert out["episode_event"] == "bootstrap_no_episode" and out["episode_id"] is None
    assert all(k.get("priority") != "P1" for k in sent) and all(s["intent"]["priority"] != "P1" for s in out["sends"])


def _state(tmp_path, monkeypatch):
    import importlib

    ev = importlib.import_module("scripts.market_risk_evaluate")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    d = tmp_path / "data/runtime/market_risk"
    (d / "receipts").mkdir(parents=True)
    return ev, d


def test_r5_missing_prior_is_bootstrap(tmp_path, monkeypatch):
    ev, d = _state(tmp_path, monkeypatch)
    assert ev._resolve_prior(d / "latest.json", shadow=False) is None


def test_r5_torn_prior_falls_back_to_the_live_snapshot(tmp_path, monkeypatch):
    ev, d = _state(tmp_path, monkeypatch)
    (d / "latest.json").write_text('{"tier": "RE')
    (tmp_path / "data/runtime/market_risk_latest.json").write_text(json.dumps({"tier": "ORANGE", "mode": "live"}))
    p = ev._resolve_prior(d / "latest.json", shadow=False)
    assert p["tier"] == "ORANGE" and p["prior_source"] == "market_risk_latest.json"


def test_r5_torn_prior_falls_back_to_the_newest_receipt(tmp_path, monkeypatch):
    ev, d = _state(tmp_path, monkeypatch)
    (d / "latest.json").write_text("[]")
    (d / "receipts" / "20261030T200000Z.json").write_text(json.dumps({"tier": "BLUE"}))
    (d / "receipts" / "20261030T210000Z.json").write_text(json.dumps({"tier": "YELLOW"}))
    (d / "receipts" / "20261030T220000Z-shadow.json").write_text(json.dumps({"tier": "RED"}))
    p = ev._resolve_prior(d / "latest.json", shadow=False)
    assert p["tier"] == "YELLOW" and p["prior_source"] == "receipts/20261030T210000Z.json"
    (d / "shadow_latest.json").write_text("{")
    assert ev._resolve_prior(d / "shadow_latest.json", shadow=True)["tier"] == "RED"


def test_r5_torn_prior_with_nothing_to_fall_back_on_is_not_a_bootstrap(tmp_path, monkeypatch):
    ev, d = _state(tmp_path, monkeypatch)
    (d / "latest.json").write_text("{")
    p = ev._resolve_prior(d / "latest.json", shadow=False)
    assert p is not None and p["tier"] == "NONE"


# Finding 4: the options-flow slots match the lane registry (reconciled from the crontab)
def test_r5_options_slots_match_the_lane_registry():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    lanes = [ln for ln in reg["lanes"] if ln.get("lane_id") == "options-chain-snapshot"]
    assert len(lanes) == 1
    slots = set()
    for expr in lanes[0]["scheduler"]["schedules"]:
        minute, hour, *_ = expr.split()
        slots.add(f"{int(hour):02d}:{int(minute):02d}")
    assert slots == set(P["options_flow_category"]["expected_slots_et"])


def test_r5_observations_computed_now_are_never_carried():
    # event and seasonal are computed at evaluation time; on a Saturday their stamp is a non-trading day but they are
    # not stored market data and must not be attributed back to Friday
    now = et(2026, 10, 31, 22, 55)
    obs = [
        _ob5("event", "CALM", 10, now),
        _ob5("seasonal", "CALM", 22, now, 24),
        _ob5("technical", "STRESS", 80, et(2026, 10, 30, 16)),
    ]
    a = scoring.compose(obs, P, prior=_prior5("YELLOW", now), now=now)
    assert a.hysteresis["carried"]["categories"] == ["technical"]
