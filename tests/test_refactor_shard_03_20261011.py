"""Shard 03 source contracts: offline previews, strict argv and scratch-only fake runs.

No real lane executor, provider, DB, sender or broker is invoked. The legacy argv
oracle executes the old source with business functions replaced by identical fakes.
"""
from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "7b36c98c32382b86c04bd5792927fc7c2bd1c729"
# Independent argv from the approved cron snapshot, plus two blocked source-only preparations.
CASES = [
    ("aegis-social-sentiment", "aegis_social_sentiment", []),
    ("etf-performance-enrich", "etf_performance_enrich", []),
    ("hermes-discovery-yield-builder", "hermes_discovery_yield_builder", ["--apply", "--json"]),
    ("hermes-social-sentiment", "hermes_social_sentiment", ["--apply"]),
    ("ask-alerts", "ask_alerts", ["--check"]),
    ("investment-costs", "investment_costs", []),
    ("opening-intelligence", "opening_intelligence", ["--persist"]),
    ("opening-intelligence-render", "opening_intelligence", ["--persist", "--render"]),
    ("register-analyst-sources", "register_analyst_sources", ["--apply"]),
    ("trade-backtest-engine", "trade_backtest_engine", []),
]
SHADOW = {lane for lane, _, _ in CASES} - {"ask-alerts", "hermes-discovery-yield-builder"}


def boom(*args, **kwargs):
    raise AssertionError("real network/DB/provider/secret operation reached")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(ROOT))
    pg = types.ModuleType("psycopg2")
    pg.connect = boom
    pg.extras = types.ModuleType("psycopg2.extras")
    pg.extras.RealDictCursor = object
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)
    for name in ("pandas", "numpy", "yfinance"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=boom, _execute=boom))
    monkeypatch.setitem(sys.modules, "lib.writers.symbol_profiles_writer", types.SimpleNamespace(upsert_profile=boom))
    monkeypatch.setitem(sys.modules, "lib.data_source_report", types.SimpleNamespace(report_source=lambda *a, **k: None))


def module(script, *, legacy=False):
    name = f"shard03_{script}_{'legacy' if legacy else 'new'}"
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / "scripts" / f"{script}.py")
    sys.modules[name] = mod
    source = (subprocess.check_output(["git", "show", f"{BASE}:scripts/{script}.py"], cwd=ROOT, text=True)
              if legacy else Path(mod.__file__).read_text())
    exec(compile(source, mod.__file__, "exec"), mod.__dict__)
    return mod, source


def setup_fake(mod, script, monkeypatch):
    calls = []

    def record(label, result):
        def fake(*args, **kwargs):
            calls.append((label, args, kwargs))
            return result
        return fake

    if hasattr(mod, "_load_env"):
        mod._load_env = lambda: None
    if script == "aegis_social_sentiment":
        mod.main = record("ingest", {"written": 2, "universe": 2, "db_ok": True})
    elif script == "etf_performance_enrich":
        mod.enrich = record("enrich", {"symbols": 2, "attempted": 2, "updated": 2,
                                      "rejected": 0, "errors": 0, "empty": 0})
    elif script == "hermes_discovery_yield_builder":
        mod.compute_yield_file = record("yield", {"entries": 2, "yield": {"fixture": {"n": 10}}})
    elif script == "hermes_social_sentiment":
        mod.RUN_ID = "fixture-run"
        mod._resolve = record("resolve", ["AAA"])
        def search(symbol):
            calls.append(("search", (symbol,), {}))
            mod._FETCH_STATS["ok"] += 1
            return [{"title": "fixture"}]
        mod.search_forum = search
        mod.normalize = record("normalize", {"sentiment": "bullish"})
        mod.persist = record("persist", True)
        monkeypatch.setattr(mod.time, "sleep", lambda *a: None)
    elif script == "ask_alerts":
        mod.check_alerts = record("check", [{"id": "fixture"}])
    elif script == "investment_costs":
        cur = object()
        conn = types.SimpleNamespace(cursor=lambda: cur)
        monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
        mod.ensure_cost_tables = record("ensure", None)
        mod.ingest_actual_fees = record("fees", {"ingested_new": 2})
        mod.accrue_fund_expenses = record("accrue", {"accrued_rows": 3})
        mod.costs_reconciliation = record("reconcile", {"checks": [], "all_ok": True})
    elif script == "opening_intelligence":
        mod.build_snapshot = record("snapshot", {"source_kind": "NONE", "evidence": [], "conflicts": [],
                                                "opening_bias": "DATA_INSUFFICIENT"})
        mod.persist = record("persist", "fixture-artifact")
        mod.render_opening_read = record("render", "fixture-render")
    elif script == "register_analyst_sources":
        mod.register = record("register", {"added": 2, "updated": 1})
    elif script == "trade_backtest_engine":
        mod.run_all = record("backtest", {"full": 2})
        mod.print_summary = record("summary", None)
    return calls


