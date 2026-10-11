"""Shard 05 source proposals: offline previews, strict argv, fake-only real work and failure proof."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CRON_PROOF = json.loads((ROOT / "tests/fixtures/refactor_shard_05/cron_argv.json").read_text())
CASES = [(lane, Path(p["command"][1]).name, p["command"][2:]) for lane, p in CRON_PROOF.items()]
# Source-only safety work; no admission without an approved matching cron line.
CASES.append(("siem-to-hermes-backlog", "siem_to_hermes_backlog.py", ["--apply"]))


def load(name):
    spec = importlib.util.spec_from_file_location("shard05_" + name.replace(".", "_"), ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADE_AI_CI", "1")
    return tmp_path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def invoke(fn, argv):
    old = sys.argv
    sys.argv = ["fixture_script", *argv]
    try:
        import inspect
        return fn(argv) if inspect.signature(fn).parameters else fn()
    finally:
        sys.argv = old


def frozen(mod, name):
    source = json.loads((ROOT / "tests/fixtures/refactor_shard_05/legacy_entrypoints.json").read_text())[name]
    namespace = dict(vars(mod))
    namespace["argparse"] = argparse
    exec(compile(source, "frozen-original-entrypoint", "exec"), namespace)
    return namespace["main"]


def fake_work(mod, name, monkeypatch):
    calls = []

    def connect():
        calls.append("connect")
        class Conn:
            def cursor(self):
                return self
            def execute(self, sql, params=None):
                calls.append(("execute", " ".join(sql.split()), params))
            def commit(self):
                calls.append("commit")
            def close(self):
                calls.append("close")
            def fetchall(self):
                return []
        return Conn()

    def work(**kwargs):
        calls.append(kwargs)
        if name == "drain_cio_stance_classification.py":
            return {"pending": 1, "counts": {"applied": 1}, "results": [{"symbol": "TEST", "status": "applied"}]}
        if name == "build_symbol_profiles.py":
            return {"updated": 1, "checked": 1}
        if name == "hermes_directive_discovery.py":
            return {"trend_directives": 1, "staged": 1, "skipped_stale": 0}

    if name == "material_change_detector.py":
        monkeypatch.setattr(mod, "_db", connect)
        monkeypatch.setattr(mod, "universe", lambda cur: {"TEST": {}})
        monkeypatch.setattr(mod, "price_excursions", lambda *a: ([], {}, []))
        for fn in ("new_catalysts", "news_bursts", "new_filings"):
            monkeypatch.setattr(mod, fn, lambda *a: ([], {}))
        monkeypatch.setattr(mod, "persist", lambda *a, **k: {"written": 0, "already_present": 0,
                            "attempted": 0, "disposition": "NOTHING_DETECTED"})
        monkeypatch.setattr(mod, "write_health_record", lambda r: calls.append(("health", r["outcome"])))
        monkeypatch.setitem(sys.modules, "scripts.lib.ddl_guard", types.SimpleNamespace(
            apply_ddl=lambda cur, ddl: calls.append("DDL")))
        boundary = "_db"
    elif name in ("drain_cio_stance_classification.py", "build_symbol_profiles.py", "hermes_directive_discovery.py"):
        monkeypatch.setattr(mod, "run", work)
        boundary = "run"
    elif name == "drain_discovery_backlog.py":
        monkeypatch.setattr(mod, "_get_conn", connect)
        monkeypatch.setattr(mod, "_select", lambda cur, cap: calls.append(("select", cap)) or
                            ([(1, "fixture_promote", None)], [(2, "fixture_archive", "DISCOVERED")]))
        monkeypatch.setattr(mod, "_transition", lambda *a: calls.append(("transition", a[1:])))
        boundary = "_get_conn"
    elif name == "finviz_sector_research.py":
        monkeypatch.setattr(mod, "_get_conn", connect)
        monkeypatch.setattr(mod, "_load_env", lambda: calls.append("narrow-env"))
        monkeypatch.setenv("FINVIZ_API_TOKEN", "fixture_only")
        monkeypatch.setattr(mod, "TOKEN", "fixture_only")
        monkeypatch.setattr(mod, "_fetch", lambda group: calls.append(("fetch", group)) or
                            [{"Name": "fixture_group", "Change": "1%", "Stocks": "1"}])
        boundary = "_get_conn"
    elif name == "siem_to_hermes_backlog.py":
        monkeypatch.setattr(mod, "_load_env", lambda: None)
        def generate(max_items=5, dry_run=True):
            calls.append(("generate", max_items, dry_run))
            mod.LAST_STATS.update(candidates=1, duplicates=0, rejected=0, inserted=1)
            return [{"display_category": "OPS", "topic": "fixture finding", "confidence_score": 0.5}], 1
        monkeypatch.setattr(mod, "generate_backlog", generate)
        boundary = "generate_backlog"
    elif name == "sweep_commitment_outcomes.py":
        monkeypatch.setattr(mod, "read_jsonl", lambda p: calls.append(("read", str(p))) or
                            ([{"commitment_id": "fixture"}] if p.name == mod.COMMITMENTS else []))
        res = types.SimpleNamespace(outcomes=[{"fixture": True}], lessons=[{"fixture": True}],
                                    to_dict=lambda: {"fixture": True})
        monkeypatch.setattr(mod, "sweep_due_commitments", lambda *a, **k: res)
        monkeypatch.setattr(mod, "append_jsonl", lambda p, rows: calls.append(("append", str(p), rows)) or len(rows))
        monkeypatch.setitem(sys.modules, "scripts.lib.commitment_price_observation", types.SimpleNamespace(
            make_price_observation_provider=lambda **k: None))
        monkeypatch.setitem(sys.modules, "scripts.resolve_due_checkpoints", types.SimpleNamespace(
            _price_lookup_factory=lambda: None))
        boundary = "read_jsonl"
    return calls, boundary


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_explicit_preview_never_reaches_business_boundary(state, monkeypatch, capsys, lane, name, argv):
    mod = load(name)
    _, boundary = fake_work(mod, name, monkeypatch)
    monkeypatch.setattr(mod, boundary, lambda *a, **k: pytest.fail("preview reached business boundary"))
    if hasattr(mod, "_load_env"):
        monkeypatch.setattr(mod, "_load_env", lambda: pytest.fail("preview loaded environment"))
    before = snapshot(state)
    assert invoke(mod.main, [*argv, "--dry-run"]) == 0
    assert snapshot(state) == before
    assert f"DRY-RUN {lane}: would" in capsys.readouterr().out


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_removing_offline_preview_guard_reaches_fake_boundary(state, monkeypatch, lane, name, argv):
    """Positive mutation control: removing the return makes the prohibited work reachable."""
    mod = load(name)
    _, boundary = fake_work(mod, name, monkeypatch)
    attempted = []
    def refuse(*a, **k):
        attempted.append("fixture business boundary")
        raise RuntimeError("fixture refuses business boundary")
    monkeypatch.setattr(mod, boundary, refuse)
    source = (ROOT / "scripts" / name).read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    preview = next(n for n in fn.body if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
                   and n.test.attr == "dry_run")
    fn.body.remove(preview)
    mutated = ast.Module(body=[fn], type_ignores=[])
    namespace = dict(vars(mod))
    exec(compile(ast.fix_missing_locations(mutated), "fixture-preview-guard-removed", "exec"), namespace)
    try:
        invoke(namespace["main"], [*argv, "--dry-run"])
    except RuntimeError:
        pass
    assert attempted == ["fixture business boundary"]


@pytest.mark.parametrize("lane,name,argv", CASES)
@pytest.mark.parametrize("bad", ["--dry-rn", "--dry", "--unknown"])
def test_unknown_or_abbreviated_flag_exits_two_before_work(state, lane, name, argv, bad):
    mod = load(name)
    with pytest.raises(SystemExit) as e:
        invoke(mod.main, [*argv, bad])
    assert e.value.code == 2 and snapshot(state) == {}


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_real_argv_matches_frozen_entrypoint_and_writes_receipt(state, monkeypatch, capsys, lane, name, argv):
    mod = load(name)
    calls, _ = fake_work(mod, name, monkeypatch)
    old = frozen(mod, name)
    assert invoke(old, argv) == 0
    old_calls = list(calls)
    old_stdout = capsys.readouterr().out
    calls.clear()
    assert invoke(mod.main, argv) == 0
    if name == "finviz_sector_research.py":
        calls.remove("narrow-env")  # deliberate loading relocation, same named dependencies
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    receipt = json.loads((state / "data/runtime" / (lane + "_last.json")).read_text())
    assert receipt["schema"] == "LaneRunReceipt@v1" and receipt["status"] == "ok" and receipt["ok_at"]
    assert receipt["summary"]


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_real_failure_keeps_previous_ok_at_and_original_exception(state, monkeypatch, lane, name, argv):
    mod = load(name)
    _, boundary = fake_work(mod, name, monkeypatch)
    assert invoke(mod.main, argv) == 0
    path = state / "data/runtime" / (lane + "_last.json")
    old = json.loads(path.read_text())["ok_at"]
    def fail(*a, **k):
        raise RuntimeError("fixture failure")
    monkeypatch.setattr(mod, boundary, fail)
    with pytest.raises(RuntimeError):
        invoke(mod.main, argv)
    result = json.loads(path.read_text())
    assert result["status"] == "failed" and result["ok_at"] == old and result["exit"] == 1


def test_finviz_partial_fetch_keeps_exit_zero_but_does_not_refresh_ok(state, monkeypatch):
    mod = load("finviz_sector_research.py")
    fake_work(mod, "finviz_sector_research.py", monkeypatch)
    assert mod.main([]) == 0
    p = state / "data/runtime/finviz-sector-research_last.json"
    old = json.loads(p.read_text())["ok_at"]
    def fetch(group):
        if group == "industry":
            raise RuntimeError("fixture fetch failed")
        return [{"Name": "fixture", "Stocks": "1"}]
    monkeypatch.setattr(mod, "_fetch", fetch)
    assert mod.main([]) == 0
    result = json.loads(p.read_text())
    assert result["status"] == "failed" and result["ok_at"] == old and result["summary"]["failed_groups"] == 1


def test_weekly_profile_partial_failure_keeps_exit_zero_without_advancing_ok(state, monkeypatch):
    mod = load("build_symbol_profiles.py")
    fake_work(mod, "build_symbol_profiles.py", monkeypatch)
    assert mod.main([]) == 0
    path = state / "data/runtime/build-symbol-profiles-at-0-19_last.json"
    old = json.loads(path.read_text())["ok_at"]
    monkeypatch.setattr(mod, "run", lambda **kw: {"checked": 2, "updated": 1, "no_profile": 1})
    assert mod.main([]) == 0
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 0 and receipt["ok_at"] == old


# Operator ruling 2026-10-11 ("yes to all 4 for train 3", applied the same way in train 4): lanes another wave
# already owns (train 2's premarket C1 stage RETIRED rows, SW4 EXCLUDED lanes) keep their owner's rows and get no
# allowlist entry; shard assertions apply only to rows this shard actually admitted. A contract may be DRAFT or
# operator-REVIEWED.
def _owned_here(row, wave):
    return (row or {}).get("scheduler", {}).get("wave") == wave


def _contract_ok(contract):
    if contract.get("status") == "DRAFT":
        return "reviewer" not in contract
    review = contract.get("review") or {}
    return contract.get("status") == "REVIEWED" and "operator" in str(review.get("reviewed_by", "")).lower()


def test_own_allowlist_source_shape_and_no_broker_names():
    lanes = {x["lane_id"]: x for x in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    rows = {x["lane_id"]: x for x in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    contracts = {x["id"]: x for x in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}
    for lane in CRON_PROOF:
        if not _owned_here(rows.get(lane), "R2-05"):
            assert lane not in lanes, lane  # held: the owner's row wins, no allowlist entry
            continue
        entry = lanes[lane]
        assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
        assert entry["env_evidence"] and entry["env_report_reason"]
        assert not any(any(t in n.upper() for t in ("ALPACA", "SCHWAB", "MOOMOO", "BROKER", "IBKR", "SNAPTRADE"))
                       for n in entry["env_names"])
        assert rows[lane]["scheduler"]["wave"] == "R2-05" and rows[lane]["dispatch"]["wave"] == "W4"
        contract = contracts[lane]
        assert _contract_ok(contract) and contract["baseline"]["runs_considered"] is None


@pytest.mark.parametrize("lane,name,argv", CASES)
def test_actual_cli_preview_from_neutral_cwd_is_offline(state, lane, name, argv):
    env = dict(os.environ, TRADEAI_STATE_ROOT=str(state), PYTHONDONTWRITEBYTECODE="1")
    before = snapshot(state)
    fixture_argv = list(argv)
    if "--state-root" in fixture_argv:
        fixture_argv[fixture_argv.index("--state-root") + 1] = str(state)
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / name), *fixture_argv, "--dry-run"],
                            cwd=state, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"DRY-RUN {lane}: would" in result.stdout and snapshot(state) == before


def test_frozen_argv_matches_observed_cron_arguments():
    proof = json.loads((ROOT / "tests/fixtures/refactor_shard_05/cron_argv.json").read_text())
    entries = {x["lane_id"]: x for x in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    for lane in CRON_PROOF:
        if lane in entries:  # held lanes (owner's row kept) have no entry; the cron proof below still applies
            assert entries[lane]["command"] == proof[lane]["command"]
        assert proof[lane]["original_line"].startswith(proof[lane]["cron"] + " ")
        tokens = shlex.split(proof[lane]["original_line"])
        if "bash" in tokens and "-c" in tokens:
            tokens = shlex.split(tokens[tokens.index("-c") + 1])
        script = proof[lane]["command"][1]
        start = tokens.index(script)
        args = []
        for token in tokens[start + 1:]:
            if token in {">>", "2>&1", "#", ";", "&&"}:
                break
            args.append(token)
        assert proof[lane]["command"][2:] == args
        actual_case = next(argv for case, _, argv in CASES if case == lane)
        assert actual_case == args
