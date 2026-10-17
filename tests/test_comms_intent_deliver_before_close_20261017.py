"""Comms-intent deliver-before-close (2026-10-17): an intent's incident stays open until the notifier delivers it.

Path under test: lane -> scripts/lib/host_comms_intents.py (QUEUED in comms_intents) -> scripts/n8n_comms_intent_consumer.py
--apply (comms_intent_incidents) -> scripts/n8n_incident_fanin.py (_comms_intent_findings) -> scripts/incident_notifier.py
--live (the sole sender; daily cap 24, quiet hours 22:00-07:00 ET).

Defect: scripts/lib/n8n_comms_intent_consumption.py close_expired CLOSED every incident whose dedupe window (1 h) had
passed, and open_incident_findings hid any row past its window, whether or not the notifier had delivered it. A P2
consumed at 22:30 ET (quiet-held) or after the cap was spent closed unsent and vanished: no message, and no recovery
either (the notifier had no record of it). Fix: past its window a notifiable row is CLOSED only on the notifier's own
delivery evidence (incident_notifier_state.json; acked_keys on its last live receipt), else DEFERRED, which the fan-in
keeps presenting, so it leaves in the next allowed batch (07:00 ET / cap reset), once.

Hermetic: tmp_path state root and ledger (the real CoordinationLedger), the real consumer CLI, fan-in reader and
notifier run() with a capture sender. The Telegram chokepoints are stubs that fail the test if reached.

COVERS = ["scripts/lib/n8n_comms_intent_consumption.py", "scripts/n8n_comms_intent_consumer.py",
          "scripts/n8n_incident_fanin.py", "scripts/incident_notifier.py", "scripts/lib/host_comms_intents.py"]
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402
from scripts import n8n_comms_intent_consumer as CLI  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import host_comms_intents as H  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

PRODUCER = "hermes_outcome_feedback_agent"
DOMAIN, KIND = "research", "hermes_closed_loop_alert"
ET = timezone(timedelta(hours=-4))  # EDT on these dates (DST ends 2026-11-01)


def _et(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=ET).astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    calls: list[tuple] = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was reached")

    fake_alert = types.ModuleType("telegram_alert")
    fake_alert.send_telegram = boom
    fake_alert.record_operator_message = boom
    fake_system = types.ModuleType("scripts.lib.autonomy_watchdog.telegram_system")
    fake_system.send_system = boom
    fake_system.preview_send = boom
    for name, mod in (
        ("telegram_alert", fake_alert),
        ("scripts.telegram_alert", fake_alert),
        ("scripts.lib.autonomy_watchdog.telegram_system", fake_system),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    yield calls
    assert calls == []


class Capture:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return {"ok": True, "message_id": len(self.calls)}

    def p2(self) -> list[dict]:
        return [c for c in self.calls if c.get("kind") == "incident_p2_batch"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    ledger = state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    monkeypatch.delenv("TRADEAI_FANIN_COMMS_INTENT", raising=False)
    CoordinationLedger(ledger).close()  # the gateway creates the ledger; a lane never does
    return types.SimpleNamespace(state=state, ledger=ledger, tmp=tmp_path, sender=Capture())


def _queue(env, at: datetime, subject: str = "closed-loop alert: 3 outcomes regressed") -> dict:
    return H.queue_intent(
        producer=PRODUCER,
        domain=DOMAIN,
        kind=KIND,
        subject=subject,
        summary=subject,
        execution_id=f"x{int(at.timestamp())}",
        ledger_path=env.ledger,
        now=at.timestamp(),
    )


def _consume(env, at: datetime, *extra: str) -> int:
    return CLI.main(["--apply", *extra, "--ledger", str(env.ledger), "--state-root", str(env.state), "--now", at.isoformat()])


def _consumer_receipt(env) -> dict:
    return json.loads((env.state / "data" / "runtime" / "n8n-comms-intent-consumer_last.json").read_text())


def _incident(env) -> dict:
    conn = sqlite3.connect(f"{env.ledger.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute("SELECT * FROM comms_intent_incidents").fetchone())
    finally:
        conn.close()


def _fanin(env, at: datetime) -> list[dict]:
    """The fan-in's comms-intent fold (the real reader), written as an apply receipt the notifier accepts."""
    out: list[dict] = []
    fanin._comms_intent_findings(env.state, at, out)
    rows = [{**f, "state": "ARTIFACT_WRITTEN", "event_id": f"evt-{f['item']}"} for f in out]
    by: dict[str, int] = {}
    for r in rows:
        by[r["severity"]] = by.get(r["severity"], 0) + 1
    p = env.state / N.FANIN_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"schema": "N8nIncidentFanin@v1", "mode": "apply", "as_of": at.isoformat(), "open": len(rows),
             "by_severity": by, "incidents": rows}
        )
    )
    return rows


