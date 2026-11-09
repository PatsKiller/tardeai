"""LQ-20261107-1511 — a regime event may not fire on a stale close, and the lane must write its receipt.

The 07:00 ET run on 2026-11-09 (n8n `d:event-detector:live:20261109T0700`, live 50d4c6c62) logged:

    [2026-11-09 07:00:28] MARKET_REGIME_CHANGE: VIX=28.18
    [2026-11-09 07:00:28]   FIRED MARKET_REGIME_CHANGE VIX_25 → ['Risk', 'Maria'] [urgent]

and queued `agent_event_queue` id 7524. The source row was `fred_economic_series` VIXCLS
`observation_date = 2026-11-05` — four days old on a Monday whose last completed session was
2026-11-06 — because the FRED ingest had stopped on 2026-11-07; live VIX was ~24.1. The lane never
looked at the observation date; it read the newest row and called it today.

Three controls pinned here, all synthetic (no DB, no network, no send):

1. a close older than the last completed trading session is REFUSED, and the refusal names both dates;
2. the NYSE calendar decides, so the Monday after a holiday weekend does not make a fresh close look
   stale (Thanksgiving 2026-11-26 is not a session);
3. the lane writes `data/runtime/event-detector_last.json` — the `output_signal` the registry and the
   n8n allowlist already declare — with `produced_count` and a `detector_status` that NAMES a check
   that crashed. Before this, the file was 30 hours old while the lane ran five times a day, and the
   contract could only answer `declared_not_enforced`.

The naive/aware crash inside PORTFOLIO_FRESH_NEEDED is LQ-20261107-691, fixed by `6b753ef14` on
`wt/livefix-cc-deepseek-4-lq691` and not yet folded; control 3 is what makes such a crash visible.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "event_detector.py"
ET = ZoneInfo("America/New_York")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("event_detector_1511", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ev(monkeypatch):
    mod = _load()
    # the shipped policy is read from the real repo config: assert against it, do not fake it away
    return mod


def _noon(y, m, d, hh=9, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ── the freshness rule ───────────────────────────────────────────────────


def test_the_live_false_positive_is_refused(ev):
    """VIXCLS 2026-11-05 read at 09:00 ET on Monday 2026-11-09: refusal, and both dates are named."""
    fresh, oldest = ev.regime_observation_fresh(date(2026, 11, 5), _noon(2026, 11, 9))
    assert fresh is False
    assert oldest == date(2026, 11, 6), "the last completed session is Friday, not today"


def test_the_last_completed_session_close_is_fresh(ev):
    fresh, oldest = ev.regime_observation_fresh(date(2026, 11, 6), _noon(2026, 11, 9))
    assert fresh is True and oldest == date(2026, 11, 6)


def test_after_the_close_the_completed_session_moves_to_today(ev):
    """16:30 ET is past the close: today's own close is the newest that can exist, so Friday's is stale."""
    fresh, oldest = ev.regime_observation_fresh(date(2026, 11, 6), _noon(2026, 11, 9, 16, 30))
    assert fresh is False and oldest == date(2026, 11, 9)


def test_a_holiday_weekend_does_not_make_a_fresh_close_look_stale(ev):
    """Thanksgiving 2026-11-26 is not a session; on Friday 11-27 the last completed session is Wednesday."""
    fresh, oldest = ev.regime_observation_fresh(date(2026, 11, 25), _noon(2026, 11, 27))
    assert fresh is True and oldest == date(2026, 11, 25)


def test_the_configured_lag_widens_the_window_by_sessions_not_days(ev):
    fresh, oldest = ev.regime_observation_fresh(date(2026, 11, 5), _noon(2026, 11, 9), lag_sessions=1)
    assert fresh is True and oldest == date(2026, 11, 5)
    fresh, oldest = ev.regime_observation_fresh(date(2026, 11, 5), _noon(2026, 11, 27), lag_sessions=1)
    assert fresh is False and oldest == date(2026, 11, 24), "one session back from Wednesday is Tuesday"


def test_a_missing_observation_is_never_fresh(ev):
    fresh, _ = ev.regime_observation_fresh(None, _noon(2026, 11, 9))
    assert fresh is False


def test_the_shipped_policy_is_the_strict_one(ev):
    assert ev.regime_policy()["max_observation_lag_sessions"] == 0
    assert json.loads((ROOT / "config" / "event_detector_policy.json").read_text())["schema"] == "EventDetectorPolicy@v1"


def test_an_unusable_policy_falls_back_to_the_strict_default(ev, tmp_path, monkeypatch):
    bad = tmp_path / "event_detector_policy.json"
    bad.write_text(json.dumps({"regime": {"max_observation_lag_sessions": "3"}}))
    monkeypatch.setattr(ev, "POLICY_PATH", bad)
    assert ev.regime_policy()["max_observation_lag_sessions"] == 0

    bad.write_text(json.dumps({"regime": {"max_observation_lag_sessions": -2}}))
    assert ev.regime_policy()["max_observation_lag_sessions"] == 0

    bad.write_text("{not json")
    assert ev.regime_policy()["max_observation_lag_sessions"] == 0


# ── the check itself ─────────────────────────────────────────────────────


class _Cursor:
    """Answers the two SELECTs the regime path makes: the VIXCLS row, and an empty cooldown queue."""

    def __init__(self, row, executed):
        self._row = row
        self._executed = executed

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self._executed.append((sql.split()[0].upper(), params, sql))

    def fetchone(self):
        sql = self._executed[-1][2]
        return self._row if "FROM fred_economic_series" in sql else None

    def fetchall(self):
        return []


class _Conn:
    """Enough of a psycopg2 connection for the regime check: the two SELECTs, then an optional INSERT."""

    def __init__(self, row):
        self.row = row
        self.executed = []
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return _Cursor(self.row, self.executed)

    def commit(self):
        self.commits += 1

    @property
    def inserted(self):
        return [sql for op, _, sql in self.executed if op == "INSERT"]


def _freeze(now):
    """A `datetime` whose .now() is pinned; every other classmethod stays the real one."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    return Frozen


