"""Active Trader motion watchdog (2026-10-19): n8n owns the supervision of the motion runtime; the loop stays systemd.

Hermetic: tmp heartbeat files, a fake /proc, a fake clock, a fake marker path, tmp state roots and coordination ledgers,
a fake systemctl and a tmp guard ledger for the operator packet. Nothing here reads the real heartbeat, /proc, /etc,
the live list or a unit, and nothing restarts anything.

  1. bands: HEALTHY / STALE / DEGRADED / DOWN (missing, unreadable, wrong contract, pid dead, pid reused) / DISABLED
  2. window: trading days 07:00 ET -> official close (early close 13:00), weekends, holidays, calendar error
  3. band-change dedupe: alert on entry, once; recovery once; out-of-window silent; DISABLED resets; failed queue retries
  4. LaneRunReceipt@v2 shape (produced / empty_allowed / fatal), the per-attempt copy, dry run writes nothing
  5. the real host comms-intent path into a tmp ledger (route, producer, workflow_id host.<producer>)
  6. wiring: route, registry rows, allowlist, REVIEWED contract, unit file gate line (no misspelt dir)
  7. the operator packet: dry by default, shellcheck, refuses --apply without a real grant, refuses open-hours start,
     installs with archive + read-back, proof PASS/FAIL, relay/rollback of the live list
  8. main's bounded grant model (#1873): authorize active-trader-motion.<step> --consume spends exactly one use of
     each finite bound grant right before the first effect; wrong tier / unbound reason / missing service grant /
     prefix id refuse with no effect and no consumption; dry runs consume nothing
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_active_trader_motion_heartbeat as W  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402

LANE = "active-trader-motion-watchdog"
ET = ZoneInfo("America/New_York")
PACKET = ROOT / "docs" / "ops" / "packets" / "active-trader-motion-n8n-20261019"
SCRIPT = PACKET / "cutover.sh"
UNIT = ROOT / "config" / "systemd" / "tradeai-active-trader-motion.service"
GID = "c6c7c582214340fb9397fe821fdf224f"
SERVICE_GID = "f" * 32
MOTION_UNIT = "tradeai-active-trader-motion.service"
RELAY_UNITS = ("tradeai-n8n-run-relay.service", "tradeai-n8n-coordination-gateway.service")


def _bound_ledger(step: str, *, uses: int = 5, drop: str = "") -> dict:
    """A guard ledger (flat tier -> row, as main's fabric-grant tests write it) bound to active-trader-motion.<step>."""
    digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    base = f"active-trader-motion.{step} {LANE} tradeai-dispatcher {digest}"
    row = lambda gid, reason: {"grant_id": gid, "expires": time.time() + 3600, "uses": uses,  # noqa: E731
                               "reason": " ".join(w for w in reason.split() if w != drop)}
    if step in ("install", "start"):
        verb = "daemon-reload" if step == "install" else "restart"
        return {"execution-ops": row(GID, f"{base} {MOTION_UNIT} {verb}")}
    reason = f"{base} restart {' '.join(RELAY_UNITS)}"
    return {"config-write": row(GID, reason), "service": row(SERVICE_GID, reason)}
CFG = W.load_config()
# Mon 2026-10-19 11:00 ET: a trading day, RTH, inside the window
MON_1100 = datetime(2026, 10, 19, 11, 0, tzinfo=ET)


def _et(*a: int) -> datetime:
    return datetime(*a, tzinfo=ET)


@pytest.fixture
def host(tmp_path):
    """A fake host: heartbeat, /proc with the runtime's pid, marker present, state root, ledger path."""
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "cmdline").write_bytes(b"/venv/bin/python\0-m\0active_trader.motion_runtime\0")
    marker = tmp_path / "etc" / "enable-active-trader-motion"
    marker.parent.mkdir()
    marker.write_text("")
    hb = tmp_path / "hb.json"
    state = tmp_path / "state"
    ledger = state / "data" / "governance" / "n8n_coordination_ledger.sqlite"

    def beat(now: datetime, *, age: float = 5.0, status: str = "healthy", pid: int = 4242, failures: int = 0,
             contract: str = "active-trader-motion-runtime-heartbeat-v1", cycles: int = 100) -> None:
        hb.write_text(json.dumps({
            "contract": contract, "updated_at": now.timestamp() - age, "status": status, "pid": pid,
            "consecutive_failures": failures, "cycle_count": cycles,
            "authority": {"order": False, "mutation": False, "canary": False},
        }))

    def ev(now: datetime = MON_1100) -> dict:
        return W.evaluate(CFG, now_epoch=now.timestamp(), heartbeat_path=hb, marker_path=marker, proc_root=proc)

    class Q:
        calls: list = []
        fail: str | None = None

        def __call__(self, cfg, subject, summary, exec_id, ledger_path, now):
            if self.fail:
                raise W.HostIntentError(self.fail)
            self.calls.append({"subject": subject, "summary": summary, "exec_id": exec_id})
            return {"intent_id": f"ci-{len(self.calls)}", "duplicate": False}

    q = Q()
    q.calls = []

    def run(now: datetime = MON_1100, apply: bool = True):
        return W.run(apply=apply, now=now.astimezone(timezone.utc), heartbeat=hb, marker=marker, proc_root=proc,
                     state_root=state, ledger=ledger, queue=q)

    import types
    return types.SimpleNamespace(tmp=tmp_path, proc=proc, marker=marker, hb=hb, state=state, ledger=ledger,
                                 beat=beat, ev=ev, run=run, q=q,
                                 state_file=state / CFG["state_rel"], receipt=R.receipt_path(LANE, state))


