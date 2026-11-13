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
    assert rc == sm.EXIT_STOPPED_AT_CAP == 40 and sm.EXIT_STOPPED_AT_CAP != 3 and last["markers"] == ["stopped_at_cap"]


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


# ── rework 3020r (review REVIEW-LQ-20261113-3020r-cc-opus-3) ───────────────────────────────────────────────────────
def _run_with_units(tree, tmp_path, answers, **kw):
    """Run len(answers) iterations; ``unit`` yields the scripted answers (None = a failed systemctl read)."""
    proc, sysroot, _ = tree
    cfg = _cfg(tmp_path, **kw)
    it = iter(answers)
    t = [1.0]
    rc = sm.run(cfg, proc, sysroot, unit=lambda: next(it), clock=lambda: t[0],
                sleep=lambda s: t.__setitem__(0, t[0] + 11), max_iterations=len(answers), release="r")
    return rc, [json.loads(x) for x in cfg.out.read_text().splitlines()]


def test_b1_a_failed_unit_read_is_not_a_restart(tree, tmp_path):
    rc, rows = _run_with_units(tree, tmp_path, [(100, CG), None, (100, CG)])
    assert rc == 0 and len(rows) == 3
    assert all("pid_changed" not in r["markers"] for r in rows) and not any(r["pid_changed"] for r in rows)
    assert rows[1]["pid"] is None and "unit_read_failed" in rows[1]["markers"]      # unknown, not 0
    assert rows[1]["cg_current_b"] == 2_000_000_000                                  # last known cgroup keeps being read
    assert rows[0]["pid"] == rows[2]["pid"] == 100


def test_b1_a_real_restart_between_known_pids_is_still_marked(tree, tmp_path):
    _, rows = _run_with_units(tree, tmp_path, [(100, CG), None, (101, CG)])
    assert "pid_changed" in rows[2]["markers"] and "pid_changed" not in rows[1]["markers"]


def test_b1_a_stopped_unit_is_a_known_pid_zero(tree, tmp_path):
    _, rows = _run_with_units(tree, tmp_path, [(100, CG), (0, "")])
    assert rows[1]["pid"] == 0 and "pid_changed" in rows[1]["markers"] and "unit_read_failed" not in rows[1]["markers"]


