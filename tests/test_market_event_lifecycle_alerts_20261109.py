"""LQ-20261107-1674 stage 4 — alerts through the brief's text path, the bounded reconcile, the self-heal report.

Fail-before: at 21143c85d a transition is evaluated and nothing is delivered, so a persisted transition has no
``alert_event_id`` and no reconcile step can find it. Pass-after: the four Fi-text stages go through
``critical_texts.send_critical_text`` (the brief's own primitive), every transition lands in the digest list, the row
records which alert was sent, and a row without one is re-sent at most once. Synthetic fixtures only: the sender is a
test double, so no phone, gateway, credential or DB is touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import market_event_lifecycle as life

SYM = "TSTX"
NOW = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)


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


def inputs(*, qty=30, stop_lifecycle="working", tranche_qty=(30, 30, 40)):
    plan = {"invalidation": 90.0, "entry_price": 100.0, "tranche_pcts": [30, 30, 40]}
    if tranche_qty:
        plan["tranches"] = [{"tranche": i + 1, "shares": q} for i, q in enumerate(tranche_qty)]
    return {
        "episode": {"episode_id": "ep-test"},
        "candidates": [{"episode_id": "ep-test", "symbol": SYM, "sector": "healthcare", "state": "ENTERED",
                        "last_price": 100.0, "fell_for_reason": False, "reason_evidence": {}, "plan": plan}],
        "positions": [{"account_key": "tst_taxable", "symbol": SYM, "qty": qty, "avg_cost": 100.0,
                       "broker_market_value": 3000.0, "as_of": NOW.isoformat()}],
        "positions_as_of": NOW.isoformat(),
        "stops": {("tst_taxable", SYM): {"lifecycle": stop_lifecycle, "stop_price": 92.0}},
        "guardian": {}, "guardian_run_at": None, "sectors": {SYM: "Healthcare"},
        "bars": {SYM: flat(), "SPY": flat()}, "quote_asof": {SYM: NOW.isoformat()},
        "sleeve_pct": {}, "sleeve_basis": "direct", "sector_targets": {}, "trim_band": {},
        "mre": {"tier": "YELLOW", "as_of": NOW.isoformat()},
        "events": [{"kind": "CPI", "at": (NOW - timedelta(hours=2)).isoformat(),
                    "released_at": (NOW - timedelta(hours=1)).isoformat()}],
        "proxy_groups": {}, "errors": {},
    }


class Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        self.conn.sql.append((s, params))
        self.rowcount = 1 if s.startswith(("INSERT INTO market_event_lifecycle",
                                           "UPDATE market_event_lifecycle",
                                           "UPDATE market_event_candidates")) else 0


class Conn:
    def __init__(self):
        self.sql = []

    def cursor(self):
        return Cur(self)


def sender(result=None, record=None):
    def _send(ev):
        if record is not None:
            record.append(ev)
        return result if result is not None else {"sent": True}
    return _send


# --------------------------------------------------------------------------- planning


def test_only_the_four_fi_text_stages_are_texted_and_every_transition_reaches_the_digest():
    p = life.load_policy()
    rows = life.build_rows(inputs(), p, NOW)
    results = life.evaluate_rows(rows, p, NOW)
    assert results[0]["stage"] == "ADD_T2_READY"            # held one tranche, t2 gate open
    texts, digest = life.alert_events(results, now=NOW)
    assert [t["event_id"] for t in texts] == [f"ep-test:{SYM}:Tst Taxable:ADD_T2_READY"]
    assert texts[0]["alert_class"] == "market_event"
    assert texts[0]["action"] == "review the second tranche; advisory only"
    assert len(digest) == 1 and digest[0]["to_stage"] == "ADD_T2_READY"


def test_a_stage_that_did_not_change_produces_neither_a_text_nor_a_digest():
    p = life.load_policy()
    stored = {"last_tier": "YELLOW", "positions": {"Tst Taxable": {"stage": "ADD_T2_READY", "qty": 30.0,
                                                                   "stop": "WORKING"}}}
    inp = inputs()
    inp["candidates"][0]["plan"]["lifecycle"] = stored
    rows = life.build_rows(inp, p, NOW)
    results = life.evaluate_rows(rows, p, NOW)
    assert results[0]["alert"] is None
    texts, digest = life.alert_events(results, now=NOW)
    assert texts == [] and digest == []


def test_the_dry_run_plans_the_text_and_sends_nothing():
    called = []
    s = life.run_lane(conn=None, db_query=lambda *a, **k: [], now=NOW, apply=False, trigger="tick",
                      inputs=inputs(), text_sender=sender(record=called))
    assert called == []                                    # a dry run never calls the sender
    assert [t["event_id"] for t in s["alerts"]["planned"]] == [f"ep-test:{SYM}:Tst Taxable:ADD_T2_READY"]
    assert s["alerts"]["sent"] == []


# --------------------------------------------------------------------------- delivering


def test_an_apply_sends_the_text_and_stamps_the_row():
    conn = Conn()
    delivered = []
    s = life.run_lane(conn=conn, db_query=lambda *a, **k: [], now=NOW, apply=True, trigger="tick",
                      inputs=inputs(), text_sender=sender(record=delivered))
    assert s["transitions"] == 1
    assert len(delivered) == 1 and delivered[0]["alert_class"] == "market_event"
    assert s["alerted"] == 1
    stamp = [x for x in conn.sql if x[0].startswith("UPDATE market_event_lifecycle SET alert_event_id")]
    assert len(stamp) == 1
    assert stamp[0][1][0] == f"ep-test:{SYM}:Tst Taxable:ADD_T2_READY"


def test_a_refused_text_is_recorded_and_keeps_its_transition():
    conn = Conn()
    s = life.run_lane(conn=conn, db_query=lambda *a, **k: [], now=NOW, apply=True, trigger="tick",
                      inputs=inputs(), text_sender=sender(result={"sent": False, "reason": "hourly text cap reached"}))
    assert s["transitions"] == 1                           # the row is persisted regardless
    assert s["alerts"]["refused"][0]["reason"] == "hourly text cap reached"
    assert s["alerted"] == 0
    assert any(h["kind"] == "persist_without_alert" for h in s["heal"])


def test_a_sender_that_raises_does_not_lose_the_run():
    def boom(ev):
        raise RuntimeError("gateway down")

    conn = Conn()
    s = life.run_lane(conn=conn, db_query=lambda *a, **k: [], now=NOW, apply=True, trigger="tick",
                      inputs=inputs(), text_sender=boom)
    assert s["transitions"] == 1
    assert s["alerts"]["refused"][0]["reason"].startswith("RuntimeError")


# --------------------------------------------------------------------------- reconcile


def unalerted_row(**over):
    r = {"id": 7, "episode_id": "ep-test", "symbol": SYM, "account_label": "Tst Taxable",
         "from_stage": "ENTERED_T1", "to_stage": "EXIT_READY", "trigger": "tick",
         "at": (NOW - timedelta(minutes=20)).isoformat()}
    r.update(over)
    return r


def test_reconcile_re_sends_an_unalerted_transition_once():
    conn = Conn()
    out = life.reconcile_unalerted(conn, lambda *a, **k: [unalerted_row()], now=NOW, send=True,
                                   text_sender=sender())
    assert out["candidates"] == 1 and out["sent"] == 1
    upd = [x for x in conn.sql if x[0].startswith("UPDATE market_event_lifecycle SET alert_attempts")]
    assert len(upd) == 1 and upd[0][1][1] is True          # sent=True stamps the event id
    assert "alert_attempts = 0" in upd[0][0]               # the at-most-once guard is in the statement


def test_reconcile_marks_a_failed_attempt_so_it_is_not_retried_forever():
    conn = Conn()
    out = life.reconcile_unalerted(conn, lambda *a, **k: [unalerted_row()], now=NOW, send=True,
                                   text_sender=sender(result={"sent": False, "reason": "class switched off"}))
    assert out["refused"] == 1
    upd = [x for x in conn.sql if x[0].startswith("UPDATE market_event_lifecycle SET alert_attempts")]
    assert upd[0][1][1] is False and upd[0][1][0] is None  # no event id, but the attempt is spent


def test_more_than_one_candidate_never_exceeds_the_bound_of_one_attempt():
    conn = Conn()
    rows = [unalerted_row(id=1), unalerted_row(id=2)]
    out = life.reconcile_unalerted(conn, lambda *a, **k: rows, now=NOW, send=True, text_sender=sender())
    assert out["candidates"] == 2 and out["sent"] == 2
    assert len([x for x in conn.sql if x[0].startswith("UPDATE market_event_lifecycle")]) == 2


def test_reconcile_sends_nothing_on_a_dry_run_or_without_a_reader():
    conn = Conn()
    called = []
    out = life.reconcile_unalerted(conn, lambda *a, **k: [unalerted_row()], now=NOW, send=False,
                                   text_sender=sender(record=called))
    assert called == [] and out["sent"] == 0 and conn.sql == []
    assert life.reconcile_unalerted(conn, None, now=NOW, send=True)["skipped"] == "no reader"


def test_a_reconcile_that_cannot_read_is_reported_by_type_and_text():
    def bad(*a, **k):
        raise RuntimeError("market_event_lifecycle is down")

    out = life.reconcile_unalerted(Conn(), bad, now=NOW, send=True)
    assert "RuntimeError" in out["error"] and "down" in out["error"]


# --------------------------------------------------------------------------- self-heal


def test_the_heal_plan_names_the_owner_and_dispatches_nothing():
    p = life.load_policy()
    heal = life.heal_actions(errors={"positions": "OperationalError: stale", "mre": "OSError: no tier",
                                     "calendar": "FileNotFoundError: absent"},
                             transitions=2, alerted=1, late_minutes=25.0, policy=p)
    kinds = sorted(h["kind"] for h in heal)
    assert kinds == ["late_anchor", "persist_without_alert"] + ["stale_input"] * 3
    pos = [h for h in heal if h.get("source") == "positions"][0]
    assert pos["owner"] == "broker-read-sync" and pos["dispatched"] is False
    assert all(h["dispatched"] is False for h in heal)


def test_an_error_free_unchanged_run_has_no_heal_actions():
    p = life.load_policy()
    assert life.heal_actions(errors={}, transitions=0, alerted=0, late_minutes=0.0, policy=p) == []


# --------------------------------------------------------------------------- the rail


def test_the_lane_still_reaches_no_broker_and_sends_only_through_the_text_primitive():
    src = open(life.__file__, encoding="utf-8").read()
    for banned in ("place_order", "requests.post", "import psycopg", "from lib import broker", "smtplib"):
        assert banned not in src
    # the only sender is critical_texts.send_critical_text — the brief's own primitive
    assert "send_critical_text" in src
