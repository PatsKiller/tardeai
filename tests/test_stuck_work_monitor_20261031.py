"""Stuck-work monitor (operator 2026-10-31: "validate all stuck agents and processes fix montior and make auto
healings with claude code").

Pins, each with a positive control: self-deadlock and lock wait (lslocks rows + /proc wchan), D-state process,
unit activating/failed, truncated JSONL tail (repairable only when the previous line parses and no lock is held),
zero-byte state with/without a backup, stalled queue (and unknown, never zero, on a query error), open breaker,
stale heartbeat, silent lane (and the new-lane guard), a unit stranded on an old release (restart only when
allowlisted, never portfolio-server / broker units). Plus: one alert per item per day; heals run only with
heals_enabled and archive first; code defects become N8nCodeDefect@v1 records only with fixer_intake_enabled; a dry
run writes nothing. Hermetic: tmp state root, telegram_alert stubbed via sys.modules, no DB, TRADE_AI_CI=1.
"""

from __future__ import annotations

#: C1 firing coverage — this module injects the condition and asserts the message reaches the (stubbed) transport.
COVERS = ["scripts/stuck_work_monitor.py"]

import copy
import fcntl
import json
import os
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import stuck_work_monitor as swm  # noqa: E402
from lib import stuck_work as SW  # noqa: E402

NOW = datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)
CFG = swm.load_config()


def _cfg(**over):
    c = copy.deepcopy(CFG)
    for k, v in over.items():
        c[k] = v
    return c


# ---------------------------------------------------------------- locks / processes
def _proc(pid, args, wchan="locks_lock_inode_wait", stat="S", minutes=120):
    return {pid: {"args": args, "stat": stat, "wchan": wchan, "uid": 1000, "started": NOW - timedelta(minutes=minutes)}}


LOCK = "/state/data/cio/cio_wake_jobs.jsonl.lock"


def test_self_deadlock_is_a_p1_code_defect():
    locks = [{"pid": 7, "mode": "WRITE", "path": LOCK}, {"pid": 7, "mode": "WRITE*", "path": LOCK}]
    procs = _proc(7, "python3 scripts/cio_wake_dispatch_entrypoint.py")
    (f,) = SW.lock_findings(locks, procs, CFG, NOW)
    assert f["class"] == "self_deadlock" and f["severity"] == "P1" and f["heal"] == "code"
    assert f["lane"] == "cio-wake-dispatch"


def test_lock_wait_needs_a_live_kernel_wait_and_age():
    locks = [{"pid": 1, "mode": "WRITE", "path": LOCK}, {"pid": 2, "mode": "WRITE*", "path": LOCK}]
    assert SW.lock_findings(locks, _proc(2, "python3 x", minutes=120), CFG, NOW)[0]["class"] == "lock_wait"
    assert SW.lock_findings(locks, _proc(2, "python3 x", minutes=5), CFG, NOW) == []  # too young
    assert SW.lock_findings(locks, _proc(2, "python3 x", wchan="do_wait"), CFG, NOW) == []  # not waiting now
    ignored = [{"pid": 2, "mode": "WRITE*", "path": "/run/user/1000/x"}]
    assert SW.lock_findings(ignored, _proc(2, "python3 x"), CFG, NOW) == []


def test_d_state_process_is_reaper_never_killed_here():
    procs = _proc(9, "python3 scripts/thing.py", wchan="io_schedule", stat="D", minutes=60)
    procs[9]["d_confirmed"] = True
    (f,) = SW.process_findings(procs, CFG, NOW, set())
    assert f["class"] == "process_stuck" and f["heal"] == "reaper"
    assert SW.process_findings(_proc(9, "python3 scripts/thing.py", stat="S", wchan="io"), CFG, NOW, set()) == []
    once = _proc(9, "python3 scripts/thing.py", wchan="io_schedule", stat="D", minutes=60)  # one D sample only
    assert SW.process_findings(once, CFG, NOW, set()) == []


# ---------------------------------------------------------------- units
def test_unit_activating_and_failed():
    units = [
        {"unit": "tradeai-cio-reactive.service", "active": "activating", "since": NOW - timedelta(hours=30)},
        {"unit": "tradeai-tax-lots-rebuild.service", "active": "failed", "since": NOW - timedelta(hours=3)},
        {"unit": "tradeai-x.service", "active": "activating", "since": NOW - timedelta(minutes=5)},
        {
            "unit": "snap.firmware-updater.firmware-notifier.service",
            "active": "failed",
            "since": NOW - timedelta(days=3),
        },
    ]
    got = {f["item"]: f for f in SW.unit_findings(units, CFG, NOW)}
    assert set(got) == {"tradeai-cio-reactive.service", "tradeai-tax-lots-rebuild.service"}
    assert got["tradeai-cio-reactive.service"]["severity"] == "P1"
    assert got["tradeai-cio-reactive.service"]["lane"] == "cio-reactive"


