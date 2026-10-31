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
import json
import sys
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
    tail = SW.tail_state(b'{"a":1}\n{"b')
    rows = [
        {"path": "/s/a.jsonl", "kind": "jsonl", "size": 10, "mtime": NOW, "tail": tail, "locked": False},
        {"path": "/s/b.jsonl", "kind": "jsonl", "size": 10, "mtime": NOW, "tail": tail, "locked": True},
        {"path": "/s/t.json", "kind": "state", "size": 0, "mtime": NOW, "backup": "/s/t.bak"},
        {"path": "/s/u.json", "kind": "state", "size": 0, "mtime": NOW, "backup": None},
        {"path": "/s/v.json", "kind": "state", "size": 9, "mtime": NOW, "backup": None},
    ]
    got = {f["item"]: f["heal"] for f in SW.file_findings(rows, CFG, NOW)}
    assert got == {
        "/s/a.jsonl": "repair_tail",
        "/s/b.jsonl": "page",
        "/s/t.json": "restore_backup",
        "/s/u.json": "page",
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


def _sr_cfg(allow=()):
    c = _cfg()
    c["stale_release"] = {**c["stale_release"], "releases_dir": REL, "restart_allowlist": list(allow)}
    return c


def test_stale_release_positive_control_and_policy():
    cur = f"{REL}/99bfa4abc-main"
    units = [
        {"unit": "tradeai-ops-applier.service", "pid": 1, "cwd": f"{REL}/f7c1e96cb-main"},
        {"unit": "portfolio-server.service", "pid": 2, "cwd": f"{REL}/f7c1e96cb-main"},
        {"unit": "tradeai-active-trader-motion.service", "pid": 3, "cwd": f"{REL}/aaa"},
        {"unit": "fresh.service", "pid": 4, "cwd": cur},
        {"unit": "elsewhere.service", "pid": 5, "cwd": "/srv/other"},
    ]
    promoted = NOW - timedelta(hours=1)
    got = {f["item"]: f for f in SW.stale_release_findings(units, cur, promoted, _sr_cfg(), NOW)}
    assert set(got) == {
        "tradeai-ops-applier.service",
        "portfolio-server.service",
        "tradeai-active-trader-motion.service",
    }
    assert all(f["heal"] == "page" for f in got.values())  # empty allowlist pages only
    got = {
        f["item"]: f
        for f in SW.stale_release_findings(
            units, cur, promoted, _sr_cfg(["tradeai-ops-applier.service", "portfolio-server.service"]), NOW
        )
    }
    assert got["tradeai-ops-applier.service"]["heal"] == "restart"
    assert got["portfolio-server.service"]["heal"] == "page"  # never restarted even when allowlisted
    assert got["tradeai-active-trader-motion.service"]["heal"] == "page"
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


def _tail_finding(path):
    return SW.file_findings(
        [
            {
                "path": str(path),
                "kind": "jsonl",
                "size": 5,
                "mtime": NOW,
                "tail": SW.tail_state(path.read_bytes()),
                "locked": False,
            }
        ],
        CFG,
        NOW,
    )


def test_apply_alerts_once_per_day_and_heals_and_intake(tmp_path, sent):
    store = tmp_path / "data" / "cio" / "cio_wake_jobs.jsonl"
    store.parent.mkdir(parents=True)
    store.write_bytes(b'{"a":1}\n{"b":2}\n{"c":"trunc')
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
    assert store.read_bytes() == b'{"a":1}\n{"b":2}\n'  # repaired
    assert out["actions"]["heals"][0]["result"] == "repaired"
    archived = list((tmp_path / "archive" / "heals").rglob("cio_wake_jobs.jsonl"))
    assert archived and archived[0].read_bytes().endswith(b'"trunc')  # archived before the repair
    defects = [json.loads(x) for x in (tmp_path / cfg["fixer_defects_rel"]).read_text().splitlines()]
    assert [d["code_defect"]["lane"] for d in defects] == ["cio-wake-dispatch"]
    d = defects[0]["code_defect"]
    assert (
        d["schema"] == "N8nCodeDefect@v1"
        and d["consumer"] == "claude_code_iterative_fix"
        and d["kind"] == "code_defect"
    )
    # same day again: no second alert, no second hand-off, no second heal
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


def test_restart_refuses_non_allowlisted(monkeypatch):
    calls = []
    monkeypatch.setattr(swm, "_run", lambda argv, timeout=20: (calls.append(argv), (0, ""))[1])
    res = swm.restart_unit("portfolio-server.service")
    assert res["result"] == "refused" and calls == []


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
    assert CFG["stale_release"]["restart_allowlist"] == []
    assert any(g.startswith("portfolio-server") for g in CFG["stale_release"]["never_restart_globs"])


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
        {"a": 0, "b": 2},
        [{"lane_id": "c", "slot_key": "s1", "attempts": 15}],
        [{"lane_id": "d", "count": 4}],
        CFG,
        NOW,
        ["a", "b"],
    )
    kinds = sorted((f["class"], f["item"]) for f in got)
    assert kinds == [("breaker_no_probe", "a"), ("poison_item", "c:s1"), ("verifier_blind", "d")]


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


def test_reconcile_lock_heal_archives_and_rechecks(tmp_path, monkeypatch):
    lock = tmp_path / "self_heal_fixer.lock"
    lock.write_text('{"pid": 999999999}')
    monkeypatch.setattr(swm, "collect_locks", lambda: [])
    plan = {"action": "reconcile_lock", "path": str(lock), "pid": 999999999, "archive_dir": str(tmp_path / "arch")}
    res = swm.do_heal(plan, tmp_path, tmp_path)
    assert res["result"] == "reconciled" and not lock.exists() and Path(res["archive"]).read_text().startswith("{")
    lock.write_text('{"pid": 1}')  # pid 1 is alive: never reconciled
    assert swm.do_heal({**plan, "pid": 1}, tmp_path, tmp_path)["result"] == "skipped" and lock.exists()


def test_heal_loop_suppresses_the_heal(tmp_path, sent):
    store = tmp_path / "x.jsonl"
    store.write_bytes(b'{"a":1}\n{"b')
    rec = _receipt(_tail_finding(store))
    rec["heal_counts_24h"] = {str(store): 3}
    out = swm.apply(rec, _cfg(heals_enabled=True), now=NOW, project=tmp_path, state=tmp_path)
    assert out["actions"]["heals"][0]["result"] == "suppressed" and store.read_bytes().endswith(b'{"b')


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
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / CFG["poison_quarantine_rel"]).write_text(json.dumps(doc))
    (f,) = SW.quarantine_findings(swm.collect_quarantined(CFG, tmp_path), NOW)
    assert f["class"] == "poison_item" and f["heal"] == "code" and f["lane"] == "cio-ask-lifecycle"
    assert SW.fixer_defect(f, NOW, receipt="r")["code_defect"]["lane"] == "cio-ask-lifecycle"
    assert swm.collect_quarantined(CFG, tmp_path / "nowhere") == []