# ── 1. bands ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_healthy(host):
    host.beat(MON_1100, age=5)
    v = host.ev()
    assert v["band"] == W.HEALTHY and v["reasons"] == [] and v["pid_state"] == "alive"
    assert v["authority_all_false"] is True and v["marker_present"] is True


def test_stale_at_the_threshold_boundary(host):
    host.beat(MON_1100, age=CFG["stale_after_s"])
    assert host.ev()["band"] == W.HEALTHY  # age == threshold is still healthy
    host.beat(MON_1100, age=CFG["stale_after_s"] + 1)
    v = host.ev()
    assert v["band"] == W.STALE and v["reasons"][0].startswith("heartbeat_age_121s>120s")


def test_degraded_on_status_or_consecutive_failures(host):
    host.beat(MON_1100, status="backoff")
    assert host.ev()["band"] == W.DEGRADED
    host.beat(MON_1100, failures=CFG["degraded_consecutive_failures"])
    v = host.ev()
    assert v["band"] == W.DEGRADED and "consecutive_failures_3" in v["reasons"]


@pytest.mark.parametrize("case,reason", [
    ("missing", "heartbeat_missing"), ("corrupt", "heartbeat_unreadable"), ("contract", "heartbeat_contract_mismatch"),
    ("dead", "pid_dead"), ("reused", "pid_not_runtime"), ("nopid", "pid_no_pid"),
])
def test_down(host, case, reason):
    host.beat(MON_1100)
    if case == "missing":
        host.hb.unlink()
    elif case == "corrupt":
        host.hb.write_text("{not json")
    elif case == "contract":
        host.beat(MON_1100, contract="something-else")
    elif case == "dead":
        host.beat(MON_1100, pid=999)
    elif case == "reused":
        (host.proc / "4242" / "cmdline").write_bytes(b"/usr/bin/vim\0notes.txt\0")
    elif case == "nopid":
        host.beat(MON_1100, pid=0)
    v = host.ev()
    assert v["band"] == W.DOWN and v["reasons"] == [reason], v


def test_disabled_when_the_marker_is_absent_and_nothing_runs(host):
    host.beat(MON_1100, pid=999, age=740000)
    host.marker.unlink()
    v = host.ev()
    assert v["band"] == W.DISABLED and v["reasons"] == ["marker_absent", "pid_dead"] and v["marker_present"] is False
    host.hb.unlink()
    assert host.ev()["reasons"] == ["marker_absent", "heartbeat_missing"]


def test_a_running_runtime_without_its_marker_is_still_banded_on_its_heartbeat(host):
    host.marker.unlink()
    host.beat(MON_1100)
    v = host.ev()
    assert v["band"] == W.HEALTHY and v["reasons"][0].startswith("marker_absent_while_running")
    host.beat(MON_1100, age=600)
    assert host.ev()["band"] == W.STALE  # a hung process without a marker still alerts


# ── 2. window ─────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("when,inside,reason", [
    (_et(2026, 10, 19, 6, 59), False, "before_window"),
    (_et(2026, 10, 19, 7, 0), True, "in_window"),
    (_et(2026, 10, 19, 9, 30), True, "in_window"),
    (_et(2026, 10, 19, 15, 59), True, "in_window"),
    (_et(2026, 10, 19, 16, 0), False, "after_close"),
    (_et(2026, 10, 19, 21, 0), False, "after_close"),
    (_et(2026, 10, 17, 11, 0), False, "not_trading_day"),   # Saturday
    (_et(2026, 11, 26, 11, 0), False, "not_trading_day"),   # Thanksgiving
    (_et(2026, 11, 27, 12, 59), True, "in_window"),          # early close day
    (_et(2026, 11, 27, 13, 0), False, "after_close"),
])
def test_window_boundaries(when, inside, reason):
    w = W.window_state(when.astimezone(timezone.utc), CFG)
    assert (w["in_window"], w["reason"]) == (inside, reason)


