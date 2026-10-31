"""The self-heal lanes are installed by the release's staged-units step (AGENTS.md 21.0.0 section 28.14; no operator
act). Pins the two manifest groups: dry run first, admission, the monitor's heartbeat readback, no fixer first run.
Hermetic: the installer is exercised with a stub systemctl and stub scripts in tmp_path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_staged_units as I  # noqa: E402

MANIFEST = json.loads((ROOT / "config/staged_user_units.json").read_text(encoding="utf-8"))
GROUPS = {g["id"]: g for g in MANIFEST["groups"]}
MON, FIX = GROUPS["self-heal-train-monitor"], GROUPS["self-heal-fixer"]


def test_groups_are_valid_admitted_and_dry_run_first():
    assert I.validate_manifest(MANIFEST) == []
    assert I.admitted(ROOT, MON) == (True, "admitted") and I.admitted(ROOT, FIX) == (True, "admitted")
    assert MON["dry_run"]["argv"] == ["scripts/self_heal_train_monitor.py", "--dry-run"]
    assert MON["dry_run"]["expect"] == {"schema": "SelfHealTrainMonitorTick@v1", "mode": "dry_run"}
    assert FIX["dry_run"]["argv"] == ["scripts/self_heal_fixer.py", "--cycle", "--dry-run"]
    assert MON["enable"] == ["tradeai-self-heal-train-monitor.timer"] and FIX["enable"] == ["tradeai-self-heal-fixer.timer"]
    assert MON["verify"]["receipt"] == "data/runtime/self-heal-train-monitor_last.json"
    assert MON["verify"]["receipt_clock"] == "ok_at"
    assert "first_run" not in FIX  # a live fixer cycle can outlast the installer's first-run wait


STUB_MON = (
    "import json, os, sys\n"
    "from datetime import datetime, timezone\n"
    "from pathlib import Path\n"
    "hb = {'schema': 'SelfHealTrainMonitorTick@v1', 'lane_id': 'self-heal-train-monitor', 'ok': True,\n"
    "      'ok_at': datetime.now(timezone.utc).isoformat(), 'mode': 'dry_run' if '--dry-run' in sys.argv else 'shadow'}\n"
    "if '--apply' in sys.argv:\n"
    "    p = Path(os.environ['TRADEAI_STATE_ROOT']) / 'data/runtime/self-heal-train-monitor_last.json'\n"
    "    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(hb))\n"
    "print(json.dumps(hb))\n"
)
STUB_FIX = "import json\nprint(json.dumps({'mode': 'dry_run', 'admitted': []}))\n"
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
[[ "$1" == "--user" ]] && shift
echo "systemctl $*" >> "$FIXTURE_EVENTS"
case "$1" in
  is-active) [[ -e "$FIXTURE_ACTIVE_DIR/${@: -1}" ]] ;;
  enable) shift; [[ "$1" == "--now" ]] && shift; for u in "$@"; do touch "$FIXTURE_ACTIVE_DIR/$u"; done ;;
  start) [[ "$2" == "tradeai-self-heal-train-monitor.service" ]] && cd "$FIXTURE_RELEASE" && "$FIXTURE_PY" scripts/self_heal_train_monitor.py --apply >/dev/null ;;
esac
exit 0
"""


def test_install_runs_dry_runs_then_enables_and_reads_back_the_heartbeat(tmp_path, monkeypatch):
    release = tmp_path / "release"
    (release / "config/systemd/user").mkdir(parents=True)
    (release / "scripts").mkdir()
    manifest = {**MANIFEST, "groups": [MON, FIX]}
    (release / "config/staged_user_units.json").write_text(json.dumps(manifest))
    (release / "config/self_heal_units_admission.json").write_bytes(
        (ROOT / "config/self_heal_units_admission.json").read_bytes())
    for unit in MON["units"] + FIX["units"]:
        (release / "config/systemd/user" / unit).write_text(f"[Unit]\nDescription={unit}\n")
    (release / "scripts/self_heal_train_monitor.py").write_text(STUB_MON)
    (release / "scripts/self_heal_fixer.py").write_text(STUB_FIX)
    units, state, active = tmp_path / "units", tmp_path / "state", tmp_path / "active"
    for d in (units, state, active):
        d.mkdir()
    fake = tmp_path / "systemctl"
    fake.write_text(FAKE_SYSTEMCTL)
    fake.chmod(0o755)
    events = tmp_path / "events.log"
    for k, v in {"TRADEAI_SYSTEMCTL": str(fake), "FIXTURE_EVENTS": str(events), "FIXTURE_ACTIVE_DIR": str(active),
                 "FIXTURE_RELEASE": str(release), "FIXTURE_PY": sys.executable, "TRADEAI_STATE_ROOT": str(state)}.items():
        monkeypatch.setenv(k, v)
    rc = I.main(["apply", "--release", str(release), "--unit-dir", str(units), "--state-root", str(state)])
    receipt = json.loads((state / I.RECEIPT).read_text())
    by = {g["id"]: g for g in receipt["groups"]}
    assert rc == 0, receipt
    assert by["self-heal-train-monitor"]["status"] == "INSTALLED" and by["self-heal-train-monitor"]["verify"]["receipt_ok"]
    assert by["self-heal-fixer"]["status"] == "INSTALLED" and by["self-heal-fixer"]["dry_run"]["expected_shape"]
    log = events.read_text().splitlines()
    assert "systemctl start tradeai-self-heal-fixer.service" not in log
    assert "systemctl enable --now tradeai-self-heal-fixer.timer" in log