# ---------------------------------------------------------------- files
def test_tail_state_and_repair_only_the_final_line():
    good = b'{"a":1}\n{"b":2}\n'
    trunc = good + b'{"c":3, "d": "trunca'
    assert SW.tail_state(good)["ok"] is True
    st = SW.tail_state(trunc)
    assert st["ok"] is False and st["prev_ok"] is True
    assert SW.repaired_bytes(trunc) == good
    assert SW.repaired_bytes(good) is None  # nothing to do
    middle = b'{"a":1}\n{broken\n{"c"'
    assert SW.repaired_bytes(middle) is None  # damage beyond the final line is never auto-repaired
    uline = '{"t":"a b"}'.encode() + b"\n" + b'{"x'  # U+2028 inside a good record: binary split keeps it
    assert SW.repaired_bytes(uline) == '{"t":"a b"}'.encode() + b"\n"


def test_file_findings_lock_guard_and_backup():
    tail = SW.tail_state(b'{"a":1}\n{"b', whole_file=True)
    old, young = NOW - timedelta(hours=1), NOW - timedelta(minutes=5)
    rows = [
        {"path": "/s/a.jsonl", "kind": "jsonl", "size": 10, "mtime": old, "tail": tail, "locked": False},
        {"path": "/s/b.jsonl", "kind": "jsonl", "size": 10, "mtime": old, "tail": tail, "locked": True},
        {"path": "/s/c.jsonl", "kind": "jsonl", "size": 10, "mtime": young, "tail": tail, "locked": False},
        {"path": "/s/t.json", "kind": "state", "size": 0, "mtime": old, "backup": "/s/t.bak", "backup_mtime": old},
        {"path": "/s/u.json", "kind": "state", "size": 0, "mtime": old, "backup": None},
        {"path": "/s/w.json", "kind": "state", "size": 0, "mtime": young, "backup": "/s/t.bak", "backup_mtime": old},
        {
            "path": "/s/x.json",
            "kind": "state",
            "size": 0,
            "mtime": old,
            "backup": "/s/t.bak",
            "backup_mtime": NOW - timedelta(hours=200),
        },
        {
            "path": "/s/y.json",
            "kind": "state",
            "size": 0,
            "mtime": old,
            "backup": "/s/t.bak",
            "backup_mtime": old,
            "locked": True,
        },
        {"path": "/s/v.json", "kind": "state", "size": 9, "mtime": old, "backup": None},
    ]
    got = {f["item"]: f["heal"] for f in SW.file_findings(rows, CFG, NOW)}
    assert got == {
        "/s/a.jsonl": "repair_tail",
        "/s/b.jsonl": "page",
        "/s/c.jsonl": "page",
        "/s/t.json": "restore_backup",
        "/s/u.json": "page",
        "/s/w.json": "page",
        "/s/x.json": "page",
        "/s/y.json": "page",
    }


# ---------------------------------------------------------------- queues / breakers / heartbeats / lanes
def test_queue_stalled_unknown_and_stuck_processing():
    rows = [
        {"name": "deep_overnight_llm_queue", "pending": 1928, "last_done": NOW - timedelta(days=160)},
        {"name": "agent_event_queue", "pending": 0, "last_done": NOW, "stuck_processing": 7},
        {"name": "watchlist_agent_jobs", "pending": 4, "last_done": NOW - timedelta(hours=1)},
        {"name": "watchlist_agent_jobs", "error": "OperationalError: down"},
    ]
    got = SW.queue_findings(rows, CFG, NOW)
    assert [(f["class"], f["item"]) for f in got] == [
        ("queue_stalled", "deep_overnight_llm_queue"),
        ("stuck_claim", "agent_event_queue: 7 rows processing"),
        ("queue_stalled", "watchlist_agent_jobs"),
    ]
    assert got[0]["lane"] == "deep-overnight-llm-drain" and got[0]["heal"] == "code"
    assert got[2]["evidence"]["unknown"] is True  # an error is unknown, never zero


