"""LQ-20261113-3083: the weekly analyst lane is proven by what a run leaves behind, never by exit 0.

Synthetic fixtures only: a temp sqlite ledger with the n8n ``runs`` schema and temp report JSONs.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyst_weekly_proof as awp  # noqa: E402

LANE = awp.LANE
NOW = "2026-01-12T03:00:00+00:00"
START = "2026-01-12T02:15:05+00:00"
END = "2026-01-12T02:40:05+00:00"  # 1500 s


def _ledger(tmp: Path, rows: list[dict]) -> Path:
    path = tmp / "data/governance/n8n_coordination_ledger.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
        "caller_id TEXT, requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, "
        "receipt_json TEXT, slot_key TEXT, attempt INTEGER, parent_run_id TEXT, class TEXT, priority INTEGER, "
        "worker_id TEXT, pid INTEGER, heartbeat_at TEXT, verdict TEXT)"
    )
    for i, r in enumerate(rows):
        receipt = {"timed_out": r.get("timed_out", False), "reason": r.get("reason"), "code_sha": "syn"}
        conn.execute(
            "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, started_at, finished_at, exit_code, "
            "duration_s, receipt_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r.get("run_id", f"syn-{i}"), r.get("lane_id", LANE), r.get("mode", "live"), r["state"],
             r.get("requested_at", START), r.get("started_at", START), r.get("finished_at", END),
             r.get("exit_code", 0), r.get("duration_s", 1500.0), json.dumps(receipt)),
        )
    conn.commit()
    conn.close()
    return path


def _report(tmp: Path, name: str, mode: str | None, at: str | None) -> None:
    d = tmp / "data/portfolios/reports/analyst"
    d.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in (("generation_mode", mode), ("generated_at", at)) if v is not None}
    (d / name).write_text(json.dumps({"meta": meta, "sections": []}))


def _batch(tmp: Path, completed_at: str, generated: int, failed: int = 0, skipped: int = 1) -> None:
    d = tmp / "data/portfolios/reports/analyst/prospectus"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"generated": [{"symbol": f"G{i}"} for i in range(generated)], "failed": [{"symbol": "F"}] * failed,
           "skipped": [{"symbol": "S"}] * skipped, "blocked": [], "eligible": generated + failed + skipped,
           "ok": failed == 0, "completed_at": completed_at}
    (d / "batch_20260111_213000.json").write_text(json.dumps(doc))


def _run(tmp: Path) -> tuple[int, dict]:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = awp.main(["--state-root", str(tmp), "--now", NOW])
    return rc, json.loads(buf.getvalue())


def test_pass_needs_a_report_written_by_the_weekly_generation_inside_the_run(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:20:00+00:00")
    _report(tmp_path, "watchlist_BBB_latest.json", "autonomous_weekly_watchlist", "2026-01-12T02:39:00+00:00")
    _batch(tmp_path, "2026-01-12T02:30:00+00:00", generated=1)
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (0, "PASS"), ev
    assert ev["reports_written"] == 2
    assert {r["file"] for r in ev["reports_sample"]} == {"prospectus_AAA_latest.json", "watchlist_BBB_latest.json"}
    assert ev["holdings_batch"]["generated"] == 1


def test_exit_zero_with_no_artifact_is_fail_not_pass(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE", "exit_code": 0}])
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (1, "FAIL"), ev
    assert "exit 0 is not evidence" in ev["why"]


@pytest.mark.parametrize("mode,at", [
    ("autonomous_full", "2026-01-12T02:20:00+00:00"),       # another lane's generation
    ("urgent", "2026-01-12T02:20:00+00:00"),
    (None, "2026-01-12T02:20:00+00:00"),                    # no mode: not attributable
    ("autonomous_weekly", "2026-01-11T02:20:00+00:00"),     # a week-old weekly report
    ("autonomous_weekly", "2026-01-12T02:42:00+00:00"),     # after the run window (+60 s slack)
    ("autonomous_weekly", None),
])
def test_only_weekly_reports_inside_the_run_window_count(tmp_path, mode, at):
    _ledger(tmp_path, [{"state": "RUN_DONE"}])
    _report(tmp_path, "prospectus_AAA_latest.json", mode, at)
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"], ev["reports_written"]) == (1, "FAIL", 0), ev


def test_over_the_n8n_timeout_is_fail_even_with_reports(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE", "duration_s": 1801.0, "finished_at": "2026-01-12T02:45:06+00:00"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:20:00+00:00")
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (1, "FAIL") and "1800 s" in ev["why"], ev


def test_duration_falls_back_to_the_timestamps(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE", "duration_s": None, "finished_at": "2026-01-12T02:50:06+00:00"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:20:00+00:00")
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (1, "FAIL") and "2101 s" in ev["why"], ev


@pytest.mark.parametrize("row", [
    {"state": "RUN_FAILED", "exit_code": 124, "timed_out": True},
    {"state": "RUN_DONE", "exit_code": 124, "timed_out": True},
    {"state": "RUN_DONE", "exit_code": 1},
    {"state": "RUN_TIMEOUT", "exit_code": None},
    {"state": "RUN_DONE", "exit_code": 0, "timed_out": True},  # the executor's timed_out flag alone decides
])
def test_failed_or_timed_out_fire_is_fail(tmp_path, row):
    _ledger(tmp_path, [row])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:20:00+00:00")
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (1, "FAIL"), ev


def test_lock_skip_is_unproven_even_when_the_lock_holder_wrote_reports(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_SKIPPED_LOCK", "exit_code": 75, "duration_s": 0.03, "reason": "flock_held",
                        "finished_at": "2026-01-12T02:15:06+00:00"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:15:05.500000+00:00")
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (2, "UNPROVEN") and "skipped" in ev["why"], ev


def test_running_fire_is_unproven(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_RUNNING", "finished_at": None, "exit_code": None, "duration_s": None}])
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (2, "UNPROVEN") and "not finished" in ev["why"], ev


def test_a_missed_weekly_slot_is_fail(tmp_path):
    old = "2026-01-03T02:15:05+00:00"  # 9 days before NOW
    _ledger(tmp_path, [{"state": "RUN_DONE", "requested_at": old, "started_at": old,
                        "finished_at": "2026-01-03T02:40:05+00:00"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-03T02:20:00+00:00")
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (1, "FAIL") and "missed" in ev["why"], ev


def test_batch_failures_are_fail(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:20:00+00:00")
    _batch(tmp_path, "2026-01-12T02:30:00+00:00", generated=1, failed=2)
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (1, "FAIL") and "2 failed" in ev["why"], ev


def test_nothing_to_refresh_is_unproven_not_pass(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE"}])
    _batch(tmp_path, "2026-01-12T02:30:00+00:00", generated=0, skipped=26)
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (2, "UNPROVEN") and "nothing to refresh" in ev["why"], ev


def test_unreadable_report_is_unproven_not_fail(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE"}])
    d = tmp_path / "data/portfolios/reports/analyst"
    d.mkdir(parents=True)
    (d / "prospectus_AAA_latest.json").write_text("{not json")
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (2, "UNPROVEN") and ev["unreadable_reports"] == ["prospectus_AAA_latest.json"], ev


def test_the_newest_live_fire_decides_and_dry_runs_and_other_lanes_are_ignored(tmp_path):
    _ledger(tmp_path, [
        {"run_id": "old-ok", "state": "RUN_DONE", "requested_at": "2026-01-05T02:15:05+00:00"},
        {"run_id": "new-bad", "state": "RUN_FAILED", "exit_code": 124, "requested_at": START},
        {"run_id": "dry", "state": "RUN_DONE", "mode": "dry_run", "requested_at": "2026-01-12T02:50:00+00:00"},
        {"run_id": "other", "state": "RUN_DONE", "lane_id": "generate-analyst-reports-autonomous-full",
         "requested_at": "2026-01-12T02:55:00+00:00"},
    ])
    rc, ev = _run(tmp_path)
    assert (rc, ev["run_id"]) == (1, "new-bad"), ev


def test_no_live_fire_is_unproven(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE", "mode": "dry_run"}])
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (2, "UNPROVEN") and "no live run" in ev["why"], ev


def test_missing_ledger_is_unproven(tmp_path):
    rc, ev = _run(tmp_path)
    assert (rc, ev["verdict"]) == (2, "UNPROVEN") and "ledger unreadable" in ev["why"], ev


def test_the_probe_never_writes_the_ledger(tmp_path):
    ledger = _ledger(tmp_path, [{"state": "RUN_DONE"}])
    _report(tmp_path, "prospectus_AAA_latest.json", "autonomous_weekly", "2026-01-12T02:20:00+00:00")
    before = hashlib.sha256(ledger.read_bytes()).hexdigest(), sorted(p.name for p in ledger.parent.iterdir())
    _run(tmp_path)
    after = hashlib.sha256(ledger.read_bytes()).hexdigest(), sorted(p.name for p in ledger.parent.iterdir())
    assert before == after
    src = (ROOT / "scripts/analyst_weekly_proof.py").read_text()
    assert "?mode=ro" in src
    assert "WHERE lane_id = ? AND mode = 'live' ORDER BY requested_at DESC LIMIT 1" in src


def test_cli_exit_codes(tmp_path):
    _ledger(tmp_path, [{"state": "RUN_DONE"}])
    out = subprocess.run([sys.executable, str(ROOT / "scripts/analyst_weekly_proof.py"), "--state-root", str(tmp_path),
                          "--now", NOW], capture_output=True, text=True, timeout=60)
    assert out.returncode == 1 and json.loads(out.stdout)["verdict"] == "FAIL", out.stdout + out.stderr
