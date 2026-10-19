"""External review 2026-10-18 (against main 3af0a8bdd; re-verified on baeda8d16): source-level false-green defects.

One section per finding. Each section's first test reproduces the reviewer's case against the pre-fix code (red),
then pins the fixed behaviour (green).

M1  SIEM bridge resolved a live RUN_FAILED on "latest decisive run is good" — a later diagnostic dry run, or a live
    request the stage clamp executed dry, closed it. Resolution now goes through scripts/lib/recovery_validator with
    the failed run's lane, effective mode, slot, time and the useful-output contract.
M2  Failure diagnosis: an incident marked ``not_this_cycle`` (per-cycle / daily cap) skipped critical P1 enrollment.
M3  Supervisor L1 restart cap read the window once and never counted restarts issued in the same cycle.
N1  Incident notifier: fan-in disappearance (e.g. a delivered comms notice expiring) was announced "SYSTEM RECOVERED"
    without business-output evidence.
N2  send_system recorded only ``delivered`` in Communications; the provider message id came from an ambient store.
N3  Communications delivery health was counted from the latest 500 rows; a missing payload rendered zero.
F1  Fixer PR-head acceptance: no required checks by default; SKIPPED/NEUTRAL passed.
F2  advance() moved a merged PR to fix_deployed although acceptance was rejected.
F3  Red-first accepted any non-zero pytest exit (collection error, timeout, usage error). Now: a valid run (exit 1, no
    ERROR entries) where a changed test failed on its assertion or on the defect's own exception — never on its
    scaffolding (ImportError / NameError / SyntaxError / missing fixture / a module attribute only the fix adds).
F4  Missing / malformed CLI usage became zero cost.

Hermetic: tmp ledgers / state roots, in-memory DB doubles, monkeypatched subprocess / transport. No network, no
live DB, no broker, no Telegram.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_siem_bridge as B  # noqa: E402
from tests.test_n8n_siem_bridge_20261010 import NOW as SIEM_NOW, FakeDB, env, fanin_doc, run_row  # noqa: E402,F401

assert env  # the imported pytest fixture (used by name below)


# ══ M1 — SIEM bridge resolution through the shared recovery validator ═══════════════════════════════════════════════

def _siem_run(n, *, state="RUN_DONE", mode="live", receipt, minutes_ago, lane="lane-b", wf="wfB"):
    ts = (SIEM_NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {"run_id": f"n8n-wf-{wf}-{n}", "lane_id": lane, "mode": mode, "state": state,
            "requested_by": f"n8n:workflow:{wf}", "requested_at": ts, "finished_at": ts,
            "exit_code": 0 if state == "RUN_DONE" else 1, "duration_s": 1.0, "receipt": receipt}


CLAMPED_DRY = {"mode": "dry_run", "requested_mode": "live", "output_verdict": {"verdict": "produced"},
               "stage_clamp": {"requested_mode": "live", "effective_mode": "dry_run", "stage": "shadow",
                               "clamped": True}}
LIVE_PRODUCED = {"mode": "live", "output_verdict": {"verdict": "produced"}}


def _open_failure(env):
    env["setup"]([run_row(1, "lane-b", "RUN_FAILED", minutes_ago=10, wf="wfB")], fanin_doc([]))
    db = FakeDB()
    env["run"](db, "--apply")
    assert [(r["event_type"], r["lifecycle_state"]) for r in db.rows] == [("RUN_FAILED", "active")]
    return db


@pytest.mark.parametrize("later", [
    _siem_run(2, receipt=CLAMPED_DRY, minutes_ago=1),                                  # live request, executed dry
    _siem_run(2, mode="dry_run", receipt={"mode": "dry_run", "output_verdict": {"verdict": "produced"}},
              minutes_ago=1),                                                          # a diagnostic dry run
    _siem_run(2, receipt={"mode": "live"}, minutes_ago=1),                             # live, output contract unproven
], ids=["clamped_live_request", "diagnostic_dry_run", "live_without_output_verdict"])
def test_M1_reviewer_case_a_later_dry_or_unproven_run_never_resolves_a_live_run_failed(env, later):
    db = _open_failure(env)
    env["setup"]([run_row(1, "lane-b", "RUN_FAILED", minutes_ago=10, wf="wfB"), later], fanin_doc([]))
    assert env["run"](db, "--apply") == 0
    assert db.rows[0]["lifecycle_state"] == "active", db.rows[0]


def test_M1_a_live_run_that_met_its_output_contract_resolves_it_and_names_the_validator(env):
    db = _open_failure(env)
    env["setup"]([run_row(1, "lane-b", "RUN_FAILED", minutes_ago=10, wf="wfB"),
                  _siem_run(2, receipt=LIVE_PRODUCED, minutes_ago=1)], fanin_doc([]))
    assert env["run"](db, "--apply") == 0
    assert db.rows[0]["lifecycle_state"] == "resolved"
    assert "recovery_validator" in db.rows[0]["action_taken"] and "n8n-wf-wfB-2" in db.rows[0]["action_taken"]


def test_M1_a_good_run_older_than_the_failure_never_resolves_it():
    failed = _siem_run(5, state="RUN_FAILED", receipt={"mode": "live"}, minutes_ago=5)
    older = _siem_run(4, receipt=LIVE_PRODUCED, minutes_ago=30)
    row = {"id": 7, "component": "n8n:lane-b", "event_type": "RUN_FAILED", "severity": "WARN",
           "message": "[n8n] lane=lane-b kind=RUN_FAILED run=n8n-wf-wfB-5 at=x", "lifecycle_state": "active"}
    for r in (failed, older):
        r["receipt_json"] = json.dumps(r.pop("receipt"))
    p = B.plan({}, [row], env="e", good_lanes={"lane-b"}, ledger_ok=True, fanin_ok=True,
               ledger_runs=[failed, older])
    assert p["resolve"] == [] and p["hold"][0]["reason"].startswith("not_recovered:")
    # the plan without ledger runs (no evidence) resolves nothing: fail closed
    p = B.plan({}, [row], env="e", good_lanes={"lane-b"}, ledger_ok=True, fanin_ok=True)
    assert p["resolve"] == []


# ══ M2 — critical enrollment independent of the diagnosis cap ═══════════════════════════════════════════════════════

def test_M2_reviewer_case_a_capped_critical_incident_is_still_enrolled_at_p1(tmp_path):
    from scripts import n8n_failure_diagnosis as D

    now = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
    capped = {"lane": "lane-x", "signature": "sig-c", "episode": 1, "incident_key": "kc9", "siem_id": 91,
              "severity": "CRITICAL", "event_type": "RUN_FAILED", "outcome": "not_this_cycle",
              "reason": "process_daily_cap"}
    warn = {**capped, "incident_key": "kw9", "siem_id": 92, "signature": "sig-w", "severity": "WARN",
            "reason": "max_incidents"}
    state = D.empty_state()
    D.apply_results({"results": [capped, warn]}, [], state, {}, now=now, store_factory=object, allowlist={},
                    root=tmp_path)
    p1 = [e for e in (state.get("escalations") or {}).values() if e["priority"] == "P1"]
    assert len(p1) == 1 and p1[0]["siem_ids"] == [91] and p1[0]["route"] == "operator_once"
    assert p1[0]["reason"].startswith("critical_unresolved:")
    assert capped["escalation"].startswith("P1:")
    # the capped incident is NOT marked diagnosed (it is retried next cycle) and the WARN one is not paged
    assert "kc9" not in (state.get("diagnosed") or {}) and "kw9" not in (state.get("diagnosed") or {})
    # idempotent: the next capped cycle keeps ONE record with its original time (no repeat page)
    first_at = p1[0]["at"]
    D.apply_results({"results": [dict(capped)]}, [], state, {}, now=now + timedelta(minutes=15),
                    store_factory=object, allowlist={}, root=tmp_path)
    p1 = [e for e in state["escalations"].values() if e["priority"] == "P1"]
    assert len(p1) == 1 and p1[0]["at"] == first_at


# ══ M3 — supervisor L1 restart cap is reserved per action ═══════════════════════════════════════════════════════════

def _sbd():
    import supervisor_breach_detector as sbd
    return sbd


def test_M3_reviewer_case_two_breaches_and_one_prior_attempt_issue_only_one_restart(tmp_path, monkeypatch):
    sbd = _sbd()
    now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    rt = tmp_path / "rt"
    rt.mkdir()
    prior = {"schema": "Recovery@v1", "ts": (now - timedelta(minutes=3)).isoformat(), "lane_id": "L",
             "level": 1, "executed": True, "rc": 0}
    (rt / "supervisor_recoveries.jsonl").write_text(json.dumps(prior) + "\n")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or
                        type("CP", (), {"returncode": 0, "stderr": ""})())
    lanes = [{"lane_id": "L", "state": "ACTIVE", "scheduler": {"kind": "systemd", "expression": "tradeai-l.timer"}}]
    rows = [{"breach_id": "b1", "lane_id": "L", "kind": "SILENT"}, {"breach_id": "b2", "lane_id": "L", "kind": "HUNG"}]
    out = sbd._self_heal_l1_l2(rows, lanes, {}, now, rt, live=True)
    assert len(calls) == 1 and out["l1_executed"] == 1           # 1 prior + 1 now = the cap of 2 per window
    recs = [json.loads(x) for x in (rt / "supervisor_recoveries.jsonl").read_text().splitlines()][1:]
    assert [r["would_execute"] for r in recs] == [True, False]
    assert recs[1]["executed"] is False and recs[1]["requested"] is False and recs[1]["cap_reason"].startswith("cap")
    # requested / command-succeeded / output-recovered are three separate facts
    assert recs[0]["requested"] is True and recs[0]["command_succeeded"] is True
    assert recs[0]["output_recovered"] is None and recs[0]["output_recovered_basis"] == "not_verified_by_supervisor"


def test_M3_a_failed_restart_command_counts_against_the_cap_and_is_not_success(tmp_path, monkeypatch):
    sbd = _sbd()
    now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    rt = tmp_path / "rt"
    rt.mkdir()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("CP", (), {"returncode": 1, "stderr": "boom"})())
    lanes = [{"lane_id": "L", "state": "ACTIVE", "scheduler": {"kind": "systemd", "expression": "tradeai-l.service"}}]
    rows = [{"breach_id": f"b{i}", "lane_id": "L", "kind": "SILENT"} for i in range(3)]
    sbd._self_heal_l1_l2(rows, lanes, {}, now, rt, live=True)
    recs = [json.loads(x) for x in (rt / "supervisor_recoveries.jsonl").read_text().splitlines()]
    assert [r["requested"] for r in recs] == [True, True, False]
    assert all(r.get("command_succeeded") is False for r in recs[:2])
    # shadow mode reserves the same way (what WOULD run respects the cap within the cycle)
    rt2 = tmp_path / "rt2"
    rt2.mkdir()
    sbd._self_heal_l1_l2(rows, lanes, {}, now, rt2, live=False)
    recs = [json.loads(x) for x in (rt2 / "supervisor_recoveries.jsonl").read_text().splitlines()]
    assert [r["would_execute"] for r in recs] == [True, True, False]


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


# ══ F1-F4 — Claude fixer acceptance ═════════════════════════════════════════════════════════════════════════════════

from scripts import self_heal_fixer as S  # noqa: E402

# The fixer imports its libraries as ``lib.*`` (scripts/ on sys.path): use THOSE module objects so a monkeypatch
# reaches the code under test.
E = S.E
F = S.F

CFG = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
H = "a" * 40


def _chk(name, conclusion="SUCCESS", status="COMPLETED"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def test_F1_reviewer_case_no_required_profile_and_skipped_checks_are_not_a_pass():
    pr = {"headRefOid": H, "statusCheckRollup": [_chk("lint", "SKIPPED")]}
    assert E.pr_head_verdict(pr, expected_head=H)["verdict"] != "pass"          # no profile: never green
    req = ["cio-hardening"]
    skipped = {"headRefOid": H, "statusCheckRollup": [_chk("cio-hardening", "SKIPPED")]}
    neutral = {"headRefOid": H, "statusCheckRollup": [_chk("cio-hardening", "NEUTRAL")]}
    assert E.pr_head_verdict(skipped, expected_head=H, required=req)["verdict"] != "pass"
    assert E.pr_head_verdict(neutral, expected_head=H, required=req)["verdict"] != "pass"
    ok = {"headRefOid": H, "statusCheckRollup": [_chk("cio-hardening"), _chk("optional-x", "SKIPPED")]}
    assert E.pr_head_verdict(ok, expected_head=H, required=req)["verdict"] == "pass"


def test_F1_the_required_check_profile_is_versioned_config():
    prof = E.required_checks(CFG)
    assert prof["version"] and prof["names"] == ["agent-governance", "cio-hardening", "release-readiness"]
    with pytest.raises(ValueError):
        E.required_checks({"acceptance": {"required_checks": {"version": "x", "names": []}}})
    with pytest.raises(ValueError):
        E.required_checks({})


def _merged_job(tmp_path, monkeypatch, rollup):
    merge = "b" * 40
    cur = tmp_path / "GIT_SHA"
    cur.write_text(merge + "\n")
    cfg = json.loads(json.dumps(CFG))
    cfg["lifecycle"]["release_current_sha_file"] = str(cur)
    monkeypatch.setattr(S, "git", lambda repo, *a, **k: {"rc": 0, "out": "", "err": ""})
    job = {"job_id": "j", "lane": "l", "state": F.FIX_PR_OPENED, "pr_number": 9, "history": [], "head_sha": H,
           "iterations": [{"passed": True, "acceptance": {"accepted": True, "commit_sha": H}}]}
    doc = {"state": "MERGED", "mergeCommit": {"oid": merge}, "mergedAt": "2026-10-18T17:00:00Z", "headRefOid": H,
           "statusCheckRollup": rollup}
    gh = lambda cmd: {"rc": 0, "out": json.dumps(doc)}
    return job, cfg, gh


ALL_REQUIRED = [_chk("agent-governance"), _chk("cio-hardening"), _chk("release-readiness")]


def test_F2_reviewer_case_merged_with_rejected_acceptance_is_never_attributed(tmp_path, monkeypatch):
    job, cfg, gh = _merged_job(tmp_path, monkeypatch, [_chk("agent-governance"), _chk("cio-hardening", "FAILURE"),
                                                       _chk("release-readiness")])
    got = S.advance(job, cfg=cfg, now=datetime(2026, 10, 18, tzinfo=timezone.utc), diag_state=None, root=tmp_path,
                    gh=gh, repo=tmp_path)
    assert got != F.FIX_DEPLOYED and job["state"] != F.FIX_DEPLOYED
    assert job["state"] == F.FIX_CLOSED and job["reason"].startswith("merged_without_acceptance")


def test_F2_pending_required_checks_wait_and_full_acceptance_deploys(tmp_path, monkeypatch):
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    job, cfg, gh = _merged_job(tmp_path, monkeypatch, [_chk("agent-governance"), _chk("cio-hardening")])
    assert S.advance(job, cfg=cfg, now=now, diag_state=None, root=tmp_path, gh=gh, repo=tmp_path) is None
    assert job["state"] == F.FIX_PR_OPENED                         # release-readiness missing: wait, not deploy
    job, cfg, gh = _merged_job(tmp_path, monkeypatch, ALL_REQUIRED)
    assert S.advance(job, cfg=cfg, now=now, diag_state=None, root=tmp_path, gh=gh, repo=tmp_path) == F.FIX_DEPLOYED
    assert job["acceptance"]["accepted"] is True and job["acceptance"]["required_profile"]


def _fake_attempt(tmp_path, monkeypatch, *, red, agent_out="{}"):
    monkeypatch.setattr(F, "build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(F, "backend_argv", lambda *a, **k: ["agent"])
    a = S.Attempt.__new__(S.Attempt)
    a.cfg, a.ev, a.dir, a.backend, a.boundary = CFG, {}, tmp_path, "claude_code", {}
    a.pytest_cmd, a.py, a.base, a.eval_root = "pytest", "python3", "c" * 40, tmp_path / "ev"
    cand = {"commit_sha": H, "tree_sha": "d" * 40, "base_sha": a.base}
    a.run_agent = lambda argv, prompt: ({"rc": 0, "out": agent_out, "err": ""}, None)
    a.candidate = lambda: cand
    a.commit_diff = lambda c: {"name_status": "M\ttests/test_bug.py\nM\tscripts/bug.py\n",
                               "numstat": "1\t0\ttests/test_bug.py\n1\t0\tscripts/bug.py\n", "unified": "",
                               "full": "diff"}
    a.guard = lambda d: []
    a.tree_of = lambda c: "d" * 40
    a._blob = lambda c, p: b""
    a.checkout = lambda name, sha, overlay=None: tmp_path

    def eval_run(kind, co, expect, argv, timeout, overlay_from=None):
        base = {"run_id": f"{kind}-1", "kind": kind, "integrity_ok": True, "checkout_sha": expect,
                "head_after": expect, "overlay_from": overlay_from, "seconds": 0.1}
        if kind == "red_first":
            return {**base, **red}
        return {**base, "rc": 0, "out": "1 passed", "err": ""}
    a.eval_run = eval_run
    return a


@pytest.mark.parametrize("red,why", [
    ({"rc": 2, "out": "ERROR tests/test_bug.py - ImportError: cannot import name 'x'\n1 error", "err": ""},
     "collection_error"),
    ({"rc": 124, "out": "", "err": "timeout after 900s"}, "timeout"),
    ({"rc": 4, "out": "ERROR: file or directory not found: tests/test_bug.py", "err": ""}, "usage"),
    ({"rc": 1, "out": "FAILED tests/test_other.py::test_unrelated - assert 0", "err": ""}, "other_test"),
    ({"rc": 1, "out": "FAILED tests/test_bug.py::test_bug - ModuleNotFoundError: No module named 'q'", "err": ""},
     "not_an_assertion"),
])
def test_F3_reviewer_case_red_first_needs_the_expected_tests_own_failure(tmp_path, monkeypatch, red, why):
    a = _fake_attempt(tmp_path, monkeypatch, red=red)
    rec = a.iterate(1, None, "rails", 0.0)
    assert rec["red_first"] is False, why
    assert "red_first:test_passes_on_base" in rec["failing"] or any(f.startswith("red_first:")
                                                                    for f in rec["failing"])


def test_F3_a_real_assertion_failure_of_the_changed_test_is_red_first(tmp_path, monkeypatch):
    red = {"rc": 1, "out": "FAILED tests/test_bug.py::test_bug - assert 1 == 2\n1 failed", "err": ""}
    rec = _fake_attempt(tmp_path, monkeypatch, red=red).iterate(1, None, "rails", 0.0)
    assert rec["red_first"] is True and not any(f.startswith("red_first:") for f in rec["failing"])
    ok, why = F.red_first_verdict(red, ["tests/test_bug.py"])
    assert ok and why == "assertion_failed:tests/test_bug.py::test_bug"
    # the defect's own exception in the code under test reproduces it (the seeded ZeroDivisionError scenario of
    # tests/test_self_heal_fixer_20261016.py); the test's scaffolding failing on base does not
    crash = {"rc": 1, "out": "FAILED tests/test_bug.py::test_bug - ZeroDivisionError: division by zero", "err": ""}
    assert F.red_first_verdict(crash, ["tests/test_bug.py"]) == (
        True, "defect_exception:ZeroDivisionError:tests/test_bug.py::test_bug")
    for reason in ("AttributeError: module 'scripts.bug' has no attribute 'new_fn'", "NameError: name 'x' is not "
                   "defined", "ImportError: cannot import name 'y'"):
        bad = {"rc": 1, "out": f"FAILED tests/test_bug.py::test_bug - {reason}", "err": ""}
        assert F.red_first_verdict(bad, ["tests/test_bug.py"])[0] is False, reason


REAL_RED = """F                                                                        [100%]
=================================== FAILURES ===================================
___________________________ test_ratio_handles_zero ____________________________

    def test_ratio_handles_zero():
        from scripts.buggy import ratio