def _notify(env, at: datetime) -> dict:
    _fanin(env, at)
    rec = N.run(
        live=True,
        root=env.state,
        now=at,
        env={"TRADEAI_SERVED_SHA": "test-sha", "TRADEAI_INCIDENT_FLOOD_POLICY_MODE": "report_only"},
        sender=env.sender,
        ledger_path=env.tmp / "no_ledger.sqlite",
    )
    N.write_receipt(env.state, rec)
    return rec


def _mine(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("comms_intent_incident_key")]


# ── the two loss paths, end to end ──────────────────────────────────────────────────────────────────────────────────


def test_a_quiet_hours_intent_is_deferred_not_closed_and_leaves_once_at_0700(env):
    t0 = _et(16, 22, 30)
    assert _queue(env, t0)["duplicate"] is False
    assert _consume(env, t0) == 0
    key = _incident(env)["incident_key"]
    rec = _notify(env, t0 + timedelta(minutes=5))
    assert rec["p2_batch"]["held"] == "quiet_hours" and env.sender.p2() == []

    # Two hours on, past the 1 h window: before the fix this run CLOSED it and the fan-in dropped it, unsent.
    t2 = t0 + timedelta(hours=2)
    assert _consume(env, t2) == 0
    inc = _incident(env)
    assert inc["state"] == C.INC_DEFERRED and inc["closed_at"] is None and inc["deferred_since"] == t2.isoformat()
    s = _consumer_receipt(env)["summary"]
    assert s["closed"] == 0 and s["held_undelivered"] == 1
    assert s["delivery_evidence"]["notifier_state"] == "ok"  # the notifier wrote its state, with no record of it
    assert [r["comms_intent_incident_key"] for r in _mine(_fanin(env, t2))] == [key]

    # Still quiet at 06:55 ET: held again, consumer still DEFERRED.
    t655 = _et(17, 6, 55)
    assert _notify(env, t655)["p2_batch"]["held"] == "quiet_hours" and env.sender.p2() == []
    assert _consume(env, t655) == 0 and _incident(env)["state"] == C.INC_DEFERRED

    # 07:00 ET: the next allowed window. One P2 batch carries it.
    t7 = _et(17, 7, 0)
    rec = _notify(env, t7)
    assert [m["status"] for m in rec["messages"] if m["kind"] == "p2_batch"] == ["SENT"]
    assert len(env.sender.p2()) == 1 and DOMAIN in env.sender.p2()[0]["text"]
    assert key in rec["messages"][-1]["incident_keys"]

    # 07:05 ET: the notifier's per-key dedupe holds; the consumer now sees delivery and closes.
    t705 = t7 + timedelta(minutes=5)
    rec = _notify(env, t705)
    assert [m for m in rec["messages"] if m["kind"] == "p2_batch"] == [] and len(env.sender.p2()) == 1
    assert _consume(env, t705) == 0
    inc = _incident(env)
    assert (inc["state"], inc["close_reason"]) == ("CLOSED", "delivered")
    assert _consumer_receipt(env)["summary"]["closed"] == 1
    assert _mine(_fanin(env, t705)) == []
    # and stays closed: no second send on later passes
    _consume(env, t705 + timedelta(minutes=5))
    _notify(env, t705 + timedelta(minutes=40))
    assert len(env.sender.p2()) == 1 and _incident(env)["state"] == "CLOSED"


