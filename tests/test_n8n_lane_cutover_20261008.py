"""`_cutover.py --lane` (2026-10-08): move one registry lane to n8n and back, per line.

Cutover comments exactly the one crontab line matching the lane's `scheduler.match` with
`# RETIRED <date> n8n-cutover <lane_id> `, flips the row to kind n8n and writes a CutoverReceipt@v1;
rollback uncomments exactly that line and restores the recorded scheduler — never a wholesale
crontab restore. Refusals (exit 2) on 0 / >1 matches, a non-ACTIVE row, a row already on n8n, a
missing --workflow-id, or a registry whose serialisation would churn. Hermetic: fake `crontab`
(CRONTAB_CMD), tmp code root with a registry in the committed file's exact format, tmp state root,
tmp lock. The tranche B stage mode keeps its own tests in tests/test_tranche_b_readiness_20261008.py.

COVERS = ["scripts/pipelines/cutover/_cutover.py", "scripts/pipelines/cutover/cutover_lane.sh", "scripts/pipelines/cutover/rollback_lane.sh"]
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CUTOVER = ROOT / "scripts" / "pipelines" / "cutover"
LANE = "fixture-warm"
MATCH = "scripts/fixture_warm.py"
LINE = f"*/8 * * * * cd $PROJ && $PY {MATCH} >> logs/fixture_warm.log 2>&1"
OTHER = "0 9 * * 1-5 cd $PROJ && $PY scripts/untouched.py >> logs/untouched.log 2>&1"
RETIRED = f"# RETIRED 2026-10-08 n8n-cutover {LANE} {LINE}"


def _rows():
    return [
        {
            "lane_id": "untouched",
            "owner": "platform",
            "scheduler": {"kind": "cron", "expression": "0 9 * * 1-5 untouched.py", "match": "scripts/untouched.py"},
            "expected_cadence_hours": 24.0,
            "state": "ACTIVE",
            "output_signal": {"kind": "file_mtime", "path": "logs/untouched.log"},
            "note": "em dash — and ünïcode stay unescaped",
        },
        {
            "lane_id": LANE,
            "owner": "platform",
            "scheduler": {"kind": "cron", "expression": "*/8 * * * * fixture_warm.py", "match": MATCH},
            "expected_cadence_hours": 1.0,
            "state": "ACTIVE",
            "output_signal": {"kind": "file_mtime", "path": "data/runtime/fixture_warm.json"},
        },
        {
            "lane_id": "fixture-timer",
            "owner": "cio",
            "scheduler": {"kind": "systemd", "expression": "x-fixture.timer"},
            "expected_cadence_hours": 24.0,
            "state": "ACTIVE",
            "output_signal": {"kind": "file_mtime", "path": "data/runtime/fixture_timer.json"},
        },
        {
            "lane_id": "fixture-paused",
            "owner": "cio",
            "scheduler": {"kind": "cron", "expression": "1 1 * * * paused.py", "match": "paused.py"},
            "expected_cadence_hours": 24.0,
            "state": "PAUSED",
            "state_reason": "fixture",
            "state_since": "2026-10-01",
            "reason_confidence": "ESTABLISHED",
            "review_by": "2026-11-01",
            "output_signal": {"kind": "file_mtime", "path": "data/runtime/paused.json"},
        },
    ]


def _serialise(doc) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, separators=(",", ": ")) + "\n"


def _code_root(tmp_path: Path, rows=None, raw: str | None = None) -> Path:
    root = tmp_path / "code"
    (root / "config").mkdir(parents=True)
    doc = {
        "schema": "LaneRegistry@v1",
        "authority": "READ_ONLY_ADVISORY",
        "lanes": rows if rows is not None else _rows(),
        "undeclared_baseline": [],
    }
    (root / "config" / "lane_registry.json").write_text(raw if raw is not None else _serialise(doc), encoding="utf-8")
    return root


def _fake_crontab(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "crontab.store"
    fake = tmp_path / "crontab"
    fake.write_text(
        '#!/usr/bin/env bash\nset -e\nif [ "$1" = "-l" ]; then cat "%s"; elif [ "$1" = "-" ]; then cat > "%s"; else exit 64; fi\n'
        % (store, store)
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake, store


def _env(tmp_path: Path, fake: Path, root: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "CRONTAB_CMD": str(fake),
            "BACKUP_DIR": str(tmp_path / "backups"),
            "CUTOVER_DATE": "2026-10-08",
            "CUTOVER_CODE_ROOT": str(root),
            "TRADEAI_STATE_ROOT": str(tmp_path / "state"),
            "N8N_CUTOVER_LOCK": str(tmp_path / "cutover.lock"),
        }
    )
    env.pop("TRADEAI_N8N_COORDINATION_LEDGER", None)
    return env


def _run(script: str, *args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(CUTOVER / script), *args], capture_output=True, text=True, env=env, timeout=60)


def _registry(root: Path) -> dict:
    return json.loads((root / "config" / "lane_registry.json").read_text(encoding="utf-8"))


def _receipts(tmp_path: Path) -> list[Path]:
    d = tmp_path / "state" / "data" / "runtime" / "n8n_cutover"
    return sorted(p for p in d.glob("*.json") if p.name != "n8n_cutover_last.json") if d.is_dir() else []


def _last(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "state" / "data" / "runtime" / "n8n_cutover" / "n8n_cutover_last.json").read_text())


def test_dry_run_writes_only_its_receipt(tmp_path):
    root = _code_root(tmp_path)
    before_reg = (root / "config" / "lane_registry.json").read_bytes()
    fake, store = _fake_crontab(tmp_path)
    before = "\n".join([OTHER, LINE]) + "\n"
    store.write_text(before)
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf-abc123", env=_env(tmp_path, fake, root))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would comment" in r.stdout and "dry-run" in r.stdout
    assert store.read_text() == before and (root / "config" / "lane_registry.json").read_bytes() == before_reg
    assert not (tmp_path / "backups").exists()
    rc = _last(tmp_path)
    assert rc["schema"] == "CutoverReceipt@v1" and rc["applied"] is False and rc["action"] == "cutover"
    assert rc["scheduler_after"] == {"kind": "n8n", "expression": "wf-abc123", "match": MATCH, "cadence": "*/8 * * * *"}
    assert rc["line_after"] == RETIRED and rc["line_before"] == LINE and rc["problems"] == []
    assert _receipts(tmp_path)[0].name.endswith("-cutover-dry-run.json")


def test_apply_comments_the_one_line_flips_the_row_and_leaves_every_other_byte_alone(tmp_path):
    root = _code_root(tmp_path)
    reg_before = (root / "config" / "lane_registry.json").read_text(encoding="utf-8")
    fake, store = _fake_crontab(tmp_path)
    before = "\n".join([OTHER, LINE]) + "\n"
    store.write_text(before)
    env = _env(tmp_path, fake, root)
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf-abc123", "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert store.read_text().splitlines() == [OTHER, RETIRED]  # commented, not deleted
    reg = _registry(root)
    row = next(l for l in reg["lanes"] if l["lane_id"] == LANE)
    assert row["scheduler"] == {"kind": "n8n", "expression": "wf-abc123", "match": MATCH, "cadence": "*/8 * * * *"}
    # byte-for-byte: only the changed row's scheduler differs
    expected = json.loads(reg_before)
    next(l for l in expected["lanes"] if l["lane_id"] == LANE)["scheduler"] = row["scheduler"]
    after_text = (root / "config" / "lane_registry.json").read_text(encoding="utf-8")
    assert after_text == _serialise(expected) and "—" in after_text and "\\u" not in after_text
    rc = _last(tmp_path)
    assert rc["applied"] is True and rc["scheduler_before"] == {
        "kind": "cron",
        "expression": "*/8 * * * * fixture_warm.py",
        "match": MATCH,
    }
    assert rc["registry_sha_before"] != rc["registry_sha_after"] and rc["crontab_backup"]
    assert Path(rc["crontab_backup"]).read_text() == before
    assert rc["code_sha"] and rc["at"] and rc["lane_id"] == LANE
    # the lane gate with --state-drift is clean afterwards (line commented) ...
    disc = tmp_path / "disc.json"
    sys.path.insert(0, str(ROOT))
    from scripts.lib.lane_registry import discover_cron

    disc.write_text(json.dumps({"cron": discover_cron(store.read_text()), "systemd": []}))
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"timers": {}}))
    reg["lanes"] = [l for l in reg["lanes"] if l["lane_id"] in (LANE, "untouched")]
    regp = tmp_path / "reg_check.json"
    regp.write_text(json.dumps(reg))
    gate = [
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
    g = subprocess.run(gate, capture_output=True, text=True, cwd=str(ROOT))
    assert g.returncode == 0, g.stdout + g.stderr
    # ... and a second apply refuses: the row is already on n8n
    r2 = _run("cutover_lane.sh", LANE, "--workflow-id", "wf-abc123", "--apply", env=env)
    assert r2.returncode == 2 and "already kind n8n" in r2.stdout
    assert store.read_text().splitlines() == [OTHER, RETIRED]


def test_refusals_touch_nothing(tmp_path):
    root = _code_root(tmp_path)
    reg_before = (root / "config" / "lane_registry.json").read_bytes()
    fake, store = _fake_crontab(tmp_path)
    env = _env(tmp_path, fake, root)
    # 0 matches
    store.write_text(OTHER + "\n")
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "found on 0 uncommented line(s)" in r.stdout
    # 2 matches
    store.write_text("\n".join([LINE, LINE.replace("*/8", "*/9")]) + "\n")
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "found on 2 uncommented line(s)" in r.stdout
    # already commented
    store.write_text("# " + LINE + "\n")
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "1 commented line(s) also contain it" in r.stdout
    # already tagged for this lane
    store.write_text(RETIRED + "\n" + LINE + "\n")
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "already tagged" in r.stdout
    store.write_text(LINE + "\n")
    # no workflow id
    r = _run("cutover_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 2 and "--workflow-id is required" in r.stdout
    # not ACTIVE / unknown lane
    r = _run("cutover_lane.sh", "fixture-paused", "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "not ACTIVE" in r.stdout
    r = _run("cutover_lane.sh", "no-such-lane", "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "no registry row" in r.stdout
    assert store.read_text() == LINE + "\n" and (root / "config" / "lane_registry.json").read_bytes() == reg_before
    assert not (tmp_path / "backups").exists()
    assert all(p.name.endswith("-refused.json") for p in _receipts(tmp_path)) and _last(tmp_path)["applied"] is False


def test_a_registry_whose_serialisation_would_churn_is_refused(tmp_path):
    doc = {"schema": "LaneRegistry@v1", "lanes": _rows(), "undeclared_baseline": []}
    root = _code_root(tmp_path, raw=json.dumps(doc, indent=2) + "\n")  # ensure_ascii escapes the em dash
    raw_before = (root / "config" / "lane_registry.json").read_bytes()
    fake, store = _fake_crontab(tmp_path)
    store.write_text(LINE + "\n")
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=_env(tmp_path, fake, root))
    assert r.returncode == 2 and "would churn" in r.stdout
    assert (root / "config" / "lane_registry.json").read_bytes() == raw_before and store.read_text() == LINE + "\n"


def test_rollback_uncomments_exactly_that_line_and_restores_the_recorded_scheduler(tmp_path):
    root = _code_root(tmp_path)
    reg_before = (root / "config" / "lane_registry.json").read_text(encoding="utf-8")
    fake, store = _fake_crontab(tmp_path)
    # a second, unrelated retired line and an older tranche-b retirement must survive untouched
    tranche = "# RETIRED 2026-10-07 tranche-b planning 7 16 * * 1-5 cd $PROJ && $PY scripts/planning.py"
    store.write_text("\n".join([tranche, OTHER, LINE]) + "\n")
    env = _env(tmp_path, fake, root)
    assert _run("cutover_lane.sh", LANE, "--workflow-id", "wf-abc123", "--apply", env=env).returncode == 0
    assert store.read_text().splitlines() == [tranche, OTHER, RETIRED]
    # rollback without an applied cutover for another lane refuses
    r = _run("rollback_lane.sh", "untouched", "--apply", env=env)
    assert r.returncode == 2 and "not n8n" in r.stdout
    # dry-run names the line and writes nothing
    r = _run("rollback_lane.sh", LANE, env=env)
    assert r.returncode == 0 and "would uncomment" in r.stdout, r.stdout + r.stderr
    assert store.read_text().splitlines() == [tranche, OTHER, RETIRED]
    assert _last(tmp_path)["action"] == "rollback" and _last(tmp_path)["applied"] is False
    # apply
    r = _run("rollback_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert store.read_text().splitlines() == [tranche, OTHER, LINE]
    assert (root / "config" / "lane_registry.json").read_text(encoding="utf-8") == reg_before  # byte-identical
    rc = _last(tmp_path)
    assert rc["action"] == "rollback" and rc["applied"] is True and rc["line_after"] == LINE
    assert rc["scheduler_after"] == {"kind": "cron", "expression": "*/8 * * * * fixture_warm.py", "match": MATCH}
    assert rc["cutover_receipt"] and Path(rc["cutover_receipt"]).name.endswith("-cutover.json")
    backups = sorted((tmp_path / "backups").glob("crontab-*"))
    assert [b.name.split("-pre-")[1] for b in backups] == [f"cutover-lane-{LANE}.txt", f"rollback-lane-{LANE}.txt"]
    # rolling back twice refuses: the row is cron again
    assert _run("rollback_lane.sh", LANE, "--apply", env=env).returncode == 2


def test_rollback_refuses_when_the_match_is_already_live_or_the_tag_is_missing(tmp_path):
    root = _code_root(tmp_path)
    fake, store = _fake_crontab(tmp_path)
    store.write_text(LINE + "\n")
    env = _env(tmp_path, fake, root)
    assert _run("cutover_lane.sh", LANE, "--workflow-id", "wf-abc123", "--apply", env=env).returncode == 0
    # someone re-added the line by hand: uncommenting would double-schedule
    store.write_text(RETIRED + "\n" + LINE + "\n")
    r = _run("rollback_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 2 and "already live" in r.stdout
    # the tagged line is gone
    store.write_text(OTHER + "\n")
    r = _run("rollback_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 2 and "found 0 line(s) tagged" in r.stdout
    assert _registry(root)["lanes"][1]["scheduler"]["kind"] == "n8n"  # registry untouched by refusals


def test_a_systemd_lane_emits_the_operator_command_and_never_runs_systemctl(tmp_path):
    root = _code_root(tmp_path)
    fake, store = _fake_crontab(tmp_path)
    store.write_text(LINE + "\n")
    env = _env(tmp_path, fake, root)
    r = _run("cutover_lane.sh", "fixture-timer", "--workflow-id", "wf-t", "--apply", env=env)
    assert r.returncode == 2 and "--cadence is required" in r.stdout
    r = _run(
        "cutover_lane.sh", "fixture-timer", "--workflow-id", "wf-t", "--cadence", "30 19 * * *", "--apply", env=env
    )
    assert r.returncode == 0, r.stdout + r.stderr
    rc = _last(tmp_path)
    assert rc["operator_command"] == "systemctl --user disable --now x-fixture.timer" and rc["crontab_backup"] is None
    assert rc["line_before"] is None and rc["applied"] is True
    row = next(l for l in _registry(root)["lanes"] if l["lane_id"] == "fixture-timer")
    assert row["scheduler"] == {
        "kind": "n8n",
        "expression": "wf-t",
        "match": "x-fixture.timer",
        "cadence": "30 19 * * *",
    }
    assert store.read_text() == LINE + "\n"
    r = _run("rollback_lane.sh", "fixture-timer", "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    rc = _last(tmp_path)
    assert rc["operator_command"] == "systemctl --user enable --now x-fixture.timer"
    assert next(l for l in _registry(root)["lanes"] if l["lane_id"] == "fixture-timer")["scheduler"] == {
        "kind": "systemd",
        "expression": "x-fixture.timer",
    }


def test_the_lock_refuses_a_concurrent_cutover(tmp_path):
    import fcntl

    root = _code_root(tmp_path)
    fake, store = _fake_crontab(tmp_path)
    store.write_text(LINE + "\n")
    env = _env(tmp_path, fake, root)
    with open(env["N8N_CUTOVER_LOCK"], "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", env=env)
    assert r.returncode == 2 and "another cutover holds" in (r.stdout + r.stderr)
    assert store.read_text() == LINE + "\n"


def test_stage_mode_and_lane_mode_are_exclusive(tmp_path):
    root = _code_root(tmp_path)
    fake, store = _fake_crontab(tmp_path)
    store.write_text(LINE + "\n")
    env = _env(tmp_path, fake, root)
    r = subprocess.run(
        [sys.executable, str(CUTOVER / "_cutover.py"), "cutover", "premarket", "premarket", "--lane", LANE],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert r.returncode == 2 and "exclusive" in r.stdout
    r = subprocess.run(
        [sys.executable, str(CUTOVER / "_cutover.py"), "cutover"], capture_output=True, text=True, env=env, timeout=60
    )
    assert r.returncode == 2 and "need <pipeline> <stage> or --lane" in r.stdout


@pytest.mark.parametrize("lane_id", [LANE, "fixture-timer"])
@pytest.mark.parametrize(
    "cadence",
    [
        "scripts docs config * *",
        "*/5 * * * *\n",
        "*/5 * * * *\x1b[0m",
        "",
        "* * * *",
        "0 */5 * * * *",
        "61 * * * *",
        "*/0 * * * *",
        "10-2 * * * *",
        "+5 * * * *",
    ],
)
def test_malformed_cadence_apply_refuses_before_scheduler_registry_or_backup_mutation(tmp_path, lane_id, cadence):
    root = _code_root(tmp_path)
    registry_before = (root / "config/lane_registry.json").read_bytes()
    fake, store = _fake_crontab(tmp_path)
    crontab_before = OTHER + "\n" + LINE + "\n"
    store.write_text(crontab_before)
    r = _run(
        "cutover_lane.sh",
        lane_id,
        "--workflow-id",
        "wf-cadence",
        "--cadence",
        cadence,
        "--apply",
        env=_env(tmp_path, fake, root),
    )
    assert r.returncode == 2 and "invalid --cadence" in r.stdout, r.stdout + r.stderr
    assert store.read_text() == crontab_before
    assert (root / "config/lane_registry.json").read_bytes() == registry_before
    assert not (tmp_path / "backups").exists()
    assert _last(tmp_path)["applied"] is False and _last(tmp_path)["scheduler_after"] is None


@pytest.mark.parametrize("cadence", ["*/9 * * * *", "0 * * * *", "*/8 * * * 1-5"])
def test_cron_cadence_override_cannot_change_the_legacy_schedule_during_apply(tmp_path, cadence):
    root = _code_root(tmp_path)
    registry_before = (root / "config/lane_registry.json").read_bytes()
    fake, store = _fake_crontab(tmp_path)
    crontab_before = OTHER + "\n" + LINE + "\n"
    store.write_text(crontab_before)
    r = _run(
        "cutover_lane.sh",
        LANE,
        "--workflow-id",
        "wf-cadence",
        "--cadence",
        cadence,
        "--apply",
        env=_env(tmp_path, fake, root),
    )
    assert r.returncode == 2 and "must match the legacy cron schedule" in r.stdout, r.stdout + r.stderr
    assert store.read_text() == crontab_before
    assert (root / "config/lane_registry.json").read_bytes() == registry_before
    assert not (tmp_path / "backups").exists()
    assert _last(tmp_path)["applied"] is False


@pytest.mark.parametrize("prefix", ["*/0 * * * *", "@reboot"])
def test_invalid_or_non_recurring_legacy_schedule_is_not_migrated_to_n8n(tmp_path, prefix):
    root = _code_root(tmp_path)
    registry_before = (root / "config/lane_registry.json").read_bytes()
    fake, store = _fake_crontab(tmp_path)
    crontab_before = prefix + " " + LINE.split(" ", 5)[5] + "\n"
    store.write_text(crontab_before)
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf-cadence", "--apply", env=_env(tmp_path, fake, root))
    assert r.returncode == 2 and "invalid legacy cron schedule" in r.stdout, r.stdout + r.stderr
    assert store.read_text() == crontab_before
    assert (root / "config/lane_registry.json").read_bytes() == registry_before
    assert not (tmp_path / "backups").exists()
    assert _last(tmp_path)["applied"] is False


def test_matching_cron_cadence_accepts_spacing_and_records_the_legacy_schedule(tmp_path):
    root = _code_root(tmp_path)
    fake, store = _fake_crontab(tmp_path)
    store.write_text(LINE + "\n")
    r = _run(
        "cutover_lane.sh",
        LANE,
        "--workflow-id",
        "wf-cadence",
        "--cadence",
        "  */8  * * * *  ",
        "--apply",
        env=_env(tmp_path, fake, root),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert store.read_text() == RETIRED + "\n"
    assert _last(tmp_path)["scheduler_after"]["cadence"] == "*/8 * * * *"
    assert _registry(root)["lanes"][1]["scheduler"]["cadence"] == "*/8 * * * *"