def test_breakers_heartbeats_and_lanes():
    br = [
        {"lane_id": "cio-ask-lifecycle", "opened_at": NOW - timedelta(hours=22), "released_at": None},
        {"lane_id": "x", "opened_at": NOW - timedelta(hours=1), "released_at": None},
        {"lane_id": "y", "opened_at": NOW - timedelta(days=3), "released_at": "2026-10-30"},
    ]
    (b,) = SW.breaker_findings(br, CFG, NOW)
    assert (
        b["item"] == "cio-ask-lifecycle"
        and "n8n_dlq.py release --lane cio-ask-lifecycle" in b["evidence"]["release_cmd"]
    )
    hb = [
        {"agent_id": "a", "last_seen": NOW - timedelta(days=3)},
        {"agent_id": "test_agent", "last_seen": None},
        {"agent_id": "b", "last_seen": NOW},
    ]
    assert [f["item"] for f in SW.heartbeat_findings(hb, CFG, NOW)] == ["a"]
    lanes = [
        {"lane_id": "cio-wake-dispatch", "cadence_hours": 0.25, "signal_at": NOW - timedelta(hours=5)},
        {"lane_id": "fresh", "cadence_hours": 24, "signal_at": NOW - timedelta(hours=1)},
        {"lane_id": "new", "cadence_hours": 24, "signal_at": None, "state_since": NOW - timedelta(hours=2)},
        {"lane_id": "old", "cadence_hours": 24, "signal_at": None, "state_since": NOW - timedelta(days=5)},
    ]
    got = SW.lane_findings(lanes, CFG, NOW)
    assert got[0]["item"] == "cio-wake-dispatch" and got[0]["severity"] == "P2"
    assert got[1]["severity"] == "P3" and [x["lane"] for x in got[1]["evidence"]["lanes"]] == ["old"]


# ---------------------------------------------------------------- stale release
REL = "/" + "/".join(["srv", "trade-ai-releases", "portfolio-server"])


def _sr_cfg():
    c = _cfg()
    c["stale_release"] = {**c["stale_release"], "releases_dir": REL}
    return c


def test_stale_release_positive_control_and_policy():
    cur = f"{REL}/99bfa4abc-main"
    units = [
        {"unit": "tradeai-ops-applier.service", "pid": 1, "cwd": f"{REL}/f7c1e96cb-main"},
        {"unit": "portfolio-server.service", "pid": 2, "cwd": f"{REL}/f7c1e96cb-main"},
        {"unit": "fresh.service", "pid": 4, "cwd": cur},
        {"unit": "inside.service", "pid": 6, "cwd": f"{cur}/apps/command-center-v3"},  # inside CURRENT: current
        {"unit": "elsewhere.service", "pid": 5, "cwd": "/srv/other"},
    ]
    promoted = NOW - timedelta(hours=1)
    got = {f["item"]: f for f in SW.stale_release_findings(units, cur, promoted, _sr_cfg(), NOW)}
    assert set(got) == {"tradeai-ops-applier.service", "portfolio-server.service"}
    assert all(f["heal"] == "page" for f in got.values())  # page only: a restart ends a run (§28.1)
    assert got["tradeai-ops-applier.service"]["evidence"]["serving"] == "f7c1e96cb-main"
    assert got["portfolio-server.service"]["evidence"]["never_auto_act"] is True
    assert SW.stale_release_findings(units, cur, NOW - timedelta(minutes=5), _sr_cfg(), NOW) == []  # inside grace


# ---------------------------------------------------------------- apply: alerts, heals, fixer intake, dry run
@pytest.fixture
def sent(monkeypatch):
    box: list[dict] = []
    mod = types.ModuleType("telegram_alert")

    def send_telegram(message, **kw):
        box.append({"message": message, **kw})
        return True

    mod.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return box


def _receipt(findings):
    return {"schema": "StuckWorkReceipt@v1", "at": SW._iso(NOW), "db_error": None, "findings": findings, "counts": {}}


def _tail_finding(path, *, now=None):
    """A finding built from the real file (its real mtime), the way the monitor builds it."""
    st = path.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
    return SW.file_findings(
        [
            {
                "path": str(path),
                "kind": "jsonl",
                "size": st.st_size,
                "mtime": mtime,
                "tail": SW.tail_state(path.read_bytes(), whole_file=True),
                "locked": False,
            }
        ],
        CFG,
        now or datetime.now(timezone.utc),
    )


def _age(path, minutes):
    t = time.time() - minutes * 60
    os.utime(path, (t, t))


