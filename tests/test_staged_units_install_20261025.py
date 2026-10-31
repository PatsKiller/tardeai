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

COVERS = ["scripts/install_staged_units.py", "config/staged_user_units.json", "scripts/lib/needs_action.py",
          "scripts/lib/platform_health.py"]
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
    sent: list[str] = []
    monkeypatch.setattr(I, "telegram_p1", lambda body: sent.append(body) or {"status": "DELIVERED", "accepted": True,
                                                                             "delivered": True})
    w = type("W", (), {})()
    w.sent = sent
    w.release, w.units, w.state, w.active, w.events = release, units, state, active, events
    w.run = lambda mode="apply": I.main([mode, "--release", str(release), "--unit-dir", str(units), "--state-root", str(state)])
    w.receipt = lambda: json.loads((state / I.RECEIPT).read_text())
    w.log = lambda: events.read_text().splitlines() if events.exists() else []
    return w


# ── the reviewed manifest ────────────────────────────────────────────────────────────────────────────────────


def test_repo_manifest_is_valid_and_lists_the_reviewed_groups():
    assert I.validate_manifest(MANIFEST) == []
    # 2026-10-25: the self-heal lanes (AGENTS.md 21.0.0 section 28.14) ride the same mechanism; their own contract is
    # pinned by tests/test_self_heal_staged_units_20261025.py
    assert [g["id"] for g in MANIFEST["groups"]] == ["cron-outage-watchdog", "self-heal-train-monitor", "self-heal-fixer"]
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
    promote, rollback = _fn(text, "cmd_promote"), _fn(text, "cmd_rollback")
    step = _fn(text, "staged_units_step") + _fn(text, "staged_units_run")
    assert promote.index('restart_root_frozen_units "$dir"') < promote.index('staged_units_step promote "$dir"') \
        < promote.index('write_deploy_receipt true promote ok')
    assert 'staged_units_step rollback "$target" "$rolled_from"' in rollback
    assert "install_staged_units.py" in step and "ACK" not in step
    assert "read -r typed" not in step and "</dev/tty" not in step and "read -r line" in step  # only reads its own output
    for fn in ("staged_units_step", "staged_units_run"):  # never fails a live release
        assert _fn(text, fn).splitlines()[-1].strip() == "return 0"


def test_deploy_units_subcommand_is_a_plan(tmp_path):
    text = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    assert 'units)    TRADEAI_STAGED_UNITS_MODE=plan staged_units_step promote' in text
    r = subprocess.run(["bash", "-n", str(ROOT / "scripts/cio_phase2_exact_main_deploy.sh")], capture_output=True)
    assert r.returncode == 0, r.stderr


def test_ci_gate_is_registered():
    from scripts.lib import ci_gates

    names = dict(ci_gates.load_gates(ROOT))
    assert names.get("staged_units_install_20261025") == ["tests/test_staged_units_install_20261025.py"]


# ── review fixes (#2134 B1/B2/F1-F5) ────────────────────────────────────────────────────────────────────────

GOOD_SERVICE = (ROOT / "ops/systemd/tradeai-cron-outage-watchdog.service").read_text()
GOOD_TIMER = (ROOT / "ops/systemd/tradeai-cron-outage-watchdog.timer").read_text()
UNITS = ["tradeai-cron-outage-watchdog.service", "tradeai-cron-outage-watchdog.timer"]


def test_reviewed_units_pass_validation_and_use_the_release_venv():
    assert I.validate_unit_text(UNITS[0], GOOD_SERVICE, UNITS) == []
    assert I.validate_unit_text(UNITS[1], GOOD_TIMER, UNITS) == []
    assert "ExecStart=%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python scripts/cron_outage_watchdog.py" \
        in GOOD_SERVICE and "trade-ai-v12-rebuild" not in GOOD_SERVICE
    assert "SuccessExitStatus=1\n" in GOOD_SERVICE


