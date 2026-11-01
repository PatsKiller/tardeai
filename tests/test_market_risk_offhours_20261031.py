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


# ── reader: session tag and post-close reference ─────────────────────────────────────────────────────────────────
class _Cur:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, [], []

    def execute(self, sql, params=None):
        self.conn.log.append((sql, params))
        if "DISTINCT ON (symbol) symbol, price, fetched_at" in sql:
            lo, hi = params[1], params[2]
            best = {}
            for r in self.conn.quotes:
                if r["symbol"] in params[0] and lo <= r["fetched_at"] <= hi and r["price"] is not None:
                    if r["symbol"] not in best or r["fetched_at"] > best[r["symbol"]]["fetched_at"]:
                        best[r["symbol"]] = r
            cols = ["symbol", "price", "fetched_at"]
            rows = list(best.values())
        elif "FROM market_quotes" in sql:
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


FRIDAY = [  # the live 2026-10-30 QQQ rows (Alpaca prev_close = Thursday's 715.42 all day)
    _q("QQQ", 690.56, 715.42, et(2026, 10, 30, 15, 58, 20)),
    _q("QQQ", 690.54, 715.42, et(2026, 10, 30, 16, 0, 4)),
    _q("QQQ", 691.11, 715.42, et(2026, 10, 30, 16, 3, 47)),
    _q("QQQ", 690.80, 715.42, et(2026, 10, 30, 16, 9, 35)),
]


def test_reader_tags_session_and_rebases_after_hours_on_the_days_close():
    r = rd.PgReader(lambda: _Conn(FRIDAY))
    rows = r.quotes(["QQQ"], start=et(2026, 10, 30, 15), end=et(2026, 10, 30, 18))
    by_t = {x["as_of"][11:19]: x for x in rows}
    assert by_t["19:58:20"]["session"] == "regular" and by_t["19:58:20"]["prev_close"] == 715.42
    assert by_t["20:00:04"]["session"] == "regular"  # the closing snapshot, inside the 16:00:59 cutoff
    ah = by_t["20:09:35"]
    assert ah["session"] == "afterhours" and ah["prev_close"] == 690.54 and ah["prev_close_stored"] == 715.42
    assert ah["reference"] == "regular close 2026-10-30"
    assert 100 * (ah["price"] / ah["prev_close"] - 1) == pytest.approx(0.04, abs=0.01)  # not -3.4%


def test_reader_drops_the_reference_when_the_days_close_is_missing():
    r = rd.PgReader(lambda: _Conn([FRIDAY[-1]]))
    (row,) = r.quotes(["QQQ"], start=et(2026, 10, 30, 16, 5), end=et(2026, 10, 30, 18))
    assert row["session"] == "afterhours" and row["prev_close"] is None
    assert row["reference"] == "no regular close found"


def test_reader_close_lookup_is_bounded_by_the_close_cutoff():
    # the day's close is the last quote at or before 16:00:59 ET (REGULAR_CLOSE_CUTOFF_ET); a 16:03 quote is not it
    conn = _Conn(FRIDAY[:1] + [FRIDAY[2]])
    r = rd.PgReader(lambda: conn)
    rows = r.quotes(["QQQ"], start=et(2026, 10, 30, 15), end=et(2026, 10, 30, 16, 5))
    close_q = [p for q, p in conn.log if "DISTINCT ON (symbol) symbol, price, fetched_at" in q]
    assert close_q and close_q[0][2] == et(2026, 10, 30, 16, 0, 59)
    assert [x for x in rows if x["session"] == "afterhours"][0]["prev_close"] == 690.56


# ── extended_hours category over production-shaped rows ──────────────────────────────────────────────────────────
class _R:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def quotes(self, symbols, *, start, end):
        self.calls.append((start, end))
        return [r for r in self.rows if r["symbol"] in symbols and start <= datetime.fromisoformat(r["as_of"]) <= end]

    def session_opens(self, symbols, *, sessions, end):
        return []

    def daily_bars(self, symbols, *, sessions, end):
        return []


def _row(sym, price, prev, at, session, source="alpaca"):
    return {
        "symbol": sym,
        "price": price,
        "prev_close": prev,
        "as_of": at.isoformat(),
        "session": session,
        "source": source,
        "reference": "regular close",
    }


def _ctx(now, rows):
    return c.EvalContext(now=now, reader=_R(rows), policy=P, session=sessions.session_label(now))