>       assert ratio(1, 0) == 0.0
               ^^^^^^^^^^^

tests/test_self_heal_buggy.py:3:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

a = 1, b = 0

    def ratio(a, b):
>       return a / b
               ^^^^^
E       ZeroDivisionError: division by zero

scripts/buggy.py:2: ZeroDivisionError
=========================== short test summary info ============================
FAILED tests/test_self_heal_buggy.py::test_ratio_handles_zero - ZeroDivisionE...
1 failed in 0.02s
"""


def test_F3_real_pytest_output_with_a_width_truncated_summary_is_judged_from_its_failure_section():
    """Captured from the seeded-defect scenario of tests/test_self_heal_fixer_20261016.py on this host: the summary
    reason is cut to 80 columns; the FAILURES section carries the real exception."""
    t = ["tests/test_self_heal_buggy.py"]
    assert F.red_first_verdict({"rc": 1, "out": REAL_RED}, t) == (
        True, "defect_exception:ZeroDivisionError:tests/test_self_heal_buggy.py::test_ratio_handles_zero")
    scaffold = REAL_RED.replace("ZeroDivisionError: division by zero", "ImportError: cannot import name 'ratio'") \
        .replace("scripts/buggy.py:2: ZeroDivisionError", "tests/test_self_heal_buggy.py:2: ImportError")
    assert F.red_first_verdict({"rc": 1, "out": scaffold}, t)[0] is False
    # what this host's harness actually produced before the fix: "No module named pytest" (exit 1) was "red"
    assert F.red_first_verdict({"rc": 1, "out": "", "err": "/usr/bin/python3: No module named pytest"}, t) == (
        False, "no_failed_test_reported")


@pytest.mark.parametrize("out", ["garbage, not json", json.dumps({"type": "result", "is_error": False}),
                                 json.dumps({"type": "result", "total_cost_usd": "n/a"})])
def test_F4_reviewer_case_unknown_usage_keeps_the_conservative_reservation(tmp_path, monkeypatch, out):
    r = F.parse_claude_result(out)
    assert r["cost_usd"] is None and r["cost_known"] is False
    red = {"rc": 1, "out": "FAILED tests/test_bug.py::test_bug - assert 0", "err": ""}
    rec = _fake_attempt(tmp_path, monkeypatch, red=red, agent_out=out).iterate(1, None, "rails", 0.0)
    budget = float(CFG["iteration"]["per_iteration_budget_usd"])
    assert rec["cost_unknown"] is True and rec["charged_usd"] == budget
    assert S.iteration_charge(rec) == budget


def test_F4_known_usage_is_charged_as_reported(tmp_path, monkeypatch):
    out = json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.5, "result": "ok"})
    red = {"rc": 1, "out": "FAILED tests/test_bug.py::test_bug - assert 0", "err": ""}
    rec = _fake_attempt(tmp_path, monkeypatch, red=red, agent_out=out).iterate(1, None, "rails", 0.0)
    assert rec["cost_unknown"] is False and rec["charged_usd"] == 0.5 and S.iteration_charge(rec) == 0.5


# ══ Doc truth — the diagnosis cadence ═══════════════════════════════════════════════════════════════════════════════

def test_doc_diagnosis_cadence_matches_the_declared_schedule():
    doc = (ROOT / "docs" / "ops" / "n8n_self_healing.md").read_text(encoding="utf-8")
    assert "every 5 min" not in doc
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r.get("lane_id") == "n8n-failure-diagnosis")
    line = json.dumps(row)
    assert "3-59/15" in line and "--max-incidents 3" in line
    assert "every 15 min" in doc and "at most 3" in doc