def test_apply_alerts_once_per_day_and_heals_and_intake(tmp_path, sent):
    store = tmp_path / "data" / "cio" / "cio_wake_jobs.jsonl"
    store.parent.mkdir(parents=True)
    store.write_bytes(b'{"a":1}\n{"b":2}\n{"c":"trunc')
    _age(store, 90)
    ino = store.stat().st_ino
    deadlock = SW.lock_findings(
        [{"pid": 7, "mode": "WRITE", "path": LOCK}, {"pid": 7, "mode": "WRITE*", "path": LOCK}],
        _proc(7, "python3 scripts/cio_wake_dispatch_entrypoint.py"),
        CFG,
        NOW,
    )
    findings = _tail_finding(store) + deadlock
    cfg = _cfg(alerts_enabled=True, heals_enabled=True, fixer_intake_enabled=True)
    cfg["heals"] = {**cfg["heals"], "archive_dir": "{state}/archive/heals"}
    out = swm.apply(_receipt(findings), cfg, now=NOW, project=tmp_path, state=tmp_path)
    assert len(sent) == 1 and sent[0]["priority"] == "P1" and "STUCK WORK" in sent[0]["message"]
    assert sent[0]["message_class"] == cfg["message_class"]
    # heals_enabled does NOT run an unratified heal (review round 2): the store is untouched
    assert out["actions"]["heals"][0]["result"] == "not_ratified"
    assert store.read_bytes().endswith(b'"trunc') and store.stat().st_ino == ino
    assert not (tmp_path / "archive").exists()
    defects = [json.loads(x) for x in (tmp_path / cfg["fixer_defects_rel"]).read_text().splitlines()]
    assert [d["code_defect"]["lane"] for d in defects] == ["cio-wake-dispatch"]
    d = defects[0]
    assert d["code_defect"]["schema"] == "N8nCodeDefect@v1" and d["code_defect"]["kind"] == "code_defect"
    assert d["receipt"]["stderr_tail"].startswith("self_deadlock")  # the fixer reads the TOP-LEVEL receipt (#2129)
    swm.apply(_receipt(findings), cfg, now=NOW + timedelta(minutes=5), project=tmp_path, state=tmp_path)
    assert len(sent) == 1
    assert len((tmp_path / cfg["fixer_defects_rel"]).read_text().splitlines()) == 1


def test_switches_off_means_no_send_no_heal_no_intake(tmp_path, sent):
    store = tmp_path / "x.jsonl"
    store.write_bytes(b'{"a":1}\n{"b')
    before = store.read_bytes()
    out = swm.apply(_receipt(_tail_finding(store)), CFG, now=NOW, project=tmp_path, state=tmp_path)
    assert sent == [] and store.read_bytes() == before
    assert out["actions"]["alerts"]["why"] == "alerts_enabled is false"
    assert not (tmp_path / CFG["fixer_defects_rel"]).exists()


def test_send_failure_is_loud(tmp_path, monkeypatch):
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda message, **kw: False
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    f = SW.queue_findings([{"name": "deep_overnight_llm_queue", "pending": 3, "last_done": None}], CFG, NOW)
    out = swm.apply(_receipt(f), _cfg(alerts_enabled=True), now=NOW, project=tmp_path, state=tmp_path)
    assert out["actions"]["alerts"]["sent"] is False and out["actions"]["errors"]


def test_no_restart_capability_exists():
    """Review 2026-10-31 (§28.1): restarting a unit ends a run; this monitor never restarts anything."""
    assert not hasattr(swm, "restart_unit") and "restart" not in SW.HEAL_KEYS
    src = (ROOT / "scripts" / "stuck_work_monitor.py").read_text()
    assert '"restart"' not in src and 'systemctl", "--user", "restart' not in src


def test_dry_run_main_writes_nothing(tmp_path, monkeypatch, sent, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        swm,
        "evaluate",
        lambda cfg, **k: _receipt(
            SW.queue_findings([{"name": "deep_overnight_llm_queue", "pending": 3, "last_done": None}], cfg, NOW)
        ),
    )
    rc = swm.main(["--dry-run"])
    assert rc == 3 and sent == [] and list(tmp_path.iterdir()) == []
    assert "would hand to the Claude Code fixer: cd-deep-overnight-llm-drain" in capsys.readouterr().out


def test_config_defaults_are_off():
    assert CFG["alerts_enabled"] is False and CFG["heals_enabled"] is False and CFG["fixer_intake_enabled"] is False
    assert "restart_allowlist" not in CFG["stale_release"]
    for word in (
        "portfolio-server",
        "broker",
        "order",
        "stop",
        "position",
        "account",
        "paper",
        "scalp",
        "sender",
        "telegram",
        "secret",
        "guard",
        "deploy",
        "release",
        "retention",
        "agent-loop",
        "dof",
    ):
        assert word in SW.NEVER_ACT
    assert SW.never_act("Tradeai-SCALP-Hot.service")  # case-insensitive
    assert SW.never_act("x-broker-y", {"never_act_extra": []})  # config cannot remove the code floor
    assert SW.never_act("custom-unit", {"never_act_extra": ["custom"]}) and not SW.never_act("custom-unit")


