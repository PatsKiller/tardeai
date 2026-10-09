"""n8n / scheduler defects from the 2026-10-09 automation audit (operator: "fix the broken cron jobs and push live").

1. tradeai-n8n-lab-watchdog.service went FAILED whenever the executor's n8n-lab-watchdog-shadow dry_run held the
   shared lock (10-08 15:15/15:30, 10-09 15:00): the unit now waits briefly and a still-held lock is a clean skip.
2. The legacy n8n monitor rows said ACTIVE after their workflows were deactivated, and the lane gate said "clean":
   the rows are RETIRED and the gate now flags an ACTIVE kind-n8n row whose workflow is not active.
3. The migration board read n8n-pilot-dispatch as ROLLED_BACK: its rollback and re-cutover receipts share a second.
4. The run executor had no retry: an opt-in, bounded per-lane policy (default off).
5. cleanup_stale_locks.sh deleted holder-less flock files (which never block) and opened a double-run race.
Fakes and tmp files only: no live ledger, no crontab, no n8n, no /tmp lock is touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_migration_board as B  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_registry as lr  # noqa: E402


# ── 1. watchdog unit: a lock miss is a skip, not a failure ─────────────────────────────────────────


def test_watchdog_unit_waits_then_skips_cleanly_on_the_shared_lock():
    unit = (ROOT / "config/systemd/user/tradeai-n8n-lab-watchdog.service").read_text(encoding="utf-8")
    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "/usr/bin/flock -w 10 -E 75 /tmp/tradeai-n8n-lab-watchdog.lock" in exec_start
    assert " -n " not in exec_start
    assert "SuccessExitStatus=75" in unit
    # the wait fits inside the unit's start timeout
    assert "TimeoutStartSec=20" in unit
    allow = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
    shadow = next(e for e in allow["lanes"] if e["lane_id"] == "n8n-lab-watchdog")
    assert shadow["lock"] == "/tmp/tradeai-n8n-lab-watchdog.lock"  # still lock-equivalent with the unit


def test_flock_conflict_exit_is_75_for_real(tmp_path):
    lock = tmp_path / "w.lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "3"])
    try:
        for _ in range(50):
            if subprocess.run(["flock", "-n", str(lock), "true"]).returncode != 0:
                break
        r = subprocess.run(["flock", "-w", "0.2", "-E", "75", str(lock), "true"])
        assert r.returncode == 75
    finally:
        holder.kill()
        holder.wait()


# ── 2. ACTIVE kind-n8n rows need an active workflow ────────────────────────────────────────────────


def _n8n_row(lane, wid, state="ACTIVE"):
    row = {
        "lane_id": lane,
        "owner": "platform",
        "state": state,
        "scheduler": {"kind": "n8n", "expression": wid, "match": f"scripts/{lane}.py", "cadence": "*/5 * * * *"},
        "expected_cadence_hours": 0.0833,
        "output_signal": {"kind": "none", "reason": "NO_SIGNAL_WITH_REASON: test"},
    }
    if state != "ACTIVE":
        row.update(state_since="2026-10-09", state_reason="test", reason_confidence="ESTABLISHED")
    return row


def test_inactive_workflow_rows_are_found_only_when_n8n_was_looked_at():
    reg = {
        "lanes": [
            _n8n_row("live-lane", "wf-on"),
            _n8n_row("dead-lane", "wf-off"),
            _n8n_row("retired-lane", "wf-gone", state="RETIRED"),
        ]
    }
    found = {"n8n": [{"kind": "n8n", "expression": "wf-on"}]}
    got = lr.find_inactive_n8n_rows(reg, found)
    assert [(g["lane_id"], g["code"]) for g in got] == [("dead-lane", lr.INACTIVE_N8N_WORKFLOW)]
    assert lr.find_inactive_n8n_rows(reg, {"cron": []}) == []  # not measured is not "fine", nor a finding


def test_the_gate_fails_on_an_active_row_whose_workflow_is_inactive(tmp_path):
    reg = {"schema": "LaneRegistry@v1", "lanes": [_n8n_row("dead-lane", "wf-off")], "undeclared_baseline": []}
    regp = tmp_path / "reg.json"
    regp.write_text(json.dumps(reg))
    disc = tmp_path / "disc.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts/check_lane_registry.py"),
        "--fail-on-new",
        "--registry",
        str(regp),
        "--discovery-json",
        str(disc),
        "--n8n-index",
        str(tmp_path / "none.json"),
    ]
    disc.write_text(json.dumps({"cron": [], "systemd": [], "n8n": [{"kind": "n8n", "expression": "wf-other"}]}))
    (tmp_path / "none.json").write_text(json.dumps({"workflows": []}))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 1 and "INACTIVE" not in r.stderr and "workflow wf-off is not active" in r.stdout, (
        r.stdout + r.stderr
    )
    disc.write_text(json.dumps({"cron": [], "systemd": [], "n8n": [{"kind": "n8n", "expression": "wf-off"}]}))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "lane registry: clean" in r.stdout, r.stdout + r.stderr


def test_registry_monitor_rows_are_retired_with_evidence_and_the_committed_gate_is_clean():
    reg = lr.load_registry()
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    for lane in ("n8n-monitor-trade-ai", "n8n-monitor-dof"):
        row = rows[lane]
        assert row["state"] == "RETIRED" and row["state_since"] == "2026-10-09"
        assert row["reason_confidence"] == "ESTABLISHED" and "13:04Z" in row["reason_evidence"]
    snap = json.loads(
        (ROOT / "docs/implementation/n8n-parallel/workflows/active_workflows_snapshot.json").read_text(encoding="utf-8")
    )
    found = {"n8n": [{"expression": w["id"]} for w in snap["workflows"]]}
    assert lr.find_inactive_n8n_rows(reg, found) == []


# ── 3. board: same-second rollback + re-cutover ────────────────────────────────────────────────────


def _receipt(d: Path, name: str, action: str, before: str, after: str, at: str, mtime_ns: int) -> None:
    p = d / name
    p.write_text(
        json.dumps(
            {
                "schema": "CutoverReceipt@v1",
                "lane_id": "pilot",
                "action": action,
                "at": at,
                "applied": True,
                "lane_kind_before": before,
                "scheduler_after": {"kind": after},
            }
        )
    )
    os.utime(p, ns=(mtime_ns, mtime_ns))


def test_same_second_rollback_then_recutover_reads_cut_over(tmp_path):
    d = tmp_path / B.CUTOVER_DIR_REL
    d.mkdir(parents=True)
    _receipt(d, "pilot-20261009T020135Z-cutover.json", "cutover", "cron", "n8n", "2026-10-09T02:01:34+00:00", 1)
    # file-name order puts the rollback last; the chain says it came first (n8n -> cron, then cron -> n8n)
    _receipt(d, "pilot-20261009T020145Z-cutover.json", "cutover", "cron", "n8n", "2026-10-09T02:01:45+00:00", 3)
    _receipt(d, "pilot-20261009T020145Z-rollback.json", "rollback", "n8n", "cron", "2026-10-09T02:01:45+00:00", 2)
    # an inverse pair is chain-ambiguous: the write time decides when nothing else is known ...
    assert B._cutover_receipts(tmp_path)["pilot"]["action"] == "cutover"
    # ... and the registry's current kind decides even when the write times are inverted (copied files)
    os.utime(d / "pilot-20261009T020145Z-rollback.json", ns=(9, 9))
    assert B._cutover_receipts(tmp_path)["pilot"]["action"] == "rollback"  # mtime alone: wrong
    assert B._cutover_receipts(tmp_path, {"pilot": "n8n"})["pilot"]["action"] == "cutover"
    assert B._cutover_receipts(tmp_path, {"pilot": "cron"})["pilot"]["action"] == "rollback"


def test_board_reads_pilot_dispatch_cut_over_from_the_real_receipt_shapes(tmp_path):
    d = tmp_path / B.CUTOVER_DIR_REL
    d.mkdir(parents=True)
    _receipt(d, "pilot-20261009T020145Z-cutover.json", "cutover", "cron", "n8n", "2026-10-09T02:01:45+00:00", 2)
    _receipt(d, "pilot-20261009T020145Z-rollback.json", "rollback", "n8n", "cron", "2026-10-09T02:01:45+00:00", 1)
    reg = {"lanes": [_n8n_row("pilot", "wf-1")]}
    tranches = {"tranches": {"N1": {"lanes": [{"lane_id": "pilot"}]}}}
    board = B.build_board(
        root=tmp_path, registry=reg, tranches=tranches, ledger=tmp_path / "none.sqlite", cron_text="", units=[]
    )
    row = next(r for r in board["lanes"] if r["lane_id"] == "pilot")
    assert row["phase"] == "CUT_OVER"


def test_a_real_later_rollback_still_reads_rolled_back(tmp_path):
    d = tmp_path / B.CUTOVER_DIR_REL
    d.mkdir(parents=True)
    _receipt(d, "pilot-a-cutover.json", "cutover", "cron", "n8n", "2026-10-09T02:01:34+00:00", 1)
    _receipt(d, "pilot-b-rollback.json", "rollback", "n8n", "cron", "2026-10-09T02:05:00+00:00", 2)
    assert B._cutover_receipts(tmp_path)["pilot"]["action"] == "rollback"


# ── 4. executor: opt-in bounded retry ──────────────────────────────────────────────────────────────

ENTRY = {
    "lane_id": "lane-x",
    "command": ["$PY", "scripts/x.py"],
    "lock": "/tmp/x.lock",
    "lock_kind": "flock",
    "timeout_s": 30,
    "dry_run_arg": [],
    "live_arg": ["--apply"],
}
ROW = {"run_id": "run-0123456789abcdef", "lane_id": "lane-x", "mode": "live"}


def _runner(codes):
    calls = []

    def run(argv, *, timeout, env, cwd):
        calls.append(argv)
        return SimpleNamespace(returncode=codes[len(calls) - 1], stdout="", stderr="")

    return run, calls


def _exec(entry, codes, tmp_path):
    run, calls = _runner(codes)
    slept = []
    rc = X.execute(ROW, entry, env={}, state_root=tmp_path, code_root=tmp_path, runner=run, sleeper=slept.append)
    return rc, calls, slept


def test_no_retry_by_default(tmp_path):
    rc, calls, slept = _exec(dict(ENTRY), [3, 0], tmp_path)
    assert rc["state"] == "RUN_FAILED" and rc["attempts"] == 1 and len(calls) == 1 and slept == []


def test_opt_in_retry_recovers_and_records_every_attempt(tmp_path):
    entry = dict(ENTRY, retry={"max": 2, "backoff_s": 45})
    rc, calls, slept = _exec(entry, [3, 124, 0], tmp_path)
    assert rc["state"] == "RUN_DONE" and rc["attempts"] == 3
    assert rc["attempt_states"] == ["RUN_FAILED", "RUN_TIMEOUT", "RUN_DONE"] and slept == [45.0, 45.0]


def test_retry_is_bounded_and_skips_do_not_retry(tmp_path):
    rc, calls, _ = _exec(dict(ENTRY, retry={"max": 1}), [3, 3, 0], tmp_path)
    assert rc["state"] == "RUN_FAILED" and rc["attempts"] == 2 and len(calls) == 2
    rc, calls, _ = _exec(dict(ENTRY, retry={"max": 2}), [X.FLOCK_CONFLICT_EXIT, 0], tmp_path)
    assert rc["state"] == "RUN_SKIPPED_LOCK" and rc["attempts"] == 1
    rc, calls, _ = _exec(dict(ENTRY, retry={"max": 2, "on": ["RUN_TIMEOUT"]}), [3, 0], tmp_path)
    assert rc["state"] == "RUN_FAILED" and rc["attempts"] == 1


def test_malformed_retry_policies_are_refused():
    assert X.validate_entry(dict(ENTRY)) is None
    assert X.validate_entry(dict(ENTRY, retry={"max": 1, "backoff_s": 60})) is None
    for bad in (
        {"max": 9},
        {"max": -1},
        {"max": True},
        {"max": 1, "backoff_s": 9999},
        {"max": 1, "on": ["RUN_DONE"]},
        {"max": 1, "on": []},
        "twice",
    ):
        assert X.validate_entry(dict(ENTRY, retry=bad)) == "bad_retry", bad


def test_no_live_allowlist_entry_opts_in_without_review():
    """Retry re-runs a writer: an entry may opt in only in its own reviewed PR. None does in this one."""
    allow = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
    assert [e["lane_id"] for e in allow["lanes"] if "retry" in e] == []
    assert all(X.validate_entry(e) is None for e in allow["lanes"])


# ── 5. lock cleanup never deletes ──────────────────────────────────────────────────────────────────


def test_cleanup_stale_locks_is_report_only():
    src = (ROOT / "scripts/cleanup_stale_locks.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "rm " not in code and "unlink" not in code
    assert "report-only" in code and "exit 0" in code
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts/cleanup_stale_locks.sh")]).returncode == 0