@pytest.mark.parametrize("mutate, needle", [
    (lambda t: t.replace("CURRENT/.venv/bin/python", "CURRENT/.venv/bin/python3x"), "must run %h/"),
    (lambda t: t.replace("ExecStart=%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python",
                         "ExecStart=%h/dev-tree/.venv/bin/python"), "must run %h/"),
    (lambda t: t.replace("scripts/cron_outage_watchdog.py", "/tmp/x.py"), "release scripts/"),
    (lambda t: t.replace("scripts/cron_outage_watchdog.py", "scripts/../x.py"), "release scripts/"),
    (lambda t: t.replace("--send-alerts", "--send-alerts; rm x"), "shell syntax"),
    (lambda t: t.replace("[Service]\n", "[Service]\nUser=root\n"), "User= not allowed"),
    (lambda t: t.replace("[Service]\n", "[Service]\nExecStartPre=/bin/sh -c true\n"), "ExecStartPre= not allowed"),
    (lambda t: t.replace("[Service]\n", "[Service]\nExecStop=/bin/true\n"), "ExecStop= not allowed"),
    (lambda t: t + "ExecStart=%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python scripts/y.py\n", "exactly one"),
    (lambda t: t + "\n[Install]\nWantedBy=multi-user.target\n", "WantedBy=multi-user.target"),
    (lambda t: t + "\n[Install]\nAlias=x.service\n", "Alias= not allowed"),
])
def test_service_refusals(mutate, needle):
    errs = I.validate_unit_text(UNITS[0], mutate(GOOD_SERVICE), UNITS)
    assert any(needle in e for e in errs), errs


def test_timer_refusals():
    assert I.validate_unit_text(UNITS[1], GOOD_TIMER.replace("Unit=tradeai-cron-outage-watchdog.service",
                                                             "Unit=other.service"), UNITS)
    assert I.validate_unit_text(UNITS[1], GOOD_TIMER.replace("timers.target", "graphical.target"), UNITS)
    assert I.validate_unit_text("x.path", "[Path]\nPathChanged=/tmp\n", UNITS)


def test_manifest_source_dir_is_pinned_to_ops_systemd():
    bad = json.loads(json.dumps(MANIFEST))
    bad["groups"][0]["source_dir"] = "config/systemd/user"
    assert any("source_dir must be ops/systemd" in e for e in I.validate_manifest(bad))


def test_invalid_unit_is_refused_before_anything_runs(world):
    (world.release / "ops/systemd" / UNITS[0]).write_text(GOOD_SERVICE.replace("[Service]\n", "[Service]\nUser=root\n"))
    assert world.run() == 1
    group = world.receipt()["groups"][0]
    assert group["status"] == "REFUSED_UNIT" and "User=" in group["reason"]
    assert list(world.units.iterdir()) == [] and not any(x.startswith("script") for x in world.log())


def test_failure_sends_one_p1_and_dedupes_then_clears_on_recovery(world, monkeypatch):
    monkeypatch.setenv("FIXTURE_DRY_EXIT", "2")
    assert world.run() == 1 and world.run() == 1
    assert len(world.sent) == 1 and "STAGED UNIT INSTALL FAILED" in world.sent[0] and "REFUSED_DRY_RUN" in world.sent[0]
    assert world.receipt()["notification"]["status"] == "DUPLICATE_SUPPRESSED"
    monkeypatch.setenv("FIXTURE_DRY_EXIT", "1")
    assert world.run() == 0 and len(world.sent) == 1
    assert "notified_failure" not in json.loads((world.state / I.STATE).read_text())


def test_will_page_lists_findings_beyond_the_one_time_ack():
    doc = {"missed_lane_ids": ["lane-a"], "refusals": [{"key": RL3, "job_id": "rl3", "active": True},
                                                       {"key": "k2", "job_id": "job2", "active": True}],
           "monitor_incidents": [{"id": "wrapper_journal_unavailable"}]}
    assert I.will_page(doc, WATCHDOG) == ["missed:lane-a", "refusal:job2:k2", "monitor:wrapper_journal_unavailable"]
    assert I.will_page({"missed_lane_ids": [], "refusals": [{"key": RL3, "active": True}]}, WATCHDOG) == []


def test_will_page_is_recorded_and_printed(world, capsys):
    stub = (world.release / "scripts/cron_outage_watchdog.py")
    stub.write_text(stub.read_text().replace('"refusals": [{"key": "%s"}]' % RL3,
                                             '"refusals": [{"key": "%s"}], "missed_lane_ids": ["lane-x"]' % RL3))
    assert world.run() == 0
    assert world.receipt()["groups"][0]["will_page"] == ["missed:lane-x"]
    assert "will page: missed:lane-x" in capsys.readouterr().out