# ---------------------------------------------------------------- sweep classes (coordinator 2026-10-31, 18 classes)
def _p(pid, **kw):
    base = {
        "args": "python3 scripts/x.py",
        "stat": "S",
        "ppid": 100,
        "wchan": "do_wait",
        "uid": 1000,
        "started": NOW - timedelta(hours=2),
        "cpu_s": 0.0,
        "cwd": "/srv/x",
        "deleted_open": [],
    }
    return {pid: {**base, **kw}}


def test_unit_lint_overrun_and_expected_refusal():
    units = [
        {"unit": "tradeai-cio-reactive.service", "type": "oneshot", "timeout_start": "infinity"},
        {"unit": "tradeai-ok.service", "type": "oneshot", "timeout_start": "5min"},
        {"unit": "other.service", "type": "oneshot", "timeout_start": "infinity"},  # not a Trade AI unit
        {"unit": "tradeai-daemon.service", "type": "simple", "timeout_start": "infinity"},  # a daemon: fine
        {
            "unit": "tradeai-cio-delivery.service",
            "type": "oneshot",
            "timeout_start": "10min",
            "last_wall_s": 273,
            "last_cpu_s": 239,
        },
    ]
    got = {f["class"]: f for f in SW.unit_lint_findings(units, CFG, NOW)}
    assert got["unit_no_timeout"]["evidence"]["units"] == ["tradeai-cio-reactive.service"]
    assert got["unit_overrun"]["evidence"]["cpu_bound"] is True
    refused = [
        {
            "unit": "tradeai-disk-hygiene-enforcer.service",
            "active": "failed",
            "exit_status": "77",
            "since": NOW - timedelta(hours=7),
        }
    ]
    (f,) = SW.unit_findings(refused, CFG, NOW)
    assert f["severity"] == "P3" and f["evidence"]["expected_refusal"] is True
    refused[0]["exit_status"] = "1"  # any other failure still pages
    assert SW.unit_findings(refused, CFG, NOW)[0]["severity"] == "P2"


def test_process_classes_spin_orphan_deleted_zombie():
    procs = {}
    procs.update(_p(1, args="python3 scripts/cio_delivery.py", cpu_s=2 * 3600 * 0.95))  # spin
    procs.update(
        _p(
            2,
            args="git rev-parse 1163^{commit}",
            ppid=1,
            cwd="/srv/wt (deleted)",
            started=NOW - timedelta(days=11),
            cpu_s=11 * 86400 * 0.9,
        )
    )  # runaway orphan
    procs.update(_p(3, args="bash killwatch.sh", deleted_open=[{"path": "/tmp/x.log (deleted)", "size": 408 << 20}]))
    procs.update(_p(4, stat="Z", ppid=50))
    procs.update(_p(5, args="python3 scripts/calm.py", cpu_s=60))  # quiet: no finding
    got = {f["class"]: f for f in SW.proc_extra_findings(procs, CFG, NOW)}
    assert set(got) == {"cpu_spin", "orphan_runaway", "deleted_open_space", "zombie"}
    assert got["orphan_runaway"]["heal"] == "reaper" and got["deleted_open_space"]["evidence"]["bytes"] == 408 << 20
    assert got["zombie"]["evidence"]["zombies"] == [4]


def test_ledger_classes_probe_poison_verifier():
    got = SW.ledger_findings(
        [{"lane_id": "c", "slot_key": "s1", "attempts": 15}], [{"lane_id": "d", "count": 4}], CFG, NOW
    )
    assert sorted((f["class"], f["item"]) for f in got) == [("poison_item", "c:s1"), ("verifier_blind", "d")]
    br = [{"lane_id": "a", "opened_at": NOW - timedelta(hours=30), "released_at": None}]
    (b,) = SW.breaker_findings(br, CFG, NOW, {"a": 0})  # one finding per breaker; "never probed" is evidence
    assert b["evidence"]["never_probed"] is True and b["heal"] == "page"
    assert SW.fixer_defect(b, NOW, receipt="r") is None  # a breaker is a symptom, never sent to the fixer


def test_registry_drift_is_not_silence():
    rows = [{"lane_id": "x", "cadence_hours": 1, "signal_at": None, "signal_missing": "signal file does not exist"}]
    (f,) = SW.lane_findings(rows, CFG, NOW)
    assert f["class"] == "registry_drift" and f["severity"] == "P3"


