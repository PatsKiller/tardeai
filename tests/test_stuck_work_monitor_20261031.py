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
    (f,) = SW.process_findings(procs, CFG, NOW, set())
    assert f["class"] == "process_stuck" and f["heal"] == "reaper"
    assert SW.process_findings(_proc(9, "python3 scripts/thing.py", stat="S", wchan="io"), CFG, NOW, set()) == []


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
    assert [f["item"] for f in got] == ["deep_overnight_llm_queue", "agent_event_queue", "watchlist_agent_jobs"]
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