def test_a_calendar_error_counts_as_inside_the_window():
    class Broken:
        def session_at(self, now):
            raise RuntimeError("calendar down")
    w = W.window_state(MON_1100, CFG, Broken())
    assert w["in_window"] is True and w["reason"].startswith("calendar_error")


# ── 3. band-change dedupe ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("last,band,inside,action,new", [
    (None, W.HEALTHY, True, None, W.HEALTHY),
    (None, W.STALE, True, "alert", W.STALE),
    (W.STALE, W.STALE, True, None, W.STALE),
    (W.STALE, W.DOWN, True, "alert", W.DOWN),
    (W.DOWN, W.HEALTHY, True, "recover", W.HEALTHY),
    (W.DEGRADED, W.HEALTHY, True, "recover", W.HEALTHY),
    (W.HEALTHY, W.HEALTHY, True, None, W.HEALTHY),
    (W.HEALTHY, W.DOWN, False, None, W.HEALTHY),      # out of window: silent, alerted band kept
    (None, W.DOWN, False, None, None),
    (W.STALE, W.DISABLED, True, "reset", W.DISABLED),  # operator gate: no page, dedupe reset
    (W.DISABLED, W.DISABLED, True, None, W.DISABLED),
    (W.DISABLED, W.HEALTHY, True, None, W.HEALTHY),    # back from the gate: no "recovered" line
    (W.DISABLED, W.DOWN, True, "alert", W.DOWN),       # marker created, unit not started: alert
])
def test_decide(last, band, inside, action, new):
    d = W.decide({"last_alerted_band": last}, band, inside, CFG)
    assert (d["action"], d["last_alerted_band"]) == (action, new)


def test_alert_once_per_band_change_then_recovery_once(host):
    host.beat(MON_1100, age=600)
    for _ in range(3):
        rc, s = host.run()
        assert rc == 0
    assert [c["subject"] for c in host.q.calls] == ["Active Trader motion runtime STALE"]
    assert "heartbeat age 10m" in host.q.calls[0]["summary"] and "never restarts" in host.q.calls[0]["summary"]
    host.beat(MON_1100, pid=999)
    host.run(); host.run()
    host.beat(MON_1100)
    host.run(); host.run()
    assert [c["subject"] for c in host.q.calls] == [
        "Active Trader motion runtime STALE", "Active Trader motion runtime DOWN", "Active Trader motion runtime RECOVERED"]
    st = json.loads(host.state_file.read_text())
    assert st["schema"] == W.STATE_SCHEMA and st["last_alerted_band"] == W.HEALTHY and st["last_band"] == W.HEALTHY


def test_out_of_window_is_silent_and_the_fault_alerts_at_window_open(host):
    night = _et(2026, 10, 19, 22, 0)
    host.beat(night, pid=999)
    rc, s = host.run(night)
    assert rc == 0 and host.q.calls == [] and s["action"] is None
    morning = _et(2026, 10, 20, 7, 0)
    host.beat(morning, pid=999)
    host.run(morning)
    assert [c["subject"] for c in host.q.calls] == ["Active Trader motion runtime DOWN"]


def test_disabled_never_alerts(host):
    host.marker.unlink()
    host.beat(MON_1100, pid=999)
    for _ in range(2):
        rc, s = host.run()
        assert rc == 0
    assert host.q.calls == [] and json.loads(host.state_file.read_text())["last_alerted_band"] == W.DISABLED


def test_a_failed_queue_fails_the_run_keeps_the_band_unalerted_and_the_next_run_retries(host):
    host.beat(MON_1100, pid=999)
    host.q.fail = "ledger_absent"
    rc, s = host.run()
    assert rc == 1 and s["error"] == "intent_queue_failed:ledger_absent"
    assert json.loads(host.state_file.read_text())["last_alerted_band"] is None
    doc = json.loads(host.receipt.read_text())
    assert doc["status"] == "failed" and doc["skipped_reasons"] == {"dependency_unavailable": 1} and doc["produced_count"] == 0
    host.q.fail = None
    rc, _ = host.run()
    assert rc == 0 and [c["subject"] for c in host.q.calls] == ["Active Trader motion runtime DOWN"]