def invoke(mod, source, script, args, monkeypatch):
    monkeypatch.setattr(sys, "argv", [f"{script}.py", *args])
    if script == "aegis_social_sentiment":
        return mod.cli()
    if hasattr(mod, "main"):
        return mod.main()
    tree = ast.parse(source)
    entry = next(node for node in reversed(tree.body)
                 if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test))
    exec(compile(ast.Module(body=entry.body, type_ignores=[]), mod.__file__, "exec"), mod.__dict__)
    return 0


@pytest.mark.parametrize("lane,script,args", CASES)
def test_real_cli_preview_is_offline_and_unknown_flags_exit_2(lane, script, args, tmp_path):
    state = tmp_path / "cli-state"
    state.mkdir()
    marker = state / "previous.json"
    marker.write_text('{"ok_at":"unchanged"}')
    before = {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    env = {"PATH": os.defpath, "TRADE_AI_CI": "1", "TRADEAI_STATE_ROOT": str(state),
           "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8"}
    command = [sys.executable, str(ROOT / "scripts" / f"{script}.py"), *args, "--dry-run"]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert f"DRY-RUN {lane}: would" in result.stdout
    for bad in ("--unrecognized-shard03-flag", "--dry-r"):
        refused = subprocess.run([*command, bad], cwd=tmp_path, env=env,
                                 capture_output=True, text=True, timeout=20)
        assert refused.returncode == 2, refused.stderr
    assert {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("lane,script,args", CASES)
def test_fake_real_run_writes_durable_receipt_and_failure_preserves_ok_at(lane, script, args, tmp_path, monkeypatch):
    mod, source = module(script)
    calls = setup_fake(mod, script, monkeypatch)
    assert invoke(mod, source, script, args, monkeypatch) in (None, 0)
    receipt = tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"
    good = json.loads(receipt.read_text())
    assert good["schema"] == "LaneRunReceipt@v1" and good["lane_id"] == lane
    assert good["status"] == "ok" and good["ok_at"] and calls
    failing = {"aegis_social_sentiment": "main", "etf_performance_enrich": "enrich",
               "hermes_discovery_yield_builder": "compute_yield_file", "hermes_social_sentiment": "_resolve",
               "ask_alerts": "check_alerts", "investment_costs": "ensure_cost_tables",
               "opening_intelligence": "build_snapshot", "register_analyst_sources": "register",
               "trade_backtest_engine": "run_all"}[script]
    def failed(*a, **k):
        raise RuntimeError("fixture failure")
    setattr(mod, failing, failed)
    try:
        exit_code = invoke(mod, source, script, args, monkeypatch)
    except RuntimeError:
        exit_code = 1
    assert exit_code == 1
    bad = json.loads(receipt.read_text())
    assert bad["status"] == "failed" and bad["ok_at"] == good["ok_at"]


@pytest.mark.parametrize("lane,script,args", CASES)
def test_legacy_cron_argv_preserves_business_calls_and_stdout(lane, script, args, monkeypatch, capsys):
    old, old_source = module(script, legacy=True)
    old_calls = setup_fake(old, script, monkeypatch)
    assert invoke(old, old_source, script, args, monkeypatch) in (None, 0)
    old_out = capsys.readouterr().out
    new, new_source = module(script)
    new_calls = setup_fake(new, script, monkeypatch)
    assert invoke(new, new_source, script, args, monkeypatch) in (None, 0)
    assert capsys.readouterr().out == old_out
    # Connection/cursor identities differ; compare business call labels and stable argv inputs.
    assert [c[0] for c in new_calls] == [c[0] for c in old_calls]
    if script != "investment_costs":
        assert new_calls == old_calls


def test_admission_and_draft_contracts_keep_operator_boundaries():
    from scripts.lib.lane_dispatch import r1_class_admission, validate_dispatch_block
    registry = json.loads((ROOT / "config/lane_registry.json").read_text())
    allowlist = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())
    for lane in SHADOW:
        row = next(r for r in registry["lanes"] if r["lane_id"] == lane)
        entry = next(r for r in allowlist["lanes"] if r["lane_id"] == lane)
        contract = next(r for r in contracts["contracts"] if r["id"] == lane)
        assert r1_class_admission(row, entry=entry)[0]
        assert not validate_dispatch_block(row)
        assert row["scheduler"]["kind"] == "cron" and row["scheduler"]["stage"] == "shadow"
        assert row["scheduler"]["wave"] == "R2-03" and row["dispatch"]["wave"] == "W4"
        assert row["dispatch"]["retry_policy"] == "none"  # existing policy admits ingest/learn, without retrying writes
        assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
        assert not any(name.startswith(("ALPACA", "SCHWAB", "SNAPTRADE", "MOOMOO", "IBKR"))
                       for name in entry["env_names"])
        assert contract["status"] == "DRAFT" and "reviewer" not in contract
        assert "UNKNOWN" not in json.dumps(contract)
        assert contract["baseline"]["evidence_class"] == "SOURCE_ONLY"
        assert contract["evidence"]["runtime_evidence_class"] == "NOT_MEASURED"
        assert "deletedAt" not in contract["evidence"]["never"]
    assert not any(r["lane_id"] == "ask-alerts" for r in allowlist["lanes"])


def test_dry_plan_changes_with_real_inputs(tmp_path, monkeypatch, capsys):
    mod, _ = module("ask_alerts")
    mod.STORE = tmp_path / "ask.json"
    mod.STORE.write_text('{"alerts":[]}')
    assert mod.main(["--check", "--dry-run"]) == 0
    first = capsys.readouterr().out
    mod.STORE.write_text('{"alerts":[{"status":"active"}]}')
    assert mod.main(["--check", "--dry-run"]) == 0
    assert capsys.readouterr().out != first


@pytest.mark.parametrize("script", ["aegis_social_sentiment", "hermes_social_sentiment",
                                   "trade_backtest_engine", "etf_performance_enrich"])
def test_own_env_loader_never_copies_undeclared_broker_names(script, tmp_path, monkeypatch):
    mod, _ = module(script)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    if script == "etf_performance_enrich":
        monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(
            dotenv_values=lambda *a: {"DB_PASSWORD": "fixture", "ALPACA_API_KEY": "not-a-credential"}))
    else:
        # Synthetic test file, never a host render or credential file.
        (tmp_path / ".env").write_text("DB_PASSWORD=fixture\nALPACA_API_KEY=not-a-credential\n")
        setattr(mod, "PROJECT_ROOT" if hasattr(mod, "PROJECT_ROOT") else "ROOT", tmp_path)
    mod._load_env()
    assert os.environ["DB_PASSWORD"] == "fixture"
    assert "ALPACA_API_KEY" not in os.environ


def test_cost_findings_preserve_success_timestamp_without_changing_legacy_exit(tmp_path, monkeypatch):
    mod, source = module("investment_costs")
    setup_fake(mod, "investment_costs", monkeypatch)
    assert invoke(mod, source, "investment_costs", [], monkeypatch) == 0
    receipt = tmp_path / "state" / "data" / "runtime" / "investment-costs_last.json"
    previous = json.loads(receipt.read_text())["ok_at"]
    mod.costs_reconciliation = lambda *a: {"checks": [{"ok": False}], "all_ok": False}
    assert invoke(mod, source, "investment_costs", [], monkeypatch) == 0
    observed = json.loads(receipt.read_text())
    assert observed["status"] == "failed" and observed["ok_at"] == previous
    assert observed["summary"]["reconciliation_ok"] is False
