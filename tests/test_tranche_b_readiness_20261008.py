"""Tranche B cutover readiness (2026-10-08): the readiness report reads only existing evidence, the cutover
scripts refuse unless every absorbed line is present and the stage line is in --dry-run, comment (never
delete) the absorbed lines, and the rollback restores the backup. Hermetic: fixture manifest, fixture
crontab served through a fake `crontab` command (CRONTAB_CMD), fixture logs under a tmp state root."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.report_tranche_b_readiness as R  # noqa: E402

CUTOVER = ROOT / "scripts" / "pipelines" / "cutover"
NOW = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)

LINE_A = "5 16 * * 1-5 cd $PROJ && $PY scripts/fixture_a.py --apply >> logs/fixture_a.log 2>&1"
LINE_B = "7 16 * * 1-5 cd $PROJ && flock -n /tmp/fixture_b.lock $PY scripts/fixture_b.py >> logs/fixture_b.log 2>&1"
STAGE = ("5 16 * * 1-5 cd $PROJ && bash scripts/pipelines/run_after_close_pipeline.sh --stage close-capture --dry-run "
         ">> logs/pipelines/after_close_cron.log 2>&1  # TRADEAI_LANE after-close-pipeline-close-capture")
OTHER = "0 9 * * 1-5 cd $PROJ && $PY scripts/untouched.py >> logs/untouched.log 2>&1"


def _step(sid: str, line: str, log: str, measured: dict) -> dict:
    return {"id": sid, "command": line.split("&& ", 1)[1], "log": log, "timeout": "5m", "continue_on_error": "True",
            "cron_line_verbatim": line, "cron_schedule": line.split(" cd ")[0], "measured": measured}


def _code_root(tmp_path: Path, steps: list[dict], window: str = "16:05-16:30") -> Path:
    root = tmp_path / "code"
    (root / "config" / "pipelines").mkdir(parents=True)
    for name in ("after_close", "premarket", "hermes_learning", "hermes_overnight"):
        stages = {}
        if name == "after_close":
            stages = {"close-capture": {"proposed_schedule": "5 16 * * 1-5", "window": window, "steps": steps}}
        (root / "config" / "pipelines" / f"{name}.json").write_text(json.dumps({"schema": "PipelineManifest@v1", "stages": stages}))
    (root / "config" / "lane_registry.json").write_text(json.dumps({"schema": "LaneRegistry@v1", "lanes": [], "undeclared_baseline": []}))
    return root


def _state(tmp_path: Path, fresh: dict[str, bool]) -> Path:
    st = tmp_path / "state"
    (st / "logs").mkdir(parents=True)
    for name, is_fresh in fresh.items():
        p = st / "logs" / f"{name}.log"
        when = NOW - timedelta(days=1 if is_fresh else 20)
        p.write_text(f"{when.date().isoformat()} ran rc=0\n")
        os.utime(p, (when.timestamp(), when.timestamp()))
    return st


MEASURED_OK = {"verified": True, "source": "safe_flock", "runs": 7, "median_s": 10.0, "p95_s": 20.0}
MEASURED_UB = {"verified": False, "source": "pam_group_max(upper)", "runs": 0, "upper_bound_median_s": 100.0, "upper_bound_p95_s": 2000.0}


def test_go_when_every_line_is_present_fresh_and_the_p95_sum_fits(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK), _step("b", LINE_B, "logs/fixture_b.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    state = _state(tmp_path, {"fixture_a": True, "fixture_b": True})
    text = "\n".join([OTHER, LINE_A, LINE_B, STAGE]) + "\n"
    rows = R.assess_all(text=text, reg={"lanes": []}, state=state, now=NOW, code_root=root)
    r = rows[0]
    assert r["verdict"] == "GO" and r["sum_p95_s"] == 40.0 and r["window_s"] == 1500
    assert r["stage_line"] == {"present": True, "count": 1, "mode": "dry-run"}


def test_no_go_names_the_missing_line_and_the_stale_step(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK), _step("b", LINE_B, "logs/fixture_b.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    state = _state(tmp_path, {"fixture_a": False, "fixture_b": True})
    text = "\n".join([OTHER, LINE_A, STAGE]) + "\n"          # LINE_B absent, fixture_a stale
    r = R.assess_all(text=text, reg={"lanes": []}, state=state, now=NOW, code_root=root)[0]
    assert r["verdict"] == "NO_GO"
    assert r["missing_lines"] == ["b"] and r["stale_steps"] == ["a"]
    assert any("cron line missing: b" in x for x in r["reasons"]) and any("no receipt in 7 d: a" in x for x in r["reasons"])


def test_upper_bound_overflow_is_go_with_notes_not_no_go(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK), _step("b", LINE_B, "logs/fixture_b.log", MEASURED_UB)]
    root = _code_root(tmp_path, steps)
    state = _state(tmp_path, {"fixture_a": True, "fixture_b": True})
    text = "\n".join([LINE_A, LINE_B, STAGE]) + "\n"
    r = R.assess_all(text=text, reg={"lanes": []}, state=state, now=NOW, code_root=root)[0]
    assert r["verdict"] == "GO_WITH_NOTES" and r["unverified"] == ["b"] and not r["fits_p95"] and r["fits_median"]


def test_a_retired_lane_explains_a_missing_line(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    state = _state(tmp_path, {"fixture_a": True})
    reg = {"lanes": [{"lane_id": "fixture-a", "state": "RETIRED", "superseded_by": "platform-maintenance-nightly",
                      "scheduler": {"kind": "cron", "match": "scripts/fixture_a.py"},
                      "output_signal": {"kind": "file_mtime", "path": "logs/fixture_a.log"}}]}
    r = R.assess_all(text=STAGE + "\n", reg=reg, state=state, now=NOW, code_root=root)[0]
    assert r["verdict"] == "NO_GO" and r["absorbed_elsewhere"] == ["a->platform-maintenance-nightly"]


def test_dry_run_writes_nothing_and_write_produces_the_receipt(tmp_path, capsys):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    state = _state(tmp_path, {"fixture_a": True})
    cf = tmp_path / "crontab.txt"
    cf.write_text("\n".join([LINE_A, STAGE]) + "\n")
    assert R.main(["--dry-run", "--crontab-file", str(cf), "--state-root", str(state), "--code-root", str(root), "--now", NOW.isoformat()]) == 0
    assert not (state / R.RECEIPT_REL).exists()
    assert R.main(["--write", "--crontab-file", str(cf), "--state-root", str(state), "--code-root", str(root), "--now", NOW.isoformat()]) == 0
    doc = json.loads((state / R.RECEIPT_REL).read_text())
    assert doc["schema"] == R.SCHEMA and doc["authority"] == "READ_ONLY_ADVISORY" and doc["summary"]["GO"] == 1


# ---- cutover / rollback scripts against a fake crontab -------------------------------------------------

def _fake_crontab(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "crontab.store"
    fake = tmp_path / "crontab"
    fake.write_text('#!/usr/bin/env bash\nset -e\nif [ "$1" = "-l" ]; then cat "%s"; elif [ "$1" = "-" ]; then cat > "%s"; else exit 64; fi\n' % (store, store))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake, store


def _env(tmp_path: Path, fake: Path, root: Path) -> dict:
    env = dict(os.environ)
    env.update({"CRONTAB_CMD": str(fake), "BACKUP_DIR": str(tmp_path / "backups"), "CUTOVER_DATE": "2026-10-08",
                "CUTOVER_CODE_ROOT": str(root)})
    return env


def test_cutover_dry_run_counts_match_the_manifest_and_writes_nothing(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK), _step("b", LINE_B, "logs/fixture_b.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    fake, store = _fake_crontab(tmp_path)
    before = "\n".join([OTHER, LINE_A, LINE_B, STAGE]) + "\n"
    store.write_text(before)
    r = subprocess.run(["bash", str(CUTOVER / "cutover_after_close_close-capture.sh"), "--dry-run"], capture_output=True, text=True,
                       env=_env(tmp_path, fake, root), timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "steps=2 absorbed present=2 missing=0" in r.stdout and r.stdout.count("would comment:") == 2
    assert store.read_text() == before and not (tmp_path / "backups").exists()


def test_cutover_refuses_when_an_absorbed_line_is_missing(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK), _step("b", LINE_B, "logs/fixture_b.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    fake, store = _fake_crontab(tmp_path)
    store.write_text("\n".join([OTHER, LINE_A, STAGE]) + "\n")
    r = subprocess.run(["bash", str(CUTOVER / "cutover_after_close_close-capture.sh"), "--apply"], capture_output=True, text=True,
                       env=_env(tmp_path, fake, root), timeout=60)
    assert r.returncode == 2 and "REFUSED" in r.stdout and "MISSING" in r.stdout
    assert "--dry-run" in store.read_text()        # untouched


def test_cutover_apply_flips_the_stage_comments_the_absorbed_lines_and_rollback_restores(tmp_path):
    steps = [_step("a", LINE_A, "logs/fixture_a.log", MEASURED_OK), _step("b", LINE_B, "logs/fixture_b.log", MEASURED_OK)]
    root = _code_root(tmp_path, steps)
    fake, store = _fake_crontab(tmp_path)
    before = "\n".join([OTHER, LINE_A, LINE_B, STAGE]) + "\n"
    store.write_text(before)
    env = _env(tmp_path, fake, root)
    r = subprocess.run(["bash", str(CUTOVER / "cutover_after_close_close-capture.sh"), "--apply"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    after = store.read_text().splitlines()
    assert OTHER in after                                             # untouched line survives
    assert "# RETIRED 2026-10-08 tranche-b close-capture " + LINE_A in after
    assert "# RETIRED 2026-10-08 tranche-b close-capture " + LINE_B in after
    assert any("--stage close-capture --apply" in ln for ln in after) and not any("--dry-run" in ln for ln in after)
    assert len(after) == 4                                            # nothing deleted
    backups = list((tmp_path / "backups").glob("crontab-*-pre-cutover-close-capture.txt"))
    assert len(backups) == 1 and backups[0].read_text() == before
    # a second apply refuses: the stage is no longer in --dry-run
    r2 = subprocess.run(["bash", str(CUTOVER / "cutover_after_close_close-capture.sh"), "--apply"], capture_output=True, text=True, env=env, timeout=60)
    assert r2.returncode == 2
    # rollback restores the backup byte for byte
    r3 = subprocess.run(["bash", str(CUTOVER / "rollback_after_close_close-capture.sh"), "--apply"], capture_output=True, text=True, env=env, timeout=60)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert store.read_text() == before
