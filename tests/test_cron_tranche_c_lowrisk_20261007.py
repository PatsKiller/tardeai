"""Hermetic proofs for cron consolidation tranche C (low-risk ranks 13, 14, 18, 9) — 2026-10-07.

Nothing here touches a real lock path under /tmp, a real log, a real receipt, a broker, an LLM lane
or the crontab. Every step command is a fake shell snippet supplied through the runners' manifests
or stub scripts in tmp_path; sequencing is proven by monotonic timestamps the stubs write.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import hermes_subject_enhance_dispatch as hd  # noqa: E402
from scripts import options_tick as ot  # noqa: E402

PY = sys.executable
OPTIONS_TICK = REPO / "scripts" / "options_tick.py"
HERMES_DISPATCH = REPO / "scripts" / "hermes_subject_enhance_dispatch.py"
ORCH_SLOT = REPO / "scripts" / "run_orchestrator_slot.sh"
DRIVE_SYNCS = REPO / "scripts" / "run_drive_syncs.sh"


def _run(argv, env=None, cwd=None):
    e = dict(os.environ)
    e.pop("TRADEAI_STATE_ROOT", None)
    if env:
        e.update(env)
    return subprocess.run([str(a) for a in argv], capture_output=True, text=True, env=e, cwd=str(cwd or REPO), timeout=120)


def _seq(path: Path) -> list[str]:
    return [ln.split()[0] for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def _stamps(path: Path) -> list[tuple[str, int]]:
    out = []
    for ln in path.read_text().splitlines():
        if ln.strip():
            tag, ns = ln.split()
            out.append((tag, int(ns)))
    return out


def _hold(path: Path):
    fh = open(path, "a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fh


# ═══════════════════════════════════════════════════════════════════════════════
# Rank 13 — scripts/options_tick.py
# ═══════════════════════════════════════════════════════════════════════════════

def test_options_default_steps_are_the_crontab_lines():
    by = {s["name"]: s for s in ot.DEFAULT_STEPS}
    assert [s["name"] for s in ot.DEFAULT_STEPS] == ["lifecycle", "projector", "export"]   # run order
    assert by["lifecycle"]["lock"] == "/tmp/options_thesis_lifecycle.lock"              # the lock the lifecycle inherits
    assert by["projector"]["lock"] == "/tmp/options_memory_projector.lock"
    assert by["export"]["lock"] == "/tmp/options_runtime_export.lock"
    src = "set -a; . /run/user/$(id -u)/tradeai/env; set +a; "
    assert by["lifecycle"]["shell"] == src + 'M2_DSN="$M2_AGENT_DSN" $PY scripts/options_thesis_lifecycle.py --apply'
    assert by["projector"]["shell"] == src + ('M2_DSN="$M2_AGENT_DSN" TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1 '
                                              '$PY scripts/options_memory_projector.py --apply')
    assert by["export"]["shell"] == "$PY scripts/export_options_runtime_snapshot.py --apply"
    assert by["lifecycle"]["log"] == "logs/options_thesis_lifecycle.log"
    assert by["projector"]["log"] == "logs/options_memory_projector.log"
    assert by["export"]["log"] == "logs/options_runtime_export.log"
    assert by["export"]["due_minute"] == 3 and not by["export"].get("every_tick")
    argv = ot.step_argv(by["lifecycle"])
    assert argv[:6] == ["flock", "-n", "-E", "75", "/tmp/options_thesis_lifecycle.lock", "bash"] and argv[6] == "-c"


def test_options_export_due_only_on_the_52_tick():
    assert [m for m in ot.DEFAULT_TICK_MINUTES if ot.export_due(m)] == [52]
    assert ot.export_due(52) and not ot.export_due(7) and not ot.export_due(22) and not ot.export_due(37)
    assert ot.export_due(3) and ot.export_due(55) and not ot.export_due(4)
    p52 = ot.plan(ot.DEFAULT_STEPS, 52, 15)
    p07 = ot.plan(ot.DEFAULT_STEPS, 7, 15)
    assert [(s["name"], s["due"]) for s in p52] == [("lifecycle", True), ("projector", True), ("export", True)]
    assert [(s["name"], s["due"]) for s in p07] == [("lifecycle", True), ("projector", True), ("export", False)]
    assert ot.plan(ot.DEFAULT_STEPS, 7, 15, force_export=True)[2]["due"]


def _tick_manifest(tmp: Path, *, b_rc: int = 0, a_shell: str | None = None) -> Path:
    seq = tmp / "seq.txt"
    def body(tag, rc=0):
        return f"echo {tag}-start $(date +%s%N) >> {seq}; sleep 0.05; echo {tag}-end $(date +%s%N) >> {seq}; exit {rc}"
    steps = [
        {"name": "lifecycle", "lock": str(tmp / "a.lock"), "log": "logs/a.log", "shell": a_shell or body("a"), "every_tick": True},
        {"name": "projector", "lock": str(tmp / "b.lock"), "log": "logs/b.log", "shell": body("b", b_rc), "every_tick": True},
        {"name": "export", "lock": str(tmp / "c.lock"), "log": "logs/c.log", "shell": body("c"), "due_minute": 3},
    ]
    m = tmp / "steps.json"
    m.write_text(json.dumps({"steps": steps}))
    return m


def _tick(tmp: Path, manifest: Path, *extra):
    return _run([PY, OPTIONS_TICK, "--manifest", manifest, "--root", tmp, "--receipt", tmp / "receipt.json",
                 "--tick-lock", tmp / "tick.lock", *extra])


def test_options_tick_plan_mode_runs_nothing_and_writes_nothing(tmp_path):
    m = _tick_manifest(tmp_path)
    r = _tick(tmp_path, m, "--tick-minute", "52")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "plan" and out["schema"] == "OptionsTickReceipt@v1"
    assert [s["due"] for s in out["steps"]] == [True, True, True]
    assert not (tmp_path / "receipt.json").exists() and not (tmp_path / "seq.txt").exists()


def test_options_tick_runs_in_order_and_exports_only_on_52(tmp_path):
    m = _tick_manifest(tmp_path)
    r = _tick(tmp_path, m, "--apply", "--tick-minute", "52")
    assert r.returncode == 0, r.stdout + r.stderr
    stamps = _stamps(tmp_path / "seq.txt")
    assert [t for t, _ in stamps] == ["a-start", "a-end", "b-start", "b-end", "c-start", "c-end"]
    assert all(stamps[i][1] <= stamps[i + 1][1] for i in range(len(stamps) - 1))   # strictly sequential
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["schema"] == "OptionsTickReceipt@v1" and rec["mode"] == "apply" and rec["ok"] is True
    assert rec["tick_minute"] == 52 and rec["outcome"] == "OK"
    assert [(s["name"], s["outcome"], s["rc"]) for s in rec["steps"]] == [("lifecycle", "RAN", 0), ("projector", "RAN", 0), ("export", "RAN", 0)]
    assert all(s["duration_s"] >= 0 for s in rec["steps"])
    for log in ("a", "b", "c"):
        text = (tmp_path / "logs" / f"{log}.log").read_text()
        assert "options_tick step=" in text and "start" in text

    (tmp_path / "seq.txt").unlink()
    r = _tick(tmp_path, m, "--apply", "--tick-minute", "7")
    assert r.returncode == 0
    assert [t for t, _ in _stamps(tmp_path / "seq.txt")] == ["a-start", "a-end", "b-start", "b-end"]
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert [(s["name"], s["outcome"]) for s in rec["steps"]] == [("lifecycle", "RAN"), ("projector", "RAN"), ("export", "NOT_DUE")]


def test_options_tick_continues_after_a_failed_step_and_exits_1(tmp_path):
    m = _tick_manifest(tmp_path, b_rc=3)
    r = _tick(tmp_path, m, "--apply", "--tick-minute", "52")
    assert r.returncode == 1
    assert _seq(tmp_path / "seq.txt") == ["a-start", "a-end", "b-start", "b-end", "c-start", "c-end"]
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["ok"] is False and rec["outcome"] == "STEP_FAILED"
    assert [(s["name"], s["outcome"], s["rc"]) for s in rec["steps"]] == [("lifecycle", "RAN", 0), ("projector", "FAILED", 3), ("export", "RAN", 0)]


def test_options_tick_held_step_lock_is_typed_not_failed(tmp_path):
    m = _tick_manifest(tmp_path)
    fh = _hold(tmp_path / "a.lock")           # a manual lifecycle run (or the old cron line) holds the lock
    try:
        r = _tick(tmp_path, m, "--apply", "--tick-minute", "7")
    finally:
        fh.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert _seq(tmp_path / "seq.txt") == ["b-start", "b-end"]          # lifecycle skipped, projector still ran
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert [(s["name"], s["outcome"], s["rc"]) for s in rec["steps"][:2]] == [("lifecycle", "LOCK_HELD", 75), ("projector", "RAN", 0)]
    assert rec["ok"] is True


def test_options_tick_step_timeout_and_tick_lock_skip(tmp_path):
    m = _tick_manifest(tmp_path, a_shell="sleep 5")
    r = _tick(tmp_path, m, "--apply", "--tick-minute", "7", "--step-timeout-s", "0.5")
    assert r.returncode == 1
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["steps"][0]["outcome"] == "TIMEOUT" and rec["steps"][1]["outcome"] == "RAN"
    assert rec["step_timeout_s"] == 0.5

    fh = _hold(tmp_path / "tick.lock")
    try:
        r = _tick(tmp_path, m, "--apply", "--tick-minute", "7")
    finally:
        fh.close()
    assert r.returncode == 0
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["outcome"] == "SKIPPED_TICK_LOCK_HELD" and all(s["outcome"] == "NOT_RUN" for s in rec["steps"])


def test_options_tick_declares_no_consumer_reason_and_lane():
    assert "not installed" in ot.NO_CONSUMER_REASON
    assert ot.LANE == "options-tick" and ot.SCHEMA == "OptionsTickReceipt@v1"


# ═══════════════════════════════════════════════════════════════════════════════
# Rank 9 — scripts/hermes_subject_enhance_dispatch.py
# ═══════════════════════════════════════════════════════════════════════════════

def test_hermes_table_matches_the_six_crontab_lines():
    by = {s["subject"]: s for s in hd.DEFAULT_TABLE}
    assert list(by) == ["scalp", "proposal", "position", "sector", "closed_trade", "report"]
    wd, every = [0, 1, 2, 3, 4], list(range(7))
    assert (by["scalp"]["minutes"], by["scalp"]["hours"], by["scalp"]["dows"]) == ([0, 30], list(range(9, 17)), wd)
    assert (by["proposal"]["minutes"], by["proposal"]["hours"], by["proposal"]["dows"]) == ([0, 20, 40], list(range(9, 17)), wd)
    assert (by["position"]["minutes"], by["position"]["hours"], by["position"]["dows"]) == ([20], list(range(0, 24, 2)), every)
    assert (by["sector"]["minutes"], by["sector"]["hours"], by["sector"]["dows"]) == ([25], [11, 14], wd)
    assert (by["closed_trade"]["minutes"], by["closed_trade"]["hours"], by["closed_trade"]["dows"]) == ([40], [16], wd)
    assert (by["report"]["minutes"], by["report"]["hours"], by["report"]["dows"]) == ([0], [8, 20], every)
    assert {k: v["lock"] for k, v in by.items()} == {
        "scalp": "/tmp/enh_scalp.lock", "proposal": "/tmp/enh_prop.lock", "position": "/tmp/enh_pos.lock",
        "sector": "/tmp/enh_sec.lock", "closed_trade": "/tmp/enh_ct.lock", "report": "/tmp/enh_report.lock"}
    assert {k: v["guard"] for k, v in by.items()} == {"scalp": False, "proposal": False, "position": True,
                                                      "sector": True, "closed_trade": False, "report": True}
    assert by["scalp"]["args"] == ["--type", "scalp", "--lanes", "grok,chatgpt", "--apply", "--limit", "10"]
    assert by["proposal"]["args"] == ["--type", "proposal", "--lanes", "grok,chatgpt", "--apply"]
    assert by["position"]["args"] == ["--type", "position", "--lanes", "grok,chatgpt", "--apply"]
    assert by["sector"]["args"] == ["--type", "sector", "--lanes", "grok,chatgpt", "--apply", "--limit", "11"]
    assert by["closed_trade"]["args"] == ["--type", "closed_trade", "--lanes", "grok,chatgpt", "--apply", "--limit", "12"]
    assert by["report"]["args"] == ["--type", "report", "--lanes", "grok,chatgpt", "--apply", "--limit", "1"]
    assert hd.union_minutes(hd.DEFAULT_TABLE) == [0, 20, 25, 30, 40]
    argv = hd.subject_argv(by["sector"], "/x/python")
    assert argv == ["flock", "-n", "-E", "75", "/tmp/enh_sec.lock", "/x/python", "scripts/hermes_subject_enhance.py",
                    "--type", "sector", "--lanes", "grok,chatgpt", "--apply", "--limit", "11"]
    assert hd.guard_argv(by["report"], Path("/r")) == ["bash", "/r/scripts/llm_priority_guard.sh"]
    assert hd.guard_argv(by["scalp"], Path("/r")) is None


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 6, 9, 0), ["scalp", "proposal"]),          # Tue 09:00 — the daily same-minute pair
    (datetime(2026, 10, 6, 10, 20), ["proposal", "position"]),     # :20 at an even hour
    (datetime(2026, 10, 5, 11, 25), ["sector"]),                    # Mon
    (datetime(2026, 10, 9, 16, 40), ["proposal", "closed_trade"]),  # Fri
    (datetime(2026, 10, 7, 8, 0), ["report"]),
    (datetime(2026, 10, 7, 20, 0), ["report"]),
    (datetime(2026, 10, 6, 9, 30), ["scalp"]),
    (datetime(2026, 10, 6, 11, 20), ["proposal"]),                 # 11 is odd: no position
    (datetime(2026, 10, 6, 16, 30), ["scalp"]),
    (datetime(2026, 10, 6, 17, 0), []),                             # 9-16 is inclusive of 16, not 17
    (datetime(2026, 10, 10, 10, 0), []),                            # Saturday: no weekday subjects
    (datetime(2026, 10, 10, 12, 20), ["position"]),                 # Saturday: position still runs
    (datetime(2026, 10, 11, 20, 0), ["report"]),                    # Sunday
    (datetime(2026, 10, 6, 9, 5), []),
])
def test_hermes_due_at_a_single_minute(now, expected):
    assert [d["subject"] for d in hd.due_subjects(hd.DEFAULT_TABLE, now)] == expected


def test_hermes_window_catch_up_runs_each_subject_once_in_table_order():
    due = hd.due_subjects(hd.DEFAULT_TABLE, datetime(2026, 10, 6, 11, 26), since=datetime(2026, 10, 6, 10, 58))
    assert [(d["subject"], d["matched_minutes"]) for d in due] == [
        ("scalp", ["11:00"]), ("proposal", ["11:00", "11:20"]), ("sector", ["11:25"])]
    # the lookback cap bounds a long outage
    due = hd.due_subjects(hd.DEFAULT_TABLE, datetime(2026, 10, 6, 11, 26), since=datetime(2026, 10, 6, 4, 0), max_lookback_min=60)
    assert [(d["subject"], d["matched_minutes"]) for d in due] == [
        ("scalp", ["10:30", "11:00"]), ("proposal", ["10:40", "11:00", "11:20"]), ("sector", ["11:25"])]
    # a stale "since" after "now" degrades to the single current minute
    assert [d["subject"] for d in hd.due_subjects(hd.DEFAULT_TABLE, datetime(2026, 10, 6, 9, 0), since=datetime(2026, 10, 6, 9, 30))] == ["scalp", "proposal"]


def test_hermes_weekly_stats_quantify_the_collisions():
    st = hd.weekly_firings(hd.DEFAULT_TABLE)
    assert st["per_subject"] == {"scalp": 80, "proposal": 120, "position": 84, "sector": 10, "closed_trade": 5, "report": 14}
    assert st["today_subject_firings_per_week"] == 313 == st["dispatcher_subject_runs_per_week"]
    assert st["same_minute_collisions_per_week"] == 65          # 40 (:00 09-16) + 20 (:20 even hours) + 5 (16:40)
    assert st["dispatched_collisions_per_week"] == 0
    assert st["dispatcher_firings_per_week"] == 5 * 24 * 7 == 840 and st["dispatcher_minutes"] == [0, 20, 25, 30, 40]


def _hermes_manifest(tmp: Path, *, s3_rc: int = 0, s1_minutes=(0,)) -> Path:
    seq = tmp / "seq.txt"
    def cmd(tag, rc=0):
        return ["bash", "-c", f"echo {tag}-start $(date +%s%N) >> {seq}; sleep 0.05; echo {tag}-end $(date +%s%N) >> {seq}; exit {rc}"]
    wd = [0, 1, 2, 3, 4]
    table = [
        {"subject": "s1", "minutes": list(s1_minutes), "hours": [9], "dows": wd, "lock": str(tmp / "s1.lock"), "guard": False, "cmd": cmd("s1")},
        {"subject": "s2", "minutes": [0], "hours": [9], "dows": wd, "lock": str(tmp / "s2.lock"), "guard": True,
         "guard_cmd": ["bash", "-c", "echo guard-deferred >> " + str(tmp / "guard.txt") + "; exit 1"], "cmd": cmd("s2")},
        {"subject": "s3", "minutes": [0], "hours": [9], "dows": wd, "lock": str(tmp / "s3.lock"), "guard": True,
         "guard_cmd": ["true"], "cmd": cmd("s3", s3_rc)},
    ]
    m = tmp / "table.json"
    m.write_text(json.dumps({"table": table}))
    return m


def _dispatch(tmp: Path, manifest: Path, *extra):
    return _run([PY, HERMES_DISPATCH, "--manifest", manifest, "--root", tmp, "--log", tmp / "enh.log",
                 "--receipt", tmp / "receipt.json", "--dispatch-lock", tmp / "dispatch.lock", *extra])


def test_hermes_plan_mode_runs_nothing(tmp_path):
    m = _hermes_manifest(tmp_path)
    r = _dispatch(tmp_path, m, "--now", "2026-10-06T09:00")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "plan" and [d["subject"] for d in out["due"]] == ["s1", "s2", "s3"]
    assert out["window_start"] == "2026-10-06T08:59:00" and out["window_end"] == "2026-10-06T09:00:00"
    assert not (tmp_path / "receipt.json").exists() and not (tmp_path / "seq.txt").exists()


def test_hermes_apply_is_sequential_honours_guard_and_continues_on_error(tmp_path):
    m = _hermes_manifest(tmp_path, s3_rc=2)
    r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-06T09:00")
    assert r.returncode == 1, r.stdout + r.stderr
    stamps = _stamps(tmp_path / "seq.txt")
    assert [t for t, _ in stamps] == ["s1-start", "s1-end", "s3-start", "s3-end"]        # s2 deferred by its guard
    assert all(stamps[i][1] <= stamps[i + 1][1] for i in range(len(stamps) - 1))      # never concurrent
    assert (tmp_path / "guard.txt").read_text().strip() == "guard-deferred"
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["schema"] == "HermesSubjectEnhanceDispatchReceipt@v1" and rec["mode"] == "apply"
    assert [(x["subject"], x["outcome"], x["rc"]) for x in rec["runs"]] == [("s1", "RAN", 0), ("s2", "DEFERRED_GUARD", 1), ("s3", "FAILED", 2)]
    assert rec["ok"] is False and rec["outcome"] == "SUBJECT_FAILED"
    assert rec["window_end"] == "2026-10-06T09:00:00" and rec["since_source"] == "none"
    assert "dispatch subject=s1 start" in (tmp_path / "enh.log").read_text()


def test_hermes_watermark_comes_from_the_previous_receipt(tmp_path):
    m = _hermes_manifest(tmp_path, s1_minutes=(0, 20))
    r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-06T09:00")
    assert r.returncode == 0, r.stdout + r.stderr
    (tmp_path / "seq.txt").unlink()
    # the 09:20 firing with no --since reads window_end 09:00 from the receipt → (09:00, 09:20]
    r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-06T09:20")
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["since_source"] == "receipt" and rec["window_start"] == "2026-10-06T09:00:00"
    assert [(x["subject"], x["matched_minutes"]) for x in rec["runs"]] == [("s1", ["09:20"])]
    assert _seq(tmp_path / "seq.txt") == ["s1-start", "s1-end"]


def test_hermes_nothing_due_and_held_locks(tmp_path):
    m = _hermes_manifest(tmp_path)
    r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-10T09:00")        # Saturday
    assert r.returncode == 0 and json.loads(r.stdout)["outcome"] == "NOTHING_DUE"
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["ok"] is True and rec["runs"] == [] and rec["due"] == []

    fh = _hold(tmp_path / "s1.lock")                                            # another s1 run in flight
    try:
        r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-06T09:00", "--since", "2026-10-06T08:59")
    finally:
        fh.close()
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert [(x["subject"], x["outcome"], x["rc"]) for x in rec["runs"]] == [("s1", "LOCK_HELD", 75), ("s2", "DEFERRED_GUARD", 1), ("s3", "RAN", 0)]
    assert _seq(tmp_path / "seq.txt") == ["s3-start", "s3-end"]

    (tmp_path / "seq.txt").unlink()
    fh = _hold(tmp_path / "dispatch.lock")                                      # the previous firing is still running
    try:
        r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-06T09:00", "--since", "2026-10-06T08:40", "--lock-wait-s", "0.3")
    finally:
        fh.close()
    assert r.returncode == 1 and json.loads(r.stdout)["outcome"] == "LOCK_WAIT_TIMEOUT"
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["window_end"] == rec["window_start"] == "2026-10-06T08:40:00"     # watermark NOT advanced: nothing is lost
    assert not (tmp_path / "seq.txt").exists()


def test_hermes_subject_timeout(tmp_path):
    seq = tmp_path / "seq.txt"
    table = [{"subject": "slow", "minutes": [0], "hours": [9], "dows": [0, 1, 2, 3, 4], "lock": str(tmp_path / "slow.lock"), "guard": False,
              "cmd": ["bash", "-c", "sleep 5"]},
             {"subject": "fast", "minutes": [0], "hours": [9], "dows": [0, 1, 2, 3, 4], "lock": str(tmp_path / "fast.lock"), "guard": False,
              "cmd": ["bash", "-c", f"echo fast $(date +%s%N) >> {seq}"]}]
    m = tmp_path / "t.json"
    m.write_text(json.dumps({"table": table}))
    r = _dispatch(tmp_path, m, "--apply", "--now", "2026-10-06T09:00", "--subject-timeout-s", "0.5")
    assert r.returncode == 1
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert [(x["subject"], x["outcome"]) for x in rec["runs"]] == [("slow", "TIMEOUT"), ("fast", "RAN")]
    assert _seq(seq) == ["fast"]


def test_hermes_declares_no_consumer_reason_and_lane():
    assert "not installed" in hd.NO_CONSUMER_REASON
    assert hd.LANE == "hermes-subject-enhance-dispatch"


# ═══════════════════════════════════════════════════════════════════════════════
# Rank 14 — scripts/run_orchestrator_slot.sh
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("now, label", [("0901", "0900"), ("0859", "0900"), ("1000", "1000"), ("1731", "1730"),
                                        ("1612", "1600"), ("1215", "1200"), ("1345", "1400")])
def test_orchestrator_slot_label_rounds_to_the_schedule_table(now, label):
    r = _run(["bash", ORCH_SLOT, "--now", now, "--print-label"])
    assert r.returncode == 0 and r.stdout.strip() == label, r.stderr


@pytest.mark.parametrize("now", ["1100", "1300", "0400", "2200", "9x00"])
def test_orchestrator_slot_refuses_to_guess_outside_a_window(now):
    r = _run(["bash", ORCH_SLOT, "--now", now, "--print-label"])
    assert r.returncode == 2 and "refusing" in r.stderr or "HHMM" in r.stderr
    assert r.stdout.strip() == ""


def test_orchestrator_slot_dry_run_is_the_crontab_command(tmp_path):
    env = {"PY": "/venv/bin/python", "PROJECT_ROOT": str(tmp_path)}
    r = _run(["bash", ORCH_SLOT, "--now", "1200", "--dry-run", "--no-llm", "--no-alerts", "--allow-underfilled"], env=env)
    assert r.returncode == 0, r.stderr
    assert "DRY RUN" in r.stdout
    assert f"bash {tmp_path}/scripts/safe_flock.sh /tmp/screener_pm.lock /venv/bin/python scripts/trade_ai_orchestrator.py --run-label 1200 --no-llm --no-alerts --allow-underfilled" in r.stdout
    # the 17:30 line has no --no-llm today; flags pass through untouched
    r = _run(["bash", ORCH_SLOT, "--now", "1730", "--dry-run", "--no-alerts", "--allow-underfilled"], env=env)
    assert "--run-label 1730 --no-alerts --allow-underfilled" in r.stdout and "--no-llm" not in r.stdout
    # explicit label passthrough skips derivation
    r = _run(["bash", ORCH_SLOT, "--run-label", "1400", "--dry-run", "--no-llm"], env=env)
    assert "--run-label 1400 --no-llm" in r.stdout
    # tolerance and slots are env-configurable, never hardcoded in the cron line
    r = _run(["bash", ORCH_SLOT, "--now", "0700", "--print-label"], env={"ORCH_SLOTS": "0400,0700"})
    assert r.stdout.strip() == "0700"


def test_orchestrator_slot_executes_safe_flock_with_the_label(tmp_path):
    (tmp_path / "scripts").mkdir()
    stub = tmp_path / "scripts" / "safe_flock.sh"
    stub.write_text("#!/usr/bin/env bash\necho \"lock=$1\" >> \"$OUT\"; shift; echo \"argv=$*\" >> \"$OUT\"; echo \"cwd=$PWD\" >> \"$OUT\"\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "out.txt"
    r = _run(["bash", ORCH_SLOT, "--now", "1600", "--no-llm"], env={"PROJECT_ROOT": str(tmp_path), "PY": "pyX", "OUT": str(out)})
    assert r.returncode == 0, r.stderr
    lines = out.read_text().splitlines()
    assert lines[0] == "lock=/tmp/screener_pm.lock"
    assert lines[1] == "argv=pyX scripts/trade_ai_orchestrator.py --run-label 1600 --no-llm"
    assert lines[2] == f"cwd={tmp_path}"


# ═══════════════════════════════════════════════════════════════════════════════
# Rank 18 — scripts/run_drive_syncs.sh
# ═══════════════════════════════════════════════════════════════════════════════

def _drive_tree(tmp: Path, *, docs_body: str = "", code_rc: int = 0) -> dict:
    cur = tmp / "cur"
    (cur / "scripts").mkdir(parents=True)
    (cur / "GIT_SHA").write_text("abc123\n")
    seq = tmp / "seq.txt"
    locks = tmp / "locklog.txt"
    (cur / "scripts" / "safe_flock.sh").write_text(
        f"#!/usr/bin/env bash\necho \"$1\" >> {locks}; shift; exec \"$@\"\n")
    (cur / "scripts" / "sync-docs-to-drive.sh").write_text(
        f"#!/usr/bin/env bash\n{docs_body}\necho docs-start $(date +%s%N) >> {seq}; sleep 0.05; echo docs-end $(date +%s%N) >> {seq}\n")
    (cur / "scripts" / "sync_code_mirror_to_drive.sh").write_text(
        f"#!/usr/bin/env bash\n[ \"$1\" = --apply ] || exit 9\necho code-start $(date +%s%N) >> {seq}; sleep 0.05; echo code-end $(date +%s%N) >> {seq}; exit {code_rc}\n")
    env = {"DRIVE_SYNCS_CURRENT": str(cur), "DRIVE_SYNCS_LOG_DIR": str(tmp / "logs"), "DRIVE_SYNCS_LOCK_DIR": str(tmp / "locks"),
           "DRIVE_SYNCS_RECEIPT": str(tmp / "receipt.json"), "DRIVE_SYNCS_STEP_TIMEOUT_S": "30"}
    (tmp / "locks").mkdir()
    return {"env": env, "seq": seq, "locks": locks, "receipt": tmp / "receipt.json", "logs": tmp / "logs"}


def test_drive_syncs_dry_run_prints_both_commands_in_order_and_writes_nothing(tmp_path):
    t = _drive_tree(tmp_path)
    r = _run(["bash", DRIVE_SYNCS, "--dry-run"], env=t["env"])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "DRY RUN" in lines[0]
    assert "1. docs:" in lines[2] and "safe_flock.sh" in lines[2] and "drive_sync.lock" in lines[2] and "sync-docs-to-drive.sh" in lines[2]
    assert "2. code_mirror:" in lines[3] and "code_mirror_drive_sync.lock" in lines[3] and "sync_code_mirror_to_drive.sh --apply" in lines[3]
    assert not t["receipt"].exists() and not t["seq"].exists()
    r = _run(["bash", DRIVE_SYNCS], env=t["env"])
    assert r.returncode == 2 and "usage" in r.stderr


def test_drive_syncs_apply_runs_docs_then_code_mirror_with_the_original_locks(tmp_path):
    t = _drive_tree(tmp_path)
    r = _run(["bash", DRIVE_SYNCS, "--apply"], env=t["env"])
    assert r.returncode == 0, r.stdout + r.stderr
    stamps = _stamps(t["seq"])
    assert [x for x, _ in stamps] == ["docs-start", "docs-end", "code-start", "code-end"]
    assert all(stamps[i][1] <= stamps[i + 1][1] for i in range(3))
    assert t["locks"].read_text().splitlines() == [str(tmp_path / "locks" / "drive_sync.lock"), str(tmp_path / "locks" / "code_mirror_drive_sync.lock")]
    rec = json.loads(t["receipt"].read_text())
    assert rec["schema"] == "DriveSyncsReceipt@v1" and rec["ok"] is True and rec["outcome"] == "OK" and rec["served_sha"] == "abc123"
    assert [(s["name"], s["outcome"], s["rc"]) for s in rec["steps"]] == [("docs", "RAN", 0), ("code_mirror", "RAN", 0)]
    assert rec["steps"][0]["log"].endswith("drive-sync.log") and rec["steps"][1]["log"].endswith("code-mirror-drive-sync.log")
    assert (t["logs"] / "drive-sync.log").exists() and (t["logs"] / "code-mirror-drive-sync.log").exists()
    assert "run_drive_syncs step=docs start" in (t["logs"] / "drive-sync.log").read_text()


def test_drive_syncs_continue_on_error_and_timeout(tmp_path):
    t = _drive_tree(tmp_path, code_rc=7)
    r = _run(["bash", DRIVE_SYNCS, "--apply"], env=t["env"])
    assert r.returncode == 1
    rec = json.loads(t["receipt"].read_text())
    assert [(s["name"], s["outcome"], s["rc"]) for s in rec["steps"]] == [("docs", "RAN", 0), ("code_mirror", "FAILED", 7)]
    assert rec["ok"] is False and rec["outcome"] == "STEP_FAILED"

    t = _drive_tree(tmp_path / "t2", docs_body="sleep 5")
    env = dict(t["env"], DRIVE_SYNCS_STEP_TIMEOUT_S="1")
    r = _run(["bash", DRIVE_SYNCS, "--apply"], env=env)
    assert r.returncode == 1
    rec = json.loads(t["receipt"].read_text())
    assert [(s["name"], s["outcome"]) for s in rec["steps"]] == [("docs", "TIMEOUT"), ("code_mirror", "RAN")]
    assert rec["step_timeout_s"] == 1 and _seq(t["seq"]) == ["code-start", "code-end"]


# ═══════════════════════════════════════════════════════════════════════════════
# Shared hygiene
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("script", [ORCH_SLOT, DRIVE_SYNCS])
def test_shell_runners_parse_and_say_they_are_proposals(script):
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = script.read_text()
    assert text.startswith("#!/usr/bin/env bash") and "NOT installed by this PR" in text and "\r" not in text


def test_python_runners_name_the_proposal_doc():
    doc = "docs/implementation/n8n-parallel/proposals/cron-tranche-c-lowrisk.md"
    for p in (OPTIONS_TICK, HERMES_DISPATCH, ORCH_SLOT, DRIVE_SYNCS):
        assert doc in p.read_text(), p
    assert (REPO / doc).exists()