# ── 4. receipts ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_in_window_receipt_is_v2_produced_one_with_an_immutable_attempt_copy(host, monkeypatch):
    monkeypatch.setenv("TRADEAI_RUN_ID", "d:active-trader-motion-watchdog:live:20261019T1100")
    host.beat(MON_1100)
    rc, _ = host.run()
    assert rc == 0
    doc = json.loads(host.receipt.read_text())
    assert doc["status"] == "ok" and doc["ok_at"] and doc["output_fields"] == "LaneRunReceipt@v2"
    assert (doc["produced_count"], doc["attempted_count"], doc["empty_reason"]) == (1, 1, None)
    attempt = R.attempt_receipt_path(LANE, "d:active-trader-motion-watchdog:live:20261019T1100", host.state)
    a = json.loads(attempt.read_text())
    assert a["schema"] == "LaneRunReceipt@v2" and a["produced_count"] == 1


@pytest.mark.parametrize("when,reason", [
    (_et(2026, 10, 19, 6, 0), "window_not_reached"),
    (_et(2026, 10, 19, 17, 0), "market_closed"),
    (_et(2026, 10, 18, 11, 0), "market_closed"),
])
def test_out_of_window_receipt_is_empty_allowed(host, when, reason):
    host.beat(when)
    rc, _ = host.run(when)
    doc = json.loads(host.receipt.read_text())
    assert rc == 0 and doc["produced_count"] == 0 and doc["empty_reason"] == reason
    contract = next(c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
                    if c["id"] == LANE)
    assert reason in contract["expected_output"]["empty_allowed_reasons"]


