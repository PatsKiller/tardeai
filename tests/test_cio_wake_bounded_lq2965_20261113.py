"""LQ-20261107-2965: the bounded CIO wake runner (scripts/run_cio_wake_bounded.py).

Pinned:
1. the admission fence refuses while a NON-comment crontab line runs the same wake, while a wake is in flight,
   while the single-flight lock is held, when crontab is unreadable, and when systemd-run is missing
   (never runs unbounded);
2. the scope argv carries every bound the incident needs, around the whole tree, in a fixed order;
3. a dry run spawns nothing and writes nothing;
4. a refused --apply exits 3 and keeps the previous ok_at; an ok run advances ok_at; a failed run keeps it;
5. peak memory / oom_kill are read from the scope cgroup while it is alive, and OOM wins the classification.

Synthetic only: fake /proc, fake cgroup tree, fake Popen. No crontab, no systemd, no wake, no live receipt.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import run_cio_wake_bounded as rb  # noqa: E402

CRON_ACTIVE = (
    "0 * * * * CUR=$(readlink -f /x/CURRENT) && cd \"$CUR\" && PERSISTENT_WAKE_ENABLED=1 "
    "$PY scripts/run_persistent_wake.py --agent-id cio >>/x/persistent_wake.log 2>&1\n"
)
CRON_PAUSED = "# PAUSED 2026-11-13 SEV-1 LQ-2954 " + CRON_ACTIVE


# ── 1. admission ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    (CRON_ACTIVE, [1]),
    (CRON_PAUSED, []),
    ("   # " + CRON_ACTIVE, []),
    ("MAILTO=x\n\n" + CRON_ACTIVE, [3]),
    (CRON_ACTIVE.replace("--agent-id cio", "--agent-id cio-shadow"), []),   # a different agent is not ours
    (CRON_ACTIVE.replace("--agent-id cio", "--agent-id=cio"), [1]),
    ("*/5 * * * * $PY scripts/cio_wake_dispatch_entrypoint.py\n", []),     # the dispatcher is another lane
])
def test_only_a_non_comment_line_running_this_agents_wake_is_active(text, expected):
    assert rb.active_cron_lines(text, "cio") == expected


def _admit(*, cron=("", None), pids=(), sysrun="/usr/bin/systemd-run"):
    return rb.admission("cio", crontab=lambda: cron, running=lambda a: list(pids), systemd_run=lambda: sysrun)


def test_admitted_when_cron_is_paused_nothing_runs_and_systemd_run_exists():
    adm = _admit(cron=(CRON_PAUSED, None))
    assert adm["refusals"] == []


def test_an_active_cron_line_is_refused_and_named():
    adm = _admit(cron=("# hdr\n" + CRON_ACTIVE, None))
    assert adm["refusals"] == ["cron_line_active"] and adm["active_cron_lines"] == [2]


def test_an_unreadable_crontab_fails_closed():
    assert _admit(cron=(None, "crontab_unreadable:rc=2"))["refusals"] == ["crontab_unreadable:rc=2"]


def test_a_wake_in_flight_is_refused():
    adm = _admit(pids=[2296820])
    assert adm["refusals"] == ["wake_in_flight"] and adm["in_flight_pids"] == [2296820]


def test_no_systemd_run_means_refuse_never_unbounded():
    assert _admit(sysrun=None)["refusals"] == ["systemd_run_unavailable"]


def _proc(tmp_path: Path, pid: int, argv: list[str]) -> None:
    d = tmp_path / "proc" / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(("\0".join(argv) + "\0").encode())


def test_running_wakes_finds_the_python_process_not_its_wrappers(tmp_path):
    _proc(tmp_path, 10, ["/usr/bin/python3", "scripts/run_persistent_wake.py", "--agent-id", "cio"])
    _proc(tmp_path, 11, ["/bin/sh", "-c", "python3 scripts/run_persistent_wake.py --agent-id cio"])
    _proc(tmp_path, 12, ["timeout", "1800s", "python3", "scripts/run_persistent_wake.py", "--agent-id", "cio"])
    _proc(tmp_path, 13, ["/usr/bin/python3", "scripts/run_persistent_wake.py", "--agent-id", "macro"])
    _proc(tmp_path, 14, ["/venv/bin/python3.14", "/r/scripts/run_persistent_wake.py", "--agent-id=cio"])
    (tmp_path / "proc" / "self").mkdir()
    assert rb.running_wakes("cio", tmp_path / "proc", self_pid=1) == [10, 14]


def test_running_wakes_on_a_missing_proc_root_is_empty(tmp_path):
    assert rb.running_wakes("cio", tmp_path / "nope", self_pid=1) == []


# ── 2. the bound ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_scope_carries_every_bound_and_wraps_the_whole_tree():
    argv = rb.build_argv(agent_id="cio", unit="cio-wake-cio-x", python="/py", wake_script="/r/w.py",
                         timeout_s=1800, kill_after_s=30, memory_max="2G")
    assert argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
    sep = argv.index("--")
    props = argv[:sep]
    for want in ("--property=MemoryMax=2G", "--property=MemorySwapMax=0", "--property=OOMPolicy=kill",
                 "--property=CPUWeight=20", "--property=IOWeight=20", "--unit=cio-wake-cio-x"):
        assert want in props, want
    assert argv[sep + 1:] == ["nice", "-n", "10", "ionice", "-c", "3", "timeout", "--kill-after=30s", "1800s",
                              "/py", "/r/w.py", "--agent-id", "cio"]


def test_wake_env_sets_the_cron_flags_but_an_explicit_value_wins(tmp_path):
    env = rb.wake_env({"WAKE_L3_ALLOW_LIVE_PROVIDER": "0", "X": "1"}, tmp_path)
    assert env["PERSISTENT_WAKE_ENABLED"] == "1" and env["PERSISTENT_WAKE_SCHEDULE_ENABLED"] == "1"
    assert env["WAKE_L3_ALLOW_LIVE_PROVIDER"] == "0" and env["X"] == "1"
    assert env["TRADEAI_WAKE_RECEIPTS_PATH"].endswith("data/persistent_wake/selection_feed/receipts.jsonl")


@pytest.mark.parametrize("rc,ooms,want", [
    (0, 0, "ok"), (0, None, "ok"), (1, 0, "failed"), (124, 0, "timeout"), (137, 0, "timeout"),
    (137, 1, "oom_killed"), (-9, 2, "oom_killed"), (-15, 0, "killed"), (None, None, "scope_failed"),
])
def test_classification(rc, ooms, want):
    assert rb.classify(rc, ooms) == want


def test_a_kill_between_polls_is_still_oom_when_systemd_says_so():
    assert rb.classify(-9, 0, "oom-kill") == "oom_killed"
    assert rb.classify(-9, 0, None) == "killed"


# ── 3/4/5. run(): dry, refused, ok, failed, oom ─────────────────────────────────────────────────────────


def _args(tmp_path, *, apply=True, **kw):
    ns = argparse.Namespace(agent_id="cio", apply=apply, wake_dry_run=False, wake_script=None,
                            lock=str(tmp_path / "w.lock"), timeout_s=1800, kill_after_s=30, memory_max="2G",
                            state_root=str(tmp_path / "state"))
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def _receipt(tmp_path) -> dict:
    return json.loads((tmp_path / "state" / "data" / "runtime" / "cio-persistent-wake_bounded_last.json").read_text())


class FakeProc:
    def __init__(self, rc: int, polls: int = 2):
        self.pid = 4242
        self._rc, self._left = rc, polls
        self.returncode = None

    def poll(self):
        if self._left <= 0:
            self.returncode = self._rc
            return self._rc
        self._left -= 1
        return None


class FakeSampler(rb.ScopeSampler):
    def __init__(self, peaks, ooms=0):
        super().__init__()
        self._peaks, self._ooms = list(peaks), ooms

    def sample(self, pid, **kw):
        self.cgroup = Path("/sys/fs/cgroup/user.slice/cio-wake.scope")
        self.samples += 1
        self.peak = max(self.peak or 0, self._peaks.pop(0))
        self.oom_kills = self._ooms


def _clock():
    t = [datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)]

    def now():
        t[0] += timedelta(seconds=5)
        return t[0]
    return now


def _no_spawn(*a, **k):
    raise AssertionError("spawned")


def test_dry_run_spawns_nothing_and_writes_nothing(tmp_path, capsys):
    rc = rb.run(_args(tmp_path, apply=False), admit=lambda a: {"refusals": ["cron_line_active"]},
                popen=_no_spawn)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["outcome"] == "dry_run" and out["would_refuse"] == ["cron_line_active"]
    assert not (tmp_path / "state").exists()


def test_refused_apply_exits_3_and_keeps_the_previous_ok_at(tmp_path):
    rpath = tmp_path / "state" / "data" / "runtime" / "cio-persistent-wake_bounded_last.json"
    rpath.parent.mkdir(parents=True)
    rpath.write_text(json.dumps({"ok_at": "2026-11-13T13:00:00Z"}))
    rc = rb.run(_args(tmp_path), admit=lambda a: {"refusals": ["wake_in_flight"], "in_flight_pids": [7]},
                popen=_no_spawn)
    doc = _receipt(tmp_path)
    assert rc == rb.EXIT_REFUSED and doc["outcome"] == "refused" and doc["ok_at"] == "2026-11-13T13:00:00Z"


def test_a_held_lock_refuses(tmp_path):
    fd = os.open(tmp_path / "w.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        rc = rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=_no_spawn)
    finally:
        os.close(fd)
    assert rc == rb.EXIT_REFUSED and _receipt(tmp_path)["admission"]["refusals"] == ["lock_held"]


def test_an_ok_run_records_exit_peak_and_advances_ok_at(tmp_path):
    seen = {}

    def popen(argv, env, cwd):
        seen.update(argv=argv, env=env)
        return FakeProc(0, polls=3)

    rc = rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=popen,
                sampler=FakeSampler([100, 300, 200]), sleep=lambda s: None, now=_clock(),
                show=lambda u: {"LoadState": "not-found"})
    doc = _receipt(tmp_path)
    assert rc == 0 and doc["outcome"] == "ok" and doc["exit_code"] == 0
    assert doc["peak_memory_bytes"] == 300 and doc["samples"] == 3 and doc["oom_kill_events"] == 0
    assert doc["ok_at"] == doc["ended_at"] and doc["schema"] == "CioWakeBoundedRun@v1"
    assert seen["argv"][0] == "systemd-run" and seen["env"]["PERSISTENT_WAKE_ENABLED"] == "1"


def test_an_oom_kill_is_named_and_does_not_advance_ok_at(tmp_path):
    rb.write_receipt(tmp_path / "state" / "data" / "runtime" / "cio-persistent-wake_bounded_last.json",
                     {"outcome": "ok", "ended_at": "2026-11-13T14:00:00Z"})
    rc = rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=lambda *a, **k: FakeProc(-9, 1),
                sampler=FakeSampler([2 * 1024**3], ooms=1), sleep=lambda s: None, now=_clock(),
                show=lambda u: {"LoadState": "not-found"})
    doc = _receipt(tmp_path)
    assert rc == -9 and doc["outcome"] == "oom_killed" and doc["oom_kill_events"] == 1
    assert doc["ok_at"] == "2026-11-13T14:00:00Z"


def test_a_spawn_failure_is_scope_failed_exit_4(tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("systemd-run")

    rc = rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=boom, sleep=lambda s: None,
                now=_clock())
    assert rc == rb.EXIT_SCOPE_FAILED and _receipt(tmp_path)["outcome"] == "scope_failed"


def test_the_sampler_reads_only_this_runs_scope_never_the_callers(tmp_path):
    proc = tmp_path / "proc" / "77"
    proc.mkdir(parents=True)
    cg_root = tmp_path / "cg"
    s = rb.ScopeSampler("cio-wake-cio-1")
    (cg_root / "user.slice" / "tmux-spawn-1.scope").mkdir(parents=True)
    (cg_root / "user.slice" / "tmux-spawn-1.scope" / "memory.peak").write_text("17461420032\n")
    (proc / "cgroup").write_text("0::/user.slice/tmux-spawn-1.scope\n")   # the caller's scope: never read
    s.sample(77, proc_root=tmp_path / "proc", cg_root=cg_root)
    assert s.cgroup is None and s.samples == 0          # not yet inside the transient scope
    scope = cg_root / "user.slice" / "cio-wake-cio-1.scope"
    scope.mkdir(parents=True)
    (proc / "cgroup").write_text("0::/user.slice/cio-wake-cio-1.scope\n")
    (scope / "memory.peak").write_text("1048576\n")
    (scope / "memory.events").write_text("low 0\nhigh 0\nmax 3\noom 1\noom_kill 1\n")
    s.sample(77, proc_root=tmp_path / "proc", cg_root=cg_root)
    (scope / "memory.peak").write_text("524288\n")       # never goes down in the receipt
    s.sample(77, proc_root=tmp_path / "proc", cg_root=cg_root)
    assert (s.peak, s.oom_kills, s.samples, s.cgroup) == (1048576, 1, 2, scope)


def test_the_shell_entry_point_execs_the_python_runner():
    text = (ROOT / "scripts" / "run_cio_wake_bounded.sh").read_text()
    assert "set -euo pipefail" in text and 'exec "${TRADEAI_VENV_PYTHON:-${PY:-python3}}" scripts/run_cio_wake_bounded.py "$@"' in text


def test_an_oom_the_sampler_missed_is_recovered_from_the_failed_scope(tmp_path):
    """Smoke 2026-11-13: 512 MB alloc under MemoryMax=256M; the last poll saw 240 MB and oom_kill 0, the process
    died -9, and the lingering scope read Result=oom-kill MemoryPeak=268435456."""
    shown = []
    rc = rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=lambda *a, **k: FakeProc(-9, 1),
                sampler=FakeSampler([240627712], ooms=0), sleep=lambda s: None, now=_clock(),
                show=lambda u: shown.append(u) or {"LoadState": "loaded", "Result": "oom-kill",
                                                    "MemoryPeak": "268435456"})
    doc = _receipt(tmp_path)
    assert rc == -9 and doc["outcome"] == "oom_killed" and doc["unit_result"] == "oom-kill"
    assert doc["peak_memory_bytes"] == 268435456 and shown == [doc["unit"] + ".scope"]


def test_a_real_run_also_writes_the_lanes_v2_receipt_and_a_dry_run_does_not(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    lane = tmp_path / "state" / "data" / "runtime" / "cio-persistent-wake_last.json"
    rb.run(_args(tmp_path, apply=False), admit=lambda a: {"refusals": []}, popen=_no_spawn)
    assert not lane.exists()
    rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=lambda *a, **k: FakeProc(0, 1),
           sampler=FakeSampler([5]), sleep=lambda s: None, now=_clock(), show=lambda u: {})
    doc = json.loads(lane.read_text())
    assert doc["schema"] == "LaneRunReceipt@v2" and doc["produced_count"] == 1 and doc["lane_id"] == "cio-persistent-wake"
    rb.run(_args(tmp_path), admit=lambda a: {"refusals": ["cron_line_active"]}, popen=_no_spawn)
    doc = json.loads(lane.read_text())
    assert doc["produced_count"] == 0 and doc["empty_reason"] == "admission_refused"
    assert doc["outcome"] == "error" and doc["outcome_reason"] == "refused"
    rb.run(_args(tmp_path), admit=lambda a: {"refusals": []}, popen=lambda *a, **k: FakeProc(-9, 1),
           sampler=FakeSampler([5], ooms=1), sleep=lambda s: None, now=_clock(), show=lambda u: {})
    doc = json.loads(lane.read_text())
    assert doc["outcome"] == "error" and doc["outcome_reason"] == "oom_killed" and doc["produced_count"] == 0


def test_a_wake_dry_run_probe_never_advances_ok_at_nor_touches_the_lane_receipt(tmp_path):
    """--apply --wake-dry-run runs selection under the bounds but no wake: it must not read as a real run."""
    runtime = tmp_path / "state" / "data" / "runtime"
    seen = {}

    def popen(argv, env, cwd):
        seen["argv"] = argv
        return FakeProc(0, polls=2)

    rc = rb.run(_args(tmp_path, wake_dry_run=True), admit=lambda a: {"refusals": []}, popen=popen,
                sampler=FakeSampler([50, 80]), sleep=lambda s: None, now=_clock(),
                show=lambda u: {"LoadState": "not-found"})
    probe = json.loads((runtime / rb.WAKE_DRY_RUN_RECEIPT).read_text())
    assert rc == 0 and seen["argv"][-1] == "--dry-run"
    assert probe["outcome"] == "ok" and probe["wake_dry_run"] is True and probe["ok_at"] is None
    assert probe["peak_memory_bytes"] == 80
    assert not (runtime / "cio-persistent-wake_bounded_last.json").exists()
    assert not (runtime / "cio-persistent-wake_last.json").exists()
