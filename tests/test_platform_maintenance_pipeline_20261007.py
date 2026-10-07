"""Proofs for the cron-rank-4 platform maintenance runner (2026-10-07).

The bash runner is exercised through subprocess in a SANDBOX copy of scripts/pipelines (PROJ = tmp_path:
no .env, no live locks, no live logs) with a fake step table supplied via --manifest. The built-in
tables are checked by dry-running the real runner from the repo (it executes nothing and writes nothing).
The purge wrapper is unit-tested against a fake connection — no Postgres, no token manager.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "pipelines" / "run_platform_maintenance_pipeline.sh"
COMMON = ROOT / "scripts" / "pipelines" / "_pipeline_common.sh"
FAKE_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def _sandbox(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "scripts" / "pipelines").mkdir(parents=True)
    shutil.copy(RUNNER, proj / "scripts" / "pipelines" / RUNNER.name)
    shutil.copy(COMMON, proj / "scripts" / "pipelines" / COMMON.name)
    (proj / "GIT_SHA").write_text(FAKE_SHA + "\n")
    (tmp_path / "locks").mkdir()
    return proj


def _env(tmp_path: Path) -> dict:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "LANG": "C.UTF-8",
        "PLATFORM_MAINT_LOCK_DIR": str(tmp_path / "locks"),
        "ALPACA_MODE": "paper",
        "LIVE_TRADING_ENABLED": "false",
    }


def _run(proj: Path, env: dict, *args: str, manifest: Path | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(proj / "scripts" / "pipelines" / RUNNER.name), *args]
    if manifest is not None:
        cmd += ["--manifest", str(manifest)]
    return subprocess.run(cmd, cwd=str(proj), env=env, capture_output=True, text=True, timeout=120)


def _summary(proj: Path, cadence: str) -> Path:
    return proj / "data" / "runtime" / f"platform_maintenance_{cadence}_last.json"


def _write_manifest(tmp_path: Path, lines: list[str]) -> Path:
    m = tmp_path / "manifest.txt"
    m.write_text("# name|timeout|lock|guard|log|env|cmd\n" + "\n".join(lines) + "\n")
    return m


# --- apply: order, continue-on-error, timeout, env, guard, summary shape ---------------------------

def test_apply_runs_in_order_continues_on_error_records_timeout_and_summary(tmp_path):
    proj = _sandbox(tmp_path)
    manifest = _write_manifest(tmp_path, [
        "step_true|1m|||steplogs/true.log||echo hello-from-true",
        "step_false|1m|||||false",
        "step_sleep|1s|||||sleep 3",
        'step_env|1m||||FOO=bar|[ "$FOO" = bar ]',
        "step_guarded|1m||missing/never.txt|||echo never-runs",
        "step_last|1m|||||echo last-still-ran",
    ])
    r = _run(proj, _env(tmp_path), "--cadence", "nightly", "--apply", manifest=manifest)
    assert r.returncode == 0, r.stdout + r.stderr   # continue-on-error; the summary is the signal

    s = json.loads(_summary(proj, "nightly").read_text())
    assert s["schema"] == "PlatformMaintenanceRun@v1"
    assert s["cadence"] == "nightly" and s["dry_run"] is False
    assert s["served_sha"] == FAKE_SHA
    assert set(s) >= {"as_of", "served_sha", "cadence", "steps", "ok", "failed_steps"}

    names = [st["step"] for st in s["steps"]]
    assert names == ["step_true", "step_false", "step_sleep", "step_env", "step_guarded", "step_last"]
    by = {st["step"]: st for st in s["steps"]}
    for st in s["steps"]:
        assert set(st) >= {"step", "rc", "duration_s", "timeout", "skipped_lock", "timed_out", "skipped_missing"}
    assert by["step_true"]["rc"] == 0 and by["step_true"]["timed_out"] is False
    assert by["step_false"]["rc"] == 1
    assert by["step_sleep"]["rc"] in (124, 137) and by["step_sleep"]["timed_out"] is True
    assert by["step_sleep"]["timeout"] == "1s" and by["step_sleep"]["duration_s"] >= 1
    assert by["step_env"]["rc"] == 0                      # manifest env reached the command
    assert by["step_guarded"]["rc"] is None and by["step_guarded"]["skipped_missing"] is True
    assert by["step_last"]["rc"] == 0                     # ran after the failures
    assert s["ok"] is False
    assert s["failed_steps"] == ["step_false", "step_sleep"]
    assert s["skipped_steps"] == ["step_guarded"]

    # the step's own log kept receiving output, and the pipeline log + run dir exist
    assert "hello-from-true" in (proj / "steplogs" / "true.log").read_text()
    log_dir = proj / "logs" / "pipelines" / "platform-maintenance" / "nightly"
    assert list(log_dir.glob("platform_nightly_*.log"))
    assert "hello-from-true" in Path(s["run_dir"], "step_true.out").read_text()
    assert "step END: step_false rc=1" in r.stdout


# --- dry run writes nothing -----------------------------------------------------------------------

def test_dry_run_prints_plan_and_writes_nothing(tmp_path):
    proj = _sandbox(tmp_path)
    manifest = _write_manifest(tmp_path, ["step_touch|1m|||||touch would-have-run.txt"])
    r = _run(proj, _env(tmp_path), "--cadence", "weekly", "--dry-run", manifest=manifest)
    assert r.returncode == 0, r.stderr
    assert "would run:" in r.stdout and "step_touch" in r.stdout
    assert not (proj / "would-have-run.txt").exists()
    assert not _summary(proj, "weekly").exists()
    assert not (proj / "logs" / "pipelines" / "platform-maintenance").exists()
    assert not (tmp_path / "locks" / "pipeline_platform-maintenance-weekly.lock").exists()


def test_default_mode_is_dry_run(tmp_path):
    proj = _sandbox(tmp_path)
    manifest = _write_manifest(tmp_path, ["step_touch|1m|||||touch would-have-run.txt"])
    r = _run(proj, _env(tmp_path), "--cadence", "monthly", manifest=manifest)
    assert r.returncode == 0 and "DRY_RUN" in r.stdout
    assert not (proj / "would-have-run.txt").exists() and not _summary(proj, "monthly").exists()


# --- locks ----------------------------------------------------------------------------------------

def test_pipeline_lock_held_skips_cleanly(tmp_path):
    proj = _sandbox(tmp_path)
    manifest = _write_manifest(tmp_path, ["step_touch|1m|||||touch would-have-run.txt"])
    lock = tmp_path / "locks" / "pipeline_platform-maintenance-nightly.lock"
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run(proj, _env(tmp_path), "--cadence", "nightly", "--apply", manifest=manifest)
    assert r.returncode == 0
    assert "already running" in (r.stdout + r.stderr)
    assert not (proj / "would-have-run.txt").exists()
    assert not _summary(proj, "nightly").exists()


def test_step_lock_held_is_recorded_as_skipped_lock_not_failure(tmp_path):
    proj = _sandbox(tmp_path)
    step_lock = tmp_path / "locks" / "db_retention.lock"
    manifest = _write_manifest(tmp_path, [
        f"locked_step|1m|{step_lock}||||touch locked-ran.txt",
        "free_step|1m|||||echo free",
    ])
    with open(step_lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run(proj, _env(tmp_path), "--cadence", "nightly", "--apply", manifest=manifest)
    assert r.returncode == 0, r.stderr
    s = json.loads(_summary(proj, "nightly").read_text())
    by = {st["step"]: st for st in s["steps"]}
    assert by["locked_step"]["rc"] == 75 and by["locked_step"]["skipped_lock"] is True
    assert by["locked_step"]["lock"] == str(step_lock)
    assert not (proj / "locked-ran.txt").exists()
    assert by["free_step"]["rc"] == 0
    assert s["ok"] is True and s["failed_steps"] == [] and s["skipped_steps"] == ["locked_step"]


# --- argument handling ----------------------------------------------------------------------------

@pytest.mark.parametrize("args", [[], ["--cadence", "daily"], ["--cadence", "all"], ["--bogus"]])
def test_bad_arguments_exit_64(tmp_path, args):
    proj = _sandbox(tmp_path)
    r = _run(proj, _env(tmp_path), *args)
    assert r.returncode == 64
    assert "ERROR" in r.stderr


def test_manifest_env_var_is_honoured(tmp_path):
    proj = _sandbox(tmp_path)
    manifest = _write_manifest(tmp_path, ["only_step|1m|||||echo via-env"])
    env = dict(_env(tmp_path), PLATFORM_MAINT_MANIFEST=str(manifest))
    r = _run(proj, env, "--cadence", "nightly", "--dry-run")
    assert r.returncode == 0 and "only_step" in r.stdout and "rotate_runtime_logs" not in r.stdout


# --- built-in tables = the absorbed crontab lines, in clock order ----------------------------------

def _plan(cadence: str) -> list[dict]:
    env = dict(os.environ, PLATFORM_MAINT_LOCK_DIR="/nonexistent-never-used")
    env.pop("PLATFORM_MAINT_MANIFEST", None)
    r = subprocess.run(["bash", str(RUNNER), "--cadence", cadence, "--dry-run"], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing executed, nothing written" in r.stdout
    steps = []
    for line in r.stdout.splitlines():
        m = re.match(r"\s+\[\d+\] step=(\S+) timeout=(\S+) lock=(\S+) env=(.*?) log=(\S+)", line)
        if m:
            steps.append({"step": m.group(1), "timeout": m.group(2), "lock": m.group(3), "env": m.group(4), "log": m.group(5)})
        elif "would run:" in line:
            steps[-1]["cmd"] = line.split("would run:", 1)[1].strip()
    return steps


def test_builtin_nightly_plan_is_the_absorbed_cron_lines_in_clock_order():
    steps = _plan("nightly")
    assert [s["step"] for s in steps] == [
        "rotate_runtime_logs", "populate_performance_context", "report_platform_conformance",
        "nightly_integrity_sweep", "strategy_config_sync", "siem_retention_purge",
        "hermes_universe_history_retention", "n8n_lab_backup", "db_retention",
        "prune_document_mentions", "report_db_hygiene",
    ]
    by = {s["step"]: s for s in steps}
    # per-step locks preserved from the crontab lines (same /tmp path => no double-run with a leftover line)
    assert by["rotate_runtime_logs"]["lock"] == "/tmp/tradeai_rotate_logs.lock"
    assert by["report_platform_conformance"]["lock"] == "/tmp/tradeai_platform_conformance.lock"
    assert by["hermes_universe_history_retention"]["lock"] == "/tmp/hermes_universe_history_retention.lock"
    assert by["db_retention"]["lock"] == "/tmp/db_retention.lock" and by["db_retention"]["timeout"] == "30m"
    assert by["prune_document_mentions"]["lock"] == "/tmp/document_mentions_prune.lock"
    assert by["prune_document_mentions"]["timeout"] == "20m"
    # args preserved verbatim
    assert by["populate_performance_context"]["cmd"].endswith("scripts/populate_performance_context.py --apply")
    assert by["nightly_integrity_sweep"]["cmd"].endswith("scripts/nightly_integrity_sweep.py --telegram")
    assert by["strategy_config_sync"]["cmd"].endswith("scripts/strategy_config_loader.py --sync-db")
    assert by["hermes_universe_history_retention"]["cmd"].endswith("hermes_universe_history_retention.py --apply")
    assert by["n8n_lab_backup"]["cmd"].endswith("bash scripts/n8n_lab_backup.sh --apply")
    assert by["db_retention"]["cmd"].endswith("scripts/db_retention.py")          # no flag added
    assert by["prune_document_mentions"]["cmd"].endswith("scripts/prune_document_mentions.py --apply")
    assert by["report_platform_conformance"]["cmd"].endswith("scripts/report_platform_conformance.py --write")
    # inline env of crontab line 1045 preserved
    assert "TRADEAI_STATE_ROOT=" in by["report_platform_conformance"]["env"]
    assert re.search(r"TRADEAI_RELEASE_SHA=[0-9a-f]{40}", by["report_platform_conformance"]["env"])
    assert by["report_platform_conformance"]["log"].endswith("persistent-state/logs/platform_conformance.log")
    # the NEW step is guarded on the file existing, never a hard failure
    assert "report_db_hygiene.py --write" in by["report_db_hygiene"]["cmd"]
    for s in steps:
        assert "sync-memory-to-drive" not in s["cmd"] and "sweep_schwab" not in s["cmd"]
        assert "sync-docs-to-drive" not in s["cmd"] and "sync_code_mirror" not in s["cmd"]


def test_builtin_weekly_and_monthly_plans():
    weekly = _plan("weekly")
    assert [s["step"] for s in weekly] == ["docs_retention", "n8n_lab_restore_drill", "check_system_versions"]
    assert weekly[1]["cmd"].endswith("bash scripts/n8n_lab_restore_drill.sh --apply")
    assert weekly[2]["log"].endswith("/logs/version_check.log")
    monthly = _plan("monthly")
    assert [s["step"] for s in monthly] == ["backup_verify", "youtube_transcript_purge"]
    assert monthly[0]["lock"] == "/tmp/backup_verify.lock"
    assert monthly[1]["cmd"].endswith("scripts/purge_youtube_transcripts.py --apply")


def test_proposal_units_point_at_runner_and_are_marked_proposal_only():
    units = ROOT / "config" / "systemd" / "user"
    for cadence, oncal in (("nightly", "*-*-* 01:15:00"), ("weekly", "Sun *-*-* 03:00:00"), ("monthly", "*-*-01 06:00:00")):
        timer = (units / f"tradeai-platform-maintenance-{cadence}.timer").read_text()
        service = (units / f"tradeai-platform-maintenance-{cadence}.service").read_text()
        assert "PROPOSAL ONLY" in timer and "PROPOSAL ONLY" in service
        assert f"OnCalendar={oncal}" in timer
        assert "WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT" in service
        assert "EnvironmentFile=-%t/tradeai/env" not in service  # review 2026-10-07: no secrets env to the unit
        assert f"run_platform_maintenance_pipeline.sh --cadence {cadence} --apply" in service


def test_registry_declares_the_three_lanes_never_scheduled():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lanes = {l["lane_id"]: l for l in reg["lanes"]}
    for cadence in ("nightly", "weekly", "monthly"):
        lane = lanes[f"platform-maintenance-{cadence}"]
        assert lane["state"] == "NEVER_SCHEDULED" and lane["scheduler"]["kind"] == "none"
        assert lane["output_signal"]["path"] == f"data/runtime/platform_maintenance_{cadence}_last.json"
        assert "grant" in lane["state_reason"]


# --- purge wrapper (crontab line 163) against a fake connection ----------------------------------

class _FakeCursor:
    def __init__(self, state):
        self.state = state
        self.executed = []
        self.rowcount = -1
        self._last = None

    def execute(self, sql):
        self.executed.append(sql)
        self._last = sql
        if sql.startswith("DELETE"):
            self.rowcount = self.state["expired"]
            self.state["expired"] = 0

    def fetchone(self):
        if "purge_after IS NULL" in self._last:
            return (self.state["undated"],)
        return (self.state["expired"],)


class _FakeConn:
    def __init__(self, state):
        self.state = state
        self.cur = _FakeCursor(state)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def test_purge_dry_run_counts_only():
    sys.path.insert(0, str(ROOT / "scripts"))
    import purge_youtube_transcripts as p
    conn = _FakeConn({"undated": 5, "expired": 3})
    res = p.purge(conn, apply=False)
    assert res["dry_run"] is True and res["undated_before"] == 5 and res["expired_before"] == 3
    assert res["deleted"] == 0 and conn.commits == 0
    assert not any(sql.startswith("DELETE") for sql in conn.cur.executed)


def test_purge_apply_stamps_deletes_commits_and_writes_receipt(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import purge_youtube_transcripts as p
    state = {"undated": 5, "expired": 3}

    def fake_set_purge_dates():
        state["undated"] = 1   # 4 rows got a date

    conn = _FakeConn(state)
    res = p.purge(conn, apply=True, set_purge_dates=fake_set_purge_dates)
    assert res["stamped"] == 4 and res["deleted"] == 3 and conn.commits == 1
    assert [s for s in conn.cur.executed if s.startswith("DELETE")] == [p.SQL_DELETE_EXPIRED]
    receipt = tmp_path / "runtime" / "youtube_transcript_purge_last.json"
    p.write_receipt(res, receipt)
    on_disk = json.loads(receipt.read_text())
    assert on_disk["schema"] == "YoutubeTranscriptPurge@v1" and on_disk["deleted"] == 3
