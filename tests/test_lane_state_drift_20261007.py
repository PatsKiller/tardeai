"""Registry state vs host state (2026-10-07): the gate must fail on a running NEVER_SCHEDULED lane."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_state_drift as LD  # noqa: E402

def _lane(lid, state, kind, expr, match=None):
    row = {"lane_id": lid, "owner": "test", "state": state, "expected_cadence_hours": 24.0,
           "scheduler": {"kind": kind, "expression": expr}, "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lid}.json"},
           "note": "fixture"}
    if match:
        row["scheduler"]["match"] = match
    if state != "ACTIVE":
        row.update({"state_reason": "fixture: declared off", "state_since": "2026-10-01", "reason_confidence": "ESTABLISHED",
                    "reason_evidence": "fixture evidence string long enough to satisfy the registry's evidence rule for tests"})
    return row


LANES = [
    _lane("adj", "NEVER_SCHEDULED", "systemd", "x-adj.timer"),
    _lane("mat", "NEVER_SCHEDULED", "cron", "40 6 * * 1 maturity_remeasure.py --write", "maturity_remeasure.py"),
    _lane("ok-timer", "ACTIVE", "systemd", "x-ok.timer"),
    _lane("ok-cron", "ACTIVE", "cron", "5 * * * * foo.py", "foo.py"),
    _lane("paused", "PAUSED", "cron", "1 1 * * * bar.py", "bar.py"),
    _lane("unknown-timer", "ACTIVE", "systemd", "x-missing.timer"),
]
HOST = {"timers": {
    "x-adj.timer": {"unit_file_state": "enabled", "sub_state": "waiting", "next_elapse": "Wed 2026-10-07 19:30:00 EDT", "recurring": True},
    "x-ok.timer": {"unit_file_state": "enabled", "sub_state": "waiting", "next_elapse": "Wed 2026-10-07 02:30:00 EDT", "recurring": True},
}}
CRON = [{"kind": "cron", "expression": "40 6 * * 1 cd $PROJ && $PY scripts/maturity_remeasure.py --write"},
        {"kind": "cron", "expression": "5 * * * * cd $PROJ && $PY scripts/foo.py"}]


def test_classifier_names_both_drift_shapes_and_leaves_aligned_rows_alone():
    rows = {r["lane_id"]: r for r in LD.classify_lanes(LANES, cron_rows=CRON, host_state=HOST)}
    assert rows["adj"]["code"] == "ENABLED_WHILE_DECLARED_NEVER_SCHEDULED"
    assert rows["mat"]["code"] == "CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED"
    assert rows["ok-timer"]["code"] == "ALIGNED" and rows["ok-cron"]["code"] == "ALIGNED" and rows["paused"]["code"] == "ALIGNED"
    assert rows["unknown-timer"]["code"] == "NOT_MEASURED"       # no state is not a pass
    assert [r["lane_id"] for r in LD.conflicts(list(rows.values()))] == ["adj", "mat"]


def test_the_gate_fails_on_drift_and_passes_once_the_rows_are_corrected(tmp_path):
    reg = {"lanes": LANES[:2] + LANES[2:4], "undeclared_baseline": [c["expression"] for c in CRON]}
    host = tmp_path / "host.json"; host.write_text(json.dumps(HOST))
    disc = tmp_path / "disc.json"; disc.write_text(json.dumps({"cron": CRON, "systemd": []}))
    regp = tmp_path / "reg.json"; regp.write_text(json.dumps(reg))
    cmd = [sys.executable, str(ROOT / "scripts" / "check_lane_registry.py"), "--fail-on-new", "--state-drift",
           "--registry", str(regp), "--discovery-json", str(disc), "--host-state-json", str(host)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 1 and "adj" in r.stdout and "mat" in r.stdout, r.stdout + r.stderr
    for l in reg["lanes"][:2]:
        l["state"] = "ACTIVE"
    regp.write_text(json.dumps(reg))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "lane registry: clean" in r.stdout, r.stdout + r.stderr


def test_served_registry_declares_the_two_running_lanes_active():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    by = {l["lane_id"]: l for l in reg["lanes"]}
    assert by["contradiction-adjudicator"]["state"] == "ACTIVE" and by["maturity-remeasure"]["state"] == "ACTIVE"
