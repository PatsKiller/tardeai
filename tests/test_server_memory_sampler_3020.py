"""LQ-20261113-3020: the fast memory sampler against a synthetic /proc and cgroup tree (fixtures only)."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ops import server_memory_sampler as sm  # noqa: E402

CG = "/user.slice/portfolio-server.service"


def w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def mkproc(proc: Path, pid: int, name: str, rss=0, swap=None, threads=1, hwm=0):
    body = f"Name:\t{name}\nVmRSS:\t{rss} kB\nVmHWM:\t{hwm} kB\nThreads:\t{threads}\n"
    if swap is not None:
        body += f"VmSwap:\t{swap} kB\n"
    w(proc / str(pid) / "status", body)
    w(proc / str(pid) / "environ", "SECRET=hunter2")
    w(proc / str(pid) / "cmdline", "python\0--token=abc")


def tcp_line(port, state):
    return f"  0: 00000000:{port:04X} 00000000:0000 {state} 0:0 00:0 0 0 0 0\n"


@pytest.fixture
def tree(tmp_path):
    proc, sysroot = tmp_path / "proc", tmp_path / "sys"
    cg = sysroot / CG.lstrip("/")
    w(cg / "memory.current", "2000000000\n")
    w(cg / "memory.peak", "2500000000\n")
    w(cg / "memory.swap.current", "4096\n")
    w(cg / "memory.stat", "anon 1500000000\nfile 400000000\nshmem 0\nkernel 5\n")
    w(cg / "memory.events", "low 0\nhigh 10\nmax 0\noom 0\noom_kill 0\n")
    w(cg / "memory.pressure", "some avg10=1.50 avg60=0.80 avg300=0.10 total=1\nfull avg10=0.50 avg60=0.20 avg300=0.00 total=2\n")
    w(cg / "cgroup.procs", "100\n101\n")
    mkproc(proc, 100, "python3", rss=900_000, hwm=1_000_000, swap=500, threads=7)
    mkproc(proc, 101, "child", rss=100_000, threads=2)
    for i in range(12):
        mkproc(proc, 200 + i, f"o{i}", swap=100 + i)
    w(proc / "100" / "task" / "1" / "comm", "swr-build-1\n")
    w(proc / "100" / "task" / "2" / "comm", "MainThread\n")
    w(proc / "meminfo", "MemAvailable:   33000000 kB\nSwapFree:   56 kB\n")
    w(proc / "net" / "tcp", "  sl\n" + tcp_line(7777, "01") + tcp_line(7777, "08") + tcp_line(7777, "08")
      + tcp_line(7777, "0A") + tcp_line(7777, "06") + tcp_line(8080, "01"))
    w(proc / "net" / "tcp6", "  sl\n")
    return proc, sysroot, tmp_path


def one(tree, st=None, pid=100, release="r1", log=None):
    proc, sysroot, _ = tree
    return sm.sample(1000.0, st or sm.State(), pid, CG, log or sm.AppLogTail(None), proc, sysroot, release)


def test_record_fields(tree):
    r = one(tree)
    assert r["cg_current_b"] == 2000000000 and r["cg_peak_b"] == 2500000000 and r["cg_swap_b"] == 4096
    assert r["cg_stat"] == {"anon": 1500000000, "file": 400000000, "shmem": 0}
    assert r["proc"]["rss_kb"] == 900000 and r["proc"]["hwm_kb"] == 1000000 and r["proc"]["threads"] == 7
    assert r["proc"]["swr_build_threads"] == 1
    assert "some avg10=1.50" in r["cg_pressure"] and " | full avg10=0.50" in r["cg_pressure"]
    assert r["host"] == {"MemAvailable": 33000000, "SwapFree": 56}
    assert r["tcp7777"] == {"est": 1, "close_wait": 2, "other": 1}   # LISTEN and port 8080 excluded
    assert r["markers"] == ["start"] and r["app_log"] is None


def test_process_vs_unit_split(tree):
    s = one(tree)["split"]
    assert s["unit_pids"] == 2 and s["main_rss_kb"] == 900000 and s["unit_rss_kb"] == 1000000
    assert s["other_rss_kb"] == 100000
    assert s["cg_unexplained_b"] == 2000000000 - 1000000 * 1024   # page cache / kernel the pids do not hold


def test_swap_top_ten_names_and_pids_only_no_secrets(tree):
    r = one(tree)
    top = r["swap_top"]
    assert len(top) == 10 and top[0] == {"pid": 100, "comm": "python3", "swap_kb": 500}
    assert all(set(x) == {"pid", "comm", "swap_kb"} for x in top)
    blob = json.dumps(r)
    assert "hunter2" not in blob and "--token" not in blob


def test_swap_top_only_every_60s(tree):
    proc, sysroot, _ = tree
    st = sm.State()
    a = sm.sample(1000.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    b = sm.sample(1002.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    c = sm.sample(1061.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    assert "swap_top" in a and "swap_top" not in b and "swap_top" in c


def test_events_delta_then_recreated_marker(tree):
    proc, sysroot, _ = tree
    cg = sysroot / CG.lstrip("/")
    st = sm.State()
    sm.sample(1.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    w(cg / "memory.events", "low 0\nhigh 14\nmax 0\noom 0\noom_kill 1\n")
    b = sm.sample(3.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    assert b["cg_events_delta"] == {"high": 4, "max": 0, "oom": 0, "oom_kill": 1} and b["markers"] == []
    w(cg / "memory.events", "low 0\nhigh 1\nmax 0\noom 0\noom_kill 0\n")
    c = sm.sample(5.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    assert c["cg_events_delta"] is None and "cgroup_recreated" in c["markers"]


def test_pid_and_release_change_markers(tree):
    proc, sysroot, _ = tree
    st = sm.State()
    sm.sample(1.0, st, 100, CG, sm.AppLogTail(None), proc, sysroot, "rel-a")
    r = sm.sample(3.0, st, 555, CG, sm.AppLogTail(None), proc, sysroot, "rel-b")
    assert r["pid_changed"] is True and r["markers"] == ["pid_changed", "release_changed"]
    r2 = sm.sample(5.0, st, 555, CG, sm.AppLogTail(None), proc, sysroot, "rel-b")
    assert r2["markers"] == [] and r2["pid_changed"] is False


def test_unreadable_is_null_not_zero(tree):
    proc, sysroot, _ = tree
    (sysroot / CG.lstrip("/") / "memory.peak").unlink()
    r = sm.sample(1.0, sm.State(), 100, CG, sm.AppLogTail(None), proc, sysroot, "r")
    assert r["cg_peak_b"] is None and r["cg_current_b"] == 2000000000
    nocg = sm.sample(1.0, sm.State(), 0, "", sm.AppLogTail(None), proc, sysroot, "r")
    assert nocg["cg_current_b"] is None and nocg["cg_events"] is None and nocg["split"]["unit_pids"] is None


def test_app_log_counts_only_new_reaped_lines(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("  [watchdog] reaped abandoned compute: /old after 99s (x)\n")
    t = sm.AppLogTail(str(log))
    assert t.poll() == {"reaped": 0, "last_path": None, "last_age_s": None}   # history before the sampler is not counted
    with log.open("a") as fh:
        fh.write("noise\n  [watchdog] reaped abandoned compute: /api/a after 31s (t)\n  [watchdog] reaped abandoned compute: /api/b after 45s (t)\n")
    assert t.poll() == {"reaped": 2, "last_path": "/api/b", "last_age_s": 45}
    assert t.poll()["reaped"] == 0
    log.write_text("  [watchdog] reaped abandoned compute: /api/c after 7s (t)\n")   # rotated/truncated
    assert t.poll()["reaped"] == 1


def test_app_log_missing_is_null(tmp_path):
    assert sm.AppLogTail(str(tmp_path / "nope")).poll() is None


def test_rotation_renames_and_overflow_goes_to_archive_never_deleted(tmp_path):
    out = tmp_path / "s.jsonl"
    for name, body in (("s.jsonl.1", "one"), ("s.jsonl.2", "two"), ("s.jsonl", "x" * 2_000_000)):
        (tmp_path / name).write_text(body)
    assert sm.rotate(out, 1, 2, stamp="T") == "rotated"
    assert (tmp_path / "s.jsonl.1").read_text() == "x" * 2_000_000 and (tmp_path / "s.jsonl.2").read_text() == "one"
    assert (tmp_path / "s.jsonl_archive" / "s.jsonl.T").read_text() == "two"   # the oldest moved, not removed
    assert not out.exists()


def test_small_file_not_rotated(tmp_path):
    (tmp_path / "s.jsonl").write_text("tiny")
    assert sm.rotate(tmp_path / "s.jsonl", 1, 2) is None


def test_interval_is_clamped_1_to_5(monkeypatch):
    monkeypatch.setenv("SAMPLER_INTERVAL_S", "0.01")
    assert sm.Config().interval == 1.0
    monkeypatch.setenv("SAMPLER_INTERVAL_S", "600")
    assert sm.Config().interval == 5.0


def _cfg(tmp_path, **kw):
    c = sm.Config()
    c.out, c.interval, c.max_hours = tmp_path / "o" / "s.jsonl", 2.0, 8
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_run_appends_n_lines_and_sleeps_the_interval(tree, tmp_path):
    proc, sysroot, _ = tree
    cfg = _cfg(tmp_path)
    slept, t = [], [1000.0]
    rc = sm.run(cfg, proc, sysroot, unit=lambda: (100, CG), clock=lambda: t[0],
                sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)), max_iterations=3, release="r")
    lines = cfg.out.read_text().splitlines()
    assert rc == 0 and len(lines) == 3 and all(json.loads(x)["schema"] == sm.SCHEMA for x in lines)
    assert slept == [2.0, 2.0, 2.0]


def test_run_stops_at_total_cap_and_says_so(tree, tmp_path):
    proc, sysroot, _ = tree
    cfg = _cfg(tmp_path, total_cap_mb=0.0005)   # ~500 bytes: one sample exceeds it
    t = [1.0]
    rc = sm.run(cfg, proc, sysroot, unit=lambda: (100, CG), clock=lambda: t[0],
                sleep=lambda s: t.__setitem__(0, t[0] + s), max_iterations=50, release="r")
    last = json.loads(cfg.out.read_text().splitlines()[-1])
    assert rc == 3 and last["markers"] == ["stopped_at_cap"]


def test_run_exits_after_max_hours(tree, tmp_path):
    proc, sysroot, _ = tree
    cfg = _cfg(tmp_path, max_hours=0.001)   # 3.6 s
    t = [0.0]
    rc = sm.run(cfg, proc, sysroot, unit=lambda: (100, CG), clock=lambda: t[0],
                sleep=lambda s: t.__setitem__(0, t[0] + s), release="r")
    assert rc == 0 and len(cfg.out.read_text().splitlines()) == 2


def test_default_paths_derive_from_state_root(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLER_OUT", raising=False)
    monkeypatch.delenv("SAMPLER_CURRENT", raising=False)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "releases" / "persistent-state"))
    c = sm.Config()
    assert c.out == tmp_path / "releases" / "persistent-state" / "data" / "ops" / sm.OUT_NAME
    assert c.current == str(tmp_path / "releases" / "portfolio-server" / "CURRENT")


def test_release_comes_from_the_current_symlink(tree, tmp_path):
    proc, sysroot, _ = tree
    rel = tmp_path / "rel" / "abc123-live"
    rel.mkdir(parents=True)
    cur = tmp_path / "rel" / "CURRENT"
    os.symlink(rel, cur)
    r = sm.sample(1.0, sm.State(), 100, CG, sm.AppLogTail(None), proc, sysroot, None, str(cur))
    assert r["release"] == "abc123-live"