def test_an_unreadable_config_is_the_fatal_skip(host, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    rc, s = W.run(apply=True, now=MON_1100, config_path=bad, heartbeat=host.hb, marker=host.marker,
                  proc_root=host.proc, state_root=host.state, ledger=host.ledger, queue=host.q)
    doc = json.loads(host.receipt.read_text())
    assert rc == 1 and doc["skipped_reasons"] == {"dependency_unavailable": 1}
    contract = next(c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
                    if c["id"] == LANE)
    # no_runner is the executor's own fatal reason (FW-M6, operator rule 2026-10-15); the script emits only this one
    assert contract["expected_output"]["fatal_skip_reasons"] == ["no_runner", "dependency_unavailable"]


def test_the_dry_run_writes_nothing(host, capsys):
    host.beat(MON_1100, pid=999)
    rc, s = host.run(apply=False)
    assert rc == 0 and s["action"] == "alert" and host.q.calls == []
    assert not host.state.exists()
    assert "DRY-RUN " in capsys.readouterr().out


def test_cli_dry_run_and_usage(host):
    host.beat(MON_1100)
    p = subprocess.run([sys.executable, str(ROOT / "scripts/check_active_trader_motion_heartbeat.py"), "--dry-run",
                        "--heartbeat", str(host.hb), "--marker", str(host.marker), "--proc-root", str(host.proc),
                        "--state-root", str(host.state), "--now", MON_1100.isoformat()],
                       capture_output=True, text=True, timeout=60, env={**os.environ, "TRADE_AI_CI": "1"})
    assert p.returncode == 0, p.stderr
    summary = json.loads(p.stdout.split("DRY-RUN ", 1)[1])["summary"]
    assert summary["verdict"]["band"] == W.HEALTHY and not host.state.exists()
    bad = subprocess.run([sys.executable, str(ROOT / "scripts/check_active_trader_motion_heartbeat.py"), "--bogus"],
                         capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2


def test_the_checker_never_restarts_imports_the_runtime_or_reads_environ():
    src = (ROOT / "scripts/check_active_trader_motion_heartbeat.py").read_text()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for bad in ("import subprocess", "systemctl ", "import active_trader", "from active_trader", "environ\"",
                "send_telegram", "requests", "urllib", "os.kill"):
        assert bad not in code, bad


# ── 5. the real host comms-intent path ────────────────────────────────────────────────────────────────────────────


def test_a_band_change_queues_one_real_host_intent_into_the_ledger(host):
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    host.ledger.parent.mkdir(parents=True)
    CoordinationLedger(host.ledger).close()  # the gateway creates the ledger; a lane never does
    host.beat(MON_1100, pid=999)
    rc, s = W.run(apply=True, now=MON_1100, heartbeat=host.hb, marker=host.marker, proc_root=host.proc,
                  state_root=host.state, ledger=host.ledger)
    assert rc == 0, s.get("error")
    rc, _ = W.run(apply=True, now=MON_1100, heartbeat=host.hb, marker=host.marker, proc_root=host.proc,
                  state_root=host.state, ledger=host.ledger)
    c = sqlite3.connect(f"file:{host.ledger}?mode=ro", uri=True)
    rows = c.execute("SELECT domain, kind, workflow_id, state, subject FROM comms_intents").fetchall()
    assert rows == [("host", "active_trader_motion_watchdog", "host.active_trader_motion_watchdog", "QUEUED",
                     "Active Trader motion runtime DOWN")]


def test_without_a_ledger_the_real_path_refuses_and_the_run_fails(host):
    host.beat(MON_1100, pid=999)
    rc, s = W.run(apply=True, now=MON_1100, heartbeat=host.hb, marker=host.marker, proc_root=host.proc,
                  state_root=host.state, ledger=host.ledger)
    assert rc == 1 and s["error"] == "intent_queue_failed:ledger_absent"


# ── 6. wiring ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _j(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_host_route_is_producer_bound_digest_never_page():
    from scripts.lib.n8n_fabric_store import load_host_intent_routes, load_intent_routes, merged_intent_routes

    hosts = load_host_intent_routes()
    r = hosts["routes"][("host", "active_trader_motion_watchdog")]
    assert r == {"tier": "DIGEST", "runbook_id": "active-trader-motion-watchdog", "producer": "active_trader_motion_watchdog"}
    merged_intent_routes(load_intent_routes(), hosts)  # no pair owned by both tables
    a = CFG["alert"]
    assert (a["domain"], a["kind"], a["tier"], a["producer"]) == ("host", "active_trader_motion_watchdog", "DIGEST",
                                                                  "active_trader_motion_watchdog")


def test_registry_row_is_a_dispatch_live_n8n_lane_at_canary_like_the_comms_consumer():
    rows = {r["lane_id"]: r for r in _j("config/lane_registry.json")["lanes"]}
    row = rows[LANE]
    assert row["scheduler"] == {"kind": "n8n", "expression": "dispatcher",
                                "match": "scripts/check_active_trader_motion_heartbeat.py", "cadence": "*/5 * * * *",
                                "stage": "canary", "wave": "W1"}
    assert row["dispatch"]["mode"] == "live" and row["dispatch"]["cron"] == ["*/5 * * * *"]
    assert row["state"] == "ACTIVE" and row["output_signal"]["path"] == "data/runtime/active-trader-motion-watchdog_last.json"
    motion = rows["tradeai-active-trader-motion-service"]
    assert motion["state"] == "ACTIVE" and "Supervised by n8n lane active-trader-motion-watchdog" in motion["evidence_note"]


def test_allowlist_entry_runs_apply_under_its_own_flock_with_enforced_env():
    e = {x["lane_id"]: x for x in _j("config/n8n_run_allowlist.json")["lanes"]}[LANE]
    assert e["command"] == ["$PY", "scripts/check_active_trader_motion_heartbeat.py"]
    assert e["live_arg"] == ["--apply"] and e["dry_run_arg"] == ["--dry-run"] and e["output_receipt"] == "v2"
    assert e["lock_kind"] == "flock" and e["lock"] == "/tmp/tradeai_active_trader_motion_watchdog.lock"
    assert e["env_allowlist_mode"] == "enforce" and e["market_gate"] is False and e["timeout_s"] == 60


def test_health_contract_is_reviewed_at_canary_with_the_codes_output_rule():
    c = {x["id"]: x for x in _j("config/n8n_health_contracts.json")["contracts"]}[LANE]
    assert (c["status"], c["stage"], c["workflow_id"], c["kind"]) == ("REVIEWED", "canary", "dispatcher", "lane")
    eo = c["expected_output"]
    assert eo["rule"] == "empty_allowed" and eo["produced_field"] == "produced_count"
    assert set(eo["empty_allowed_reasons"]) == {W.EMPTY_MARKET_CLOSED, W.EMPTY_WINDOW_NOT_REACHED}
    assert eo["fatal_skip_reasons"] == ["no_runner", W.SKIP_DEPENDENCY]  # no_runner: FW-M6, operator rule 2026-10-15
    assert eo["empty_allowed_reasons"] is not None and {e["kind"] for e in eo["evidence"]} <= {"store_rows", "receipt_field", "ledger_row"}
    assert "PAGE" not in json.dumps(c["alerting"]["failed"])


def test_unit_file_gate_line_is_the_root_owned_marker_and_no_misspelt_dir():
    text = UNIT.read_text()
    assert "tardeai" not in text
    lines = text.splitlines()
    assert "ConditionPathExists=/etc/tradeai/enable-active-trader-motion" in lines
    assert "EnvironmentFile=-%h/.config/tradeai/active-trader-motion.env" in lines
    assert CFG["marker_path"] == "/etc/tradeai/enable-active-trader-motion"
    assert "tardeai" not in (ROOT / "config/systemd/active-trader-motion.env.example").read_text()


# ── 7. the operator packet ────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pk(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl.calls"
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {calls}\n'
        'case "$*" in *"show -p MainPID"*) echo 4242 ;; *is-active*) echo active ;; esac\n'
    )
    (bin_dir / "systemctl").chmod(0o755)
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "cmdline").write_bytes(b"python\0-m\0active_trader.motion_runtime\0")
    units = tmp_path / "units"
    units.mkdir()
    old = UNIT.read_text().replace("/etc/tradeai/enable-active-trader-motion", "/etc/tar" "deai/enable-active-trader-motion")
    (units / UNIT.name).write_text(old)
    marker = tmp_path / "enable-active-trader-motion"
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text("# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-comms-intent-consumer\n")
    live.chmod(0o600)
    approvals = tmp_path / "approvals"
    approvals.mkdir()
    journal = tmp_path / "journal.jsonl"
    journal.write_text("{}\n")
    hb = tmp_path / "hb.json"
    env = {
        "PATH": os.environ["PATH"], "HOME": str(tmp_path), "PY": sys.executable, "SERVED": str(ROOT),
        "STATE": str(tmp_path / "state"), "LIVE_LANES_ENV": str(live), "SYSTEMCTL_BIN": str(bin_dir / "systemctl"),
        "PROC_ROOT": str(proc), "UNIT_DIR": str(units), "MARKER": str(marker), "HEARTBEAT": str(hb),
        "RESTART_SETTLE_S": "0", "PROOF_GAP_S": "0", "GUARD_APPROVALS_DIR": str(approvals), "TRADE_AI_CI": "1",
        "NOW_ISO": "2026-10-19T22:00:00-04:00", "GUARD_AUDIT_LOG": str(tmp_path / "grant-audit.jsonl"),
        "TRADEAI_FABRIC_SERVICE_GRANT": SERVICE_GID,
    }

    def grant(step: str, **kw) -> dict:
        doc = _bound_ledger(step, **kw)
        (approvals / "grants.json").write_text(json.dumps(doc))
        return doc

    def ledger() -> dict:
        # Guard ledger v2 keys rows "<tier>@<grant_id>"; these packets hold one row per tier.
        return {k.split("@", 1)[0]: v for k, v in json.loads((approvals / "grants.json").read_text()).items()}

    def audit() -> list[dict]:
        log = tmp_path / "grant-audit.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def beat(cycles: int, age: float = 1.0) -> None:
        hb.write_text(json.dumps({"contract": "active-trader-motion-runtime-heartbeat-v1", "updated_at": time.time() - age,
                                  "status": "healthy", "pid": 4242, "cycle_count": cycles, "journal_path": str(journal),
                                  "authority": {"order": False, "mutation": False}}))

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                              timeout=120, cwd=str(tmp_path))

    import types
    return types.SimpleNamespace(run=run, grant=grant, ledger=ledger, audit=audit, beat=beat, calls=calls, units=units, marker=marker, live=live,
                                 proc=proc, journal=journal, hb=hb, env=env)


