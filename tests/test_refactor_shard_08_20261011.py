"""Source-only shard08 rehearsal: offline CLI and fake work, never runtime acceptance."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
FIXTURES = ROOT / "tests/fixtures/refactor_shard_08"
PROOF = json.loads((FIXTURES / "cron_argv.json").read_text())
CASES = [(lane, Path(p["command"][1]).name, p["command"][2:]) for lane, p in PROOF.items()]


def load(name):
    spec = importlib.util.spec_from_file_location("shard08_" + name.replace(".", "_"), ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADE_AI_CI", "1")
    return tmp_path


def invoke(fn, argv):
    import inspect

    old = sys.argv
    sys.argv = ["fixture_script", *argv]
    try:
        return fn(argv) if inspect.signature(fn).parameters else fn()
    finally:
        sys.argv = old


def frozen(mod, name):
    source = json.loads((FIXTURES / "legacy_entrypoints.json").read_text())[name]
    namespace = dict(vars(mod))
    namespace["argparse"] = argparse
    exec(compile(source, "frozen-base-entrypoint", "exec"), namespace)
    return namespace["main"]


def fake_work(mod, name, monkeypatch):
    calls = []
    if name == "agent_recommendation_normalizer.py":
        class Conn:
            def close(self):
                calls.append("close")

        def connect():
            calls.append("connect")
            return Conn()

        def extract(conn, agent, symbol):
            calls.append(("extract", agent, symbol))
            return [{"source_table": "watchlist_agent_results", "source_id": "fixture-1",
                     "agent_name": "fixture-reviewer"}]

        monkeypatch.setattr(mod, "_load_env", lambda: None)
        monkeypatch.setattr(mod, "_get_conn", connect)
        monkeypatch.setattr(mod, "normalize_watchlist_results", extract)
        for fn in ("normalize_cio_decisions", "normalize_debates"):
            monkeypatch.setattr(mod, fn, lambda *a: [])
        monkeypatch.setattr(mod, "save_recommendations", lambda conn, recs, dry_run:
                            calls.append(("save", recs, dry_run)) or len(recs))
        boundary = "_get_conn"
    else:
        def run(apply=False):
            calls.append(("run", apply))
            out = {"ok": True, "apply": apply, "events_found": 2, "enqueued": 1,
                   "reactivated_s3_to_s1": 0, "skipped_s3_reactivation": 1}
            print(json.dumps(out, indent=2))
            return out

        monkeypatch.setattr(mod, "run", run)
        boundary = "run"
    return calls, boundary


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_explicit_preview_reaches_no_work_or_state(state, monkeypatch, capsys, lane, name, argv):
    mod = load(name)
    calls, boundary = fake_work(mod, name, monkeypatch)

    def forbidden(*a, **k):
        raise AssertionError("offline preview reached " + boundary)

    monkeypatch.setattr(mod, boundary, forbidden)
    if hasattr(mod, "_load_env"):
        monkeypatch.setattr(mod, "_load_env", forbidden)
    before = snapshot(state)
    assert mod.main([*argv, "--dry-run"]) == 0
    assert capsys.readouterr().out.startswith("DRY-RUN " + lane + ":")
    assert calls == [] and snapshot(state) == before


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_negative_control_removing_preview_reaches_fake_boundary(state, monkeypatch, lane, name, argv):
    mod = load(name)
    _, boundary = fake_work(mod, name, monkeypatch)

    def forbidden(*a, **k):
        raise RuntimeError("preview guard removed reaches fake work")

    monkeypatch.setattr(mod, boundary, forbidden)
    tree = ast.parse((ROOT / "scripts" / name).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    guard = next(n for n in fn.body if isinstance(n, ast.If)
                 and isinstance(n.test, ast.Attribute) and n.test.attr == "dry_run")
    fn.body.remove(guard)
    namespace = dict(vars(mod))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 "preview-guard-negative-control", "exec"), namespace)
    with pytest.raises(RuntimeError, match="preview guard removed"):
        namespace["main"]([*argv, "--dry-run"])


@pytest.mark.parametrize("lane,name,argv", CASES)
@pytest.mark.parametrize("flag", ["--unknown-live", "--app", "--dry"])
def test_strict_parser_rejects_unknown_and_abbreviated_flags(state, monkeypatch, lane, name, argv, flag):
    mod = load(name)
    calls, _ = fake_work(mod, name, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        mod.main([*argv, flag])
    assert exc.value.code == 2 and calls == [] and snapshot(state) == {}


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_exact_approved_cron_argv_matches_frozen_base(state, monkeypatch, capsys, lane, name, argv):
    mod = load(name)
    calls, _ = fake_work(mod, name, monkeypatch)
    invoke(frozen(mod, name), argv)
    old_stdout, old_calls = capsys.readouterr().out, list(calls)
    calls.clear()
    assert mod.main(argv) == 0
    assert capsys.readouterr().out == old_stdout and calls == old_calls
    rec = json.loads((state / "data/runtime" / (lane + "_last.json")).read_text())
    assert rec["status"] == "ok" and rec["ok_at"] and rec["exit"] == 0
    if name == "agent_recommendation_normalizer.py":
        assert rec["summary"]["inserted"] == 1
        assert (state / "data/runtime/agent_recommendation_normalizer_last.json").exists()
    else:
        assert rec["summary"]["enqueued"] == 1


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_failed_work_preserves_previous_success_and_exception(state, monkeypatch, lane, name, argv):
    mod = load(name)
    _, boundary = fake_work(mod, name, monkeypatch)
    assert mod.main(argv) == 0
    path = state / "data/runtime" / (lane + "_last.json")
    previous = json.loads(path.read_text())["ok_at"]

    def broken(*a, **k):
        raise RuntimeError("fake startup failure")

    monkeypatch.setattr(mod, boundary, broken)
    with pytest.raises(RuntimeError, match="fake startup failure"):
        mod.main(argv)
    rec = json.loads(path.read_text())
    assert rec["status"] == "failed" and rec["ok_at"] == previous and rec["exit"] == 1


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_neutral_cwd_offline_cli(state, lane, name, argv):
    before = snapshot(state)
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / name), *argv, "--dry-run"],
                            cwd=state, env=dict(os.environ), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("DRY-RUN " + lane + ":") and snapshot(state) == before


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_allowlist_keeps_exact_arguments_and_original_lock(lane, name, argv):
    doc = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    entry = next(e for e in doc["lanes"] if e["lane_id"] == lane)
    assert entry["command"] == PROOF[lane]["command"]
    assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
    tokens = shlex.split(PROOF[lane]["job_line"])
    cmd_start = tokens.index("scripts/" + name)
    assert tokens[cmd_start + 1:cmd_start + 1 + len(argv)] == argv
    locks = [t for t in tokens if t.startswith("/tmp/") and t.endswith(".lock")]
    assert entry["lock"] == (locks[0] if locks else "/tmp/" + lane + ".lock")
    from lib.env_bootstrap import is_broker_name

    assert not any(is_broker_name(n) for n in entry["env_names"])


def test_feeder_soft_failure_keeps_zero_exit_and_previous_ok_at(state, monkeypatch):
    mod = load("hermes_score_event_feeder.py")
    fake_work(mod, "hermes_score_event_feeder.py", monkeypatch)
    assert mod.main(["--apply"]) == 0
    path = state / "data/runtime/hermes-score-event-feeder_last.json"
    old_ok = json.loads(path.read_text())["ok_at"]
    monkeypatch.setattr(mod, "run", lambda **kwargs: {"ok": False, "reason": "fixture kill switch"})
    assert mod.main(["--apply"]) == 0
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 0 and receipt["ok_at"] == old_ok


def test_normalizer_loader_passes_only_own_database_names(monkeypatch):
    mod = load("agent_recommendation_normalizer.py")
    from lib import env_bootstrap

    seen = []
    monkeypatch.setattr(env_bootstrap, "load_env", lambda **kwargs: seen.append(kwargs))
    mod._load_env()
    assert seen == [{"names": ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")}]


def test_normalizer_prior_startup_failure_had_no_canonical_receipt(state, monkeypatch):
    mod = load("agent_recommendation_normalizer.py")
    fake_work(mod, "agent_recommendation_normalizer.py", monkeypatch)
    monkeypatch.setattr(mod, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("fake startup failure")))
    with pytest.raises(RuntimeError, match="fake startup failure"):
        frozen(mod, "agent_recommendation_normalizer.py")(["--apply"])
    path = state / "data/runtime/agent-recommendation-normalizer_last.json"
    assert not path.exists()
    with pytest.raises(RuntimeError, match="fake startup failure"):
        mod.main(["--apply"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["ok_at"] is None and receipt["exit"] == 1


def test_normalizer_close_failure_cannot_advance_success(state, monkeypatch):
    mod = load("agent_recommendation_normalizer.py")
    fake_work(mod, "agent_recommendation_normalizer.py", monkeypatch)
    assert mod.main(["--apply"]) == 0
    path = state / "data/runtime/agent-recommendation-normalizer_last.json"
    previous = json.loads(path.read_text())["ok_at"]

    class CloseFailure:
        def close(self):
            raise RuntimeError("fake close failure")

    monkeypatch.setattr(mod, "_get_conn", CloseFailure)
    with pytest.raises(RuntimeError, match="fake close failure"):
        mod.main(["--apply"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["ok_at"] == previous and receipt["exit"] == 1
