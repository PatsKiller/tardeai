"""Lane registry scheduler kind `n8n` (2026-10-08, scheduler-of-record program).

A lane moved to an n8n workflow keeps its row: `scheduler.expression` is the workflow id,
`scheduler.match` the retired cron command / timer unit. Scheduler presence is proven by the run
ledger (or a RunReceipt) within one cadence, never by n8n's UI; the retired host entry still live
beside the workflow is a double scheduler and fails `check_lane_registry --state-drift`.
Hermetic: tmp sqlite ledger, tmp receipt files, injected discovery.

COVERS = ["scripts/lib/lane_registry.py", "scripts/lib/lane_state_drift.py", "scripts/lib/n8n_lane_host_conflict.py"]
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_registry as lr  # noqa: E402
from scripts.lib import lane_state_drift as LD  # noqa: E402
from scripts.lib import n8n_lane_host_conflict as HC  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)  # a Thursday
LANE = "fixture-warm"
MATCH = "scripts/fixture_warm.py"
LINE = f"*/8 * * * * cd $PROJ && $PY {MATCH} >> logs/fixture_warm.log 2>&1"


def _row(**kw):
    base = {
        "lane_id": LANE,
        "owner": "platform",
        "state": "ACTIVE",
        "expected_cadence_hours": 1.0,
        "scheduler": {"kind": "n8n", "expression": "wf-abc123", "match": MATCH, "cadence": "*/8 * * * *"},
        "output_signal": {"kind": "file_mtime", "path": "data/runtime/fixture_warm.json"},
    }
    base.update(kw)
    return base


def _signal(root: Path, age_h: float) -> None:
    p = root / "data" / "runtime" / "fixture_warm.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    t = (NOW - timedelta(hours=age_h)).timestamp()
    os.utime(p, (t, t))


def _ledger(root: Path, rows: list[tuple]) -> Path:
    p = lr.n8n_ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id, mode, state, requested_by, caller_id, requested_at, "
        "started_at, finished_at, exit_code, duration_s, receipt_json)"
    )
    for run_id, lane_id, mode, state, finished_at, exit_code in rows:
        conn.execute(
            "INSERT INTO runs(run_id, lane_id, mode, state, finished_at, exit_code) VALUES (?,?,?,?,?,?)",
            (run_id, lane_id, mode, state, finished_at, exit_code),
        )
    conn.commit()
    conn.close()
    return p


def _receipt(
    root: Path, run_id: str, *, lane_id=LANE, mode="live", state="RUN_DONE", finished_at: datetime, exit_code=0
) -> Path:
    d = lr.n8n_runs_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{run_id}.json"
    p.write_text(
        json.dumps(
            {
                "schema": "RunReceipt@v1",
                "run_id": run_id,
                "lane_id": lane_id,
                "mode": mode,
                "state": state,
                "exit_code": exit_code,
                "finished_at": finished_at.isoformat(),
            }
        )
    )
    return p


@pytest.fixture(autouse=True)
def _no_live_ledger(monkeypatch):
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)


# ── validation ────────────────────────────────────────────────────────────────────────────────


def test_n8n_is_a_scheduler_kind_and_requires_expression_and_match():
    assert "n8n" in lr.SCHEDULER_KINDS
    assert lr.validate_row(_row()) == []
    errs = lr.validate_row(_row(scheduler={"kind": "n8n", "expression": "wf-abc123"}))
    assert any("scheduler.match is required for kind=n8n" in e for e in errs)
    errs = lr.validate_row(_row(scheduler={"kind": "n8n", "match": MATCH}))
    assert any("scheduler.expression is required" in e for e in errs)
    assert any(
        "scheduler.kind must be one of" in e
        for e in lr.validate_row(_row(scheduler={"kind": "airflow", "expression": "x"}))
    )


def test_the_monitor_labels_the_scheduler_n8n_colon_workflow_id(tmp_path):
    _signal(tmp_path, 0.2)
    _receipt(tmp_path, "r1", finished_at=NOW - timedelta(minutes=10))
    v = lr.evaluate_lane(_row(), now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)
    assert v["scheduler_label"] == "n8n:wf-abc123"
    assert lr.scheduler_label({"kind": "cron", "expression": "*/8 * * * * x.py"}) == "cron:*/8 * * * * x.py"


# ── scheduler presence from the ledger / receipts ─────────────────────────────────────────────


def test_a_fresh_run_done_ledger_row_proves_the_scheduler_and_the_lane_is_live(tmp_path):
    _signal(tmp_path, 0.2)
    _ledger(
        tmp_path,
        [
            ("r1", LANE, "live", "RUN_DONE", (NOW - timedelta(minutes=20)).isoformat(), 0),
            ("r0", "other-lane", "live", "RUN_DONE", (NOW - timedelta(minutes=1)).isoformat(), 0),
        ],
    )
    v = lr.evaluate_lane(_row(), now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)
    assert v["scheduler_present"] is True and v["verdict"] == lr.LIVE
    assert v["n8n_last_run"]["run_id"] == "r1" and v["n8n_last_run"]["source"] == "ledger"


def test_a_run_skipped_lock_row_also_counts_as_the_scheduler_firing(tmp_path):
    _signal(tmp_path, 0.2)
    _ledger(tmp_path, [("r1", LANE, "live", "RUN_SKIPPED_LOCK", (NOW - timedelta(minutes=5)).isoformat(), 0)])
    assert (
        lr.evaluate_lane(_row(), now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)["scheduler_present"] is True
    )


def test_a_stale_or_failed_run_does_not_prove_the_scheduler_so_the_lane_is_orphaned(tmp_path):
    _signal(tmp_path, 0.2)
    _ledger(
        tmp_path,
        [
            ("old", LANE, "live", "RUN_DONE", (NOW - timedelta(hours=3)).isoformat(), 0),
            ("bad", LANE, "live", "RUN_FAILED", (NOW - timedelta(minutes=5)).isoformat(), 1),
        ],
    )
    v = lr.evaluate_lane(_row(), now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)
    assert v["scheduler_present"] is False and v["verdict"] == lr.ORPHANED
    # the report still names the newest run of ANY state so a failing n8n lane is not a bare ORPHANED
    assert v["n8n_last_run"]["state"] == "RUN_FAILED" and v["n8n_last_run"]["run_id"] == "bad"


def test_without_a_ledger_the_newest_run_receipt_file_is_the_evidence(tmp_path):
    _signal(tmp_path, 0.2)
    _receipt(tmp_path, "r-old", finished_at=NOW - timedelta(hours=5))
    _receipt(tmp_path, "r-new", finished_at=NOW - timedelta(minutes=15), mode="dry_run")
    _receipt(tmp_path, "r-other", lane_id="someone-else", finished_at=NOW)
    last = lr.n8n_last_run(LANE, root=tmp_path)
    assert last["run_id"] == "r-new" and last["source"] == "receipt"
    assert lr.evaluate_lane(_row(), now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)["verdict"] == lr.LIVE


def test_neither_ledger_nor_receipt_means_orphaned_and_a_bad_sqlite_file_falls_back(tmp_path):
    _signal(tmp_path, 0.2)
    v = lr.evaluate_lane(_row(), now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)
    assert v["verdict"] == lr.ORPHANED and v["n8n_last_run"] is None
    p = lr.n8n_ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a database")
    _receipt(tmp_path, "r1", finished_at=NOW - timedelta(minutes=1))
    assert lr.n8n_last_run(LANE, root=tmp_path)["source"] == "receipt"


def test_a_ledger_without_a_runs_table_falls_back_to_receipts(tmp_path):
    p = lr.n8n_ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(p).execute("CREATE TABLE nonces(nonce TEXT PRIMARY KEY)").connection.commit()
    _receipt(tmp_path, "r1", finished_at=NOW - timedelta(minutes=1))
    assert lr.n8n_last_run(LANE, root=tmp_path)["source"] == "receipt"


# ── the n8n-cutover retirement tag ────────────────────────────────────────────────────────────


def test_the_retired_n8n_cutover_tag_is_a_retirement_not_a_running_job():
    text = f"# RETIRED 2026-10-08 n8n-cutover {LANE} {LINE}\n0 4 * * * /bin/false\n"
    assert [c["expression"] for c in lr.discover_cron(text)] == ["0 4 * * * /bin/false"]
    got = lr.discover_commented_cron(text)
    assert got[0]["retired_lane_id"] == LANE and got[0]["retired_on"] == "2026-10-08"
    assert "n8n-cutover" in got[0]["tags"] and "RETIRED 2026-10-08" in got[0]["tags"]
    assert lr.n8n_cutover_tag(f"# RETIRED 2026-10-08 n8n-cutover {LANE} {LINE}") == {
        "date": "2026-10-08",
        "lane_id": LANE,
    }
    assert lr.n8n_cutover_tag(f"# RETIRED 2026-10-08 tranche-b stage {LINE}") is None
    reg = {"lanes": [_row()], "undeclared_baseline": []}
    assert lr.find_undeclared(reg, lr.discover_all(cron_text=text, include_systemd=False)) == [
        {"kind": "cron", "expression": "0 4 * * * /bin/false"}
    ]


# ── double scheduler ──────────────────────────────────────────────────────────────────────────


def test_classifiers_name_the_double_scheduler():
    assert (
        HC.classify_cron(declared_state="ACTIVE", command_present=True, scheduler_kind="n8n")
        == HC.CRON_PRESENT_WHILE_SCHEDULER_N8N
    )
    assert HC.classify_cron(declared_state="ACTIVE", command_present=False, scheduler_kind="n8n") == HC.ALIGNED
    assert HC.classify_cron(declared_state="ACTIVE", command_present=True) == HC.ALIGNED  # unchanged default
    assert (
        HC.classify_timer(
            declared_state="ACTIVE",
            unit_file_state="enabled",
            sub_state="waiting",
            next_elapse="x",
            recurring=True,
            scheduler_kind="n8n",
        )
        == HC.TIMER_ENABLED_WHILE_SCHEDULER_N8N
    )
    assert (
        HC.classify_timer(
            declared_state="ACTIVE",
            unit_file_state="disabled",
            sub_state="dead",
            next_elapse="",
            recurring=True,
            scheduler_kind="n8n",
        )
        == HC.ALIGNED
    )
    assert (
        HC.classify_timer(
            declared_state="ACTIVE",
            unit_file_state="enabled",
            sub_state="elapsed",
            next_elapse="",
            recurring=False,
            scheduler_kind="n8n",
        )
        == HC.ALIGNED
    )  # spent one-shot
    assert (
        HC.CRON_PRESENT_WHILE_SCHEDULER_N8N in LD.CONFLICT_CODES
        and HC.TIMER_ENABLED_WHILE_SCHEDULER_N8N in LD.CONFLICT_CODES
    )


def test_state_drift_counts_both_n8n_conflicts_and_a_commented_line_is_aligned():
    timer_lane = _row(
        lane_id="fixture-timer",
        scheduler={"kind": "n8n", "expression": "wf-t", "match": "x-fixture.timer", "cadence": "0 19 * * *"},
    )
    host = {
        "timers": {
            "x-fixture.timer": {
                "unit_file_state": "enabled",
                "sub_state": "waiting",
                "next_elapse": "Thu",
                "recurring": True,
            }
        }
    }
    cron_rows = lr.discover_cron(LINE + "\n")
    rows = {r["lane_id"]: r for r in LD.classify_lanes([_row(), timer_lane], cron_rows=cron_rows, host_state=host)}
    assert (
        rows[LANE]["code"] == HC.CRON_PRESENT_WHILE_SCHEDULER_N8N
        and rows[LANE]["evidence"]["workflow_id"] == "wf-abc123"
    )
    assert rows["fixture-timer"]["code"] == HC.TIMER_ENABLED_WHILE_SCHEDULER_N8N
    assert sorted(r["lane_id"] for r in LD.conflicts(list(rows.values()))) == sorted([LANE, "fixture-timer"])
    cron_rows = lr.discover_cron(f"# RETIRED 2026-10-08 n8n-cutover {LANE} {LINE}\n")
    host["timers"]["x-fixture.timer"]["unit_file_state"] = "disabled"
    rows = {r["lane_id"]: r for r in LD.classify_lanes([_row(), timer_lane], cron_rows=cron_rows, host_state=host)}
    assert rows[LANE]["code"] == HC.ALIGNED and rows["fixture-timer"]["code"] == HC.ALIGNED
    unknown = LD.classify_lanes([timer_lane], cron_rows=[], host_state={"timers": {}})[0]
    assert unknown["code"] == LD.NOT_MEASURED


def test_the_gate_fails_on_a_double_scheduler_and_passes_once_the_line_is_retired(tmp_path):
    reg = {"schema": "LaneRegistry@v1", "lanes": [_row()], "undeclared_baseline": []}
    regp = tmp_path / "reg.json"
    regp.write_text(json.dumps(reg))
    disc = tmp_path / "disc.json"
    disc.write_text(json.dumps({"cron": lr.discover_cron(LINE + "\n"), "systemd": []}))
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"timers": {}}))
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "check_lane_registry.py"),
        "--fail-on-new",
        "--state-drift",
        "--registry",
        str(regp),
        "--discovery-json",
        str(disc),
        "--host-state-json",
        str(host),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 1 and "CRON_PRESENT_WHILE_SCHEDULER_N8N" in r.stdout, r.stdout + r.stderr
    disc.write_text(
        json.dumps({"cron": lr.discover_cron(f"# RETIRED 2026-10-08 n8n-cutover {LANE} {LINE}\n"), "systemd": []})
    )
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "lane registry: clean" in r.stdout, r.stdout + r.stderr


def test_native_monitor_rows_do_not_flip_a_host_scheduler():
    """Native monitors, declared N1 ownership and unscheduled reminders remain distinct."""
    reg = lr.load_registry()
    assert lr.validate_registry(reg) == []
    native = {r["lane_id"]: r for r in reg["lanes"] if (r.get("scheduler") or {}).get("kind") == "n8n"}
    monitors = {"n8n-monitor-trade-ai", "n8n-monitor-dof"}
    reminders = {
        "openclaw-reminder-claude-plan-1",
        "openclaw-reminder-claude-plan-2",
        "openclaw-reminder-supergrok-expiry",
        "openclaw-reminder-sentinelone-earnings",
    }
    migrated = {
        "crontab-snapshot-for-health-agent",
        "n8n-pilot-dispatch",
        "n8n-incident-fanin",
        "n8n-research-intake-consumer",
    }
    assert set(native) == monitors | reminders | migrated
    assert all(native[lane]["state"] == "ACTIVE" for lane in monitors | migrated)
    for lane in migrated:
        assert isinstance(native[lane]["scheduler"].get("cadence"), str)
        assert lr.validate_row(native[lane]) == []
    assert all(native[lane]["state"] == "NEVER_SCHEDULED" for lane in reminders)


@pytest.mark.parametrize(
    "cadence",
    [
        " ".join(["docs"] * 337),
        "*/5 * * * *\n",
        "*/5 * * * *\x1b[0m",
        "٥ * * * *",
        "",
        "* * * *",
        "0 */5 * * * *",
        "61 * * * *",
        "*/0 * * * *",
        "10-2 * * * *",
        "+5 * * * *",
        None,
        ["*/5", "*", "*", "*", "*"],
    ],
    ids=[
        "expanded-directory-list",
        "newline",
        "terminal-escape",
        "non-ascii-digit",
        "empty",
        "four-fields",
        "six-fields",
        "out-of-range",
        "zero-step",
        "descending-range",
        "signed-number",
        "null",
        "list",
    ],
)
def test_n8n_provided_cadence_must_be_a_valid_recurring_cron_expression(cadence):
    row = _row()
    row["scheduler"]["cadence"] = cadence
    errors = lr.validate_row(row)
    assert any("scheduler.cadence" in error for error in errors), errors


@pytest.mark.parametrize(
    "cadence",
    [
        "*/5 * * * *",
        "25 6-18/3 * * 1-5",
        "0,30 9-16 * * 1-5",
        "0 0 29 2 *",
        "0 0 * * 0,7",
        "  */15  * * * *  ",
    ],
)
def test_n8n_valid_recurring_cadence_forms_are_accepted(cadence):
    row = _row()
    row["scheduler"]["cadence"] = cadence
    assert lr.validate_row(row) == []


def test_n8n_legacy_row_can_omit_scheduler_cadence_when_expected_cadence_is_declared():
    row = _row()
    row["scheduler"].pop("cadence")
    assert lr.validate_row(row) == []


@pytest.mark.parametrize(
    ("module", "import_root"),
    [
        ("scripts.lib.lane_registry", ROOT),
        ("lib.lane_registry", ROOT / "scripts"),
        ("lane_registry", ROOT / "scripts" / "lib"),
    ],
)
def test_cadence_validation_preserves_all_import_contracts(tmp_path, module, import_root):
    program = """
import importlib, json, sys
registry = importlib.import_module(sys.argv[1])
row = json.loads(sys.argv[2])
assert registry.validate_row(row) == []
row["scheduler"]["cadence"] = " ".join(["docs"] * 337)
assert any("scheduler.cadence" in error for error in registry.validate_row(row))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, module, json.dumps(_row())],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(import_root)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
