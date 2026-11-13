"""ANCHOR: STOP_COVERAGE_INCIDENTS_LQ2145_20261111 — the stop-coverage-incidents lane (LQ-20261107-2145/2146).

Synthetic symbols/accounts, fake connection, fake publisher. No broker, no real DB, no order route.
Proves the plan (gaps, proven recoveries, unknowns) and that the lane publishes through the single writer.
It does NOT prove record_occurrence's counting against Postgres: that is the non-author DB run in the READY note.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import stop_coverage_incidents as sci  # noqa: E402

T0 = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
ACCT = "acct_synthetic_1"
H = sci.account_hash(ACCT)


class Conn:
    def __init__(self, open_rows=()):
        self.open_rows = list(open_rows)

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, p=()):
        assert "FROM alert_incidents" in sql and p == (sci.ALERT_TYPE, sci.SOURCE_PRODUCER)

    def fetchall(self):
        return self.open_rows


class Pub:
    def __init__(self):
        self.calls = []

    def __call__(self, event, *, resolving=False, **kw):
        self.calls.append((event, resolving))
        return {"ok": True, "occurrence_id": len(self.calls)}


def rec(sym, acct=ACCT, *, unprotected=True, health=None, duration="GOOD_TILL_CANCEL", status="canceled"):
    return {"symbol": sym, "account": acct, "flags": ["unprotected"] if unprotected else [],
            "health": health or ("alert" if unprotected else "ok"), "held_qty": 100,
            "duration": duration, "status": status}


def scan(stops, at=T0, **kw):
    return {"stops": stops, "generated_at": at.isoformat(), "summary": {"total": len(stops)}, **kw}


def test_dry_run_publishes_nothing_and_apply_publishes_one_event_per_position():
    pub = Pub()
    s = scan([rec("AAA"), rec("AAA"), rec("BBB")])   # two terminal stops on AAA still = one gap
    out = sci.run(s, conn=Conn(), publish=pub)
    assert out["gaps"] == [(H, "AAA"), (H, "BBB")] and out["applied"] is False and pub.calls == []
    out = sci.run(s, conn=Conn(), publish=pub, apply=True)
    assert out["applied"] is True and len(pub.calls) == 2
    ev, resolving = pub.calls[0]
    assert resolving is False
    assert (ev.alert_type, ev.source_producer, ev.severity, ev.operator_action_type) == (
        "position_unprotected", "stop_coverage_incidents", "critical", "PROTECTION_REPAIR")
    assert ev.account_id == H and ACCT not in json.dumps(ev.payload) and ev.created_at == T0


def test_event_identity_is_stable_across_scans_so_the_writer_counts_one_incident():
    from operator_alert_policy_v2 import alert_fingerprint, incident_id_for
    a, b = (sci._event((H, "AAA"), T0 + timedelta(minutes=5 * i), rec("AAA")) for i in range(2))
    assert alert_fingerprint(a) == alert_fingerprint(b) and incident_id_for(a) == incident_id_for(b)
    other = sci._event((sci.account_hash("acct_synthetic_2"), "AAA"), T0, rec("AAA"))
    assert incident_id_for(other) != incident_id_for(a)
    resolved = sci._event((H, "AAA"), T0, None)   # the resolving event keeps the opening event's identity
    assert alert_fingerprint(resolved) == alert_fingerprint(a)


def test_recovery_needs_a_covered_record_in_a_complete_scan():
    pub = Pub()
    open_ = [(H, "AAA")]
    out = sci.run(scan([rec("ZZZ", unprotected=False)]), conn=Conn(open_), publish=pub, apply=True)
    assert out["resolve"] == [] and out["unresolved_unknown"] == [(H, "AAA")] and pub.calls == []   # absence != recovery
    out = sci.run(scan([rec("AAA", unprotected=False)], schwab_stops_status="UNAVAILABLE"),
                  conn=Conn(open_), publish=pub, apply=True)
    assert out["ok"] is False and out["reason"] == "incomplete_scan" and pub.calls == []   # a blind scan proves nothing
    out = sci.run(scan([rec("AAA", unprotected=False)]), conn=Conn(open_), publish=pub, apply=True)
    assert out["resolve"] == [(H, "AAA")]
    (ev, resolving), = pub.calls
    assert resolving is True and ev.symbol == "AAA"


def test_a_still_unprotected_sibling_blocks_resolution():
    out = sci.run(scan([rec("AAA", unprotected=False), rec("AAA")]), conn=Conn([(H, "AAA")]), publish=Pub())
    assert out["resolve"] == [] and out["gaps"] == [(H, "AAA")]


def test_incomplete_scans_publish_nothing():
    for bad in ({"errors": ["boom"]}, {"ok": False}, {"schwab_stops_status": "UNAVAILABLE"}):
        pub = Pub()
        out = sci.run(scan([rec("AAA")], **bad), conn=Conn(), publish=pub, apply=True)
        assert out["ok"] is False and pub.calls == []
    pub = Pub()
    assert sci.run({"stops": [], "generated_at": T0.isoformat(), "summary": {"total": 0}}, conn=Conn(),
                   publish=pub, apply=True)["ok"] is False


def test_off_hours_expired_day_stop_opens_no_incident():
    s = scan([rec("AAA", duration="DAY", status="expired"), rec("BBB", duration="GOOD_TILL_CANCEL", status="canceled")])
    out = sci.run(s, conn=Conn(), publish=Pub(), session_open=False)
    assert out["day_stop_expired"] == [(H, "AAA")] and out["gaps"] == [(H, "BBB")]
    out = sci.run(s, conn=Conn(), publish=Pub(), session_open=True)   # in session the same row IS a gap
    assert out["gaps"] == [(H, "AAA"), (H, "BBB")] and out["day_stop_expired"] == []


def test_rows_without_identity_are_never_keyed():
    s = scan([{"symbol": "AAA", "account": "", "flags": ["unprotected"], "health": "alert"},
              {"symbol": "", "account": ACCT, "flags": ["unprotected"], "health": "alert"}, rec("OK1", unprotected=False)])
    assert sci.run(s, conn=Conn(), publish=Pub())["gaps"] == []


def test_dry_run_does_not_advance_the_freshness_key(tmp_path):
    p = tmp_path / "hb.json"
    sci._heartbeat({"status": "error", "finished_at": "x"}, p)
    assert json.loads(p.read_text())["ok_at"] is None
    sci._heartbeat({"status": "ok", "finished_at": "2026-11-11T20:00:00+00:00"}, p)
    assert json.loads(p.read_text())["ok_at"] == "2026-11-11T20:00:00+00:00"
    sci._heartbeat({"status": "error", "finished_at": "later"}, p)   # a failed run keeps the previous ok_at
    assert json.loads(p.read_text())["ok_at"] == "2026-11-11T20:00:00+00:00"


# ---- C2 / C3 / heartbeat path (review of 7d4943004) -------------------------------------------------------------------

def _apply(pub, stops=None):
    return sci.run(scan(stops or [rec("AAA"), rec("BBB")]), conn=Conn(), publish=pub, apply=True)


def test_c2_volatile_fallback_is_not_a_recorded_incident():
    def pub(event, *, resolving=False, **kw):
        return {"ok": True, "volatile_fallback": True, "occurrence_id": 3}
    out = _apply(pub)
    assert out["ok"] is False and out["applied"] is False and out["failed"] == 2 and out["reason"] == "publish_failed"


def test_c2_ok_without_occurrence_id_is_not_proof():
    out = _apply(lambda e, **k: {"ok": True})
    assert out["ok"] is False and out["failed"] == 2


def test_c2_non_dict_and_ok_false_results_fail():
    assert _apply(lambda e, **k: None)["failed"] == 2
    assert _apply(lambda e, **k: {"ok": False, "occurrence_id": 5})["failed"] == 2


def test_c3_one_raising_key_does_not_hide_the_rest_and_fails_the_run():
    calls = []

    def pub(event, *, resolving=False, **kw):
        calls.append(event.symbol)
        if event.symbol == "AAA":
            raise RuntimeError("db gone")
        return {"ok": True, "occurrence_id": 1}
    out = _apply(pub)
    assert calls == ["AAA", "BBB"] and out["failed"] == 1 and out["ok"] is False and out["applied"] is False


def test_c3_failed_run_exits_nonzero_and_leaves_no_fresh_ok_at(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    # LQ-2968: main() reads the persisted snapshot, not the broker; run() is stubbed below, so the inputs are empty
    fake_db = type(sys)("db_adapter")
    fake_db._get_conn = lambda: Conn()
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    _now = datetime.now(timezone.utc)   # a fresh snapshot, so the stubbed run() result is what main() reports
    monkeypatch.setattr(sci, "_fetch", lambda conn, sql: [{"account": ACCT, "symbol": "AAA", "lifecycle": "working",
                                                           "snapshot_at": _now, "as_of": _now, "account_key": ACCT,
                                                           "qty": 1, "broker_market_value": 5000.0,
                                                           "asset_type": "EQUITY", "is_cash": False}])
    monkeypatch.setattr(sci, "run", lambda s, **k: {"ok": False, "reason": "publish_failed", "failed": 1,
                                                    "gaps": [1], "resolve": [], "unresolved_unknown": [],
                                                    "day_stop_expired": [], "applied": False})
    assert sci.main(["--apply"]) == 2
    hb = json.loads((tmp_path / "data" / "runtime" / sci.HEARTBEAT_NAME).read_text())
    assert hb["status"] == "error" and hb["ok_at"] is None


def test_heartbeat_follows_state_root_the_reader_uses(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert sci.heartbeat_path() == tmp_path / "data" / "runtime" / "stop_coverage_incidents_last.json"
    from scripts.home_status_verdict import ORDERS_HEARTBEAT
    assert ORDERS_HEARTBEAT == sci.HEARTBEAT_NAME


def test_dry_run_main_writes_no_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    # LQ-2968: main() reads the persisted snapshot, not the broker; run() is stubbed below, so the inputs are empty
    fake_db = type(sys)("db_adapter")
    fake_db._get_conn = lambda: Conn()
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    _now = datetime.now(timezone.utc)   # a fresh snapshot, so the stubbed run() result is what main() reports
    monkeypatch.setattr(sci, "_fetch", lambda conn, sql: [{"account": ACCT, "symbol": "AAA", "lifecycle": "working",
                                                           "snapshot_at": _now, "as_of": _now, "account_key": ACCT,
                                                           "qty": 1, "broker_market_value": 5000.0,
                                                           "asset_type": "EQUITY", "is_cash": False}])
    monkeypatch.setattr(sci, "run", lambda s, **k: {"ok": True, "gaps": [1], "resolve": [], "unresolved_unknown": [],
                                                    "day_stop_expired": [], "applied": False, "reason": None})
    assert sci.main([]) == 0
    assert not (tmp_path / "data" / "runtime" / sci.HEARTBEAT_NAME).exists()