def test_missed_window_only_on_trading_days():
    due = NOW - timedelta(hours=3)
    w = [{"lane": "premarket-pipeline", "due": due, "grace_min": 60, "signal_at": due - timedelta(days=1)}]
    assert SW.missed_window_findings(w, NOW, trading_day=True)[0]["class"] == "missed_window"
    assert SW.missed_window_findings(w, NOW, trading_day=False) == []
    w[0]["signal_at"] = due + timedelta(minutes=5)
    assert SW.missed_window_findings(w, NOW, trading_day=True) == []


def test_claim_board_and_starved_consumer():
    claims = [
        {"claim_id": "c1", "status": "active", "heartbeat_at": NOW - timedelta(days=6)},
        {"claim_id": "c2", "status": "active", "heartbeat_at": NOW - timedelta(hours=1)},
        {"claim_id": "c3", "status": "done", "heartbeat_at": NOW - timedelta(days=9)},
    ]
    (f,) = SW.claim_findings(claims, CFG, NOW)
    assert f["evidence"]["count"] == 1
    rows = [
        {"name": "deep_overnight_llm_queue", "pending": 9, "last_done": NOW - timedelta(days=3), "consumer_fresh": True}
    ]
    assert SW.queue_findings(rows, CFG, NOW)[0]["class"] == "starved_consumer"


def test_heal_loop_precursors_and_stale_lock():
    (f,) = SW.heal_loop_findings({"trade_ai_session_stale": 189, "once": 1}, CFG, NOW)
    assert f["item"] == "trade_ai_session_stale" and f["severity"] == "P1"
    got = SW.precursor_findings({"disk_pct": {"/": 95.0}, "swap_pct": 100.0, "pg_in_recovery": True}, CFG, NOW)
    assert [(x["item"], x["severity"]) for x in got] == [
        ("disk /", "P1"),
        ("swap", "P2"),
        ("postgres in recovery", "P1"),
    ]
    assert SW.precursor_findings({"disk_pct": {"/": 73.0}, "swap_pct": 10.0, "pg_in_recovery": False}, CFG, NOW) == []
    locks = [
        {"path": "/s/self_heal_fixer.lock", "pid": 182522, "pid_alive": False, "held": False, "mtime": NOW},
        {"path": "/s/live.lock", "pid": 1, "pid_alive": True, "held": False, "mtime": NOW},
        {"path": "/s/held.lock", "pid": 9, "pid_alive": False, "held": True, "mtime": NOW},
    ]
    (lk,) = SW.stale_lock_findings(locks, NOW)
    assert lk["item"] == "/s/self_heal_fixer.lock" and SW.heal_plan(lk, CFG)["action"] == "reconcile_lock"


def test_reconcile_lock_heal_archives_and_rechecks(tmp_path):
    lock = tmp_path / "self_heal_fixer.lock"
    lock.write_text('{"pid": 999999999}')
    plan = {"action": "reconcile_lock", "path": str(lock), "pid": 999999999, "archive_dir": str(tmp_path / "arch")}
    holder = lock.open("a")  # someone holds the flock: an active flock-style lock is never moved (M3)
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert swm.do_heal(plan, tmp_path, tmp_path, CFG)["result"] == "skipped" and lock.exists()
    fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
    holder.close()
    res = swm.do_heal(plan, tmp_path, tmp_path, CFG)
    assert res["result"] == "reconciled" and not lock.exists() and Path(res["archive"]).read_text().startswith("{")
    lock.write_text('{"pid": 1}')  # pid 1 is alive: never reconciled
    assert swm.do_heal({**plan, "pid": 1}, tmp_path, tmp_path, CFG)["result"] == "skipped" and lock.exists()


def test_heal_loop_suppresses_the_heal(tmp_path, sent):
    store = tmp_path / "x.jsonl"
    store.write_bytes(b'{"a":1}\n{"b":2}\n{"c')
    _age(store, 90)
    rec = _receipt(_tail_finding(store))
    rec["heal_counts_24h"] = {str(store): 3}
    out = swm.apply(rec, _cfg(heals_enabled=True), now=NOW, project=tmp_path, state=tmp_path)
    assert out["actions"]["heals"][0]["result"] == "suppressed" and store.read_bytes().endswith(b'{"c')


