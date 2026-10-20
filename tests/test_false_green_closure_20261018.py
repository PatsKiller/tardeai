"""External review 2026-10-18 (against main 3af0a8bdd; re-verified on baeda8d16): source-level false-green defects.

One section per finding. Each section's first test reproduces the reviewer's case against the pre-fix code (red),
then pins the fixed behaviour (green).

This file covers the notification findings only. M1 (SIEM resolution), M2 (critical enrollment past the cap), M3
(supervisor restart budget) and F1-F4 (Claude fixer acceptance) were closed on main by separately reviewed
implementations (0fa3ea614, d06f7a11b, 5fef53c66) with their own suites; they are not re-tested here.

N1  Incident notifier: fan-in disappearance (e.g. a delivered comms notice expiring) was announced "SYSTEM RECOVERED"
    without business-output evidence.
N2  send_system recorded only ``delivered`` in Communications; the provider message id came from an ambient store.
N3  Communications delivery health was counted from the latest 500 rows; a missing payload rendered zero.
Doc truth: the diagnosis cadence in docs/ops/n8n_self_healing.md matches the declared schedule.

Hermetic: tmp ledgers / state roots, in-memory DB doubles, monkeypatched transport. No network, no live DB, no
broker, no Telegram.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: A live run whose receipt met its useful-output contract (scripts/lib/recovery_validator).
LIVE_PRODUCED = {"mode": "live", "output_verdict": {"verdict": "produced"}}

# ══ N1 — notification settlement is not recovery ════════════════════════════════════════════════════════════════════

def _notifier():
    from scripts import incident_notifier as N
    return N


T0 = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)


def _fanin(N, root: Path, rows, *, as_of):
    p = root / N.FANIN_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    by: dict = {}
    for r in rows:
        by[r["severity"]] = by.get(r["severity"], 0) + 1
    p.write_text(json.dumps({"schema": "N8nIncidentFanin@v1", "mode": "apply", "as_of": as_of.isoformat(),
                             "open": len(rows), "by_severity": by, "incidents": rows}))


def _inc(source, item, sev, **kw):
    return {"source": source, "item": item, "severity": sev, "detail": "d", "detected_at": T0.isoformat(),
            "event_id": f"evt-{source}-{item}", "state": "ARTIFACT_WRITTEN", **kw}


class _Cap:
    def __init__(self):
        self.calls = []

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return {"ok": True, "message_id": len(self.calls)}


def _notify(N, root, now, cap, ledger):
    return N.run(live=True, root=root, now=now, env={"TRADEAI_SERVED_SHA": "t"}, sender=cap, previewer=None,
                 ledger_path=ledger)


def test_N1_reviewer_case_a_settled_comms_notice_is_not_announced_as_system_recovered(tmp_path):
    N = _notifier()
    led = tmp_path / "no_ledger.sqlite"
    comms = _inc("n8n_comms_intent", "wf123:digest", "P1")
    _fanin(N, tmp_path, [comms], as_of=T0)
    cap = _Cap()
    _notify(N, tmp_path, T0, cap, led)
    t = T0 + timedelta(minutes=5)
    _fanin(N, tmp_path, [], as_of=t)                    # the delivered notice expired: it left the fan-in
    rec = _notify(N, tmp_path, t, cap, led)
    assert [m["kind"] for m in rec["messages"]] == ["recovery"]
    text = cap.calls[-1]["text"]
    assert "RECOVERED" not in text, text
    assert text.startswith("TRADE AI SYSTEM NOTICE SETTLED — 1 incident(s) no longer reported at P1/P2")
    assert rec["messages"][0]["settlement"] == {"verified_recovered": 0, "settled_unverified": 1}
    st = json.loads((tmp_path / N.STATE_REL).read_text())["notified"][N.incident_key("n8n_comms_intent",
                                                                                    "wf123:digest")]
    assert st["open"] is False and st["settlement"] == "no_longer_reported" and st["recovery_verified"] is False


def _runs_ledger(path: Path, runs):
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
              "requested_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, receipt_json TEXT)")
    for r in runs:
        c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (r["run_id"], r["lane_id"], r["mode"], r["state"], "t", r["finished_at"], r["finished_at"],
                   r["exit_code"], 1.0, json.dumps(r["receipt"])))
    c.commit()
    c.close()


def test_N1_recovered_wording_requires_a_verified_live_output_run(tmp_path):
    N = _notifier()
    led = tmp_path / "ledger.sqlite"
    lane_inc = _inc("runs", "lane-x:RUN_FAILED", "P1", lane="lane-x", event_type="RUN_FAILED")
    _fanin(N, tmp_path, [lane_inc], as_of=T0)
    cap = _Cap()
    _notify(N, tmp_path, T0, cap, tmp_path / "none.sqlite")
    t = T0 + timedelta(minutes=10)
    fin = (T0 + timedelta(minutes=5)).isoformat()
    # a dry run after the page is NOT recovery evidence
    _runs_ledger(led, [{"run_id": "r-dry", "lane_id": "lane-x", "mode": "dry_run", "state": "RUN_DONE",
                        "finished_at": fin, "exit_code": 0,
                        "receipt": {"mode": "dry_run", "output_verdict": {"verdict": "produced"}}}])
    _fanin(N, tmp_path, [], as_of=t)
    rec = _notify(N, tmp_path, t, _Cap(), led)
    assert "RECOVERED" not in rec["messages"][0]["text"]
    # a fresh state: the same clear with a verified live output run is a real recovery
    root2 = tmp_path / "s2"
    root2.mkdir()
    _fanin(N, root2, [lane_inc], as_of=T0)
    _notify(N, root2, T0, _Cap(), tmp_path / "none.sqlite")
    led2 = tmp_path / "ledger2.sqlite"
    _runs_ledger(led2, [{"run_id": "r-live", "lane_id": "lane-x", "mode": "live", "state": "RUN_DONE",
                         "finished_at": fin, "exit_code": 0, "receipt": LIVE_PRODUCED}])
    _fanin(N, root2, [], as_of=t)
    cap2 = _Cap()
    rec = _notify(N, root2, t, cap2, led2)
    assert cap2.calls[-1]["text"].startswith("TRADE AI SYSTEM RECOVERED — 1 incident(s) recovered (verified output)")
    assert "run r-live" in cap2.calls[-1]["text"]


# ══ N2 — explicit provider message id into the Communications record ════════════════════════════════════════════════

def _alert_modules():
    import importlib
    mods = []
    for name in ("telegram_alert", "scripts.telegram_alert"):
        try:
            mods.append(importlib.import_module(name))
        except Exception:  # noqa: BLE001
            pass
    return mods


def _transport_modules():
    import importlib
    mods = []
    for name in ("telegram_transport", "scripts.telegram_transport"):
        try:
            mods.append(importlib.import_module(name))
        except Exception:  # noqa: BLE001
            pass
    return mods


SEND_ENV = {"TELEGRAM_BOT_TOKEN": "t0k", "TELEGRAM_CHAT_ID": "42", "SYSTEM_TELEGRAM_ENABLED": "1"}


def test_N2_reviewer_case_send_system_passes_the_provider_message_id_it_received(tmp_path, monkeypatch):
    from scripts.lib.autonomy_watchdog import telegram_system as TS

    for m in _transport_modules():
        monkeypatch.setattr(m, "deliver_text", lambda **k: {"ok": True, "message_id": 777, "status_code": 200},
                            raising=False)
    seen = []
    for m in _alert_modules():
        monkeypatch.setattr(m, "record_operator_message", lambda text, **k: seen.append(k) or {"ok": True})
    rec = TS.send_system("hello", identity="id-n2", kind="test", root=tmp_path, env=dict(SEND_ENV))
    assert rec["ok"] and rec["message_id"] == 777
    assert seen and seen[0].get("provider_message_id") == "777" and seen[0].get("delivered") is True


def test_N2_comms_record_uses_the_explicit_id_never_the_ambient_store(monkeypatch):
    mods = _alert_modules()
    TA = mods[0]
    settled = []

    class _Pub:
        delivery_ids = ["d-1"]

    import scripts.lib.comms.client as CL
    import scripts.lib.comms.delivery as DL
    monkeypatch.setattr(CL, "publish_communication", lambda ev: _Pub())
    monkeypatch.setattr(DL, "settle_delivery", lambda did, **k: settled.append((did, k)))
    monkeypatch.setattr(TA, "_tag_outbound", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(TA, "last_message_ids", lambda: ["999-stale"])
    TA._best_effort_comms_publish("x", message_class="ops", producer="p", delivered=True, provider_message_id="777")
    assert settled and settled[0][1]["provider_message_id"] == "777" and settled[0][1]["status"] == "SENT"
    settled.clear()
    # an explicit "no id" is LEGACY_DELIVERED, never the stale ambient id
    TA._best_effort_comms_publish("x", message_class="ops", producer="p", delivered=True, provider_message_id=None)
    assert settled[0][1]["provider_message_id"] is None and settled[0][1]["status"] == "LEGACY_DELIVERED"


def test_N2_a_reconciliation_failure_is_recorded_on_the_send(tmp_path, monkeypatch):
    from scripts.lib.autonomy_watchdog import telegram_system as TS
    from scripts.lib.autonomy_watchdog.heartbeat import paths

    for m in _transport_modules():
        monkeypatch.setattr(m, "deliver_text", lambda **k: {"ok": True, "message_id": 778, "status_code": 200},
                            raising=False)
    for m in _alert_modules():
        monkeypatch.setattr(m, "record_operator_message",
                            lambda text, **k: {"ok": False, "errors": ["settle SENT failed for d-1: OperationalError"]})
    rec = TS.send_system("hello", identity="id-n2b", kind="test", root=tmp_path, env=dict(SEND_ENV))
    assert rec["comms_record"]["ok"] is False and "OperationalError" in rec["comms_record"]["errors"][0]
    last = json.loads(Path(paths(tmp_path)["system_sends"]).read_text().splitlines()[-1])
    assert last["comms_record"]["ok"] is False


# ══ N3 — Communications delivery health from a server-side count ════════════════════════════════════════════════════

def test_N3_reviewer_case_unavailable_db_is_unavailable_not_zero(monkeypatch):
    import communications_portal as CP

    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: None)
    s = CP.delivery_summary()
    assert s["status"] == "UNAVAILABLE" and s["unsettled"] is None and s["failed"] is None and s["ok"] is False


class _Cur:
    def __init__(self, row, cols):
        self.row, self.description = row, [(c,) for c in cols]
        self.sql = None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


def test_N3_counts_and_oldest_age_come_from_one_server_side_aggregate(monkeypatch):
    import communications_portal as CP

    as_of = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    cols = ["unsettled", "failed", "total", "oldest_unsettled_at", "as_of"]
    cur = _Cur((1234, 7, 90000, as_of - timedelta(hours=3), as_of), cols)
    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: _Conn(cur))
    s = CP.delivery_summary()
    assert s["status"] == "OK" and s["unsettled"] == 1234 and s["failed"] == 7 and s["total"] == 90000
    assert s["oldest_unsettled_age_s"] == 3 * 3600 and s["basis"] == "server_side_aggregate"
    assert "LIMIT" not in cur.sql.upper() and "COUNT(*)" in cur.sql.upper()
    # a failing query is UNAVAILABLE with the error, never zero
    class _Boom(_Cur):
        def execute(self, sql, params=None):
            raise RuntimeError("relation does not exist")
    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: _Conn(_Boom(None, cols)))
    s = CP.delivery_summary()
    assert s["status"] == "UNAVAILABLE" and s["unsettled"] is None and "RuntimeError" in s["error"]


def test_N3_route_and_frontend_use_the_summary_not_the_500_row_sample():
    api = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/communications/deliveries/summary": _communications_delivery_summary' in api
    page = (ROOT / "apps/command-center-v3/src/pages/CommunicationsHub.tsx").read_text(encoding="utf-8")
    assert "/api/v2/communications/deliveries/summary" in page and "deliveryHealthFrom(" in page
    assert "counts.RESERVED" not in page                  # no client-side count over the latest-500 sample
    pkg = (ROOT / "apps/command-center-v3/package.json").read_text(encoding="utf-8")
    assert "src/lib/commsDeliveryHealth.test.ts" in pkg


# ══ Doc truth — the diagnosis cadence ═══════════════════════════════════════════════════════════════════════════════

def test_doc_diagnosis_cadence_matches_the_declared_schedule():
    doc = (ROOT / "docs" / "ops" / "n8n_self_healing.md").read_text(encoding="utf-8")
    assert "every 5 min" not in doc
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r.get("lane_id") == "n8n-failure-diagnosis")
    line = json.dumps(row)
    assert "3-59/15" in line and "--max-incidents 3" in line
    assert "every 15 min" in doc and "at most 3" in doc