def test_b1_unit_info_failure_is_none_not_zero(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError
    monkeypatch.setattr(sm.subprocess, "run", boom)
    assert sm.unit_info() is None
    class R:
        returncode, stdout = 1, "MainPID=5\n"
    monkeypatch.setattr(sm.subprocess, "run", lambda *a, **k: R())
    assert sm.unit_info() is None
    R.returncode, R.stdout = 0, "MainPID=0\nControlGroup=\n"
    assert sm.unit_info() == (0, "")


def test_b2_a_reaped_line_split_across_two_polls_is_counted_once(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("old\n")
    t = sm.AppLogTail(str(log))
    assert t.poll()["reaped"] == 0
    line = "  [watchdog] reaped abandoned compute: /api/y after 40s extra\n"
    with log.open("a") as fh:
        fh.write(line[:30])
    assert t.poll()["reaped"] == 0
    with log.open("a") as fh:
        fh.write(line[30:])
    got = t.poll()
    assert got == {"reaped": 1, "last_path": "/api/y", "last_age_s": 40}
    assert t.poll()["reaped"] == 0                                # not counted twice


def test_b2_complete_lines_before_a_partial_tail_are_counted_now(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("")
    t = sm.AppLogTail(str(log))
    t.poll()
    one = "[watchdog] reaped abandoned compute: /a after 5s\n"
    with log.open("a") as fh:
        fh.write(one + one[:20])
    assert t.poll()["reaped"] == 1
    with log.open("a") as fh:
        fh.write(one[20:])
    assert t.poll()["reaped"] == 1


def test_b2_a_replaced_log_is_read_from_the_start(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("x" * 10)
    t = sm.AppLogTail(str(log))
    t.poll()
    os.replace(log, tmp_path / "app.log.1")
    log.write_text("[watchdog] reaped abandoned compute: /n after 9s\n" + "pad" * 20)   # bigger than the old offset
    assert t.poll()["reaped"] == 1


def test_s1_env_values_must_be_finite_and_positive(monkeypatch):
    for name in ("SAMPLER_TOTAL_CAP_MB", "SAMPLER_MAX_HOURS", "SAMPLER_ROTATE_MB", "SAMPLER_KEEP"):
        for bad in ("nan", "inf", "-1", "0", "abc"):
            monkeypatch.setenv(name, bad)
            with pytest.raises(sm.ConfigError):
                sm.Config()
        monkeypatch.delenv(name)


def test_s1_total_cap_is_clamped_to_1024_mb_and_main_exits_2_on_a_bad_value(monkeypatch, capsys):
    monkeypatch.setenv("SAMPLER_TOTAL_CAP_MB", "999999")
    assert sm.Config().total_cap_mb == 1024.0
    monkeypatch.setenv("SAMPLER_MAX_HOURS", "nan")
    assert sm.main() == sm.EXIT_BAD_CONFIG == 2
    assert "SAMPLER_MAX_HOURS" in capsys.readouterr().err


def test_s1_rotate_with_no_out_file_does_not_crash(tmp_path):
    assert sm.rotate(tmp_path / "missing.jsonl", 0, 2) is None            # threshold 0: the old code renamed a file that is not there


def test_s2_k4_the_cap_counts_the_archive_directory(tmp_path):
    out = tmp_path / "s.jsonl"
    out.write_text("a" * 10)
    arch = tmp_path / "s.jsonl_archive"
    arch.mkdir()
    (arch / "s.jsonl.1").write_text("b" * 500)
    assert sm.total_bytes(out) == 510


def test_s2_k5_the_cap_counts_every_numbered_segment(tmp_path):
    out = tmp_path / "s.jsonl"
    out.write_text("a" * 10)
    (tmp_path / "s.jsonl.1").write_text("b" * 100)
    (tmp_path / "s.jsonl.2").write_text("c" * 1000)
    (tmp_path / "other.log").write_text("z" * 5000)                # not ours
    assert sm.total_bytes(out) == 1110


def test_s2_k4_k5_archive_growth_stops_the_run(tree, tmp_path):
    proc, sysroot, _ = tree
    cfg = _cfg(tmp_path, total_cap_mb=0.01)                         # ~10 KB
    cfg.out.parent.mkdir(parents=True, exist_ok=True)
    (cfg.out.parent / "s.jsonl_archive").mkdir()
    (cfg.out.parent / "s.jsonl_archive" / "s.jsonl.9").write_text("x" * 20_000)
    rc = sm.run(cfg, proc, sysroot, unit=lambda: (100, CG), clock=lambda: 1.0, sleep=lambda s: None, max_iterations=3, release="r")
    assert rc == sm.EXIT_STOPPED_AT_CAP
    assert json.loads(cfg.out.read_text().splitlines()[-1])["markers"] == ["stopped_at_cap"]


def test_s2_r6_keep_zero_is_clamped_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLER_KEEP", "0.4")
    assert sm.Config().keep == 1
    out = tmp_path / "s.jsonl"
    out.write_text("x" * 2_000_000)
    (tmp_path / "s.jsonl.1").write_text("first")
    sm.rotate(out, 1, 0, stamp="T")                                  # keep=0 handed straight to rotate
    assert (tmp_path / "s.jsonl_archive" / "s.jsonl.T").read_text() == "first"   # moved, not overwritten
    assert (tmp_path / "s.jsonl.1").read_text() == "x" * 2_000_000


def test_s2_r5_two_rotations_in_the_same_second_keep_both_segments(tmp_path):
    out = tmp_path / "s.jsonl"
    for body in ("one", "two", "three"):
        (tmp_path / "s.jsonl.1").write_text(body)
        out.write_text("x" * 2_000_000)
        sm.rotate(out, 1, 1, stamp="SAME")
    got = sorted(p.read_text() for p in (tmp_path / "s.jsonl_archive").iterdir())
    assert got == ["one", "three", "two"]                             # nothing overwritten, all three same-second archives kept


def test_s2_r7_rotate_threshold_is_megabytes(tmp_path):
    out = tmp_path / "s.jsonl"
    out.write_text("x" * 900_000)                                     # 0.86 MiB
    assert sm.rotate(out, 1, 2) is None
    out.write_text("x" * 1_100_000)                                   # 1.05 MiB
    assert sm.rotate(out, 1, 2) == "rotated"


def test_s4_unreadable_tcp_is_null_not_zero(tmp_path):
    assert sm.tcp_states(tmp_path / "no-proc") is None
    w(tmp_path / "p" / "net" / "tcp", "  sl\n")
    assert sm.tcp_states(tmp_path / "p") == {"est": 0, "close_wait": 0, "other": 0}      # readable and empty is a real 0


def test_s4_unlistable_proc_swap_top_is_null(tmp_path):
    assert sm.swap_top(tmp_path / "no-proc") is None


def test_s4_other_rss_is_null_when_the_main_pid_is_unreadable(tree):
    proc, sysroot, _ = tree
    got = sm.unit_split(999, sysroot / CG.lstrip("/"), 2_000_000_000, proc)       # 999 has no /proc entry
    assert got["main_rss_kb"] is None and got["other_rss_kb"] is None and got["unit_rss_kb"] == 1_000_000


def test_a_write_error_says_stopped_on_error_and_returns_41(tree, tmp_path, monkeypatch, capsys):
    proc, sysroot, _ = tree
    cfg = _cfg(tmp_path)
    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(sm, "rotate", boom)
    rc = sm.run(cfg, proc, sysroot, unit=lambda: (100, CG), clock=lambda: 1.0, sleep=lambda s: None, max_iterations=2, release="r")
    assert rc == sm.EXIT_WRITE_ERROR == 41
    assert "stopped_on_error" in capsys.readouterr().err
    assert json.loads(cfg.out.read_text().splitlines()[-1])["markers"] == ["stopped_on_error"]


def test_b1_sample_with_unit_failed_never_marks_pid_changed_even_with_a_different_pid(tree):
    st = sm.State()
    one(tree, st, pid=100)
    rec = sm.sample(1002.0, st, 0, CG, sm.AppLogTail(None), tree[0], tree[1], "r1", unit_failed=True)
    assert "pid_changed" not in rec["markers"] and "unit_read_failed" in rec["markers"] and rec["pid"] is None
    back = sm.sample(1004.0, st, 100, CG, sm.AppLogTail(None), tree[0], tree[1], "r1")
    assert "pid_changed" not in back["markers"]                      # 100 -> (unknown) -> 100 is not a restart