def test_a_stale_close_inserts_nothing(ev, monkeypatch):
    monkeypatch.setattr(ev, "datetime", _freeze(_noon(2026, 11, 9)))
    conn = _Conn({"observation_date": date(2026, 11, 5), "value": 28.18})

    assert ev.check_market_regime_change(conn) == 0
    assert conn.inserted == [], "a four-day-old close must never become an urgent event"
    assert conn.commits == 0


def test_a_current_close_still_fires(ev, monkeypatch):
    monkeypatch.setattr(ev, "datetime", _freeze(_noon(2026, 11, 9)))
    conn = _Conn({"observation_date": date(2026, 11, 6), "value": 28.18})

    assert ev.check_market_regime_change(conn) == 1
    assert len(conn.inserted) == 1 and conn.commits == 1


# ── the receipt ──────────────────────────────────────────────────────────


def test_a_real_run_writes_the_declared_receipt_and_names_a_crashed_check(ev, monkeypatch, tmp_path):
    """The `output_signal` the registry declares must be written by the lane, and a crash must be visible."""
    calls = []
    import lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", lambda lane_id, **kw: calls.append((lane_id, kw)))
    monkeypatch.setattr(ev, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ev, "_get_conn", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(sys, "argv", ["event_detector.py"])

    for name in ("check_sec_insider_buy", "check_rsi_extreme", "check_fred_rate_change", "check_dividend_cut",
                 "check_earnings_beat", "check_stop_triggered", "check_irmaa_threshold",
                 "check_income_floor_risk", "check_market_regime_change"):
        monkeypatch.setattr(ev, name, lambda conn, dry_run=False: 0)

    def boom(conn, dry_run=False):
        raise TypeError("can't compare offset-naive and offset-aware datetimes")

    monkeypatch.setattr(ev, "check_portfolio_fresh_needed", boom)

    ev.main()

    assert len(calls) == 1, "a real run must write exactly one receipt"
    lane_id, kw = calls[0]
    assert lane_id == "event-detector"
    assert kw["produced_count"] == 0
    assert kw["ok"] is False, "a crashed check means the run did not fully succeed"
    assert kw["summary"]["detector_status"]["PORTFOLIO_FRESH_NEEDED"] == "error:TypeError"
    assert kw["summary"]["detector_status"]["MARKET_REGIME_CHANGE"] == "ok"
    assert "offset-naive" not in json.dumps(kw, default=str), "the receipt carries a class name, never the message"


def test_a_dry_run_writes_no_receipt(ev, monkeypatch, tmp_path):
    calls = []
    import lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", lambda lane_id, **kw: calls.append((lane_id, kw)))
    monkeypatch.setattr(ev, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ev, "_get_conn", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(sys, "argv", ["event_detector.py", "--dry-run"])
    for name in ("check_sec_insider_buy", "check_rsi_extreme", "check_fred_rate_change", "check_dividend_cut",
                 "check_earnings_beat", "check_stop_triggered", "check_irmaa_threshold",
                 "check_income_floor_risk", "check_market_regime_change", "check_portfolio_fresh_needed"):
        monkeypatch.setattr(ev, name, lambda conn, dry_run=False: 1)

    ev.main()

    assert calls == [], "a dry run never reaches the receipt write"
