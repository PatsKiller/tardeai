"""n8n -> Command Center SIEM bridge (REMEDIATION_PLAN §5 L2/L7, operator 2026-10-09 23:20 ET).

Hermetic: a temp state root (ledger sqlite + fan-in receipt), a temp registry and release link, and an in-memory
double of the system_health_events table. Also executes the served `_inbox` and `_system_siem_dashboard` from
api_v2's source with a query double (no application imports), as tests/test_siem_incident_visibility.py does.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import n8n_siem_bridge as cli
from scripts.lib import n8n_siem_bridge as B

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 10, 4, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- doubles and fixtures


class FakeDB:
    """In-memory system_health_events. Records every statement; READ ONLY transactions refuse writes."""

    def __init__(self, rows=None):
        self.rows = [dict(r) for r in rows or []]
        self.sql: list[str] = []
        self.readonly = False
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1
        self.readonly = False

    def rollback(self):
        self.readonly = False


class FakeCursor:
    def __init__(self, db):
        self.db, self.description, self._res = db, None, []

    def execute(self, sql, params=()):
        db = self.db
        db.sql.append(sql)
        head = sql.lstrip().split()[0].upper()
        if sql.strip().upper() == "SET TRANSACTION READ ONLY":
            db.readonly = True
            return
        if head in ("INSERT", "UPDATE", "DELETE") and db.readonly:
            raise RuntimeError("cannot execute in a read-only transaction")
        if head == "SELECT":
            cols = ["id", "component", "event_type", "severity", "message", "lifecycle_state", "created_at"]
            self.description = [(c,) for c in cols]
            rows = [
                r
                for r in db.rows
                if r["component"].startswith("n8n:")
                and (r.get("lifecycle_state") or "active") in ("active", "acknowledged")
            ]
            self._res = [tuple(r.get(c) for c in cols) for r in sorted(rows, key=lambda r: -r["id"])]
        elif head == "INSERT":
            comp, et, sev, msg, action = params
            rid = max([r["id"] for r in db.rows] or [0]) + 1
            db.rows.append(
                {
                    "id": rid,
                    "component": comp,
                    "event_type": et,
                    "severity": sev,
                    "message": msg,
                    "action_taken": action,
                    "lifecycle_state": "active",
                    "created_at": NOW,
                }
            )
            self._res = [(rid,)]
        elif head == "UPDATE":
            row = next(r for r in db.rows if r["id"] == params[-1])
            if "lifecycle_state='resolved'" in sql:
                row.update(lifecycle_state="resolved", resolved_by=params[0], action_taken=params[1])
            else:
                row.update(severity=params[0], message=params[1], action_taken=params[2])

    def fetchall(self):
        return self._res

    def fetchone(self):
        return self._res[0] if self._res else None


def _ledger(path: Path, runs):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()  # each setup() call is a fresh ledger snapshot
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
        "caller_id TEXT, requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, "
        "receipt_json TEXT)"
    )
    for r in runs:
        c.execute(
            "INSERT INTO runs (run_id, lane_id, mode, state, requested_by, requested_at, finished_at, exit_code, "
            "duration_s, receipt_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r["run_id"],
                r["lane_id"],
                r.get("mode", "live"),
                r["state"],
                r.get("requested_by"),
                r["requested_at"],
                r.get("finished_at"),
                r.get("exit_code"),
                r.get("duration_s"),
                None if r.get("receipt") is None else json.dumps(r["receipt"]),
            ),
        )
    c.commit()
    c.close()


def run_row(n, lane, state, *, minutes_ago, wf="2c725c7dfd4ac62f", reason=None, stderr=None, receipt=True):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    rec = (
        {
            "schema": "RunReceipt@v1",
            "state": state,
            "reason": reason,
            "stderr_tail": stderr,
            "mode": "live",
            "output_signal": None,
        }
        if receipt
        else None
    )
    return {
        "run_id": f"n8n-wf-{wf}-{n}",
        "lane_id": lane,
        "state": state,
        "requested_by": f"n8n:workflow:{wf}",
        "requested_at": ts,
        "finished_at": ts,
        "exit_code": 0 if state == "RUN_DONE" else 1,
        "duration_s": 2.0,
        "receipt": rec,
    }


def fanin_doc(incidents, *, age_min=3, ok=True):
    return {
        "schema": "N8nIncidentFanin@v1",
        "as_of": (NOW - timedelta(minutes=age_min)).isoformat(),
        "ok": ok,
        "incidents": incidents,
    }


def inc(source, item, sev, detail="d", detected_at="2026-10-10T03:00:00+00:00"):
    return {"source": source, "item": item, "severity": sev, "detail": detail, "detected_at": detected_at}


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)
    rel = tmp_path / "rel" / "abc123-main-exact"
    rel.mkdir(parents=True)
    (rel / "SOURCE_COMMIT").write_text("abc123def4567890\n")
    link = tmp_path / "CURRENT"
    link.symlink_to(rel)
    reg = tmp_path / "lane_registry.json"
    reg.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "lane_id": "lane-a",
                        "scheduler": {"kind": "n8n", "expression": "wfA"},
                        "severity": "High",
                        "remediation": "Restart lane-a per runbook R7.",
                    },
                    {"lane_id": "lane-b", "scheduler": {"kind": "n8n", "expression": "wfB"}},
                    {"lane_id": "n8n-incident-fanin", "scheduler": {"kind": "n8n", "expression": "722fac0e043ea5c4"}},
                ]
            }
        )
    )

    def setup(runs=(), fanin=None):
        _ledger(state / B.LEDGER_REL, list(runs))
        if fanin is not None:
            p = state / B.FANIN_RECEIPT_REL
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(fanin))

    def run(db, *args, now=NOW):
        return cli.main(list(args), conn_factory=lambda: db, now=now, release_link=link, registry_path=reg)

    return {"state": state, "setup": setup, "run": run, "tmp": tmp_path}


# ---------------------------------------------------------------- mapping


@pytest.mark.parametrize(
    "source,item,expected",
    [
        ("breach_detector", "cio-opportunity-curator:UNGOVERNED", ("cio-opportunity-curator", "UNGOVERNED")),
        ("runs", "lane-a:RUN_FAILED", ("lane-a", "RUN_FAILED")),
        ("runs", "executor:stalled", ("n8n-run-executor", "EXECUTOR_STALLED")),
        ("relay", "relay:down", ("n8n-run-relay", "RELAY_DOWN")),
        ("n8n_lab_watchdog", "healthz", ("n8n-lab-watchdog", "N8N_DOWN")),
        (
            "expected_services",
            "MISSING:tradeai-phone-status.service",
            ("expected_services/tradeai-phone-status.service", "MISSING"),
        ),
        ("gap_resolution", "OPEN_NO_ATTEMPT:118", ("gap_resolution", "OPEN_NO_ATTEMPT")),
        ("dlq", "breaker:lane-b", ("lane-b", "BREAKER_OPEN")),
        (
            "data_plausibility",
            "symbol_profiles.ytd_return_pct",
            ("data_plausibility/symbol_profiles.ytd_return_pct", "DATA_PLAUSIBILITY"),
        ),
    ],
)
def test_fanin_item_maps_to_lane_and_kind(source, item, expected):
    assert B.lane_kind(source, item) == expected


def test_gap_resolution_count_does_not_churn_the_dedupe_key():
    assert B.lane_kind("gap_resolution", "OPEN_NO_ATTEMPT:118") == B.lane_kind("gap_resolution", "OPEN_NO_ATTEMPT:119")


@pytest.mark.parametrize(
    "reg,prio,expected",
    [
        ({"severity": "Critical"}, "P3", "CRITICAL"),
        ({"severity": "High"}, "P3", "URGENT"),
        ({"severity": "Medium"}, "P1", "WARN"),
        ({"severity": "Low"}, "P1", "INFO"),
        ({}, "P0", "CRITICAL"),
        ({}, "P1", "CRITICAL"),
        ({}, "P2", "WARN"),
        ({}, "P3", "INFO"),
        (None, "P2", "WARN"),
    ],
)
def test_severity_registry_first_then_fanin_priority(reg, prio, expected):
    sev, basis = B.severity_for(reg, prio)
    assert sev == expected
    assert basis.startswith("registry:" if (reg or {}).get("severity") else "priority:")


def test_stored_vocabulary_only():
    assert set(B.REGISTRY_SEVERITY.values()) | set(B.PRIORITY_SEVERITY.values()) <= {
        "CRITICAL",
        "URGENT",
        "WARN",
        "INFO",
    }


def test_run_id_parses_workflow_and_execution():
    assert B.parse_run_id("n8n-wf-2c725c7dfd4ac62f-1557") == ("2c725c7dfd4ac62f", "1557")
    assert B.parse_run_id("adhoc-run-000000001", "n8n:workflow:wfZ") == ("wfZ", None)


# ---------------------------------------------------------------- message fields


def test_message_carries_lane_workflow_execution_time_env_error_remediation(env):
    env["setup"](
        [run_row(41, "lane-a", "RUN_FAILED", minutes_ago=5, wf="wfA", reason="exit_1", stderr="Traceback: boom")],
        fanin_doc([]),
    )
    db = FakeDB()
    assert env["run"](db, "--apply") == 0
    (row,) = db.rows
    assert row["component"] == "n8n:lane-a" and row["event_type"] == "RUN_FAILED"
    assert row["severity"] == "URGENT"  # registry High
    m = row["message"]
    for part in (
        "lane=lane-a",
        "workflow=wfA",
        "execution=41",
        "run=n8n-wf-wfA-41",
        f"at={(NOW - timedelta(minutes=5)).isoformat()}",
        "env=release:abc123-main-exact@abc123def",
        "Traceback: boom",
        'remediation="Restart lane-a per runbook R7."',
        "dedupe=n8n:lane-a|RUN_FAILED",
    ):
        assert part in m, part


def test_default_remediation_when_registry_has_none(env):
    env["setup"]([run_row(7, "lane-b", "RUN_TIMEOUT", minutes_ago=5, wf="wfB")], fanin_doc([]))
    db = FakeDB()
    env["run"](db, "--apply")
    (row,) = db.rows
    assert row["severity"] == "WARN" and B.DEFAULT_REMEDIATION["RUN_TIMEOUT"][:40] in row["message"]


# ---------------------------------------------------------------- dedupe


def test_second_identical_run_writes_nothing(env):
    env["setup"](
        [run_row(1, "lane-b", "RUN_FAILED", minutes_ago=5, wf="wfB")],
        fanin_doc([inc("expected_services", "MISSING:x.service", "P1")]),
    )
    db = FakeDB()
    assert env["run"](db, "--apply") == 0
    assert len(db.rows) == 2
    n_sql = len(db.sql)
    assert env["run"](db, "--apply") == 0
    assert len(db.rows) == 2
    assert not [s for s in db.sql[n_sql:] if s.lstrip().upper().startswith(("INSERT", "UPDATE"))]


def test_timestamp_only_change_is_skipped_but_severity_change_updates_in_place():
    f = B.merge(
        [
            B._finding(
                "lane-b",
                "MISSING",
                priority="P2",
                source="fanin:x",
                detail="ran_at 2026-10-10T03:00:00+00:00",
                detected_at="2026-10-10T03:00:00+00:00",
                registry={},
                workflow_id=None,
                execution_id=None,
                run_id=None,
            )
        ]
    )
    msg = B.message(next(iter(f.values())), "release:r")
    open_rows = [
        {
            "id": 9,
            "component": "n8n:lane-b",
            "event_type": "MISSING",
            "severity": "WARN",
            "message": msg.replace("03:00:00", "02:55:00"),
            "lifecycle_state": "active",
        }
    ]
    p = B.plan(f, open_rows, env="release:r", good_lanes=set(), ledger_ok=True, fanin_ok=True)
    assert [r["id"] for r in p["skip"]] == [9] and not p["insert"] and not p["update"]
    open_rows[0]["severity"] = "INFO"
    p = B.plan(f, open_rows, env="release:r", good_lanes=set(), ledger_ok=True, fanin_ok=True)
    assert [(r["id"], r["was_severity"], r["severity"]) for r in p["update"]] == [(9, "INFO", "WARN")]
    assert not p["insert"]


def _diag_line(key, *, siem_id, kind="diagnosis", **kw):
    rec = {"schema": B.DIAGNOSIS_SCHEMA, "kind": kind, "incident_key": key, "siem_id": siem_id,
           "at": "2026-10-10T04:01:00+00:00"}
    if kind == "diagnosis":
        rec.update(cause="lane-b exited 1 on a refused DB connection", confidence=0.85, action_id="rerun_dry_run",
                   outcome="requested:dry_run:rem-x-dry_run", provider="grok", model_id="grok-fast", cost_usd=0.0012,
                   latency_ms=900, citations=["siem:1", "run:n8n-wf-wfB-1"])
    rec.update(kw)
    return json.dumps(rec) + "\n"


def test_bridge_folds_a_diagnosis_into_the_right_row_once_and_rerun_is_idempotent(env):
    """2026-10-10 (§9.4 one writer): the diagnoser writes data/runtime/n8n_diagnoses/diagnoses.jsonl; the bridge
    folds the record into the n8n:<lane> row whose incident key it names — and into no other row — exactly once."""
    env["setup"]([run_row(1, "lane-a", "RUN_FAILED", minutes_ago=6, wf="wfA"),
                  run_row(2, "lane-b", "RUN_FAILED", minutes_ago=5, wf="wfB")], fanin_doc([]))
    db = FakeDB()
    assert env["run"](db, "--apply") == 0
    rows = {r["component"]: r for r in db.rows}
    a, b = rows["n8n:lane-a"], rows["n8n:lane-b"]
    msg_a = a["message"]
    store = env["state"] / B.DIAGNOSES_REL
    store.parent.mkdir(parents=True, exist_ok=True)
    key_b = B.incident_key(b["id"], b["severity"], b["message"])
    store.write_text(_diag_line(key_b, siem_id=b["id"]) + "not json\n"
                     + _diag_line("siem999-000000000000", siem_id=999))      # a stale incident: ignored
    n_sql = len(db.sql)
    assert env["run"](db, "--apply") == 0
    writes = [q for q in db.sql[n_sql:] if q.lstrip().upper().startswith(("INSERT", "UPDATE"))]
    assert len(writes) == 1 and len(db.rows) == 2                             # one UPDATE, onto lane-b only
    assert a["message"] == msg_a
    assert B.DIAG_MARKER in b["message"] and "action=rerun_dry_run" in b["message"]
    assert 'cause="lane-b exited 1 on a refused DB connection"' in b["message"]
    assert "model=grok/grok-fast" in b["message"] and "cost_usd=0.0012" in b["message"]
    assert f"key={key_b}" in b["message"] and "cites=siem:1,run:n8n-wf-wfB-1" in b["message"]
    assert b["action_taken"].startswith("n8n_siem_bridge: diagnosis folded (n8n_failure_diagnosis: rerun_dry_run")
    assert B.strip_diagnosis(b["message"]) in b["message"] and B.incident_key(b["id"], b["severity"], b["message"]) == key_b
    rec = json.loads((env["state"] / B.RECEIPT_REL).read_text())
    assert rec["diagnoses_folded"] == 1 and rec["source_notes"]["diagnoses"] == "diagnoses:ok:2:bad_lines=1"
    # idempotent: the same store again writes nothing
    folded, n_sql = b["message"], len(db.sql)
    assert env["run"](db, "--apply") == 0
    assert not [q for q in db.sql[n_sql:] if q.lstrip().upper().startswith(("INSERT", "UPDATE"))]
    assert b["message"] == folded
    # a remediation step for the same incident is one more fold, then idempotent again
    with store.open("a") as fh:
        fh.write(_diag_line(key_b, siem_id=b["id"], kind="remediation", outcome="remediated"))
    assert env["run"](db, "--apply") == 0
    assert b["message"].endswith("remediation=remediated") and B.DIAG_MARKER in b["message"]
    n_sql = len(db.sql)
    assert env["run"](db, "--apply") == 0
    assert not [q for q in db.sql[n_sql:] if q.lstrip().upper().startswith(("INSERT", "UPDATE"))]


def test_changed_finding_drops_the_old_diagnosis_and_unreadable_store_keeps_it():
    def plan_for(detail, rows, diagnoses):
        f = B._finding("lane-b", "RUN_FAILED", priority="P2", source="ledger", detail=detail,
                       detected_at="2026-10-10T03:00:00+00:00", registry={}, workflow_id=None, execution_id=None,
                       run_id=None)
        return B.plan(B.merge([f]), rows, env="release:r", good_lanes=set(), ledger_ok=True, fanin_ok=True,
                      diagnoses=diagnoses), B.message(f, "release:r")

    _, base = plan_for("exit=1", [], {})
    row = {"id": 4, "component": "n8n:lane-b", "event_type": "RUN_FAILED", "severity": "WARN", "message": base,
           "lifecycle_state": "active"}
    key = B.incident_key(4, "WARN", base)
    diags = {key: {"diagnosis": json.loads(_diag_line(key, siem_id=4)), "remediation": None}}
    p, _ = plan_for("exit=1", [row], diags)
    row["message"] = p["update"][0]["message"]
    assert B.DIAG_MARKER in row["message"]
    # the store unreadable (None): an unchanged finding keeps the suffix it shows (skip, no erase)
    p, _ = plan_for("exit=1", [row], None)
    assert [r["id"] for r in p["skip"]] == [4]
    # the finding changed: new evidence, new key -> the row is rewritten without the old diagnosis
    p, _ = plan_for("exit=2", [row], diags)
    assert B.DIAG_MARKER not in p["update"][0]["message"] and p["update"][0]["diagnosis_folded"] is None
    # the workaround is gone: stable_text compares the whole message, suffix included
    assert B.stable_text(row["message"]) != B.stable_text(base) and B.finding_text(row["message"]) == B.finding_text(base)
    assert B.read_diagnoses(Path("/nonexistent/diagnoses.jsonl")) == ({}, "diagnoses:none")


def test_acknowledged_row_counts_as_open_and_is_not_duplicated():
    f = B.merge(
        [
            B._finding(
                "lane-b",
                "RUN_FAILED",
                priority="P2",
                source="ledger",
                detail="x",
                detected_at="t",
                registry={},
                workflow_id=None,
                execution_id=None,
                run_id=None,
            )
        ]
    )
    rows = [
        {
            "id": 3,
            "component": "n8n:lane-b",
            "event_type": "RUN_FAILED",
            "severity": "WARN",
            "message": "old",
            "lifecycle_state": "acknowledged",
        }
    ]
    p = B.plan(f, rows, env="e", good_lanes=set(), ledger_ok=True, fanin_ok=True)
    assert not p["insert"] and [r["id"] for r in p["update"]] == [3]


def test_ledger_and_fanin_findings_for_the_same_key_merge_to_one_row(env):
    env["setup"](
        [run_row(5, "lane-b", "RUN_FAILED", minutes_ago=5, wf="wfB")],
        fanin_doc([inc("runs", "lane-b:RUN_FAILED", "P2")]),
    )
    db = FakeDB()
    env["run"](db, "--apply")
    assert [(r["component"], r["event_type"]) for r in db.rows] == [("n8n:lane-b", "RUN_FAILED")]
    assert "source=ledger" in db.rows[0]["message"]


# ---------------------------------------------------------------- resolve on recovery


def test_good_latest_run_resolves_the_open_failure(env):
    env["setup"]([run_row(1, "lane-b", "RUN_FAILED", minutes_ago=10, wf="wfB")], fanin_doc([]))
    db = FakeDB()
    env["run"](db, "--apply")
    assert db.rows[0]["lifecycle_state"] == "active"
    env["setup"](
        [
            run_row(1, "lane-b", "RUN_FAILED", minutes_ago=10, wf="wfB"),
            run_row(2, "lane-b", "RUN_DONE", minutes_ago=1, wf="wfB"),
        ],
        fanin_doc([]),
    )
    assert env["run"](db, "--apply") == 0
    assert db.rows[0]["lifecycle_state"] == "resolved" and db.rows[0]["resolved_by"] == "n8n_siem_bridge"
    assert "latest_run_good" in db.rows[0]["action_taken"]


def test_lock_skip_after_failure_does_not_resolve(env):
    env["setup"](
        [
            run_row(1, "lane-b", "RUN_FAILED", minutes_ago=10, wf="wfB"),
            run_row(2, "lane-b", "RUN_SKIPPED_LOCK", minutes_ago=1, wf="wfB"),
        ],
        fanin_doc([]),
    )
    db = FakeDB()
    env["run"](db, "--apply")
    assert [(r["event_type"], r["lifecycle_state"]) for r in db.rows] == [("RUN_FAILED", "active")]


def test_cleared_fanin_finding_resolves_only_when_fanin_is_fresh(env):
    env["setup"]([], fanin_doc([inc("expected_services", "MISSING:x.service", "P1")]))
    db = FakeDB()
    env["run"](db, "--apply")
    assert db.rows[0]["severity"] == "CRITICAL"
    # stale fan-in receipt with the incident gone: hold (and flag the fan-in itself), never resolve
    env["setup"]([], fanin_doc([], age_min=180))
    assert env["run"](db, "--apply") == 0
    assert db.rows[0]["lifecycle_state"] == "active"
    assert any(r["component"] == "n8n:n8n-incident-fanin" and r["event_type"] == "STALE_OUTPUT" for r in db.rows)
    # fresh again: both the cleared incident and the fan-in staleness resolve
    env["setup"]([], fanin_doc([]))
    env["run"](db, "--apply")
    assert {r["lifecycle_state"] for r in db.rows} == {"resolved"}


def test_unreadable_ledger_resolves_nothing_and_exits_1(env):
    env["setup"]([], fanin_doc([]))
    db = FakeDB(
        [
            {
                "id": 1,
                "component": "n8n:lane-b",
                "event_type": "RUN_FAILED",
                "severity": "WARN",
                "message": "m",
                "lifecycle_state": "active",
            }
        ]
    )
    (env["state"] / B.LEDGER_REL).unlink()
    assert env["run"](db, "--apply") == 1
    assert db.rows[0]["lifecycle_state"] == "active"
    rec = json.loads((env["state"] / B.RECEIPT_REL).read_text())
    assert rec["ok"] is False and rec["ok_at"] is None and rec["source_notes"]["ledger"].startswith("unavailable")


# ---------------------------------------------------------------- dry run


def test_dry_run_reaches_no_write_and_reports_what_it_would_write(env, capsys):
    env["setup"](
        [run_row(1, "lane-b", "RUN_FAILED", minutes_ago=5, wf="wfB")],
        fanin_doc([inc("expected_services", "MISSING:x.service", "P1"), inc("breach_detector", "z:UNGOVERNED", "P3")]),
    )
    db = FakeDB(
        [
            {
                "id": 1,
                "component": "n8n:gone",
                "event_type": "NO_OUTPUT",
                "severity": "WARN",
                "message": "m",
                "lifecycle_state": "active",
            }
        ]
    )
    out = env["tmp"] / "dry.json"
    assert env["run"](db, "--dry-run", "--out", str(out)) == 0
    assert not [s for s in db.sql if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert "SET TRANSACTION READ ONLY" in db.sql and db.commits == 0
    assert db.rows[0]["lifecycle_state"] == "active"
    assert not (env["state"] / B.RECEIPT_REL).exists()
    rep = json.loads(out.read_text())
    assert rep["counts"]["insert"]["by_severity"] == {"CRITICAL": 1, "WARN": 1, "INFO": 1}
    assert [r["id"] for r in rep["would_write"]["resolve"]] == [1]
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"


def test_dry_run_report_varies_with_the_state(env):
    """Mutation check (AGENTS.md §6): change the input, the report changes."""
    env["setup"]([], fanin_doc([inc("expected_services", "MISSING:x.service", "P1")]))
    a, b = env["tmp"] / "a.json", env["tmp"] / "b.json"
    env["run"](FakeDB(), "--dry-run", "--out", str(a))
    (env["state"] / B.FANIN_RECEIPT_REL).write_text(
        json.dumps(fanin_doc([inc("expected_services", "MISSING:x.service", "P2")]))
    )
    env["run"](FakeDB(), "--dry-run", "--out", str(b))
    assert json.loads(a.read_text())["counts"]["insert"]["by_severity"] == {"CRITICAL": 1}
    assert json.loads(b.read_text())["counts"]["insert"]["by_severity"] == {"WARN": 1}


def test_dry_run_branch_returns_before_apply_plan_is_reachable():
    src = (ROOT / "scripts" / "n8n_siem_bridge.py").read_text()
    body = src[src.index("def main(") :]
    assert (
        body.index("if args.dry_run:") < body.index('return 0 if report["ok"] else 1') < body.index("apply_plan(conn")
    )
    assert src.index("def read_open_rows") < src.index('SET TRANSACTION READ ONLY")')


def test_apply_receipt_has_ok_at(env):
    env["setup"]([], fanin_doc([]))
    assert env["run"](FakeDB(), "--apply") == 0
    rec = json.loads((env["state"] / B.RECEIPT_REL).read_text())
    assert rec["schema"] == "N8nSiemBridge@v1" and rec["ok"] is True and rec["ok_at"] == NOW.isoformat()


def test_bridge_never_sends():
    for p in ("scripts/n8n_siem_bridge.py", "scripts/lib/n8n_siem_bridge.py"):
        code = "\n".join(line for line in (ROOT / p).read_text().splitlines() if not line.lstrip().startswith("#"))
        tree = ast.parse(code)
        names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not ({"send_telegram", "telegram_alert", "requests", "urllib"} & (names | mods)), p


# ---------------------------------------------------------------- Command Center readers


def _compile(name):
    path = ROOT / "scripts" / "api_v2.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec")


def test_inbox_now_returns_critical_and_urgent_siem_rows():
    she = [
        {
            "component": "n8n:lane-a",
            "event_type": "RUN_FAILED",
            "severity": "CRITICAL",
            "message": "m",
            "created_at": NOW,
        },
        {
            "component": "n8n:lane-b",
            "event_type": "RUN_TIMEOUT",
            "severity": "URGENT",
            "message": "m",
            "created_at": NOW,
        },
        {"component": "legacy", "event_type": "X", "severity": "P1", "message": "m", "created_at": NOW},
        {
            "component": "stop_health",
            "event_type": "STOP_HEALTH_SCAN",
            "severity": "WARN",
            "message": "m",
            "created_at": NOW,
        },
        {"component": "n8n:lane-c", "event_type": "UNGOVERNED", "severity": "INFO", "message": "m", "created_at": NOW},
    ]

    def query(sql, params=None, **_kw):
        if "FROM system_health_events" not in sql:
            return []
        allowed = set(re.search(r"IN \(([^)]*)\)", sql).group(1).replace("'", "").replace(" ", "").split(","))
        return [r for r in she if (r["severity"].upper() if "UPPER(severity)" in sql else r["severity"]) in allowed]

    ns = {"_db_query": query, "_json_clean": lambda v: v.isoformat() if hasattr(v, "isoformat") else v}
    exec(_compile("_inbox"), ns)
    res = ns["_inbox"]()
    siem = [i for i in res["items"] if i["type"] == "siem"]
    assert res["siem"] == 3
    assert sorted((i["detail"], i["priority"], i["severity"]) for i in siem) == [
        ("legacy — X", "P1", "P1"),
        ("n8n:lane-a — RUN_FAILED", "P0", "CRITICAL"),
        ("n8n:lane-b — RUN_TIMEOUT", "P1", "URGENT"),
    ]
    assert res["p0_count"] == 1


def test_siem_dashboard_keeps_n8n_severity_and_event_type():
    rows = {
        "system_health_events": [
            {
                "id": 7,
                "event_type": "RUN_FAILED",
                "component": "n8n:lane-a",
                "severity": "CRITICAL",
                "message": "[n8n] lane=lane-a kind=RUN_FAILED",
                "created_at": NOW,
                "lifecycle_state": "active",
            },
            {
                "id": 8,
                "event_type": "UNGOVERNED",
                "component": "n8n:lane-c",
                "severity": "INFO",
                "message": "[n8n] lane=lane-c",
                "created_at": NOW,
                "lifecycle_state": "active",
            },
        ]
    }

    def query(sql, params):
        src = re.search(r"\bFROM\s+(\w+)", sql).group(1)
        return rows.get(src) or []

    ns = {"_db_query": query, "_json_clean": lambda v: v.isoformat()}
    exec(_compile("_system_siem_dashboard"), ns)
    res = ns["_system_siem_dashboard"]()
    evs = {e["component"]: e for e in res["recent_events"]}
    assert (evs["n8n:lane-a"]["event_type"], evs["n8n:lane-a"]["severity"]) == ("RUN_FAILED", "P0")
    assert (evs["n8n:lane-c"]["event_type"], evs["n8n:lane-c"]["severity"]) == ("UNGOVERNED", "P3")
