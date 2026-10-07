"""Cron tranche B (2026-10-07): manifest-driven pipeline runner — hermetic tests.

What is proven here, without touching the host, a broker, an LLM wrapper or the live crontab:

  * the runner executes NOTHING in its default --dry-run, even with --apply-style steps present;
  * --apply with an EMPTY stage executes nothing and writes an `overall_status: "empty"` summary;
  * --apply with a hermetic manifest (true / false / sleep) runs every step in order, applies the
    per-step timeout, continues after a failed step, and records each outcome in a
    PipelineStepReceipt@v1 line and in the PipelineRun@v1 summary;
  * a held stage lock is a clean skip (exit 0, no steps run);
  * the four committed manifests validate, every absorbed command is a verbatim slice of its
    crontab line, no excluded broker/stop/order/market_day_gate token appears in a step, every
    Hermes step keeps its own LLM wrapper, and the runner source never names an LLM wrapper
    (so a stage can never be wrapped in one guard);
  * `bash -n` passes on the runner library and the three runners.

Nothing here reads the token store, the live .env or the network (feedback 2026-09-28).
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = ROOT / "scripts" / "pipelines"
RUNNER_LIB = PIPELINES / "_manifest_runner.sh"
RUNNERS = [
    PIPELINES / "run_after_close_pipeline.sh",
    PIPELINES / "run_premarket_data_pipeline.sh",
    PIPELINES / "run_hermes_pipeline.sh",
]
MANIFEST_PY = PIPELINES / "pipeline_manifest.py"
MANIFESTS = {
    "after_close": ROOT / "config" / "pipelines" / "after_close.json",
    "premarket": ROOT / "config" / "pipelines" / "premarket.json",
    "hermes_learning": ROOT / "config" / "pipelines" / "hermes_learning.json",
    "hermes_overnight": ROOT / "config" / "pipelines" / "hermes_overnight.json",
}

sys.path.insert(0, str(PIPELINES))
import pipeline_manifest as pm  # noqa: E402


def _hermetic_manifest(tmp_path: Path, name: str, steps: list[dict], stage: str = "test") -> Path:
    manifest = {
        "schema": pm.MANIFEST_SCHEMA,
        "pipeline": name,
        "stages": {stage: {"steps": steps}},
    }
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def _run(tmp_root: Path, manifest: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ALPACA_MODE", None)
    env.pop("LIVE_TRADING_ENABLED", None)
    env["PIPELINE_TODAY_DOW"] = "3"
    if env_extra:
        env.update(env_extra)
    cmd = ["bash", str(RUNNERS[0]), "--manifest", str(manifest), "--project-root", str(tmp_root), *args]
    return subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)


def _summary(tmp_root: Path, pipeline: str, stage: str) -> dict:
    p = tmp_root / "data" / "runtime" / f"pipeline_{pipeline}_{stage}_last.json"
    assert p.exists(), f"summary missing: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- bash -n

@pytest.mark.parametrize("script", [RUNNER_LIB, *RUNNERS])
def test_bash_syntax(script):
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_runner_never_names_an_llm_wrapper():
    src = RUNNER_LIB.read_text(encoding="utf-8") + "".join(r.read_text(encoding="utf-8") for r in RUNNERS)
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for w in pm.LLM_WRAPPERS:
        assert w not in body, f"runner must never wrap a stage in {w}; the step keeps it verbatim"


# --------------------------------------------------------------------------- dry-run default

def test_dry_run_default_executes_nothing(tmp_path):
    marker = tmp_path / "touched"
    man = _hermetic_manifest(tmp_path, "hermetic_dry", [
        {"id": "touch", "cron_line": 1, "command": f"touch {marker}", "timeout": "10s"},
    ])
    r = _run(tmp_path, man, "--stage", "test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[DRY_RUN] would run" in r.stdout
    assert not marker.exists(), "dry-run must not execute a step"
    s = _summary(tmp_path, "hermetic_dry", "test")
    assert s["schema"] == pm.RUN_SCHEMA
    assert s["dry_run"] is True and s["overall_status"] == "dry_run" and s["executed_any"] is False
    assert [st["status"] for st in s["steps"]] == ["dry_run"]


def test_apply_with_empty_stage_executes_nothing(tmp_path):
    man = _hermetic_manifest(tmp_path, "hermetic_empty", [])
    r = _run(tmp_path, man, "--stage", "test", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no steps for stage=test" in r.stdout
    s = _summary(tmp_path, "hermetic_empty", "test")
    assert s["overall_status"] == "empty" and s["step_count"] == 0 and s["executed_any"] is False
    assert s["apply_requested"] is True


# --------------------------------------------------------------------------- apply semantics

def test_apply_runs_in_order_times_out_and_continues_on_error(tmp_path):
    order = tmp_path / "order.txt"
    man = _hermetic_manifest(tmp_path, "hermetic_apply", [
        {"id": "ok1", "cron_line": 10, "command": f"echo ok1 >> {order}; true", "timeout": "10s"},
        {"id": "bad", "cron_line": 11, "command": f"echo bad >> {order}; false", "timeout": "10s"},
        {"id": "slow", "cron_line": 12, "command": f"echo slow >> {order}; sleep 5", "timeout": "1s"},
        {"id": "ok2", "cron_line": 13, "command": f"echo ok2 >> {order}; true", "timeout": "10s",
         "log": "logs/hermetic_ok2.log"},
        {"id": "weekend_only", "cron_line": 14, "command": f"echo weekend >> {order}", "timeout": "10s", "dow": [0, 6]},
    ])
    r = _run(tmp_path, man, "--stage", "test", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert order.read_text().split() == ["ok1", "bad", "slow", "ok2"], "steps run in manifest order; failure does not cascade"
    s = _summary(tmp_path, "hermetic_apply", "test")
    by_id = {st["id"]: st for st in s["steps"]}
    assert by_id["ok1"]["status"] == "ok" and by_id["ok1"]["rc"] == 0
    assert by_id["bad"]["status"] == "failed" and by_id["bad"]["rc"] == 1
    assert by_id["slow"]["status"] == "timeout" and by_id["slow"]["rc"] in (124, 137)
    assert by_id["slow"]["ms"] < 4000, "timeout must cut the step well before its 5 s sleep"
    assert by_id["ok2"]["status"] == "ok"
    assert by_id["weekend_only"]["status"] == "skipped_dow"
    assert s["overall_status"] == "degraded" and s["executed_any"] is True and s["dry_run"] is False
    for st in s["steps"]:
        assert st["schema"] == pm.STEP_RECEIPT_SCHEMA
    # the step's own log file received the step output; the receipts jsonl has one line per step
    assert (tmp_path / "logs" / "hermetic_ok2.log").exists()
    receipts = (tmp_path / "logs" / "pipelines" / "hermetic_apply" / "test_steps.jsonl").read_text().splitlines()
    assert len(receipts) == 5


def test_held_stage_lock_is_a_clean_skip(tmp_path):
    marker = tmp_path / "ran"
    man = _hermetic_manifest(tmp_path, "hermetic_lock", [
        {"id": "touch", "cron_line": 1, "command": f"touch {marker}", "timeout": "10s"},
    ])
    lockfile = "/tmp/pipeline_hermetic_lock-test.lock"
    with open(lockfile, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run(tmp_path, man, "--stage", "test", "--apply")
    assert r.returncode == 0
    assert "already running" in r.stdout + r.stderr
    assert not marker.exists()


def test_unknown_stage_and_invalid_manifest_refuse(tmp_path):
    man = _hermetic_manifest(tmp_path, "hermetic_stage", [
        {"id": "x", "cron_line": 1, "command": "true", "timeout": "5s"},
    ])
    r = _run(tmp_path, man, "--stage", "nope")
    assert r.returncode == 64 and "unknown stage" in r.stderr
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": "bad", "stages": {
        "s": {"steps": [{"id": "b", "cron_line": 1, "command": "bash scripts/market_day_gate.sh x", "timeout": "5s"}]}}}))
    r = _run(tmp_path, bad, "--stage", "s", "--apply")
    assert r.returncode == 65 and "excluded token" in r.stderr


# --------------------------------------------------------------------------- committed manifests

@pytest.mark.parametrize("name", sorted(MANIFESTS))
def test_committed_manifest_is_valid_and_verbatim(name):
    manifest = pm.load(MANIFESTS[name])
    assert pm.validate(manifest) == []
    for stage_name, stage in manifest["stages"].items():
        assert stage.get("proposed_schedule"), f"{name}/{stage_name} needs a proposed_schedule"
        for st in stage["steps"]:
            assert st["command"] in st["cron_line_verbatim"], (name, stage_name, st["id"])
            assert st["cron_line_verbatim"].split(None, 5)[:5] == st["cron_schedule"].split()
            assert "measured" in st and "verified" in st["measured"]
            assert st.get("continue_on_error") is True
            for tok in pm.FORBIDDEN_COMMAND_TOKENS:
                assert tok not in st["command"]
    assert isinstance(manifest.get("excluded"), list) and manifest["excluded"], f"{name}: excluded list must be explicit"
    for e in manifest["excluded"]:
        assert e.get("reason") and e.get("category") and isinstance(e.get("cron_line"), int)


def test_after_close_exclusions_name_the_broker_lines():
    manifest = pm.load(MANIFESTS["after_close"])
    excluded = {e["basename"] for e in manifest["excluded"]}
    for must in ("schwab_position_sync.py", "positions_sync.py", "schwab_transaction_ingest.py",
                 "snaptrade_sync.py", "sync_basis_from_broker.py", "stop_drift_alert.py"):
        assert must in excluded, f"{must} must be listed as excluded with a reason"
    cats = {e["category"] for e in manifest["excluded"]}
    assert {"MARKET_DAY_GATE", "BROKER_SYNC", "STOP_ADVISORY"} <= cats
    assert manifest["deferred"], "slow steps must be named under deferred"
    slow = {d["basename"] for d in manifest["deferred"]}
    assert "trade_ai_orchestrator.py" in slow


def test_hermes_steps_keep_their_wrappers_verbatim():
    for name in ("hermes_learning", "hermes_overnight"):
        manifest = pm.load(MANIFESTS[name])
        wrapped = 0
        for stage in manifest["stages"].values():
            for st in stage["steps"]:
                verbatim = st["cron_line_verbatim"]
                for w in pm.LLM_WRAPPERS:
                    if w in verbatim:
                        assert w in st["command"], f"{name}/{st['id']}: {w} must stay inside the step"
                        wrapped += 1
        assert wrapped >= 2, f"{name}: expected wrapped Hermes steps"


def test_plan_cli_matches_module(tmp_path):
    manifest = pm.load(MANIFESTS["premarket"])
    r = subprocess.run([sys.executable, str(MANIFEST_PY), str(MANIFESTS["premarket"]), "--plan", "premarket"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if l]
    assert len(lines) == len(manifest["stages"]["premarket"]["steps"])
    first = lines[0].split(pm.SEP)
    assert first[0] == manifest["stages"]["premarket"]["steps"][0]["id"]
    assert first[1] == str(manifest["stages"]["premarket"]["steps"][0]["cron_line"])
    assert first[2].isdigit()


def test_committed_runners_dry_run_print_plan_only(tmp_path):
    """The real manifests, dry-run against a scratch project root: plan printed, nothing executed."""
    env = dict(os.environ)
    env.pop("ALPACA_MODE", None)
    env.pop("LIVE_TRADING_ENABLED", None)
    for runner, extra in ((RUNNERS[0], ["--manifest", str(MANIFESTS["after_close"]), "--stage", "close-capture"]),
                          (RUNNERS[1], ["--manifest", str(MANIFESTS["premarket"])]),
                          (RUNNERS[2], ["--manifest", str(MANIFESTS["hermes_overnight"]), "--stage", "night"])):
        r = subprocess.run(["bash", str(runner), "--project-root", str(tmp_path), *extra],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[DRY_RUN] would run" in r.stdout
        assert "status=ok" not in r.stdout and "status=failed" not in r.stdout
