"""Scheduling the n8n workflow drift check (operator 2026-10-27, verbatim: "I want all of your recommendations done").

AGENTS.md §23.23 "Workflow governance" (2): any git-vs-live n8n workflow drift pages P1. §23.24 Logging (5): the drift
check runs on a schedule outside n8n. Nothing ran it: lane n8n-workflow-drift-check sat PAUSED on a host cron line
that the cron freeze (operator 2026-10-09) never allowed, and the bare checker that line named cannot page P1 (its
fan-in findings are P2 and the fan-in is an n8n-fired lane). This file pins the change that schedules it:

* config/systemd/user/tradeai-n8n-drift-watch.{service,timer}: the reviewed FW-P3 packet units
  (docs/ops/packets/n8n-platform-hardening-20261022/units/), directives unchanged. They run
  scripts/n8n_drift_watch.py --live every 15 minutes on the host, never in n8n, and page P1 through send_system;
* the registry row: kind systemd, PAUSED pending install (green before and after), cadence 0.25 h, output_signal =
  the drift receipt the watch writes, never dispatch-eligible, no crontab install_line;
* what reads the row: state drift, undeclared-unit discovery, the lane monitor, fan-in liveness, the maturity P18
  "scheduled" check, and backup coverage of the two new unit files.

Hermetic: repo files and tmp_path only. No systemctl, crontab, docker or send.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from n8n_maturity import core  # noqa: E402
from n8n_maturity import dims_governance as G  # noqa: E402

from scripts import check_n8n_workflow_drift as D  # noqa: E402
from scripts import n8n_drift_watch as DW  # noqa: E402
from scripts import n8n_incident_fanin as FANIN  # noqa: E402
from scripts import probe_n8n_platform_facts as PROBE  # noqa: E402
from scripts.lib import host_p1_pager as PG  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib import lane_state_drift as SD  # noqa: E402

LANE = "n8n-workflow-drift-check"
TIMER = "tradeai-n8n-drift-watch.timer"
SERVICE = "tradeai-n8n-drift-watch.service"
UNITS = ROOT / "config" / "systemd" / "user"
PACKET_UNITS = ROOT / "docs" / "ops" / "packets" / "n8n-platform-hardening-20261022" / "units"
REG = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROW = next(r for r in REG["lanes"] if r["lane_id"] == LANE)
NOW = dt.datetime(2026, 10, 27, 20, 0, tzinfo=dt.timezone.utc)
OPERATOR = "I want all of your recommendations done"


def _directives(path: Path) -> list[tuple[str, str, str]]:
    """(section, key, value) in file order; comments and blank lines dropped."""
    out, section = [], ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, _, value = line.partition("=")
        out.append((section, key.strip(), value.strip()))
    return out


def _values(path: Path, section: str, key: str) -> list[str]:
    return [v for s, k, v in _directives(path) if s == section and k == key]


# ------------------------------------------------------------------------------------------------ the unit files


@pytest.mark.parametrize("unit", [SERVICE, TIMER])
def test_units_are_the_reviewed_packet_units_with_identical_directives(unit):
    installed, proposed = UNITS / unit, PACKET_UNITS / f"{unit}.proposed"
    assert installed.is_file() and proposed.is_file()
    assert _directives(installed) == _directives(proposed)
    assert not installed.read_text(encoding="utf-8").startswith("# PROPOSED, NOT INSTALLED")


def test_service_runs_the_drift_watch_live_on_the_host_and_pages_through_send_system():
    svc = UNITS / SERVICE
    (exec_start,) = _values(svc, "Service", "ExecStart")
    assert exec_start.startswith("/usr/bin/flock -n /tmp/tradeai-n8n-drift-watch.lock ")
    assert exec_start.endswith("%h/trade-ai-releases/portfolio-server/CURRENT/scripts/n8n_drift_watch.py --live")
    assert "--dry-run" not in exec_start and (ROOT / "scripts" / "n8n_drift_watch.py").is_file()
    # nothing on the command line reaches n8n (relay, gateway, container): the host runs it, n8n is only read
    assert "n8n" not in exec_start.replace("n8n_drift_watch.py", "").replace("tradeai-n8n-drift-watch", "")
    assert _values(svc, "Service", "Type") == ["oneshot"]
    assert _values(svc, "Service", "WorkingDirectory") == ["%h/trade-ai-releases/portfolio-server/CURRENT"]
    assert _values(svc, "Service", "SuccessExitStatus") == ["1"]  # 1 = drift found and paged; 2 = cannot run
    env = _values(svc, "Service", "Environment")
    assert "TRADEAI_STATE_ROOT=%h/trade-ai-releases/persistent-state" in env and "SYSTEM_TELEGRAM_ENABLED=1" in env
    # least privilege: only the ops-bot file, never the full .env or the secrets render (broker credentials)
    assert _values(svc, "Service", "EnvironmentFile") == ["-%h/.config/tradeai/n8n/host-alert.env"]
    # the P1 path is the host SYSTEM ops transport, not n8n and not the n8n-fired fan-in
    sender = PG.default_sender()
    assert sender.__name__ == "send_system" and sender.__module__.endswith("autonomy_watchdog.telegram_system")
    assert PG.P1_PATH.startswith("host:") and "n8n not involved" in PG.P1_PATH
    assert TIMER in DW.SCHEDULED_ENTRYPOINT and "config/systemd/user" in DW.SCHEDULED_ENTRYPOINT


def test_timer_fires_every_15_minutes_and_the_registry_cadence_and_stale_bounds_agree():
    tmr = UNITS / TIMER
    assert _values(tmr, "Timer", "OnCalendar") == ["*-*-* *:07/15:00"]  # :07 :22 :37 :52
    assert _values(tmr, "Timer", "Unit") == [SERVICE] and _values(tmr, "Timer", "Persistent") == ["true"]
    assert _values(tmr, "Install", "WantedBy") == ["timers.target"]
    assert ROW["expected_cadence_hours"] == 0.25 == DW.CADENCE_MIN / 60
    # the fan-in calls the receipt stale after 3 x cadence; the FW-P3 host probe uses the same 45-minute bound
    assert FANIN.GOVERNANCE_STALE_FACTOR * ROW["expected_cadence_hours"] * 60 == PROBE.DRIFT_MAX_AGE_MIN == 45
    assert PROBE.DRIFT_TIMER == TIMER


# ------------------------------------------------------------------------------------------------ the registry row


def test_registry_row_is_a_paused_timer_row_pending_install():
    assert LR.validate_row(ROW) == []
    assert ROW["scheduler"] == {"kind": "systemd", "expression": TIMER, "match": "scripts/n8n_drift_watch.py --live"}
    assert ROW["state"] == "PAUSED" and ROW["review_by"] >= "2026-10-27"
    assert "PENDING INSTALL" in ROW["state_reason"] and "2026-10-27" in ROW["state_reason"]
    assert OPERATOR in ROW["state_reason"] and OPERATOR in ROW["scheduler_note"]
    assert ROW["output_signal"] == {"kind": "file_mtime", "path": str(D.RECEIPT_REL)}
    assert ROW["recommendation"] == "KEEP_ON_CRON" and not ROW.get("dispatch")


def test_no_crontab_line_schedules_the_drift_receipt():
    """Cron freeze, and one writer: the watch and the bare checker both write the drift receipt, so neither may
    come back as a crontab install_line beside the timer."""
    for r in REG["lanes"]:
        line = str((r.get("scheduler") or {}).get("install_line") or "")
        assert "check_n8n_workflow_drift.py" not in line and "n8n_drift_watch.py" not in line, r["lane_id"]


def test_never_dispatch_eligible_and_held_out_of_the_n8n_cutover():
    assert LD.dispatch_eligible(ROW, cutover_policy=LD.EMPTY_CUTOVER_POLICY)[0] is False
    assert LD.dispatch_eligible(ROW)[0] is False
    policy = json.loads((ROOT / "config" / "lane_cutover_policy.json").read_text(encoding="utf-8"))
    assert LANE in policy["holds"]


# ------------------------------------------------------------------------------------------------ gates on the row


def _timer_state(enabled: bool) -> dict:
    return {
        "timers": {
            TIMER: {
                "unit_file_state": "enabled" if enabled else "disabled",
                "sub_state": "waiting" if enabled else "dead",
                "next_elapse": "Tue 2026-10-27 16:07:00 EDT" if enabled else None,
                "recurring": True,
            }
        }
    }


def test_state_drift_is_green_before_install_after_install_and_after_the_flip():
    for enabled in (False, True):
        rows = SD.classify_lanes([ROW], cron_rows=[], host_state=_timer_state(enabled))
        assert SD.conflicts(rows) == [], (enabled, rows)
    flipped = SD.classify_lanes([dict(ROW, state="ACTIVE")], cron_rows=[], host_state=_timer_state(True))
    assert flipped[0]["code"] == "ALIGNED"
    # why the row is PAUSED and not NEVER_SCHEDULED: the install would turn that into a conflict
    never = SD.classify_lanes([dict(ROW, state="NEVER_SCHEDULED")], cron_rows=[], host_state=_timer_state(True))
    assert [r["code"] for r in SD.conflicts(never)] == ["ENABLED_WHILE_DECLARED_NEVER_SCHEDULED"]


def test_the_installed_timer_is_declared_and_without_the_row_it_would_not_be():
    found = {"cron": [], "systemd": [{"expression": TIMER, "enabled_state": "enabled"}]}
    assert LR.find_undeclared(REG, found, n8n_known_ids=[]) == []
    without = {**REG, "lanes": [r for r in REG["lanes"] if r["lane_id"] != LANE]}
    assert [u["expression"] for u in LR.find_undeclared(without, found, n8n_known_ids=[])] == [TIMER]


def test_the_registry_gate_is_clean_with_the_timer_installed(tmp_path):
    disco = tmp_path / "discovery.json"
    disco.write_text(
        json.dumps({"cron": [], "cron_commented": [], "systemd": [{"expression": TIMER, "enabled_state": "enabled"}]})
    )
    host = tmp_path / "host.json"
    host.write_text(json.dumps(_timer_state(True)))
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "check_lane_registry.py"),
        "--fail-on-new",
        "--state-drift",
        "--discovery-json",
        str(disco),
        "--host-state-json",
        str(host),
    ]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "lane registry: clean" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]


def test_paused_row_is_expected_silent_for_the_lane_monitor(tmp_path):
    v = LR.evaluate_lane(ROW, now=NOW, found={"cron": [], "systemd": []}, root=tmp_path)
    assert v["verdict"] == LR.EXPECTED_SILENT, v


def _drift_items(tmp_path, monkeypatch, row):
    monkeypatch.delenv("TRADEAI_FANIN_GOVERNANCE", raising=False)
    monkeypatch.setattr(FANIN, "_governance_lane", lambda lane_id: row if lane_id == LANE else None)
    return sorted(
        f["item"] for f in FANIN._governance_findings(tmp_path, NOW, prev={}) if f["source"] == "n8n_workflow_drift"
    )


def _write_receipt(root: Path, minutes_old: float) -> None:
    p = root / D.RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    as_of = (NOW - dt.timedelta(minutes=minutes_old)).isoformat()
    p.write_text(json.dumps({"schema": D.SCHEMA, "as_of": as_of, "verdict": "CLEAN", "workflows": []}))


def test_fanin_liveness_stays_quiet_until_the_flip_then_arms_at_45_minutes(tmp_path, monkeypatch):
    assert _drift_items(tmp_path, monkeypatch, ROW) == []  # PAUSED: no receipt is not a finding
    active = dict(ROW, state="ACTIVE")
    assert _drift_items(tmp_path, monkeypatch, active) == ["receipt:missing"]
    _write_receipt(tmp_path, 40)
    assert _drift_items(tmp_path, monkeypatch, active) == []
    _write_receipt(tmp_path, 50)
    assert _drift_items(tmp_path, monkeypatch, active) == ["receipt:stale"]


# ------------------------------------------------------------------------------------------------ what one fire does


def _live_set() -> list[dict]:
    """The committed reviewed workflow set, as the n8n DB would return it when nothing has drifted."""
    out = []
    for wid, (_path, doc) in sorted(D.git_reviewed_set().items()):
        wf = copy.deepcopy(doc)
        wf.update(id=wid, active=True)
        out.append(wf)
    return out


class _Sender:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, text, *, identity, kind):
        self.sent.append((text, identity, kind))
        return {"ok": True, "message_id": len(self.sent)}


def test_a_live_fire_writes_the_registry_output_signal_and_pages_p1_on_drift(tmp_path):
    root, sender = tmp_path / "state", _Sender()
    workflows = _live_set()
    assert workflows, "the committed reviewed workflow set is empty"
    clean = DW.run_once(live=True, root=root, workflows=workflows, now=NOW, sender=sender)
    assert clean["verdict"] == "CLEAN" and clean["page"]["action"] == PG.NONE and not sender.sent
    receipt = json.loads((root / ROW["output_signal"]["path"]).read_text(encoding="utf-8"))
    assert receipt["schema"] == "N8nWorkflowDriftReceipt@v1" and receipt["fanin_wired"] is True  # maturity "alerting"
    drifted = copy.deepcopy(workflows)
    drifted[0]["settings"] = {**(drifted[0].get("settings") or {}), "timezone": "UTC-drift"}
    rec = DW.run_once(live=True, root=root, workflows=drifted, now=NOW + dt.timedelta(minutes=15), sender=sender)
    assert rec["verdict"] == "DRIFT" and rec["severity"] == "P1" and rec["page"]["delivered"] is True
    assert len(sender.sent) == 1 and sender.sent[0][2] == "n8n_workflow_drift" and "P1" in sender.sent[0][0]
    assert rec["page"]["p1_path"].startswith("host:")


# ------------------------------------------------------------------------------------------------ maturity + backup


def _p18_scheduled_by(tmp_path, p18: dict, timers: str) -> list[str]:
    cfg = json.loads((ROOT / "config" / "n8n_platform_maturity.json").read_text(encoding="utf-8"))
    probe = core.Probe(root=tmp_path, proj=ROOT, now=NOW, env={}, config=cfg, runner=None)
    gcfg = G._governance_cfg(probe)
    metrics: dict = {}
    G._check_scheduled(probe, {**gcfg["p18"], **p18}, gcfg, None, timers, [], "p18", [], metrics)
    return metrics["p18"]["scheduled_by"]


def test_maturity_p18_counts_the_drift_watch_timer_as_scheduled(tmp_path):
    timers = f"NEXT LEFT LAST PASSED UNIT ACTIVATES\nx y z w {TIMER} {SERVICE}\n"
    assert _p18_scheduled_by(tmp_path, {}, timers) == ["systemd-timer"]
    # the config change is what makes it visible: the old script name does not match the timer's name
    assert _p18_scheduled_by(tmp_path, {"script": "check_n8n_workflow_drift"}, timers) == []
    assert _p18_scheduled_by(tmp_path, {}, "NEXT LEFT UNIT\n") == []


def test_backup_manifest_covers_both_new_unit_files():
    text = (ROOT / "config" / "backup_coverage_manifest.json").read_text(encoding="utf-8")
    for unit in (SERVICE, TIMER):
        assert f'"unit:{unit}"' in text
