"""LQ-20261107-339 (WP6): market-event outcome arithmetic, scorecard and the Friday check -- synthetic data only."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import market_event_outcomes as MO  # noqa: E402
import scripts.market_event_outcomes as LANE  # noqa: E402

SESS = MO.weekday_calendar(date(2026, 10, 1), date(2027, 2, 28), holidays=[date(2026, 11, 26), date(2026, 12, 25)])
ET = MO.ET


def _closes(sym, start, vals):
    i = SESS.index(start)
    return {sym: {SESS[i + k]: v for k, v in enumerate(vals)}}


def test_anchor_is_last_completed_close():
    assert MO.anchor_session(datetime(2026, 11, 6, 10, 0, tzinfo=ET), SESS) == date(2026, 11, 5)
    assert MO.anchor_session(datetime(2026, 11, 6, 16, 0, tzinfo=ET), SESS) == date(2026, 11, 6)
    # Saturday signal anchors to Friday's close
    assert MO.anchor_session(datetime(2026, 11, 7, 12, 0, tzinfo=ET), SESS) == date(2026, 11, 6)


def test_nth_session_skips_weekend_and_holiday():
    assert MO.nth_session_after(date(2026, 11, 6), 1, SESS) == date(2026, 11, 9)
    assert MO.nth_session_after(date(2026, 11, 25), 1, SESS) == date(2026, 11, 27)  # Thanksgiving skipped


def test_returns_none_is_not_zero():
    closes = _closes("AAA", date(2026, 11, 4), [100, 90, 80, 85, 88, 92, 95])
    r = MO.returns_for(100.0, date(2026, 11, 4), closes["AAA"], SESS, today=date(2026, 11, 20))
    assert r["ret_5"] == -8.0
    assert r["ret_20"] is None and r["ret_60"] is None  # horizon not reached: unknown, never 0


def test_returns_none_when_close_missing_or_future():
    closes = {"AAA": {date(2026, 11, 11): 110.0}}
    assert MO.returns_for(100.0, date(2026, 11, 4), closes["AAA"], SESS, today=date(2026, 11, 10))["ret_5"] is None  # future
    assert MO.returns_for(100.0, date(2026, 11, 4), {}, SESS, today=date(2026, 12, 30))["ret_5"] is None  # no close


def test_ready_stamps_skip_malformed():
    plan = {"tranches": [{"tranche": 1, "ready_at": "2026-11-09T10:00:00-05:00", "price": 50},
                         {"tranche": 2, "ready_at": "not a date"}, {"tranche": 9, "ready_at": "2026-11-09T10:00:00-05:00"},
                         {"tranche": 3, "ready_at": "2026-11-09T10:00:00"}, "junk"]}
    st = MO.ready_stamps(plan)
    assert list(st) == ["READY_t1"] and st["READY_t1"]["price"] == 50.0
    assert MO.ready_stamps(None) == {}


EP = {"episode_id": "EP-1", "baseline_date": date(2026, 11, 4)}
NOW = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)


def test_build_signals_baseline_ready_and_skips():
    closes = {**_closes("AAA", date(2026, 11, 4), [100, 90, 80, 85]), "CCC": {}}
    cands = [
        {"symbol": "AAA", "state": "READY", "plan": {"tranches": [{"tranche": 1, "ready_at": "2026-11-09T11:00:00-05:00", "price": 82}]}},
        {"symbol": "BBB", "state": "READY", "plan": None, "baseline_price": 40.0, "last_price": 41.0},   # unstamped READY -> first_seen
        {"symbol": "CCC", "state": "WATCH", "plan": None},                           # no price anywhere -> skipped, counted
    ]
    rows, skipped = MO.build_signals(EP, cands, closes, SESS, NOW)
    by = {(r["symbol"], r["signal"]): r for r in rows}
    assert by[("AAA", "baseline")]["price"] == 100.0 and by[("AAA", "baseline")]["price_source"] == "finviz_close"
    assert by[("AAA", "READY_t1")]["anchor_session"] == date(2026, 11, 6) and by[("AAA", "READY_t1")]["signal_basis"] == "plan_stamp"
    assert by[("BBB", "baseline")]["price_source"] == "candidate_baseline_price"
    assert by[("BBB", "READY_t1")]["signal_basis"] == "first_seen"
    assert by[("BBB", "READY_t1")]["price_source"] == "candidate_last_price"
    assert ("BBB", "READY_t1") not in {k for k in by if k[0] == "CCC"}
    assert skipped.get("baseline_no_price") == 1


def test_scorecard_and_paired_edge():
    scored = [
        {"episode_id": "E", "symbol": "A", "signal": "baseline", "ret_5": -10.0, "ret_20": None, "ret_60": None},
        {"episode_id": "E", "symbol": "B", "signal": "baseline", "ret_5": -4.0, "ret_20": None, "ret_60": None},
        {"episode_id": "E", "symbol": "A", "signal": "READY_t1", "ret_5": 3.0, "ret_20": None, "ret_60": None},
    ]
    card = MO.scorecard(scored, "E")
    b = card["signals"]["baseline"]["ret_5"]
    assert (b["n"], b["n_observed"], b["median"], b["hit_rate"]) == (2, 2, -7.0, 0.0)
    assert card["signals"]["baseline"]["ret_20"]["n_observed"] == 0 and card["signals"]["baseline"]["ret_20"]["median"] is None
    assert card["edge_vs_baseline"]["READY_t1.ret_5"] == {"n_paired": 1, "median_diff": 13.0}  # only A is paired
    assert card["edge_vs_baseline"]["READY_t2.ret_5"] == {"n_paired": 0, "median_diff": None}


def _friday_world(n_fridays, rebound):
    fridays = [d for d in SESS if d.weekday() == 4 and d >= date(2026, 10, 2)][:n_fridays]
    closes = {}
    for sym in ("A", "B", "C", "D"):
        c = {}
        px = 100.0
        for s in SESS[: SESS.index(fridays[-1]) + 5]:
            if s.weekday() == 4:
                px *= 0.97  # the Friday dump
            elif s.weekday() == 0:
                px *= 1.0 + rebound  # Monday rebound
            c[s] = px
        closes[sym] = c
    return closes, fridays


def test_friday_check_insufficient_then_measured():
    closes, fr = _friday_world(2, 0.02)
    out = MO.friday_check(closes, list("ABCD"), SESS, fr[0], fr[-1])
    assert out["verdict"] == "insufficient" and out["fridays_used"] == 2
    closes, fr = _friday_world(4, 0.02)
    out = MO.friday_check(closes, list("ABCD"), SESS, fr[0], fr[-1])
    assert out["verdict"] == "measured"
    assert out["thu_to_fri"]["median"] == -3.0
    assert out["fri_to_mon"]["median"] == 2.0 and out["fri_to_mon"]["share_positive"] == 1.0
    assert out["control_1_session"]["median"] == 0.0  # flat on non-Friday, non-Monday days


def test_upsert_never_moves_the_entry():
    set_clause = LANE.UPSERT.split("DO UPDATE SET")[1]
    for entry in ("signal_at", "price", "anchor_session", "signal_basis", "price_source"):
        assert entry + " =" not in set_clause.replace("EXCLUDED.", "")
    assert "COALESCE(EXCLUDED.ret_5" in set_clause  # a later NULL cannot erase an observed return


class _Cur:
    def __init__(self): self.sql, self._r = [], None
    def execute(self, q, p=None):
        self.sql.append(q)
        if "to_regclass" in q: self._r = [(True,)]
        elif "FROM market_event_episodes" in q: self._r = [("EP-1", date(2026, 11, 4), "OPEN", datetime(2026, 11, 5, tzinfo=ET))]
        elif "FROM market_event_candidates" in q: self._r = [("EP-1", "AAA", 100.0, "WATCH", None)]
        elif "FROM ticker_prices" in q: self._r = [("AAA", date(2026, 11, 4), 100.0), ("AAA", date(2026, 11, 11), 110.0)]
        else: raise AssertionError("unexpected write in dry run: " + q)
    def fetchone(self): return self._r[0]
    def fetchall(self): return self._r


class _Conn:
    def __init__(self): self.c = _Cur()
    def cursor(self): return self.c
    def commit(self): raise AssertionError("dry run must not commit")
    def close(self): pass


def test_cli_dry_run_writes_nothing(monkeypatch, capsys):
    conn = _Conn()
    monkeypatch.setattr(LANE, "_connect", lambda read_only: (_ for _ in ()).throw(AssertionError) if not read_only else conn)
    monkeypatch.setattr(LANE, "_now", lambda: datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(LANE, "sessions_for", lambda today: SESS)
    assert LANE.main([]) == 0
    out = capsys.readouterr().out
    assert '"mode": "dry_run"' in out and '"signal_rows": 1' in out and '"returns_observed": 1' in out