def test_a_capped_intent_is_deferred_and_sent_after_the_cap_day_resets(env):
    t0 = _et(16, 15, 0)
    st = {"schema": N.STATE_SCHEMA, "notified": {}, "sends_by_day": {"2026-10-16": 24}}
    (env.state / N.STATE_REL).parent.mkdir(parents=True, exist_ok=True)
    (env.state / N.STATE_REL).write_text(json.dumps(st))
    _queue(env, t0)
    assert _consume(env, t0) == 0
    key = _incident(env)["incident_key"]
    rec = _notify(env, t0 + timedelta(minutes=5))
    assert [m["status"] for m in rec["messages"] if m["kind"] == "p2_batch"] == ["CAPPED"] and env.sender.calls == []
    # past the window, cap still spent
    for t in (t0 + timedelta(hours=2), _et(16, 21, 0)):
        assert _consume(env, t) == 0 and _incident(env)["state"] == C.INC_DEFERRED
        rec = _notify(env, t)
        assert [m["status"] for m in rec["messages"] if m["kind"] == "p2_batch"] in (["CAPPED"], [])
    assert env.sender.calls == []
    # 00:10 ET: a new cap day, but quiet hours hold the P2 batch until 07:00
    t_mid = _et(17, 0, 10)
    assert _notify(env, t_mid)["p2_batch"]["held"] == "quiet_hours" and env.sender.calls == []
    assert _consume(env, t_mid) == 0 and _incident(env)["state"] == C.INC_DEFERRED
    t7 = _et(17, 7, 0)
    rec = _notify(env, t7)
    assert [m["status"] for m in rec["messages"] if m["kind"] == "p2_batch"] == ["SENT"]
    assert key in rec["messages"][-1]["incident_keys"] and len(env.sender.p2()) == 1
    assert _consume(env, t7 + timedelta(minutes=5)) == 0
    assert (_incident(env)["state"], _incident(env)["close_reason"]) == ("CLOSED", "delivered")


def test_a_delivered_intent_still_closes_at_the_window(env):
    t0 = _et(16, 12, 0)
    _queue(env, t0)
    assert _consume(env, t0) == 0
    assert [m["status"] for m in _notify(env, t0 + timedelta(minutes=5))["messages"]] == ["SENT"]
    assert _consume(env, t0 + timedelta(hours=2)) == 0
    assert (_incident(env)["state"], _incident(env)["close_reason"]) == ("CLOSED", "delivered")


# ── no evidence is never delivery ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("content", [None, "{not json", json.dumps({"schema": "Other@v9", "notified": {}})])
def test_absent_unreadable_or_foreign_notifier_state_holds_the_row(env, content):
    t0 = _et(16, 12, 0)
    _queue(env, t0)
    assert _consume(env, t0) == 0
    if content is not None:
        p = env.state / C.NOTIFIER_STATE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    assert _consume(env, t0 + timedelta(hours=3)) == 0
    assert _incident(env)["state"] == C.INC_DEFERRED
    ev = _consumer_receipt(env)["summary"]["delivery_evidence"]
    assert ev["notifier_state"] == {None: "absent", "{not json": "unreadable"}.get(content, "unrecognized")


def test_a_dry_run_reports_the_hold_and_writes_nothing(env, capsys):
    t0 = _et(16, 23, 0)
    _queue(env, t0)
    assert _consume(env, t0) == 0
    before = _incident(env)
    receipt = env.state / "data" / "runtime" / "n8n-comms-intent-consumer_last.json"
    mtime = receipt.stat().st_mtime_ns
    capsys.readouterr()
    t2 = t0 + timedelta(hours=2)
    assert CLI.main(["--dry-run", "--ledger", str(env.ledger), "--state-root", str(env.state), "--now", t2.isoformat()]) == 0
    out = capsys.readouterr().out
    assert before["incident_key"] in out and "would_hold_undelivered" in out
    assert _incident(env) == before and receipt.stat().st_mtime_ns == mtime


def test_a_deferred_row_folds_a_new_intent_in_the_same_generation(env):
    t0 = _et(16, 23, 0)
    _queue(env, t0)
    assert _consume(env, t0) == 0
    assert _consume(env, t0 + timedelta(hours=2)) == 0 and _incident(env)["state"] == C.INC_DEFERRED
    t3 = t0 + timedelta(hours=3)
    _queue(env, t3, subject="closed-loop alert: 4 outcomes regressed")
    assert _consume(env, t3) == 0
    inc = _incident(env)
    assert (inc["state"], inc["generation"], inc["count"]) == ("OPEN", 1, 2)
    assert inc["opened_at"] == t0.isoformat()  # delivery is still judged against the first undelivered opening
    assert _consumer_receipt(env)["summary"]["incidents_updated"] == 1