def test_shadow_lane_alive_by_ledger_run_done_without_a_receipt():
    """Coordinator 2026-10-31: shadow/canary lanes never write the live receipt; a RUN_DONE in the ledger is life."""
    base = {
        "cadence_hours": 1,
        "signal_at": None,
        "signal_missing": "signal file does not exist",
        "state_since": NOW - timedelta(days=9),
    }
    alive = {"lane_id": "x-shadow", "stage": "shadow", "ledger_done_at": NOW - timedelta(minutes=40), **base}
    assert SW.lane_findings([alive], CFG, NOW) == []  # no receipt, but a fresh RUN_DONE: not flagged, not drift
    dead = {**alive, "lane_id": "y-canary", "stage": "canary", "ledger_done_at": NOW - timedelta(days=2)}
    (f,) = SW.lane_findings([dead], CFG, NOW)
    assert f["class"] == "lane_silent" and f["evidence"]["lanes"][0]["lane"] == "y-canary"
    live = {**alive, "lane_id": "z-live", "stage": None}  # a live lane with no receipt is still drift
    assert SW.lane_findings([live], CFG, NOW)[0]["class"] == "registry_drift"


def test_quarantined_items_are_poison_findings_for_the_fixer(tmp_path):
    doc = {
        "cio-ask-lifecycle": {
            "streaks": {},
            "quarantined": {
                "thr_b00c8806cf63a6bf": {"at": NOW.isoformat(), "consecutive_failures": 3, "reason": "CHECK_FAILED"}
            },
        }
    }
    d = tmp_path / CFG["poison_quarantine_dir_rel"]
    d.mkdir(parents=True)
    (d / "cio-ask-lifecycle.json").write_text(json.dumps(doc["cio-ask-lifecycle"]))  # #2380: one store per lane
    (f,) = SW.quarantine_findings(swm.collect_quarantined(CFG, tmp_path), NOW)
    assert f["class"] == "poison_item" and f["heal"] == "code" and f["lane"] == "cio-ask-lifecycle"
    assert SW.fixer_defect(f, NOW, receipt="r")["code_defect"]["lane"] == "cio-ask-lifecycle"
    assert swm.collect_quarantined(CFG, tmp_path / "nowhere") == []


# ---------------------------------------------------------------- review 2026-10-31: every failing input is a test
def test_m1_m2_and_blank_tail():
    assert SW.tail_state(b'{"a":1}\n\n\n', whole_file=True)["ok"] is True  # trailing blank lines are not damage
    mid = SW.tail_state(b'{"a":1}\n{broken\n{"b":2}\n{"c', whole_file=True)
    assert mid["ok"] is False and mid["repairable"] is False  # any bad complete line refuses (M1)
    assert SW.truncate_offset(b'{"a":1}\n{broken\n{"b":2}\n{"c') is None
    one = SW.tail_state(b'{"only', whole_file=True)
    assert one["repairable"] is False and SW.truncate_offset(b'{"only') is None  # fewer than two records (M2)
    assert SW.truncate_offset(b'{"a":1}\n{"b":2}\n{"c') == len(b'{"a":1}\n{"b":2}\n')
    window = SW.tail_state(b'tial-cut-record"}\n{"a":1}\n{"c')  # first line of a window may be cut: ignored
    assert window["repairable"] is True


def test_h1_repair_refuses_live_writer_young_file_and_changed_file(tmp_path):
    store = tmp_path / "s.jsonl"
    store.write_bytes(b'{"a":1}\n{"b":2}\n{"c')
    _age(store, 90)
    (f,) = _tail_finding(store)
    plan = SW.heal_plan(f, CFG)
    lockf = tmp_path / "s.jsonl.lock"
    lockf.write_text("")
    holder = lockf.open("a")  # the store's real flock held by a writer
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert swm.do_heal(plan, tmp_path, tmp_path, CFG, allow_unratified=True)["result"] == "skipped"
    fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
    holder.close()
    with store.open("ab") as fh:  # a writer appended after the finding: mtime changed -> refuse
        fh.write(b'\n{"d":4}\n')
    _age(store, 60)
    assert swm.do_heal(plan, tmp_path, tmp_path, CFG, allow_unratified=True)["why"] == "file changed since the finding"
    young = tmp_path / "y.jsonl"
    young.write_bytes(b'{"a":1}\n{"b":2}\n{"c')
    (fy,) = _tail_finding(young)
    assert fy["heal"] == "page" and "min ago" in fy["evidence"]["why_not_auto"]