def test_after_hours_quote_is_read_with_its_age():
    rows = [_row("QQQ", 675.0, 690.0, et(2026, 10, 30, 17, 0), "afterhours")]  # -2.2%
    o = xh.evaluate(_ctx(et(2026, 10, 30, 18, 0), rows))
    assert o.state == "STRESS" and "afterhours" in o.evidence[0].label
    assert "1.0h old" in o.evidence[0].detail and "17:00 ET" in o.evidence[0].detail


def test_overnight_quote_counts():
    rows = [_row("SPY", 740.0, 750.0, et(2026, 11, 2, 1, 0), "overnight", source="schwab")]
    o = xh.evaluate(_ctx(et(2026, 11, 2, 1, 30), rows))
    assert o.state == "WARN"


def test_regular_close_feed_is_not_an_after_hours_print():
    rows = [_row("SPY", 750.0, 750.0, et(2026, 10, 30, 17, 54), "afterhours", source="yfinance")]
    o = xh.evaluate(_ctx(et(2026, 10, 30, 18, 0), rows))
    assert o.state == "UNKNOWN"


def test_weekend_names_the_last_after_hours_quote_and_its_age():
    rows = [_row("QQQ", 690.80, 690.54, et(2026, 10, 30, 16, 9, 35), "afterhours")]
    ctx = _ctx(et(2026, 10, 31, 19, 50), rows)
    o = xh.evaluate(ctx)
    assert o.state == "UNKNOWN"
    assert "QQQ +0.0%" in o.reason_unknown and "Fri 10-30 16:09 ET" in o.reason_unknown
    assert "7.8 market hours old" in o.reason_unknown
    assert ctx.reader.calls[0][0] <= et(2026, 10, 30, 16, 0)  # the query reached back to Friday's close


# ── --shadow: snapshot written, alert path never touched ─────────────────────────────────────────────────────────
class _FixedReader(_R):
    pass


def test_shadow_writes_snapshot_and_never_imports_telegram(tmp_path, monkeypatch):
    import importlib

    ev = importlib.import_module("scripts.market_risk_evaluate")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(tmp_path / "ep.json"))
    monkeypatch.setenv("MARKET_RISK_SENT_LEDGER", str(tmp_path / "sk.json"))
    trip = types.ModuleType("telegram_alert")

    def _boom(*a, **k):
        raise AssertionError("shadow reached send_telegram")

    trip.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", trip)
    monkeypatch.setitem(sys.modules, "scripts.telegram_alert", trip)
    from scripts.lib.market_risk import alerts

    monkeypatch.setattr(alerts, "deliver", _boom)
    monkeypatch.setattr(alerts, "outbox_put", _boom)
    monkeypatch.setattr(ev, "production_reader", lambda: _R([]))
    rc = ev.main(["--shadow", "--no-portfolio", "--as-of", "2026-10-31T23:50:00+00:00"])
    assert rc == 0
    snap = json.loads((tmp_path / "data/runtime/market_risk_latest.json").read_text())
    assert snap["tier"] in c.TIERS
    d = tmp_path / "data/runtime/market_risk"
    assert (d / "shadow_latest.json").exists() and not (d / "latest.json").exists()
    assert [p.name for p in (d / "receipts").iterdir()] == ["20261031T235000Z-shadow.json"]
    assert json.loads((d / "shadow_latest.json").read_text())["mode"] == "shadow"
    assert not (tmp_path / "ep.json").exists() and not (tmp_path / "sk.json").exists()


def test_dry_run_beats_shadow(tmp_path, monkeypatch):
    import importlib

    ev = importlib.import_module("scripts.market_risk_evaluate")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(tmp_path / "ep.json"))
    monkeypatch.setenv("MARKET_RISK_SENT_LEDGER", str(tmp_path / "sk.json"))
    monkeypatch.setattr(ev, "production_reader", lambda: _R([]))
    assert ev.main(["--shadow", "--dry-run", "--no-portfolio", "--as-of", "2026-10-31T23:50:00+00:00"]) == 0
    assert not (tmp_path / "data").exists()


def test_shadow_reports_the_files_it_wrote(tmp_path, monkeypatch, capsys):
    import importlib

    ev = importlib.import_module("scripts.market_risk_evaluate")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(ev, "production_reader", lambda: _R([]))
    assert ev.main(["--shadow", "--json", "--no-portfolio", "--as-of", "2026-10-31T23:50:00+00:00"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "shadow" and doc["written"].endswith("market_risk/shadow_latest.json")
    assert Path(doc["written"]).exists() and Path(doc["snapshot"]).exists()
