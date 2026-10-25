"""Staged user units are installed by the release itself (2026-10-25, operator: "turn on everything... It
shouldn't need me to turn on anything"). Fixture-only: a fake release, a fake systemctl and a temp unit dir and
state root. No host unit, crontab, journal, Telegram or broker is touched."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import install_staged_units as I  # noqa: E402

COVERS = ["scripts/install_staged_units.py", "config/staged_user_units.json"]
MANIFEST = json.loads((ROOT / "config/staged_user_units.json").read_text(encoding="utf-8"))
WATCHDOG = next(g for g in MANIFEST["groups"] if g["id"] == "cron-outage-watchdog")
RL3 = "safe_flock:2817912-1792876677401655717:refused"

# Stand-in for scripts/cron_outage_watchdog.py: logs each call, honours --dry-run / --ack-refusal / --run.
STUB = r'''
import json, os, sys
from datetime import datetime, timezone
state = os.environ["TRADEAI_STATE_ROOT"]
with open(os.environ["FIXTURE_EVENTS"], "a") as log:
    log.write("script " + " ".join(sys.argv[1:]) + "\n")
now = datetime.now(timezone.utc).isoformat()
if "--dry-run" in sys.argv:
    print(json.dumps({"schema": "CronOutageWatchdog@v1", "mode": "dry_run", "status": "CRIT", "observed_at": now,
                      "refusals": [{"key": "%s"}]}, indent=2))
    raise SystemExit(int(os.environ.get("FIXTURE_DRY_EXIT", "1")))
if "--ack-refusal" in sys.argv:
    if os.environ.get("FIXTURE_ACK_ABSENT"):
        print(json.dumps({"ok": False, "reason": "refusal_key_not_in_current_journal_window"}))
        raise SystemExit(1)
    if "--apply-ack" in sys.argv:
        os.makedirs(state + "/data/runtime", exist_ok=True)
        with open(state + "/data/runtime/cron_outage_watchdog_refusal_acks.jsonl", "a") as acks:
            acks.write(json.dumps({"key": sys.argv[sys.argv.index("--ack-refusal") + 1]}) + "\n")
        print(json.dumps({"ok": True, "mode": "applied"}))
    else:
        print(json.dumps({"ok": True, "mode": "preview"}))
    raise SystemExit(0)
if "--run" in sys.argv:
    os.makedirs(state + "/data/runtime", exist_ok=True)
    with open(state + "/data/runtime/cron_outage_watchdog_latest.json", "w") as out:
        json.dump({"schema": "CronOutageWatchdog@v1", "mode": "monitor", "status": "OK", "observed_at": now}, out)
''' % RL3

FAKE_SYSTEMCTL = r'''#!/usr/bin/env bash
shift  # --user
echo "systemctl $*" >> "$FIXTURE_EVENTS"
active="$FIXTURE_ACTIVE_DIR"
case "$1" in
  is-active) [[ -e "$active/${3:-$2}" ]]; exit $? ;;
  enable) shift; [[ "$1" == "--now" ]] && shift; for u in "$@"; do touch "$active/$u"; done ;;
  disable) shift; [[ "$1" == "--now" ]] && shift; for u in "$@"; do rm -f "$active/$u"; done ;;
  start) cd "$FIXTURE_RELEASE" && "$FIXTURE_PY" scripts/cron_outage_watchdog.py --run ;;
esac
exit 0
'''


@pytest.fixture()
def world(tmp_path, monkeypatch):
    release = tmp_path / "release"
    (release / "config").mkdir(parents=True)
    (release / "scripts").mkdir()
    (release / "ops/systemd").mkdir(parents=True)
    (release / "config/staged_user_units.json").write_text(json.dumps(MANIFEST))
    (release / "config/cron_outage_watchdog.json").write_bytes((ROOT / "config/cron_outage_watchdog.json").read_bytes())
    for unit in WATCHDOG["units"]:
        (release / "ops/systemd" / unit).write_bytes((ROOT / "ops/systemd" / unit).read_bytes())
    (release / "scripts/cron_outage_watchdog.py").write_text(STUB)
    units, state, active = tmp_path / "units", tmp_path / "state", tmp_path / "active"
    units.mkdir(), state.mkdir(), active.mkdir()
    fake = tmp_path / "bin/systemctl"
    fake.parent.mkdir()
    fake.write_text(FAKE_SYSTEMCTL)
    fake.chmod(0o755)
    events = tmp_path / "events.log"
    for key, value in {"TRADEAI_SYSTEMCTL": str(fake), "FIXTURE_EVENTS": str(events), "FIXTURE_ACTIVE_DIR": str(active),
                       "FIXTURE_RELEASE": str(release), "FIXTURE_PY": sys.executable,
                       "TRADEAI_STATE_ROOT": str(state)}.items():
        monkeypatch.setenv(key, value)
    w = type("W", (), {})()
    w.release, w.units, w.state, w.active, w.events = release, units, state, active, events
    w.run = lambda mode="apply": I.main([mode, "--release", str(release), "--unit-dir", str(units), "--state-root", str(state)])
    w.receipt = lambda: json.loads((state / I.RECEIPT).read_text())
    w.log = lambda: events.read_text().splitlines() if events.exists() else []
    return w


# ── the reviewed manifest ────────────────────────────────────────────────────────────────────────────────────


def test_repo_manifest_is_valid_and_admits_only_the_watchdog():
    assert I.validate_manifest(MANIFEST) == []
    assert [g["id"] for g in MANIFEST["groups"]] == ["cron-outage-watchdog"]
    for unit in WATCHDOG["units"]:
        assert (ROOT / WATCHDOG["source_dir"] / unit).is_file()
    assert WATCHDOG["dry_run"]["argv"] == ["scripts/cron_outage_watchdog.py", "--dry-run"]
    ack = WATCHDOG["once"][0]
    assert ack["argv"][ack["argv"].index("--ack-refusal") + 1] == RL3 and ack["apply_flag"] == "--apply-ack"
    cfg = json.loads((ROOT / WATCHDOG["admission"]["config"]).read_text())
    assert cfg["enabled"] is True and cfg["review_status"] == "REVIEWED" and cfg["approved_by"].strip()


def test_watchdog_lane_is_registered_as_a_host_timer_not_n8n():
    from scripts.lib import lane_registry as LRG

    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r["lane_id"] == WATCHDOG["lane_id"])
    assert LRG.validate_row(row) == []
    assert row["scheduler"]["kind"] == "systemd" and row["scheduler"]["expression"] == WATCHDOG["enable"][0]
    assert row["state"] == "ACTIVE" and row["output_signal"]["path"] == WATCHDOG["verify"]["receipt"]
    timer = (ROOT / "ops/systemd/tradeai-cron-outage-watchdog.timer").read_text()
    service = (ROOT / "ops/systemd/tradeai-cron-outage-watchdog.service").read_text()
    assert "OnCalendar=*-*-* *:*:00" in timer
    assert "--run --send-alerts" in service and "safe_flock" not in service.split("ExecStart=")[1].split("\n")[0]
    assert "n8n" not in service.split("ExecStart=")[1].split("\n")[0]


def test_manifest_validation_rejects_shell_paths_and_missing_dry_run():
    bad = json.loads(json.dumps(MANIFEST))
    bad["groups"][0]["dry_run"] = {}
    bad["groups"][0]["once"][0]["argv"] = ["/bin/sh", "-c", "true"]
    bad["groups"][0]["units"] = ["../evil.service"]
    errs = I.validate_manifest(bad)
    assert any("dry_run" in e for e in errs) and any("scripts/*.py" in e for e in errs) and any("bare" in e for e in errs)


# ── apply / plan / idempotence ───────────────────────────────────────────────────────────────────────────────


def test_plan_writes_nothing(world, capsys):
    assert world.run("plan") == 0
    assert list(world.units.iterdir()) == [] and not (world.state / I.RECEIPT).exists()
    assert "WOULD_INSTALL" in capsys.readouterr().out
    assert not any(line.startswith("script") for line in world.log())


def test_apply_runs_dry_run_then_ack_then_enables_and_reads_back(world):
    assert world.run() == 0
    log = world.log()
    dry = log.index("script --dry-run")
    preview = next(i for i, x in enumerate(log) if x.startswith("script --ack-refusal") and "--apply-ack" not in x)
    applied = next(i for i, x in enumerate(log) if x.startswith("script --ack-refusal") and x.endswith("--apply-ack"))
    enable = log.index("systemctl enable --now tradeai-cron-outage-watchdog.timer")
    first = log.index("systemctl start tradeai-cron-outage-watchdog.service")
    assert dry < preview < applied < log.index("systemctl daemon-reload") < enable < first
    for unit in WATCHDOG["units"]:
        assert (world.units / unit).read_bytes() == (ROOT / "ops/systemd" / unit).read_bytes()
    receipt = world.receipt()
    group = receipt["groups"][0]
    assert receipt["ok"] is True and group["status"] == "INSTALLED"
    assert group["dry_run"]["exit"] == 1 and group["dry_run"]["summary"]["refusal_keys"] == [RL3]  # quoted, recorded
    assert group["once"][0]["result"] == "APPLIED"
    assert group["verify"]["active"] == {"tradeai-cron-outage-watchdog.timer": True} and group["verify"]["receipt_ok"]
    acks = (world.state / "data/runtime/cron_outage_watchdog_refusal_acks.jsonl").read_text().splitlines()
    assert [json.loads(x)["key"] for x in acks] == [RL3]


def test_second_release_is_unchanged_and_the_ack_runs_once(world):
    assert world.run() == 0
    before = len(world.log())
    assert world.run() == 0
    assert world.receipt()["groups"][0]["status"] == "UNCHANGED"
    assert not any(x.startswith("script") or x.startswith("systemctl enable") for x in world.log()[before:])
    assert len((world.state / "data/runtime/cron_outage_watchdog_refusal_acks.jsonl").read_text().splitlines()) == 1


def test_changed_installed_copy_is_archived_not_deleted(world):
    old = world.units / "tradeai-cron-outage-watchdog.timer"
    old.write_text("[Timer]\nOnCalendar=hourly\n")
    assert world.run() == 0
    archives = list(world.units.glob("archived-staged-units-*"))
    assert len(archives) == 1
    assert (archives[0] / "tradeai-cron-outage-watchdog.timer").read_text() == "[Timer]\nOnCalendar=hourly\n"
    manifest = (archives[0] / "MANIFEST").read_text()
    assert "archived tradeai-cron-outage-watchdog.timer" in manifest and "new tradeai-cron-outage-watchdog.service" in manifest
    assert old.read_bytes() == (ROOT / "ops/systemd/tradeai-cron-outage-watchdog.timer").read_bytes()


def test_failed_dry_run_installs_and_enables_nothing(world, monkeypatch):
    monkeypatch.setenv("FIXTURE_DRY_EXIT", "2")
    assert world.run() == 1
    group = world.receipt()["groups"][0]
    assert group["status"] == "REFUSED_DRY_RUN" and list(world.units.iterdir()) == []
    assert not any(x.startswith("systemctl enable") or "--ack-refusal" in x for x in world.log())


def test_unadmitted_group_is_pending_and_untouched(world):
    cfg = world.release / "config/cron_outage_watchdog.json"
    cfg.write_text(json.dumps(dict(json.loads(cfg.read_text()), enabled=False)))
    assert world.run() == 0
    assert world.receipt()["groups"][0]["status"] == "PENDING_ADMISSION"
    assert list(world.units.iterdir()) == [] and not any(x.startswith("script") for x in world.log())


def test_ack_key_already_gone_is_not_needed_and_remembered(world, monkeypatch):
    monkeypatch.setenv("FIXTURE_ACK_ABSENT", "1")
    assert world.run() == 0
    group = world.receipt()["groups"][0]
    assert group["once"][0]["result"] == "NOT_NEEDED:refusal_key_not_in_current_journal_window"
    state = json.loads((world.state / I.STATE).read_text())
    assert "ack-rl3-safe-flock-refusal-20261025" in state["once_done"]


def test_rollback_disables_and_archives(world):
    assert world.run() == 0
    assert world.run("rollback") == 0
    assert "systemctl disable --now tradeai-cron-outage-watchdog.timer" in world.log()
    assert not (world.units / "tradeai-cron-outage-watchdog.timer").exists()
    archived = list(world.units.glob("archived-staged-units-rollback-*/tradeai-cron-outage-watchdog.timer"))
    assert len(archived) == 1


# ── the deploy calls it on every promote, with no TTY step ──────────────────────────────────────────────────


def _fn(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    return text[start:text.index("\n}\n", start)]


def test_promote_and_rollback_call_the_installer_without_a_tty_ack():
    text = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    promote, rollback, step = _fn(text, "cmd_promote"), _fn(text, "cmd_rollback"), _fn(text, "staged_units_step")
    assert promote.index('restart_root_frozen_units "$dir"') < promote.index('staged_units_step promote "$dir"') \
        < promote.index('write_deploy_receipt true promote ok')
    assert 'staged_units_step rollback "$target" "$rolled_from"' in rollback
    assert "install_staged_units.py" in step and "ACK" not in step
    assert "read -r typed" not in step and "</dev/tty" not in step and "read -r line" in step  # only reads its own output
    assert "return 0" in step.splitlines()[-1]  # never fails a live release


def test_deploy_units_subcommand_is_a_plan(tmp_path):
    text = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    assert 'units)    TRADEAI_STAGED_UNITS_MODE=plan staged_units_step promote' in text
    r = subprocess.run(["bash", "-n", str(ROOT / "scripts/cio_phase2_exact_main_deploy.sh")], capture_output=True)
    assert r.returncode == 0, r.stderr


def test_ci_gate_is_registered():
    from scripts.lib import ci_gates

    names = dict(ci_gates.load_gates(ROOT))
    assert names.get("staged_units_install_20261025") == ["tests/test_staged_units_install_20261025.py"]