def test_packet_is_dry_by_default_set_f_and_never_deletes_or_runs_sudo_stop_or_cron():
    src = SCRIPT.read_text()
    assert src.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in src and "\nset -f\n" in src
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for bad in ("rm ", "crontab", "import:workflow", "update:workflow", "DELETE ", "DROP ", "deactivate", "kill ",
                "--user stop", "--user enable", "--user disable", "mask", "EnvironmentFile=-/"):
        assert bad not in code.replace('echo "      $OPCTL --user stop', ""), bad
    # /proc/<pid>/environ is read only for the relay and gateway units (the comms-consumer packet's live-list
    # read-back), never for the motion unit, whose EnvironmentFile and environ stay unread (AGENTS.md §24.7)
    environ_lines = [line for line in code.splitlines() if "/environ" in line]
    assert environ_lines and all('"$PROC_ROOT/$pid/environ"' in line for line in environ_lines)
    restart_fn = code[code.index("restart_relay_units(){"):code.index("write_live_list(){")]
    assert "RELAY_UNITS" in restart_fn and "$UNIT" not in restart_fn
    for line in code.splitlines():  # sudo appears only inside printed text, never executed
        if "sudo" in line:
            assert line.strip().startswith("echo"), line
    assert os.access(SCRIPT, os.X_OK)
    assert "tardeai" not in src


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_packet_passes_shellcheck():
    p = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


def test_marker_step_prints_the_operator_command_and_never_runs_it(pk):
    p = pk.run("marker")
    assert p.returncode == 0 and f"sudo touch {pk.marker}" in p.stdout and not pk.marker.exists()