def test_retire_rolls_back_only_groups_the_target_lacks(world, tmp_path):
    assert world.run() == 0
    target = tmp_path / "older"
    (target / "config").mkdir(parents=True)
    (target / "config/staged_user_units.json").write_text(json.dumps(dict(MANIFEST, groups=[])))
    assert I.main(["retire", "--release", str(world.release), "--target", str(target), "--unit-dir", str(world.units),
                   "--state-root", str(world.state)]) == 0
    assert [g["status"] for g in world.receipt()["groups"]] == ["ROLLED_BACK"]
    keep = tmp_path / "same"
    (keep / "config").mkdir(parents=True)
    (keep / "config/staged_user_units.json").write_text(json.dumps(MANIFEST))
    assert I.main(["retire", "--release", str(world.release), "--target", str(keep), "--unit-dir", str(world.units),
                   "--state-root", str(world.state)]) == 0
    assert world.receipt()["groups"] == []


def test_deploy_rollback_retires_from_release_then_applies_target():
    text = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    step = _fn(text, "staged_units_step")
    assert step.index('staged_units_run "$from" retire --target "$dir"') < step.index('staged_units_run "$dir" "$verb"')


def test_needs_action_raises_one_p1_for_a_failed_install(tmp_path):
    from datetime import datetime, timezone
    from scripts.lib import needs_action as NA

    assert NA.probe_staged_units(tmp_path) == {"status": "NO_RECEIPT", "path": str(tmp_path / NA.STAGED_UNITS_RECEIPT)}
    assert set(NA.STAGED_UNITS_GOOD) == I.GOOD
    now = datetime.now(timezone.utc)
    assert NA.rule_staged_units({"schema": I.SCHEMA.replace("StagedUserUnits", "StagedUnitsInstall"), "ok": True}, now) == []
    bad = {"schema": "StagedUnitsInstall@v1", "ok": False, "at": "2026-10-25T19:00:00+00:00",
           "groups": [{"id": "cron-outage-watchdog", "status": "REFUSED_DRY_RUN"}]}
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / NA.STAGED_UNITS_RECEIPT).write_text(json.dumps(bad))
    items = NA.rule_staged_units(NA.probe_staged_units(tmp_path), now)
    assert len(items) == 1 and items[0]["severity"] == "P1" and "REFUSED_DRY_RUN" in items[0]["why"]
    assert "staged_units" in NA.RULES
    api = (ROOT / "scripts/api_v2.py").read_text()
    assert '"staged_units": _na.probe_staged_units,' in api


def test_platform_health_reads_the_install_receipt(tmp_path):
    from scripts.lib import platform_health as PH

    deps = PH.Deps(state_root=tmp_path)
    assert PH.probe_staged_units(deps)[0]["status"] == "UNKNOWN"
    (tmp_path / "data/runtime").mkdir(parents=True)
    path = tmp_path / "data/runtime/staged_units_install_latest.json"
    path.write_text(json.dumps({"schema": "StagedUnitsInstall@v1", "ok": False, "at": "2026-10-25T19:00:00+00:00",
                                "groups": [{"id": "cron-outage-watchdog", "status": "VERIFY_FAILED"}]}))
    assert PH.probe_staged_units(deps)[0]["status"] == "CRIT"
    path.write_text(json.dumps({"schema": "StagedUnitsInstall@v1", "ok": True, "groups": []}))
    assert PH.probe_staged_units(deps)[0]["status"] == "OK"
    assert any(fn is PH.probe_staged_units for fn, _ in PH.PROBES)


@pytest.mark.skip(
    reason="Release Train v2 retired 2026-10-27 (operator directive #2240); release_train_controller is archived "
           "under archive/release_train_20261026/, so the train's protected-surface and glob assertions no longer "
           "apply (the train can never change these files)."
)
def test_installer_and_unit_sources_are_refused_by_the_train():
    from scripts.lib import release_train_controller as RTC

    assert "scripts/install_staged_units.py" in RTC.PROTECTED_SURFACES
    rules = {r["id"]: r for r in json.loads((ROOT / "config/release_train_policy.json").read_text())["rules"]}
    assert "scripts/install_staged_units.py" in rules["train_self"]["globs"]
    assert rules["scheduler_live_list"]["class"] == "needs_operator"
    assert {"config/staged_user_units.json", "ops/systemd/**"} <= set(rules["scheduler_live_list"]["globs"])
