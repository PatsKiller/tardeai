"""Premarket stage, bounded concurrency (2026-10-10; operator: parallelise premarket before C1 flip 4).

Proven here, hermetically (scratch project root, sleep/echo steps, no host state, no .env, no network):
  * a stage with `parallel.max_concurrency` N runs its `group`s in manifest order with a barrier between
    groups, never more than N steps of a group at once, and still continues past a failed step;
  * two steps that take the same lock in different groups both run (one after the other); two in one group
    are refused by the validator (one would silently skip);
  * --dry-run executes nothing and prints the wave plan; a stage without `parallel` stays serial;
  * the committed premarket manifest: groups are the steps' cron minutes (two read-after-write pairs split
    a/b), concurrency 4, and the p95 critical path is <= 60% of the 06:00-07:30 window;
  * the real premarket runner in --dry-run (env -i) prints the waves and executes nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = ROOT / "scripts" / "pipelines"
RUNNER = PIPELINES / "run_after_close_pipeline.sh"
PREMARKET_RUNNER = PIPELINES / "run_premarket_data_pipeline.sh"
PREMARKET = ROOT / "config" / "pipelines" / "premarket.json"
sys.path.insert(0, str(PIPELINES))
import pipeline_manifest as pm  # noqa: E402

WINDOW_S = 90 * 60  # 06:00 -> 07:30 brief


def _manifest(tmp: Path, steps: list[dict], parallel: dict | None) -> tuple[Path, str]:
    name = f"par_{uuid.uuid4().hex[:8]}"  # unique: the stage lock is a /tmp path shared by every checkout
    stage: dict = {"steps": steps}
    if parallel is not None:
        stage["parallel"] = parallel
    p = tmp / f"{name}.json"
    p.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": name, "stages": {"s": stage}}), encoding="utf-8")
    return p, name


def _run(tmp: Path, manifest: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ALPACA_MODE", None)
    env.pop("LIVE_TRADING_ENABLED", None)
    env["PIPELINE_TODAY_DOW"] = "3"
    return subprocess.run(["bash", str(RUNNER), "--manifest", str(manifest), "--project-root", str(tmp), "--stage", "s", *args],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)


def _step(sid: str, group: str, cmd: str, line: int = 1) -> dict:
    return {"id": sid, "cron_line": line, "command": cmd, "timeout": "20s", "group": group}


def _intervals(log: Path) -> dict[str, tuple[float, float]]:
    out: dict[str, list[float]] = {}
    for ln in log.read_text().splitlines():
        sid, kind, ts = ln.split()
        out.setdefault(sid, [0.0, 0.0])[0 if kind == "S" else 1] = float(ts)
    return {k: (v[0], v[1]) for k, v in out.items()}


def test_groups_barrier_and_concurrency_bound(tmp_path):
    log = tmp_path / "t.log"
    rec = lambda s: f'echo "{s} S $(date +%s.%N)" >> {log}; sleep 1; echo "{s} E $(date +%s.%N)" >> {log}'  # noqa: E731
    steps = [_step(f"a{i}", "g1", rec(f"a{i}"), i) for i in range(4)]
    steps.append(_step("bad", "g1", "false", 9))
    steps.append(_step("b0", "g2", rec("b0"), 10))
    man, name = _manifest(tmp_path, steps, {"max_concurrency": 2})
    r = _run(tmp_path, man, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    iv = _intervals(log)
    a = [iv[f"a{i}"] for i in range(4)]
    # never more than 2 at once, and actually parallel (2 overlap at some point)
    events = sorted([(s, 1) for s, _ in a] + [(e, -1) for _, e in a])
    live = peak = 0
    for _, d in events:
        live += d
        peak = max(peak, live)
    assert peak == 2, peak
    assert iv["b0"][0] >= max(e for _, e in a), "group g2 must start after every g1 step ended"
    s = json.loads((tmp_path / "data" / "runtime" / f"pipeline_{name}_s_last.json").read_text())
    by = {x["id"]: x for x in s["steps"]}
    assert len(by) == 6 and by["bad"]["status"] == "failed" and by["b0"]["status"] == "ok"
    assert s["overall_status"] == "degraded"
    assert "[waves] stage=s max_concurrency=2 groups=2" in r.stdout


def test_same_lock_across_groups_runs_both_in_order(tmp_path):
    out = tmp_path / "o.txt"
    lk = tmp_path / "shared.lock"
    steps = [_step("x", "g1", f"flock -n {lk} bash -c 'sleep 1; echo x >> {out}'"),
             _step("y", "g2", f"flock -n {lk} bash -c 'echo y >> {out}'", 2)]
    man, _ = _manifest(tmp_path, steps, {"max_concurrency": 4})
    r = _run(tmp_path, man, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.read_text().split() == ["x", "y"], "the barrier serialises steps that share a lock"


def test_validator_refuses_unsafe_parallel_stages():
    def errs(steps, par):
        return pm.validate({"schema": pm.MANIFEST_SCHEMA, "pipeline": "v", "stages": {"s": {"steps": steps, "parallel": par}}})
    base = lambda sid, g, cmd="true": {"id": sid, "cron_line": 1, "command": cmd, "timeout": "1m", "group": g}  # noqa: E731
    assert errs([base("a", "g1"), base("b", "g1")], {"max_concurrency": 2}) == []
    assert any("share lock" in e for e in errs([base("a", "g1", "flock -n /tmp/l.lock true"),
                                                base("b", "g1", "bash scripts/safe_flock.sh /tmp/l.lock true")],
                                               {"max_concurrency": 2}))
    assert any("not contiguous" in e for e in errs([base("a", "g1"), base("b", "g2"), base("c", "g1")], {"max_concurrency": 2}))
    assert any("has no group" in e for e in errs([{"id": "a", "cron_line": 1, "command": "true", "timeout": "1m"}],
                                                 {"max_concurrency": 2}))
    assert any("max_concurrency" in e for e in errs([base("a", "g1")], {"max_concurrency": 99}))


def test_dry_run_executes_nothing_and_no_parallel_block_is_serial(tmp_path):
    out = tmp_path / "o.txt"
    man, _ = _manifest(tmp_path, [_step("a", "g1", f"echo a >> {out}"), _step("b", "g1", f"echo b >> {out}", 2)],
                       {"max_concurrency": 2})
    r = _run(tmp_path, man)
    assert r.returncode == 0 and not out.exists()
    assert r.stdout.count("[DRY_RUN] would run") == 2 and "[waves]" in r.stdout
    serial = {"stages": {"s": {"steps": [{"id": "a", "cron_line": 1, "command": "true", "timeout": "1m", "group": "g"},
                                          {"id": "b", "cron_line": 2, "command": "true", "timeout": "1m", "group": "g"}]}}}
    assert pm.stage_concurrency(serial["stages"]["s"]) == 1
    assert [g["group"] for g in pm.wave_plan(serial, "s")["groups"]] == ["a", "b"], "no parallel block: every step its own group"
    for name in ("after_close", "hermes_learning", "hermes_overnight"):
        m = pm.load(ROOT / "config" / "pipelines" / f"{name}.json")
        assert all("parallel" not in st for st in m["stages"].values()), name


def test_committed_premarket_manifest_parallel_plan():
    m = pm.load(PREMARKET)
    assert pm.validate(m) == []
    st = m["stages"]["premarket"]
    assert st["parallel"]["max_concurrency"] == 4
    for s in st["steps"]:
        assert s["group"].rstrip("ab") == s["cron_time"], s["id"]
    groups = [s["group"] for s in st["steps"]]
    assert groups == sorted(groups), "groups run in cron-time order"
    pos = {s["id"]: groups.index(s["group"]) for s in st["steps"]}
    assert pos["sync_watchlist_items_to_db"] < pos["build_symbol_profiles"]  # watchlist_items writer -> reader
    assert pos["research_watchlist_discovery"] < pos["iris_taxonomy_agent"]
    plan = pm.wave_plan(m, "premarket", today_dow=3)
    assert plan["critical_path_p95_s"] <= 0.6 * WINDOW_S, plan["critical_path_p95_s"]
    assert len({s["id"] for s in st["steps"]}) == 37


def test_wave_plan_p95_matches_readiness_rule():
    """The wave plan's serial p95 must equal the readiness report's sum of p95 (same per-step rule): an
    unverified partial p95_s never undercuts the design's upper bound."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import report_tranche_b_readiness as rtb  # noqa: E402
    m = pm.load(PREMARKET)
    steps = m["stages"]["premarket"]["steps"]
    want = round(sum(rtb.step_duration(s.get("measured") or {})["p95_s"] for s in steps), 1)
    assert pm.wave_plan(m, "premarket")["serial_p95_s"] == want
    assert pm._p95({"measured": {"verified": False, "p95_s": 1.0, "upper_bound_p95_s": 444.8}}) == (444.8, False)
    assert pm._p95({"measured": {"verified": True, "p95_s": 2.0, "upper_bound_p95_s": 9.0}}) == (2.0, True)
    assert pm._p95({"measured": {"verified": False, "p95_s": 3.0}}) == (3.0, False)


def test_real_premarket_runner_dry_run_prints_waves_executes_nothing(tmp_path):
    env = {"HOME": os.environ.get("HOME", "/tmp"), "PATH": "/usr/bin:/bin", "PY": "/usr/bin/python3", "PIPELINE_TODAY_DOW": "3"}
    r = subprocess.run(["bash", str(PREMARKET_RUNNER), "--manifest", str(PREMARKET), "--project-root", str(tmp_path),
                        "--dry-run"],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[waves] stage=premarket max_concurrency=4 groups=23" in r.stdout
    assert r.stdout.count("[DRY_RUN] would run") == 37
    assert " START 20" not in r.stdout.replace("] START pipeline", "")
    s = json.loads((tmp_path / "data" / "runtime" / "pipeline_premarket_premarket_last.json").read_text())
    assert s["dry_run"] is True and s["executed_any"] is False and s["step_count"] == 37