# ── the verdict, unit ──────────────────────────────────────────────────────────────────────────────────────────────


OPENED = datetime(2026, 10, 17, 2, 30, tzinfo=timezone.utc)


def _ev(rec: dict | None = None, acked: set | None = None) -> dict:
    return {"notified": {} if rec is None else {"inc-k": rec}, "acked_keys": acked or set()}


@pytest.mark.parametrize(
    "row,ev,expect",
    [
        ({"severity": "P3"}, _ev(), (True, "not_notifiable")),
        ({"severity": "P2"}, None, (False, "undelivered")),
        ({"severity": "P2"}, _ev(), (False, "undelivered")),
        ({"severity": "P2"}, _ev(acked={"inc-k"}), (True, "operator_ack")),
        ({"severity": "P2"}, _ev({"open": True}), (False, "undelivered")),
        ({"severity": "P2"}, _ev({"open": True, "last_notified_at": (OPENED + timedelta(hours=5)).isoformat()}),
         (True, "delivered")),
        # an older notice the operator still holds as open (no recovery since): the notifier's dedupe covers it
        ({"severity": "P2"}, _ev({"open": True, "last_notified_at": (OPENED - timedelta(hours=3)).isoformat()}),
         (True, "covered_by_open_notice")),
        # an older notice the operator was told recovered: this generation is new and undelivered
        ({"severity": "P2"}, _ev({"open": False, "last_notified_at": (OPENED - timedelta(hours=3)).isoformat(),
                                  "recovered_at": (OPENED - timedelta(hours=2)).isoformat()}), (False, "undelivered")),
        ({"severity": "P1"}, _ev({"open": True, "last_notified_at": (OPENED - timedelta(hours=3)).isoformat(),
                                  "recovered_at": (OPENED - timedelta(hours=2)).isoformat()}), (False, "undelivered")),
    ],
)
def test_delivery_verdict(row, ev, expect):
    assert C.delivery_verdict({"incident_key": "inc-k", "opened_at": OPENED.isoformat(), **row}, ev) == expect


def test_a_dry_run_notifier_receipt_never_counts_as_an_ack(tmp_path):
    p = tmp_path / C.NOTIFIER_RECEIPT_REL
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"mode": "dry-run", "acked_keys": ["inc-k"]}))
    ev = C.load_delivery_evidence(tmp_path)
    assert ev["acked_keys"] == set() and ev["receipt_status"] == "not_live"
    p.write_text(json.dumps({"mode": "live", "acked_keys": ["inc-k"]}))
    assert C.load_delivery_evidence(tmp_path)["acked_keys"] == {"inc-k"}


# ── pins + migration ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_notifier_file_literals_match_the_notifier():
    assert C.NOTIFIER_STATE_REL == N.STATE_REL
    assert C.NOTIFIER_RECEIPT_REL == N.RECEIPT_REL
    assert C.NOTIFIER_STATE_SCHEMA == N.STATE_SCHEMA
    assert C.NOTIFIABLE_SEVERITIES >= set(N.NOTIFY_SEVERITIES)


def test_connect_rw_adds_the_new_columns_to_an_existing_ledger(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(C.DDL)  # the 10-15 CREATE TABLE: the two columns are added by connect_rw, not by DDL
    conn.close()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(comms_intent_incidents)")}
    assert not {"close_reason", "deferred_since"} & cols
    C.connect_rw(path).close()
    C.connect_rw(path).close()  # idempotent
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(comms_intent_incidents)")}
    assert {"close_reason", "deferred_since"} <= cols


def test_the_consumption_module_still_never_imports_a_sender():
    src = (ROOT / "scripts" / "lib" / "n8n_comms_intent_consumption.py").read_text()
    for banned in ("telegram", "incident_notifier", "send_system", "subprocess", "urllib", "requests"):
        assert f"import {banned}" not in src and f"from scripts import {banned}" not in src