@pytest.mark.parametrize("step", ["install", "start", "relay", "rollback"])
def test_every_apply_refuses_without_a_real_grant(pk, step):
    pk.marker.write_text("")
    p = pk.run(step, "--apply")
    assert p.returncode == 1 and "TRADEAI_FABRIC_GRANT not set" in p.stdout
    pk.grant(step)
    for bad in ("config-write-20261019T2200", GID[:8], "0" * 32):  # a label, a prefix, an unknown id
        p = pk.run(step, "--apply", TRADEAI_FABRIC_GRANT=bad)
        assert p.returncode == 1 and "grant refused" in p.stdout, (bad, p.stdout)
    assert not pk.calls.exists() and not pk.audit()
    assert all(r["uses"] == 5 for r in pk.ledger().values())


def test_install_dry_then_apply_archives_installs_reads_back_and_reloads(pk):
    before = (pk.units / UNIT.name).read_text()
    p = pk.run("install")
    assert p.returncode == 0 and "DRY RUN" in p.stdout and (pk.units / UNIT.name).read_text() == before
    pk.grant("install")
    p = pk.run("install", "--apply", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.ledger()["execution-ops"]["uses"] == 4
    [event] = pk.audit()
    assert event["action"] == "active-trader-motion.install" and event["event"] == "fabric-grant-consumed"
    assert (pk.units / UNIT.name).read_text() == UNIT.read_text()
    archived = [f for f in pk.units.iterdir() if ".archived-" in f.name]
    assert len(archived) == 1 and archived[0].read_text() == before
    assert pk.calls.read_text().splitlines() == ["--user daemon-reload"]


def test_start_refuses_without_the_marker_or_the_fixed_unit(pk):
    pk.grant("start")
    p = pk.run("start")
    assert p.returncode == 1 and "marker" in p.stdout
    pk.marker.write_text("")
    p = pk.run("start")
    assert p.returncode == 1 and "install --apply first" in p.stdout


@pytest.mark.parametrize("now,state", [
    ("2026-10-19T11:00:00-04:00", "RTH"),
    ("2026-10-19T09:29:00-04:00", "PRE"),
    ("2026-10-19T16:30:00-04:00", "POST"),
])
def test_start_refuses_open_hours_unless_forced(pk, now, state):
    pk.marker.write_text("")
    (pk.units / UNIT.name).write_text(UNIT.read_text())
    pk.grant("start")
    p = pk.run("start", "--apply", NOW_ISO=now, TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 1 and f"market session is {state}" in p.stdout
    assert "restart" not in (pk.calls.read_text() if pk.calls.exists() else "")
    assert pk.ledger()["execution-ops"]["uses"] == 5 and not pk.audit()  # refused before --consume
    p = pk.run("start", "--force-open-hours", NOW_ISO=now)
    assert p.returncode == 0 and "WARNING --force-open-hours" in p.stdout and "DRY RUN" in p.stdout


def test_start_while_closed_restarts_the_unit_once(pk):
    pk.marker.write_text("")
    (pk.units / UNIT.name).write_text(UNIT.read_text())
    p = pk.run("start")
    assert p.returncode == 0 and "session CLOSED" in p.stdout and "DRY RUN" in p.stdout and not pk.calls.exists()
    pk.grant("start")
    p = pk.run("start", "--apply", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 0, p.stdout
    assert pk.ledger()["execution-ops"]["uses"] == 4 and len(pk.audit()) == 1
    assert "--user restart tradeai-active-trader-motion.service" in pk.calls.read_text().splitlines()
    for weekend in ("2026-10-17T11:00:00-04:00",):  # Saturday midday is CLOSED
        assert pk.run("start", NOW_ISO=weekend).returncode == 0


def test_proof_fails_when_nothing_moves_and_passes_when_the_runtime_cycles(pk):
    pk.beat(100)
    p = pk.run("proof")
    assert p.returncode == 1 and "FAIL cycle_count increasing" in p.stdout

    def tick():
        time.sleep(0.4)
        pk.beat(107)
        with pk.journal.open("a") as fh:
            fh.write("{}\n")
    t = threading.Thread(target=tick)
    t.start()
    p = pk.run("proof", PROOF_GAP_S="1.5")
    t.join()
    assert p.returncode == 0, p.stdout
    assert "proof: PASS" in p.stdout


def test_relay_and_rollback_edit_only_the_lane_with_backup_and_read_back(pk):
    pk.grant("relay")
    p = pk.run("relay")
    assert p.returncode == 0 and "DRY RUN" in p.stdout and LANE not in pk.live.read_text()
    (pk.proc / "4242" / "environ").write_text(f"TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch {LANE}\0")
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-comms-intent-consumer " + LANE in pk.live.read_text()
    assert pk.live.read_text().startswith("# keep me")
    assert {t: r["uses"] for t, r in pk.ledger().items()} == {"config-write": 4, "service": 4}
    pk.grant("rollback")
    (pk.proc / "4242" / "environ").write_text("TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch\0")
    p = pk.run("rollback", "--apply", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 0, p.stdout + p.stderr
    assert LANE not in pk.live.read_text() and "n8n-comms-intent-consumer" in pk.live.read_text()
    assert "systemctl --user stop" in p.stdout  # printed for the operator, never run
    assert not any("stop" in c for c in pk.calls.read_text().splitlines())
    assert len(list(pk.live.parent.glob("n8n-live-lanes.env.bak-*"))) == 2
    assert [e["action"] for e in pk.audit()] == ["active-trader-motion.relay", "active-trader-motion.rollback"]


def test_install_refuses_open_hours_like_start(pk):
    """AGENTS.md §24.10 binds every motion-unit mutation to CLOSED, not only the restart."""
    pk.grant("install")
    before = (pk.units / UNIT.name).read_text()
    p = pk.run("install", "--apply", NOW_ISO="2026-10-19T11:00:00-04:00", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 1 and "market session is RTH" in p.stdout
    assert (pk.units / UNIT.name).read_text() == before and not pk.calls.exists() and not pk.audit()


@pytest.mark.parametrize("step,ledger_step,drop", [
    ("start", "relay", ""),          # a config-write + service grant is not execution-ops
    ("install", "start", ""),        # bound to another action (and verb)
    ("start", "start", MOTION_UNIT),  # reason does not name the unit
    ("start", "start", "restart"),   # nor the verb
    ("relay", "relay", "tradeai-n8n-coordination-gateway.service"),
])
def test_wrong_tier_or_unbound_reason_refuses_without_effect_or_consumption(pk, step, ledger_step, drop):
    pk.marker.write_text("")
    (pk.proc / "4242" / "environ").write_text(f"TRADEAI_N8N_RELAY_LIVE_LANES={LANE}\0")
    if step == "start":
        (pk.units / UNIT.name).write_text(UNIT.read_text())
    original = pk.grant(ledger_step, drop=drop)
    live_before, unit_before = pk.live.read_text(), (pk.units / UNIT.name).read_text()
    p = pk.run(step, "--apply", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 1 and "grant refused" in p.stdout, p.stdout
    assert pk.ledger() == original and not pk.audit() and not pk.calls.exists()
    assert pk.live.read_text() == live_before and (pk.units / UNIT.name).read_text() == unit_before


def test_relay_without_the_service_grant_and_exhausted_grants_refuse(pk):
    doc = pk.grant("relay")
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT=GID, TRADEAI_FABRIC_SERVICE_GRANT="")
    assert p.returncode == 1 and "TRADEAI_FABRIC_SERVICE_GRANT" in p.stdout and pk.ledger() == doc
    pk.grant("relay", uses=0)
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT=GID)
    assert p.returncode == 1 and "grant refused" in p.stdout and LANE not in pk.live.read_text()
    assert not pk.calls.exists() and not pk.audit()


def test_dry_runs_consume_nothing(pk):
    pk.marker.write_text("")
    for step in ("install", "start", "relay", "rollback"):
        doc = pk.grant(step)
        assert pk.run(step).returncode in (0, 1)
        assert pk.ledger() == doc and not pk.audit(), step


def test_the_motion_actions_are_registered_with_their_section_24_10_tiers():
    from scripts.lib import fabric_grant as F
    rel = "docs/ops/packets/active-trader-motion-n8n-20261019/cutover.sh"
    acts = {k: v for k, v in F.ACTIONS.items() if v["packet"] == rel}
    assert set(acts) == {f"active-trader-motion.{s}" for s in ("install", "start", "relay", "rollback")}
    for step in ("install", "start"):
        a = acts[f"active-trader-motion.{step}"]
        assert a["tiers"] == ("execution-ops",) and a["units"] == (MOTION_UNIT,)
    for step in ("relay", "rollback"):
        a = acts[f"active-trader-motion.{step}"]
        assert a["tiers"] == ("config-write", "service") and a["units"] == RELAY_UNITS
    assert all(a["lanes"] == (LANE,) and a["workflow"] == "tradeai-dispatcher" for a in acts.values())
    assert rel in F.NO_CONSUMER_REASON
    src = SCRIPT.read_text()
    assert src.count("need_grant --consume") == 4 and " verify " not in src


def test_first_run_record_is_committed_and_read_only():
    text = (PACKET / "01_first_run.txt").read_text()
    summary = json.loads(text.split("DRY-RUN ", 1)[1].splitlines()[0])["summary"]
    assert summary["mode"] == "dry_run" and summary["verdict"]["band"] in (W.DISABLED, W.DOWN)