def test_h2_restore_rechecks_mtime_backup_age_and_json(tmp_path):
    target = tmp_path / "t.json"
    target.write_bytes(b"")
    _age(target, 120)
    bak = tmp_path / "t.json.bak"
    bak.write_text('{"lots": []}')
    _age(bak, 60)
    mt = SW._iso(datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc))
    plan = {
        "action": "restore_backup",
        "path": str(target),
        "from": str(bak),
        "archive_dir": str(tmp_path / "a"),
        "mtime": mt,
    }
    bak.write_text("{not json")
    _age(bak, 60)
    assert swm.do_heal(plan, tmp_path, tmp_path, CFG, allow_unratified=True)["why"] == "backup is not valid JSON now"
    bak.write_text('{"lots": []}')
    _age(bak, 60 * 200)
    assert (
        "backup" in swm.do_heal(plan, tmp_path, tmp_path, CFG, allow_unratified=True)["why"]
    )  # older than backup_max_age_h
    _age(bak, 60)
    _age(target, 30)  # touched since the finding
    assert swm.do_heal(plan, tmp_path, tmp_path, CFG, allow_unratified=True)["why"] == "file changed since the finding"
    _age(target, 120)
    plan["mtime"] = SW._iso(datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc))
    res = swm.do_heal(plan, tmp_path, tmp_path, CFG, allow_unratified=True)
    assert res["result"] == "restored" and json.loads(target.read_text()) == {"lots": []}


def test_dedupe_keys_never_carry_counts_or_pids():
    with pytest.raises(ValueError):
        SW.finding("process_stuck", "pid 12", since=None, now=NOW, severity="P2", heal="page", evidence={})
    a = SW.claim_findings([{"claim_id": "c", "status": "active", "heartbeat_at": NOW - timedelta(days=9)}], CFG, NOW)
    b = SW.claim_findings(
        [{"claim_id": c, "status": "active", "heartbeat_at": NOW - timedelta(days=9)} for c in ("c", "d")], CFG, NOW
    )
    assert a[0]["dedupe_key"] == b[0]["dedupe_key"]  # 1 claim or 2: one daily alert
    p1 = SW.proc_extra_findings(
        _p(1, args="python3 scripts/cio_delivery.py --run 111", cpu_s=2 * 3600 * 0.95), CFG, NOW
    )
    p2 = SW.proc_extra_findings(
        _p(2, args="python3 scripts/cio_delivery.py --run 222", cpu_s=2 * 3600 * 0.95), CFG, NOW
    )
    assert p1[0]["dedupe_key"] == p2[0]["dedupe_key"]


def test_cutover_lane_alive_by_ledger_and_tilde_signal_paths(tmp_path, monkeypatch):
    row = {
        "lane_id": "c",
        "stage": "cutover",
        "cadence_hours": 1,
        "signal_at": None,
        "signal_missing": "signal file does not exist",
        "ledger_done_at": NOW - timedelta(minutes=30),
    }
    assert SW.lane_findings([row], CFG, NOW) == []
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "sig.json").write_text("{}")
    reg = {
        "lanes": [
            {
                "lane_id": "t",
                "state": "ACTIVE",
                "expected_cadence_hours": 1,
                "output_signal": {"kind": "file_mtime", "path": "~/sig.json"},
            }
        ]
    }
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lane_registry.json").write_text(json.dumps(reg))
    (got,) = swm.collect_lanes(CFG, tmp_path)
    assert got["signal_missing"] is None and got["signal_at"] is not None


def test_deadman_is_not_a_window_lane():
    assert "premarket-delivery-deadman" not in {w["lane"] for w in CFG["market_windows"]}


# ---------------------------------------------------------------- review round 2 (2026-10-31)
def test_only_ratified_heals_can_run(tmp_path):
    assert SW.RATIFIED_HEALS == frozenset({"reconcile_lock"})
    store = tmp_path / "s.jsonl"
    store.write_bytes(b'{"a":1}\n{"b":2}\n{"c')
    _age(store, 90)
    (f,) = _tail_finding(store)
    plan = SW.heal_plan(f, CFG)
    assert swm.do_heal(plan, tmp_path, tmp_path, CFG)["result"] == "refused"  # not ratified: refused in code
    assert store.read_bytes().endswith(b'{"c')


def test_never_act_is_enforced_on_heals(tmp_path):
    lock = tmp_path / "broker_session.lock"
    lock.write_text('{"pid": 999999999}')
    plan = {"action": "reconcile_lock", "path": str(lock), "pid": 999999999, "archive_dir": str(tmp_path / "a")}
    res = swm.do_heal(plan, tmp_path, tmp_path, CFG)
    assert res["result"] == "refused" and "NEVER_ACT" in res["why"] and lock.exists()


def test_corrupt_quarantine_store_is_reported_not_empty(tmp_path):
    d = tmp_path / CFG["poison_quarantine_dir_rel"]
    d.mkdir(parents=True)
    (d / "cio-ask-lifecycle.json").write_text("{half")
    (row,) = swm.collect_quarantined(CFG, tmp_path)
    assert row["item"] == "<store unreadable>" and row["lane"] == "cio-ask-lifecycle"
