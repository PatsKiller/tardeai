"""LQ-20261107-1674 stage 3 — what fired this run: calendar anchors, tier, qty and stop changes.

Fail-before: at 21143c85d nothing derives a trigger — the lane takes ``--trigger`` (default ``tick``) and every run
records that string. Pass-after: :func:`scripts.lib.market_event_lifecycle.derive_trigger` names the anchor or the
observed change it saw, and the persisted row carries it. Synthetic fixtures only: no DB, no broker, no credential.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import market_event_lifecycle as life

SYM = "TSTX"


def policy(**lc_over):
    p = life.load_policy()          # the merged plan block, the shape evaluate_position reads
    lc = dict(p["lifecycle"])
    lc.update(lc_over)
    p["lifecycle"] = lc
    return p


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 11, 9, h, m, tzinfo=timezone.utc)


def flat(n=40, close=100.0):
    d = datetime(2026, 10, 1).date()
    out = []
    for _ in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "open": close, "high": close, "low": close,
                    "close": close, "volume": 1_000_000})
        d += timedelta(days=1)
    return out


def candidate(stored=None):
    plan = {"invalidation": 90.0, "entry_price": 100.0, "tranche_pcts": [30, 30, 40]}
    if stored is not None:
        plan["lifecycle"] = stored
    return {"episode_id": "ep-test", "symbol": SYM, "sector": "healthcare", "state": "ENTERED",
            "last_price": 100.0, "fell_for_reason": False, "reason_evidence": {}, "plan": plan}


def position(qty=30, stop_lifecycle="working", now=None):
    now = now or at(14, 0)
    return {"account_key": "tst_taxable", "symbol": SYM, "qty": qty, "avg_cost": 100.0,
            "broker_market_value": 3000.0, "as_of": now.isoformat()}, stop_lifecycle


def inputs(*, now=None, stored=None, qty=30, stop_lifecycle="working", events=None, tier="YELLOW"):
    now = now or at(14, 0)
    pos, _ = position(qty=qty, now=now)
    stops = {} if stop_lifecycle is None else {
        ("tst_taxable", SYM): {"lifecycle": stop_lifecycle, "stop_price": 92.0}}
    return {
        "episode": {"episode_id": "ep-test"}, "candidates": [candidate(stored)], "positions": [pos],
        "positions_as_of": now.isoformat(), "stops": stops, "guardian": {}, "guardian_run_at": None,
        "sectors": {SYM: "Healthcare"}, "bars": {SYM: flat(), "SPY": flat()},
        "quote_asof": {SYM: now.isoformat()}, "sleeve_pct": {}, "sleeve_basis": "direct",
        "sector_targets": {}, "trim_band": {}, "mre": {"tier": tier, "as_of": now.isoformat()},
        "events": events or [], "proxy_groups": {}, "errors": {},
    }


def cpi(*, released_at, kind="CPI"):
    return {"kind": kind, "at": released_at, "released_at": released_at}


class Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.conn.sql.append((" ".join(str(sql).split()), params))
        self.rowcount = 1 if str(sql).startswith("INSERT INTO market_event_lifecycle") else 0


class Conn:
    def __init__(self):
        self.sql = []

    def cursor(self):
        return Cur(self)


# --------------------------------------------------------------------------- calendar anchors


def test_a_released_event_fires_at_release_plus_settle_minutes():
    ev = [cpi(released_at=at(13, 30).isoformat())]          # 08:30 ET
    on_time = life.calendar_anchor_triggers(ev, now=at(13, 50), settle_min=15)   # anchor 13:45, 5 min late
    assert [a["trigger"] for a in on_time] == ["calendar:CPI"]
    assert on_time[0]["late_minutes"] == pytest.approx(5.0)
    # before the settle has elapsed the gate is still closed and the anchor is not due
    assert life.calendar_anchor_triggers(ev, now=at(13, 40), settle_min=15) == []
    # an unreleased event is scheduled, never due
    assert life.calendar_anchor_triggers([{"kind": "CPI", "at": at(13, 30).isoformat(), "released_at": None}],
                                         now=at(14, 0), settle_min=15) == []


def test_late_past_the_slack_says_so_and_past_the_window_is_not_claimed():
    ev = [cpi(released_at=at(13, 30).isoformat())]
    late = life.calendar_anchor_triggers(ev, now=at(14, 0), settle_min=15)      # 15 min after the anchor
    assert [a["trigger"] for a in late] == ["calendar:CPI:late"]
    # a lane that was down for four hours does not relabel the gap as an on-time anchored run
    assert life.calendar_anchor_triggers(ev, now=at(18, 0), settle_min=15, window_min=60) == []


def test_the_settle_comes_from_the_same_policy_block_the_gate_reads():
    ev = [cpi(released_at=at(13, 30).isoformat())]
    d = life.derive_trigger(rows=[], events=ev, now=at(13, 50), policy=policy(settle_min=30))
    assert d["trigger"] == "tick"          # 30-min settle: not due yet
    d2 = life.derive_trigger(rows=[], events=ev, now=at(14, 5), policy=policy(settle_min=30))
    assert d2["trigger"] == "calendar:CPI"


# --------------------------------------------------------------------------- observed changes


def test_a_tier_change_names_both_tiers_and_an_unchanged_tier_is_a_tick():
    p = policy()
    changed = life.build_rows(inputs(stored={"last_tier": "GREEN", "positions": {}}), p, at(14, 0))
    assert life.derive_trigger(rows=changed, events=[], now=at(14, 0), policy=p)["triggers"] == ["tier:GREEN->YELLOW"]
    same = life.build_rows(inputs(stored={"last_tier": "YELLOW", "positions": {}}), p, at(14, 0))
    assert life.derive_trigger(rows=same, events=[], now=at(14, 0), policy=p)["trigger"] == "tick"


def test_a_qty_or_stop_change_names_the_symbol():
    p = policy()
    stored = {"last_tier": "YELLOW", "positions": {"Tst Taxable": {"stage": "HELD_T2", "qty": 10.0,
                                                                   "stop": "WORKING"}}}
    qty = life.build_rows(inputs(stored=stored, qty=30), p, at(14, 0))
    assert life.derive_trigger(rows=qty, events=[], now=at(14, 0), policy=p)["triggers"] == [f"qty:{SYM}"]
    stop = life.build_rows(inputs(stored=stored, qty=10, stop_lifecycle="filled"), p, at(14, 0))
    assert life.derive_trigger(rows=stop, events=[], now=at(14, 0), policy=p)["triggers"] == [f"stop:{SYM}"]
    # nothing moved: a tick, not an empty list
    same = life.build_rows(inputs(stored=stored, qty=10), p, at(14, 0))
    assert life.derive_trigger(rows=same, events=[], now=at(14, 0), policy=p)["trigger"] == "tick"


def test_a_first_run_has_no_history_so_it_cannot_claim_a_change():
    p = policy()
    rows = life.build_rows(inputs(), p, at(14, 0))       # no stored lifecycle at all
    assert life.derive_trigger(rows=rows, events=[], now=at(14, 0), policy=p)["trigger"] == "tick"


def test_triggers_are_deduplicated_with_calendar_first():
    p = policy()
    ev = [cpi(released_at=at(13, 30).isoformat()),
          cpi(released_at=at(13, 30).isoformat(), kind="FOMC")]
    rows = life.build_rows(inputs(stored={"last_tier": "GREEN", "positions": {}}), p, at(14, 0))
    d = life.derive_trigger(rows=rows, events=ev, now=at(14, 0), policy=p)
    assert d["triggers"][0].startswith("calendar:")
    assert len(d["triggers"]) == len(set(d["triggers"]))
    assert d["trigger"] == d["triggers"][0]
    assert d["anchor_max_late_minutes"] == pytest.approx(15.0)


# --------------------------------------------------------------------------- the lane step


def test_an_auto_run_labels_the_anchor_and_the_persisted_row_carries_it():
    conn = Conn()
    s = life.run_lane(conn=conn, db_query=None, now=at(13, 50), apply=True, trigger="auto",
                      inputs=inputs(events=[cpi(released_at=at(13, 30).isoformat())]))
    assert s["trigger"] == "calendar:CPI"
    assert s["triggers"] == ["calendar:CPI"]
    assert s["transitions"] == 1
    inserts = [x for x in conn.sql if x[0].startswith("INSERT INTO market_event_lifecycle")]
    assert inserts and inserts[0][1][5] == "calendar:CPI"


def test_the_dry_run_derives_the_trigger_and_writes_nothing():
    def boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("supplied inputs must not touch the DB")

    s = life.run_lane(conn=None, db_query=boom, now=at(14, 0), apply=False, trigger="auto",
                      inputs=inputs(events=[cpi(released_at=at(13, 30).isoformat())]))
    assert s["trigger"] == "calendar:CPI:late"
    assert s["anchor_max_late_minutes"] == pytest.approx(15.0)
    assert s["transitions"] == 0


def test_an_explicit_trigger_is_recorded_verbatim_for_a_replay():
    s = life.run_lane(conn=None, db_query=None, now=at(14, 0), apply=False, trigger="tick",
                      inputs=inputs(events=[cpi(released_at=at(13, 30).isoformat())]))
    assert s["trigger"] == "tick"
    assert s["triggers"] == ["tick"]


def test_the_state_map_records_the_qty_and_stop_the_next_run_compares_against():
    conn = Conn()
    now = at(14, 0)
    life.run_lane(conn=conn, db_query=None, now=now, apply=True, trigger="tick", inputs=inputs(qty=30))
    plan_doc = [x for x in conn.sql if x[0].startswith("UPDATE market_event_candidates")][0][1][0]
    import json

    doc = json.loads(plan_doc)
    assert doc["positions"]["Tst Taxable"]["qty"] == 30.0
    assert doc["positions"]["Tst Taxable"]["stop"] == "WORKING"
    assert doc["last_tier"] == "YELLOW"
