"""Agent 2 W1: schedule evidence, safe routing, and real CLI receipt behaviour."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import scheduled_job_receipt as R  # noqa: E402
from scripts.lib.lane_registry import load_registry, validate_registry  # noqa: E402
from scripts.pipelines.cutover._cutover import load_registry_exact  # noqa: E402

NEW = {
    "alert-daily-digest",
    "ops-daily-digest",
    "ops-weekly-learning-report",
    "system-rollup-snapshot",
    "generate-weekly-docx",
    "generate-analyst-daily-digest",
    "desk-suggestions-digest",
    "rotation-rebalance-digest",
    "job-coverage-monitor",
    "llm-retry-monitor",
    "catalyst-calibration-monitor",
    "source-attribution-monitor",
    "watch-directives-monitor",
    "hermes-pipeline-health",
    "youtube-cookie-health-check",
    "finviz-health-check",
    "crawl-v3-dashboard",
    "alert-missing-conditions",
    "backup-generated-docs",
    "sync-memory-to-drive",
    "commit-hermes-daily",
}


def test_registry_has_all_21_observed_cron_lanes_without_serialisation_churn():
    registry = load_registry(ROOT / "config/lane_registry.json")
    assert validate_registry(registry) == []
    _, _, problem = load_registry_exact(ROOT / "config/lane_registry.json")
    assert problem is None
    rows = {row["lane_id"]: row for row in registry["lanes"]}
    assert NEW <= rows.keys()
    for lane in NEW:
        row = rows[lane]
        assert row["scheduler"]["kind"] == "cron"
        assert len(row["scheduler"]["expression"].split()) == 5
        assert row["scheduler"]["match"]
        assert row["state"] == "ACTIVE"
        assert row["state_since"] == "2026-10-08"
        assert "Observed crontab" in row["note"]
        if row["output_signal"]["kind"] == "none":
            assert "NO_SIGNAL" in row["note"]


def test_native_monitors_record_observed_ids_not_uninstalled_replacements():
    rows = {row["lane_id"]: row for row in load_registry(ROOT / "config/lane_registry.json")["lanes"]}
    exported = json.loads((ROOT / "docs/implementation/n8n-parallel/workflows/INDEX.json").read_text())
    for workflow in exported["workflows"]:
        if workflow["name"] not in {"n8n-monitor-trade-ai", "n8n-monitor-dof"}:
            continue
        row = rows[workflow["name"]]
        assert workflow["active"] is True
        assert row["scheduler"]["kind"] == "n8n"
        assert row["scheduler"]["expression"] == workflow["id"]
        assert row["scheduler"]["cadence"] == "*/5 * * * *"
        assert row["output_signal"]["kind"] == "none"
        assert "NO_SIGNAL" in row["note"] and "not installed" in row["note"]


@pytest.mark.parametrize("result", [0, 7, {"pending": 3, "top": ["do-not-persist"]}])
def test_receipt_keeps_original_result_exit_and_arguments(monkeypatch, tmp_path, result):
    dest = tmp_path / "receipt.json"
    original = ["job.py", "--receipt", str(dest), "--top", "7"]
    monkeypatch.setattr(sys, "argv", original[:])

    def action():
        assert sys.argv == ["job.py", "--top", "7"]
        return result

    assert R.run_with_receipt(action, script="job", root=tmp_path) == result
    assert sys.argv == original
    doc = json.loads(dest.read_text())
    assert doc["schema"] == "ScheduledJobReceipt@v1"
    assert doc["as_of"]
    assert doc["exit"] == (result if isinstance(result, int) else 0)
    assert "do-not-persist" not in dest.read_text()


def test_failure_receipt_does_not_swallow_exception_or_persist_secret(monkeypatch, tmp_path):
    dest = tmp_path / "failed.json"
    monkeypatch.setattr(sys, "argv", ["job.py", "--receipt", str(dest)])

    def fail():
        raise RuntimeError("bearer SHOULD_NOT_BE_STORED")

    with pytest.raises(RuntimeError, match="SHOULD_NOT"):
        R.run_with_receipt(fail, script="job", root=tmp_path)
    doc = json.loads(dest.read_text())
    assert doc["exit"] == 1
    assert doc["summary"] == {"state": "failed", "exception_type": "RuntimeError"}
    assert "SHOULD_NOT" not in dest.read_text()


def test_system_exit_and_atomic_write_failure_preserve_truth(monkeypatch, tmp_path):
    dest = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", ["job.py", "--receipt", str(dest)])

    def fail():
        raise SystemExit(4)

    with pytest.raises(SystemExit) as exc:
        R.run_with_receipt(fail, script="job", root=tmp_path)
    assert exc.value.code == 4
    assert json.loads(dest.read_text())["exit"] == 4
    prior = dest.read_bytes()
    monkeypatch.setattr(
        R.atomic_write_json.__globals__["os"], "replace", lambda *_: (_ for _ in ()).throw(OSError("disk"))
    )
    with pytest.raises(OSError):
        R.run_with_receipt(lambda: 0, script="job", root=tmp_path)
    assert dest.read_bytes() == prior


def test_default_path_is_state_root_and_help_is_not_a_run(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert R.default_receipt("job", ROOT) == tmp_path / "data/runtime/job_last.json"
    monkeypatch.setattr(sys, "argv", ["job.py", "--help"])
    R.run_with_receipt(lambda: 0, script="job", root=ROOT)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "script", ["alert_daily_digest", "desk_suggestions_digest", "job_coverage_monitor", "youtube_cookie_health_check"]
)
def test_legacy_main_with_receipt_cli_runs_hermetically_from_neutral_cwd(tmp_path, script):
    # Import the real main, mock only its source boundary, then exercise the
    # same CLI wrapper used by __main__. No live DB, token, cookie, or sender.
    code = """
import importlib.util, pathlib, sys
sys.path[:0] = [str(pathlib.Path(sys.argv[1]) / 'scripts'), sys.argv[1]]
path = pathlib.Path(sys.argv[1]) / 'scripts' / (sys.argv[2] + '.py')
spec = importlib.util.spec_from_file_location('job_under_test', path)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
if sys.argv[2] == 'alert_daily_digest':
    job._build_message = lambda: None
elif sys.argv[2] == 'job_coverage_monitor':
    job.evaluate = lambda: []
elif sys.argv[2] == 'youtube_cookie_health_check':
    job._auth_cookie_count = lambda: 1
    job._transcript_age_h = lambda: 0
else:
    class Cursor:
        def execute(self, *args): pass
        def fetchall(self): return []
    class Conn:
        def cursor(self): return Cursor()
        def close(self): pass
    job._get_conn = Conn
from lib.scheduled_job_receipt import run_with_receipt
name, receipt = sys.argv[2:4]
sys.argv = [str(path), '--receipt', receipt]
value = run_with_receipt(job.main, script=name, root=path.parent.parent)
raise SystemExit(value if isinstance(value, int) else 0)
"""
    dest = tmp_path / "receipt.json"
    proc = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), script, str(dest)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(dest.read_text())["exit"] == 0
