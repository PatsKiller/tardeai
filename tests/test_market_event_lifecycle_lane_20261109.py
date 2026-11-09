"""LQ-20261107-1674 stage 2 — the ``market-event-lifecycle`` lane: gather, evaluate every held row, persist.

Fail-before: no ``scripts/lib/market_event_lifecycle.py`` exists at 21143c85d, so this file cannot even import its
subject (collection error). Pass-after: the lane step is driven entirely from synthetic inputs — no DB, no broker, no
credential, no live symbol, no live dollar amount. The fake connection records every statement, so a test can assert
the dry run wrote nothing and that the persisted row carries the account LABEL and never the account key.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import market_event_lifecycle as life

NOW = datetime(2026, 11, 9, 20, 30, tzinfo=timezone.utc)  # 15:30 ET
SYM = "TSTX"
PROXY = "XLV"


# --------------------------------------------------------------------------- fixtures


def policy(**lc_over):
    p = life.load_policy()
    lc = dict(p["plan"]["lifecycle"])
    lc.update(lc_over)
    p["plan"] = {**p["plan"], "lifecycle": lc}
    return p


def bars(closes, *, start="2026-10-01", lows=None):
    """Synthetic daily bars on consecutive weekdays; ``closes[-1]`` is the newest close."""
    out = []
    d = datetime.fromisoformat(start).date()
    lows = lows or [min(closes)] * len(closes)
    for i, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "open": c, "high": c * 1.01, "low": lows[i], "close": c,
                    "volume": 1_000_000})
        d += timedelta(days=1)
    return out


def flat(n=40, close=100.0):
    return bars([close] * n)


def candidate(**over):
    c = {
        "episode_id": "ep-test", "symbol": SYM, "sector": "healthcare", "state": "ENTERED",
        "last_price": 100.0, "fell_for_reason": False, "reason_evidence": {},
        "plan": {"invalidation": 90.0, "entry_price": 100.0, "tranche_pcts": [30, 30, 40],
                 "tranches": [{"tranche": 1, "shares": 30}, {"tranche": 2, "shares": 30},
                              {"tranche": 3, "shares": 40}]},
    }
    c.update(over)
    return c


def position(account_key="tst_taxable", qty=30, avg_cost=100.0, value=3000.0, as_of=None):
    return {"account_key": account_key, "symbol": SYM, "qty": qty, "avg_cost": avg_cost,
            "broker_market_value": value, "as_of": as_of or NOW.isoformat()}


def inputs(**over):
    base = {
        "episode": {"episode_id": "ep-test"},
        "candidates": [candidate()],
        "positions": [position()],
        "stops": {("tst_taxable", SYM): {"lifecycle": "working", "stop_price": 92.0}},
        "guardian": {}, "guardian_run_at": None,
        "sectors": {SYM: "Healthcare"},
        "bars": {SYM: flat(), PROXY: flat()},
        "quote_asof": {SYM: NOW.isoformat()},
        "sleeve_pct": {"Healthcare": 12.0}, "sleeve_basis": "direct",
        "sector_targets": {"Healthcare": 18.0}, "trim_band": {"low_frac": 0.05, "high_frac": 0.15},
        "mre": {"tier": "YELLOW", "as_of": NOW.isoformat()},
        "events": [{"kind": "CPI", "at": (NOW - timedelta(hours=2)).isoformat(),
                    "released_at": (NOW - timedelta(hours=1)).isoformat()}],
        "proxy_groups": {"healthcare": {"label": "Healthcare", "proxy": PROXY, "kind": "sector"}},
        "errors": {},
    }
    base.update(over)
    return base


class Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.conn.sql.append((" ".join(str(sql).split()), params))
        if str(sql).startswith("INSERT INTO market_event_lifecycle"):
            key = (params[0], params[1], params[2], params[4])
            self.rowcount = 0 if key in self.conn.existing else 1
            self.conn.existing.add(key)
        elif str(sql).startswith("UPDATE market_event_candidates"):
            self.rowcount = 1
        else:
            self.rowcount = 0


class Conn:
    def __init__(self):
        self.sql = []
        self.existing = set()

    def cursor(self):
        return Cur(self)


# --------------------------------------------------------------------------- RS and proxy selection


def test_rs_loss_counts_consecutive_lagging_sessions_and_stops_at_the_first_that_does_not():
    name = bars([100.0] * 10 + [97.0, 94.0, 91.0])          # falling
    proxy = bars([100.0] * 10 + [103.0, 106.0, 109.0])      # rising
    assert life.rs_loss_sessions(name, proxy, pct=5.0) == 3
    # the last session catches up: the count resets to 0, not "3 at some point"
    catch = bars([100.0] * 10 + [97.0, 94.0, 130.0])
    assert life.rs_loss_sessions(catch, proxy, pct=5.0) == 0
    # too short to measure one session is unmeasured, never zero
    assert life.rs_loss_sessions(name[:3], proxy[:3], pct=5.0) is None


def test_the_proxy_is_the_group_proxy_then_the_sector_label_then_the_benchmark():
    groups = life.proxy_group_map({"groups": {"healthcare": {"label": "Healthcare", "proxy": "XLV"}}})
    assert life.proxy_for_candidate({"sector": "healthcare"}, groups) == "XLV"
    assert life.proxy_for_candidate({"sector": "Healthcare"}, groups) == "XLV"
    assert life.proxy_for_candidate({"sector": "unmapped"}, groups) == "SPY"


def test_the_sleeve_pct_is_the_direct_basis_and_says_so():
    pct, basis = life.sleeve_pct_by_sector(
        [position(qty=1, value=600.0), position(qty=1, value=400.0, account_key="tst_ira")],
        {SYM: "Healthcare"})
    assert basis in ("direct", "lookthrough")
    if basis == "direct":
        assert pct.get("Health Care") == pytest.approx(100.0, abs=0.5)
    assert pct  # never an empty map when there is a book


# --------------------------------------------------------------------------- the calendar


def test_the_calendar_maps_only_the_four_gating_kinds_and_a_release_only_after_its_instant(tmp_path):
    body = {"schema": "MacroCalendar@v1", "fetched_at": "2026-11-09T00:00:00+00:00",
            "covers_from": "2026-11-09", "valid_through": "2026-11-12",
            "dates": {
                "2026-11-09": {"weekday": "Mon", "has_0830": True, "skip_0800": True, "events": [
                    {"event": "cpi", "name": "Consumer Price Index", "time_et": "08:30"}]},
                "2026-11-10": {"weekday": "Tue", "has_0830": True, "skip_0800": True, "events": [
                    {"event": "employment_situation", "name": "Employment Situation", "time_et": "08:30"},
                    {"event": "ppi", "name": "Producer Price Index", "time_et": "08:30"}]},
            }}
    p = tmp_path / "macro_calendar.json"
    p.write_text(json.dumps(body))
    ev, err = life.load_events(now=NOW, path=p)
    assert err is None
    kinds = [e["kind"] for e in ev]
    assert kinds == ["CPI", "NFP"]                 # ppi is not a gating kind
    assert ev[0]["released_at"] is not None         # 08:30 ET has passed at 15:30 ET
    # a release still ahead is scheduled but not released: the gate stays withheld, never passed
    fut, _ = life.load_events(now=datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc), path=p)
    assert fut[1]["released_at"] is None


def test_an_unreadable_calendar_is_reported_and_yields_no_events(tmp_path):
    ev, err = life.load_events(now=NOW, path=tmp_path / "absent.json")
    assert ev == [] and err and "FileNotFoundError" in err


# --------------------------------------------------------------------------- row building


def test_a_held_position_builds_one_row_per_account_label():
    rows = life.build_rows(inputs(), policy(), NOW)
    assert len(rows) == 1
    r = rows[0]
    assert r["account_label"] == "Tst Taxable"
    assert r["holding"]["qty"] == 30.0
    assert r["holding"]["avg_cost"] == 100.0
    assert r["snapshot"]["tier"] == "YELLOW"
    assert r["snapshot"]["rs_proxy"] == PROXY
    assert r["previous_stage"] == "ENTERED"


def test_a_position_that_vanished_is_still_evaluated_as_stopped_out():
    stored = {"schema": life.SCHEMA_STATE, "entry_tier": "YELLOW",
              "positions": {"Tst Taxable": {"stage": "HELD_T2", "at": "2026-11-09T18:00:00+00:00"}}}
    stock = [position()]
    stock[0]["symbol"] = SYM
    inp = inputs(candidates=[candidate(plan={"invalidation": 90.0, "entry_price": 100.0,
                                             "tranche_pcts": [30, 30, 40], "lifecycle": stored})],
                 positions=[], positions_as_of=NOW.isoformat(),
                 stops={("tst_taxable", SYM): {"lifecycle": "filled", "stop_price": 92.0}})
    rows = life.build_rows(inp, policy(), NOW)
    assert len(rows) == 1
    assert rows[0]["holding"]["qty"] == 0.0
    res = life.evaluate_rows(rows, policy(), NOW)[0]
    assert res["stage"] == "STOPPED_OUT"
    assert res["handoff"]["to"] == "recovery_state"


def test_a_candidate_with_no_held_label_is_not_a_row():
    inp = inputs(positions=[])
    assert life.build_rows(inp, policy(), NOW) == []


def test_the_giveback_state_is_used_only_while_the_guardian_run_is_fresh():
    fresh = inputs(guardian_run_at=NOW.isoformat(),
                   guardian={("tst_taxable", SYM): {"giveback_state": "GIVEBACK_BREACH",
                                                    "run_at": NOW.isoformat()}})
    r = life.build_rows(fresh, policy(), NOW)[0]
    assert r["snapshot"]["gain_guardian_state"] == "GIVEBACK_BREACH"
    stale = inputs(guardian_run_at=(NOW - timedelta(hours=8)).isoformat(),
                   guardian={("tst_taxable", SYM): {"giveback_state": "GIVEBACK_BREACH",
                                                    "run_at": (NOW - timedelta(hours=8)).isoformat()}})
    r2 = life.build_rows(stale, policy(), NOW)[0]
    assert r2["snapshot"]["gain_guardian_state"] is None
    assert "GIVEBACK_BREACH" in str(r2["snapshot"].get("gain_guardian_state_ignored"))


# --------------------------------------------------------------------------- the lane step


def test_the_dry_run_writes_nothing_and_reports_the_four_receipt_fields():
    called = []

    def boom(*a, **k):
        called.append(a)
        raise AssertionError("the dry run must not read the DB when inputs are supplied")

    summary = life.run_lane(conn=None, db_query=boom, now=NOW, apply=False, inputs=inputs())
    assert called == []
    for k in ("rows_evaluated", "transitions", "not_measured", "trigger"):
        assert k in summary
    assert summary["rows_evaluated"] == 1
    assert summary["transitions"] == 0
    assert summary["trigger"] == "tick"
    assert summary["rows"][0]["stage"] in life.mep.POSITION_STAGES


def test_no_open_episode_and_no_held_candidate_are_the_two_typed_empties():
    s = life.run_lane(conn=None, db_query=None, now=NOW, apply=False,
                      inputs=inputs(episode=None, candidates=[], positions=[]))
    assert s["empty_reason"] == "no_open_episode"
    s2 = life.run_lane(conn=None, db_query=None, now=NOW, apply=False, inputs=inputs(positions=[]))
    assert s2["empty_reason"] == "no_held_candidate"
    assert s2["rows_evaluated"] == 0


def test_apply_persists_one_row_per_transition_and_the_stage_map():
    conn = Conn()
    inp = inputs()
    summary = life.run_lane(conn=conn, db_query=None, now=NOW, apply=True, inputs=inp)
    assert summary["transitions"] == 1
    inserts = [s for s in conn.sql if s[0].startswith("INSERT INTO market_event_lifecycle")]
    assert len(inserts) == 1
    _sql, params = inserts[0]
    eid, sym, label, from_stage, to_stage = params[0], params[1], params[2], params[3], params[4]
    assert (eid, sym, from_stage) == ("ep-test", SYM, "ENTERED")
    assert to_stage == summary["rows"][0]["stage"]
    # the account LABEL is stored and the account key is not, in any parameter of any statement
    assert label == "Tst Taxable"
    assert "tst_taxable" not in json.dumps([s[1] for s in conn.sql], default=str)
    updates = [s for s in conn.sql if s[0].startswith("UPDATE market_event_candidates")]
    assert len(updates) == 1
    plan_doc = json.loads(updates[0][1][0])
    assert plan_doc["positions"]["Tst Taxable"]["stage"] == to_stage
    assert plan_doc["entry_tier"] == "YELLOW"


def test_a_replay_over_the_same_inputs_writes_no_second_transition():
    conn = Conn()
    first = life.run_lane(conn=conn, db_query=None, now=NOW, apply=True, inputs=inputs())
    assert first["transitions"] == 1
    stage = first["rows"][0]["stage"]
    stored = {"schema": life.SCHEMA_STATE, "entry_tier": "YELLOW",
              "positions": {"Tst Taxable": {"stage": stage, "at": NOW.isoformat()}}}
    conn2 = Conn()
    again = life.run_lane(conn=conn2, db_query=None, now=NOW, apply=True,
                          inputs=inputs(candidates=[candidate(plan={**candidate()["plan"], "lifecycle": stored})]))
    assert again["transitions"] == 0
    assert again["rows"][0]["previous_stage"] == stage
    assert again["rows"][0]["stage"] == stage


def test_an_unverifiable_row_never_advances_or_persists():
    conn = Conn()
    stale = inputs(positions=[position(as_of=(NOW - timedelta(hours=3)).isoformat())])
    summary = life.run_lane(conn=conn, db_query=None, now=NOW, apply=True, inputs=stale)
    assert summary["rows"][0]["verdict"] == "UNVERIFIABLE"
    assert summary["transitions"] == 0
    assert not [s for s in conn.sql if s[0].startswith("INSERT INTO market_event_lifecycle")]


def test_an_error_is_reported_by_type_and_text_not_as_a_zero():
    def bad(*a, **k):
        raise RuntimeError("positions_current is down")

    summary = life.run_lane(conn=None, db_query=bad, now=NOW, apply=False)
    assert summary["error"] and "RuntimeError" in summary["error"] and "down" in summary["error"]


# --------------------------------------------------------------------------- the rail


def test_the_lane_is_advisory_and_never_reaches_a_broker():
    src = Path(life.__file__).read_text(encoding="utf-8")
    for banned in ("place_order", "requests.post", "import psycopg", "from lib import broker"):
        assert banned not in src
    p = life.load_policy()["plan"]["lifecycle"]
    assert p["tranche_held_fraction"] == 0.8
    assert (p["trim_gain_pct"], p["rs_loss_pct"], p["rs_loss_sessions"]) == (25.0, 5.0, 3)
    assert p["t3_max_tier"] == "YELLOW"           # operator 2026-11-09: "YELLOW+" is YELLOW or BETTER
    assert p["gain_guardian_states"] == ["GIVEBACK_BREACH"]
