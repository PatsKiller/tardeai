"""Incident fan-in reader for n8n workflow-error events (gap 11, operator-approved 2026-10-10).

Since #1663/#1664 the relay's POST /event writes one gateway event per failed n8n execution on lane
`n8n-workflow-error` into the coordination ledger (`receipts` rows, key `wferr-<workflow_id>-<execution_id>`), but
nothing read them: n8n workflow errors reached neither the SIEM (n8n:<lane> rows via scripts/n8n_siem_bridge.py) nor
Telegram. The fan-in now maps them to incidents: dedupe by idempotency key, one grouped incident per workflow, P1
for the dispatcher, incident router and heartbeat watcher, otherwise P2/WARN unless a health contract raises it. The existing notifier routes it;
nothing here sends.

Hermetic: synthetic ledgers (the real CoordinationLedger schema) and relay logs under tmp_path; pure notifier and
SIEM-bridge functions; no live state root, no gateway, no DB, no send.

COVERS = ["scripts/n8n_incident_fanin.py", "scripts/lib/n8n_siem_bridge.py"]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import n8n_siem_bridge as B  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

NOW = datetime(2026, 10, 10, 21, 22, tzinfo=timezone.utc)          # 17:22 ET, just after the W0 re-run errors
MSG = "Bad gateway - the service failed to handle your request"


def _ledger(path: Path, events: list[tuple[str, datetime]], *, state: str = "ACCEPTED",
            other_lane: bool = True) -> Path:
    """A ledger with the real schema and one receipts row per (idempotency_key, recorded_at)."""
    CoordinationLedger(path).close()
    conn = sqlite3.connect(path)
    for key, at in events:
        rec = {"idempotency_key": key, "event_id": f"evt-n8n-workflow-error-{key[6:]}", "lane_id": "n8n-workflow-error",
               "state": state, "recorded_at": at.isoformat(), "schema": "N8nCoordinationReceipt@v1"}
        conn.execute("INSERT INTO receipts (store_key, payload_hash, receipt_json, project, lane_id, state, updated_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (f"trade-ai:{key}", "h", json.dumps(rec), "trade-ai", "n8n-workflow-error", state,
                      (at + timedelta(seconds=4)).isoformat()))
    if other_lane:
        conn.execute("INSERT INTO receipts (store_key, payload_hash, receipt_json, project, lane_id, state, updated_at)"
                     " VALUES ('trade-ai:inc-abc', 'h', '{}', 'trade-ai', 'incident-fanin', 'ARTIFACT_WRITTEN', ?)",
                     (NOW.isoformat(),))
    conn.commit()
    conn.close()
    return path


def _relay_log(root: Path, rows: list[dict]) -> None:
    p = root / fanin.WFERR_RELAY_LOG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _ev(wf: str, ex: str, at: datetime, node: str = "GET relay /due", message: str = MSG) -> dict:
    return {"at": at.isoformat(), "op": "event", "state": "ACCEPTED", "lane_id": "n8n-workflow-error",
            "workflow_id": wf, "execution_id": ex, "node": node, "message": message,
            "idempotency_key": f"wferr-{wf}-{ex}", "duplicate": False, "gateway_http_status": 200}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("TRADEAI_FANIN_WFERR", raising=False)
    monkeypatch.delenv("TRADEAI_FANIN_WFERR_WINDOW_MIN", raising=False)
    monkeypatch.setattr(fanin, "HEALTH_CONTRACTS_PATH", tmp_path / "no_contracts.json")
    return tmp_path


# The W0 re-run shape measured in the live ledger 2026-10-10 (21:15-21:20Z): 8 events, three workflows.
W0 = [("tradeai-event-router", "2039", 0), ("tradeai-digest-scheduler", "2041", 0), ("tradeai-dispatcher", "2040", 1),
      ("tradeai-event-router", "2047", 60), ("tradeai-dispatcher", "2046", 60), ("tradeai-event-router", "2063", 303),
      ("tradeai-dispatcher", "2064", 303), ("tradeai-digest-scheduler", "2061", 303)]
T_W0 = datetime(2026, 10, 10, 21, 15, 13, tzinfo=timezone.utc)


def _w0(root: Path, *, relay: bool = True) -> None:
    _ledger(root / "ledger.sqlite", [(f"wferr-{wf}-{ex}", T_W0 + timedelta(seconds=s)) for wf, ex, s in W0])
    if relay:
        _relay_log(root, [_ev(wf, ex, T_W0 + timedelta(seconds=s + 5)) for wf, ex, s in W0])


# ── mapping ─────────────────────────────────────────────────────────────────────────────────────────

def test_w0_rerun_errors_group_per_workflow_with_p1_only_for_the_dispatcher(env):
    _w0(env)
    found = fanin._workflow_error_findings(env, NOW)
    by = {f["item"]: f for f in found}
    assert sorted(by) == ["wferr:tradeai-digest-scheduler", "wferr:tradeai-dispatcher", "wferr:tradeai-event-router"]
    assert {i: f["severity"] for i, f in by.items()} == {"wferr:tradeai-digest-scheduler": "P2",
                                                        "wferr:tradeai-dispatcher": "P1",
                                                        "wferr:tradeai-event-router": "P2"}
    d = by["wferr:tradeai-dispatcher"]
    assert d["source"] == "n8n_workflow_error" and d["count"] == 3 and d["workflow_id"] == "tradeai-dispatcher"
    assert d["event_keys"] == ["wferr-tradeai-dispatcher-2040", "wferr-tradeai-dispatcher-2046",
                               "wferr-tradeai-dispatcher-2064"]
    assert d["detail"].startswith("3 error(s) 21:15-21:20Z exec 2040,2046,2064 · GET relay /due: Bad gateway")
    assert d["detail"].endswith("[dispatcher]") and len(d["detail"]) <= 160
    assert by["wferr:tradeai-event-router"]["detail"].endswith("[default:WARN]")
    assert d["detected_at"] == (T_W0 + timedelta(seconds=1)).isoformat()      # first error: stable payload
    assert d["artifact_rel"] == fanin.LEDGER_REL and d["store"] == "persistent-state"
    assert fanin.NOTES["workflow_error_source"] == ("ledger:ok:8:relay_log_rows=8:events=8:in_window=8:workflows=3:"
                                                    "window_min=60")


def test_an_idempotency_key_counts_once_however_often_it_is_seen(env):
    at = NOW - timedelta(minutes=3)
    _ledger(env / "ledger.sqlite", [("wferr-tradeai-dispatcher-7", at)])
    _relay_log(env, [_ev("tradeai-dispatcher", "7", at), _ev("tradeai-dispatcher", "7", at)])   # relay retry
    [f] = fanin._workflow_error_findings(env, NOW)
    assert f["count"] == 1 and f["event_keys"] == ["wferr-tradeai-dispatcher-7"]


def test_only_errors_inside_the_window_open_an_incident(env, monkeypatch):
    _w0(env)
    assert fanin._workflow_error_findings(env, T_W0 + timedelta(minutes=61)) != []
    assert fanin._workflow_error_findings(env, T_W0 + timedelta(minutes=66)) == []   # all older than 60 min: closed
    monkeypatch.setenv("TRADEAI_FANIN_WFERR_WINDOW_MIN", "1440")
    assert len(fanin._workflow_error_findings(env, T_W0 + timedelta(hours=3))) == 3
    monkeypatch.setenv("TRADEAI_FANIN_WFERR_WINDOW_MIN", "junk")                    # bad value -> the default
    assert fanin._workflow_error_findings(env, T_W0 + timedelta(hours=3)) == []
    # a burst that is still arriving: only the in-window part counts
    monkeypatch.delenv("TRADEAI_FANIN_WFERR_WINDOW_MIN")
    found = fanin._workflow_error_findings(env, T_W0 + timedelta(minutes=62))
    assert {f["item"]: f["count"] for f in found} == {"wferr:tradeai-digest-scheduler": 1,
                                                      "wferr:tradeai-dispatcher": 1, "wferr:tradeai-event-router": 1}


def test_an_event_slightly_ahead_of_now_is_tolerated_but_not_a_far_future_one(env):
    _ledger(env / "ledger.sqlite", [("wferr-tradeai-dispatcher-1", NOW + timedelta(minutes=2)),
                                    ("wferr-tradeai-event-router-2", NOW + timedelta(hours=2))])
    assert [f["item"] for f in fanin._workflow_error_findings(env, NOW)] == ["wferr:tradeai-dispatcher"]


def test_refused_receipts_and_other_lanes_are_not_errors(env):
    _ledger(env / "ledger.sqlite", [("wferr-tradeai-dispatcher-9", NOW - timedelta(minutes=1))], state="REFUSED")
    assert fanin._workflow_error_findings(env, NOW) == []


def test_ledger_is_the_record_and_the_relay_log_only_enriches_it(env):
    at = NOW - timedelta(minutes=2)
    _ledger(env / "ledger.sqlite", [("wferr-tradeai-event-router-11", at)])
    _relay_log(env, [_ev("tradeai-event-router", "11", at, node="Fetch due", message="timeout"),
                     _ev("tradeai-dispatcher", "12", at)])                         # relay-only: not in the ledger
    [f] = fanin._workflow_error_findings(env, NOW)
    assert f["item"] == "wferr:tradeai-event-router" and "Fetch due: timeout" in f["detail"]


def test_without_a_ledger_the_relay_log_stands_in(env, monkeypatch):
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(env / "absent.sqlite"))
    _relay_log(env, [_ev("tradeai-dispatcher", "12", NOW - timedelta(minutes=2)),
                     {"at": NOW.isoformat(), "state": "REFUSED", "reason": "relay_bad_bearer", "op": "event"},
                     {"op": "due", "state": "OK", "at": NOW.isoformat()}])
    [f] = fanin._workflow_error_findings(env, NOW)
    assert f["item"] == "wferr:tradeai-dispatcher" and f["severity"] == "P1"
    assert fanin.NOTES["workflow_error_source"].startswith("ledger:absent:relay_log_rows=1:")


def test_a_broken_ledger_is_a_note_never_a_crash(env):
    (env / "ledger.sqlite").write_bytes(b"not a database at all" * 100)
    assert fanin._workflow_error_findings(env, NOW) == []
    assert fanin.NOTES["workflow_error_source"].startswith("ledger:error:DatabaseError")


def test_env_opt_out(env, monkeypatch):
    _w0(env)
    monkeypatch.setenv("TRADEAI_FANIN_WFERR", "0")
    assert fanin._workflow_error_findings(env, NOW) == []
    assert fanin.NOTES["workflow_error_source"] == "unavailable:RuntimeError:disabled_by_env"


@pytest.mark.parametrize("key,expected", [
    ("wferr-tradeai-dispatcher-2040", ("tradeai-dispatcher", "2040")),
    ("wferr-a-1", ("a", "1")),
    ("wferr-tradeai-event-router-abc_9", ("tradeai-event-router", "abc_9")),
    ("wferr-nohyphen", None),
    ("inc-tradeai-dispatcher-1", None),
])
def test_key_split(key, expected):
    assert fanin._wferr_split(key) == expected


def test_severity_p1_for_the_alerting_path_and_contracts_only_raise(env, monkeypatch):
    """Operator 2026-10-10 ("Yes to everything"): dispatcher, incident router and heartbeat watcher are P1; any other
    workflow is P2 unless its health contract raises it (never above P1, never below P2)."""
    contracts = env / "contracts.json"
    contracts.write_text(json.dumps({"schema": "N8nHealthContracts@v1", "contracts": [
        {"id": "tradeai-event-router", "kind": "generic_workflow",
         "alerting": {"failed": {"siem_severity": "URGENT", "notifier_priority": "P1"}}},
        {"id": "tradeai-digest-scheduler", "kind": "generic_workflow",
         "alerting": {"failed": {"notifier_priority": "P0"}}},
        {"id": "tradeai-approval-router", "kind": "generic_workflow",
         "alerting": {"failed": {"notifier_priority": "P3"}}},
        {"id": "tradeai-dispatcher", "kind": "generic_workflow",
         "alerting": {"failed": {"notifier_priority": "P3"}}},
        {"id": "tradeai-incident-router", "kind": "generic_workflow",
         "alerting": {"failed": {"notifier_priority": "P2"}}},
    ]}))
    monkeypatch.setattr(fanin, "HEALTH_CONTRACTS_PATH", contracts)
    assert fanin._wferr_severity("tradeai-event-router") == ("P1", "contract:P1")
    assert fanin._wferr_severity("tradeai-digest-scheduler") == ("P1", "contract:P0->P1")       # ceiling P1
    assert fanin._wferr_severity("tradeai-approval-router") == ("P2", "contract:P3->P2")        # never lowered
    assert fanin._wferr_severity("tradeai-dispatcher") == ("P1", "dispatcher")
    assert fanin._wferr_severity("tradeai-incident-router") == ("P1", "alert_path")
    assert fanin._wferr_severity("tradeai-heartbeat-watcher") == ("P1", "alert_path")
    assert fanin._wferr_severity("some-other-workflow") == ("P2", "default:WARN")
    monkeypatch.setattr(fanin, "HEALTH_CONTRACTS_PATH", env / "missing.json")
    assert fanin._wferr_severity("tradeai-event-router") == ("P2", "default:WARN")
    assert fanin._wferr_severity("tradeai-incident-router") == ("P1", "alert_path")


def test_main_contract_file_is_absent_so_the_default_is_warn():
    """The contract is read only 'if config/n8n_health_contracts.json exists on main'. It does not (measured
    2026-10-10 on 590f797b1); when it lands, the contract test above governs."""
    if fanin.HEALTH_CONTRACTS_PATH.exists():
        pytest.skip("health contracts present: the contract test governs")
    assert fanin._wferr_severity("tradeai-event-router") == ("P2", "default:WARN")
    assert {w: fanin._wferr_severity(w)[0] for w in fanin.WFERR_P1_WORKFLOWS} == {
        "tradeai-dispatcher": "P1", "tradeai-incident-router": "P1", "tradeai-heartbeat-watcher": "P1"}


# ── the fan-in run carries it; the notifier and the SIEM bridge route it ────────────────────────────

def _quiet_other_sources(monkeypatch):
    for var in ("TRADEAI_FANIN_LANE_REGISTRY", "TRADEAI_FANIN_RUNS", "TRADEAI_FANIN_RELAY", "TRADEAI_FANIN_DLQ",
                "TRADEAI_FANIN_GOVERNANCE", "TRADEAI_FANIN_DIAGNOSIS", "TRADEAI_ALERT_PATH_WATCH"):
        monkeypatch.setenv(var, "0")
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "_scalp_lane_findings", lambda root, now: [])
    monkeypatch.setattr(fanin, "_scalp_cycle_findings", lambda root, now: [])


def test_collect_includes_workflow_errors(env, monkeypatch):
    _quiet_other_sources(monkeypatch)
    _w0(env)
    items = [f["item"] for f in fanin.collect(env, NOW, prev={})]
    assert sorted(i for i in items if i.startswith("wferr:")) == [
        "wferr:tradeai-digest-scheduler", "wferr:tradeai-dispatcher", "wferr:tradeai-event-router"]


def test_main_dry_run_lists_the_incidents_and_writes_nothing(env, monkeypatch, capsys):
    _quiet_other_sources(monkeypatch)
    now = datetime.now(timezone.utc)
    _ledger(env / "ledger.sqlite", [("wferr-tradeai-dispatcher-1", now - timedelta(minutes=2))])
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(env))
    monkeypatch.setenv("TRADEAI_SERVED_SHA", "test-sha")
    def files():   # sqlite's -wal/-shm sidecars appear on any read of a WAL ledger; they are not writes
        return sorted(p.name for p in env.rglob("*") if not p.name.endswith(("-wal", "-shm")))

    def rows():
        conn = sqlite3.connect(f"file:{env / 'ledger.sqlite'}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT * FROM receipts ORDER BY store_key").fetchall()
        finally:
            conn.close()

    before, before_rows = files(), rows()
    assert fanin.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["by_severity"] == {"P1": 1}
    assert ["P1", "n8n_workflow_error", "wferr:tradeai-dispatcher"] in [list(x) for x in out["sample"]]
    assert files() == before and rows() == before_rows                           # dry run: no receipt, no write


def _receipt_rows(env: Path) -> list[dict]:
    """The fan-in's apply-mode incident rows for these findings (the shape main() writes), built without a gateway."""
    rows = []
    for f in fanin._workflow_error_findings(env, NOW):
        ev = fanin.build_event(f, day=NOW.strftime("%Y-%m-%d"), now=NOW, sha="test-sha")
        rows.append({**{k: f[k] for k in ("source", "item", "severity", "detail", "detected_at")},
                     "idempotency_key": ev["idempotency_key"], "event_id": ev["event_id"], "state": "ARTIFACT_WRITTEN",
                     "workflow_id": f["workflow_id"], "count": f["count"], "event_keys": f["event_keys"]})
    return rows


def test_the_existing_notifier_routes_them_p1_at_once_p2_batched(env):
    _w0(env)
    rows = _receipt_rows(env)
    fanin_doc = {"status": "OK", "as_of": NOW.isoformat(), "incidents": rows,
                 "by_severity": {"P1": 1, "P2": 2}}
    open_now, acked = N.open_incidents(fanin_doc, set())
    assert acked == [] and len(open_now) == 3
    cfg = N.config_from_env({})
    msgs, _batch = N.plan_messages(open_now, {"notified": {}}, NOW, cfg, fanin_doc, set())
    kinds = [(m["kind"], [i["item"] for i in m["incidents"]]) for m in msgs]
    assert kinds[0] == ("p1", ["wferr:tradeai-dispatcher"])
    assert ("p2_batch", ["wferr:tradeai-digest-scheduler", "wferr:tradeai-event-router"]) in [
        (k, sorted(i)) for k, i in kinds]
    assert "• n8n_workflow_error wferr:tradeai-dispatcher — 3 error(s)" in N._line(msgs[0]["incidents"][0])


def test_the_siem_bridge_keeps_one_row_per_workflow_at_critical_or_warn(env):
    _w0(env)
    doc = {"as_of": NOW.isoformat(), "ok": True, "incidents": _receipt_rows(env)}
    found, healthy, _note = B.fanin_findings(doc, NOW, {}, {})
    assert healthy
    by = {f["component"]: f for f in found}
    assert set(by) == {"n8n:tradeai-dispatcher", "n8n:tradeai-event-router", "n8n:tradeai-digest-scheduler"}
    d = by["n8n:tradeai-dispatcher"]
    assert (d["event_type"], d["severity"], d["severity_basis"]) == ("WORKFLOW_ERROR", "CRITICAL", "priority:P1")
    assert d["workflow_id"] == "tradeai-dispatcher" and d["execution_id"] == "2064"
    assert by["n8n:tradeai-event-router"]["severity"] == "WARN"
    assert B.lane_kind("n8n_workflow_error", "wferr:") == ("n8n_workflow_error/", "WFERR")   # malformed: generic path
