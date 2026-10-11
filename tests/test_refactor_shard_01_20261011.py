"""Shard 01 source preparation: scratch receipts, no production DB or secret reads."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def module(name):
    spec = importlib.util.spec_from_file_location(f"shard01_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def refuse(*args, **kwargs):
    raise AssertionError("source plan reached a production dependency")


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def receipt(root, lane):
    return json.loads((root / "data" / "runtime" / f"{lane}_last.json").read_text())


def test_goods_plan_cannot_backfill_or_open_db(monkeypatch, scratch, capsys):
    mod = module("watch_goods_consistency_check")
    monkeypatch.setattr(mod, "_conn", refuse)
    monkeypatch.setattr(mod, "_run", refuse)
    before = snapshot(scratch)
    assert mod.main(["--apply-proposal-backfill", "--dry-run"]) == 0
    assert "DRY-RUN watch-goods-consistency:" in capsys.readouterr().out
    assert snapshot(scratch) == before


@pytest.mark.parametrize("argv", [["--bogus"], ["--apply-proposal-back"]])
def test_goods_unknown_flags_refused_before_connection(monkeypatch, scratch, argv):
    mod = module("watch_goods_consistency_check")
    monkeypatch.setattr(mod, "_conn", refuse)
    with pytest.raises(SystemExit) as exc:
        mod.main(argv)
    assert exc.value.code == 2
    assert snapshot(scratch) == {}


def test_goods_real_fake_run_receipt_and_argv(monkeypatch, scratch):
    mod = module("watch_goods_consistency_check")
    observed = []

    def fake(args):
        observed.append((args.apply_proposal_backfill, args.json))
        return {"watchlist_symbols": 7, "symbols_missing_any": 2, "proposals_with_mismatch": 1}

    monkeypatch.setattr(mod, "_run", fake)
    assert mod.main(["--apply-proposal-backfill"]) == 0
    assert observed == [(True, False)]
    rec = receipt(scratch, "watch-goods-consistency")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["watchlist_symbols"] == 7


def test_goods_failure_keeps_ok_at_and_exception(monkeypatch, scratch):
    mod = module("watch_goods_consistency_check")
    path = scratch / "data/runtime/watch-goods-consistency_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    monkeypatch.setattr(mod, "_run", refuse)
    with pytest.raises(AssertionError):
        mod.main([])
    rec = receipt(scratch, "watch-goods-consistency")
    assert rec["status"] == "failed" and rec["exit"] == 1
    assert rec["ok_at"] == "2026-10-01T00:00:00Z"


PREPARED = {
    "watch_goods_consistency_check": ("watch-goods-consistency", ["--apply-proposal-backfill"]),
    "finviz_screener_runner": ("finviz-screener-runner", ["--run"]),
    "feedback_loop_processor": ("feedback-loop-processor", []),
    "research_watchlist_discovery": ("research-watchlist-discovery", ["--apply"]),
    "daily_incubator_refresh": ("daily-incubator-refresh", ["--apply"]),
    "resolve_due_checkpoints": ("resolve-due-checkpoints", ["--apply", "--apply-pending-data"]),
}


@pytest.mark.parametrize("name", PREPARED)
def test_every_cli_plan_is_offline_and_write_free(name, monkeypatch, scratch, capsys):
    mod = module(name)
    for attr in ("_conn", "_get_conn", "get_conn", "_run", "_get_finviz_cookie", "_get_finviz_token",
                 "_fetch_screener_tickers", "_load_env"):
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, refuse)
    cli = getattr(mod, "cli", mod.main)
    before = snapshot(scratch)
    assert cli([*PREPARED[name][1], "--dry-run"]) == 0
    assert "DRY-RUN " + PREPARED[name][0] + ":" in capsys.readouterr().out
    assert snapshot(scratch) == before


@pytest.mark.parametrize("name", PREPARED)
def test_every_unknown_or_abbreviated_cli_flag_is_usage_error(name, monkeypatch, scratch):
    mod = module(name)
    for attr in ("_conn", "_get_conn", "get_conn", "_run", "_get_finviz_cookie", "_load_env"):
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, refuse)
    cli = getattr(mod, "cli", mod.main)
    for argv in (["--bogus"], ["--dry-ru"]):
        with pytest.raises(SystemExit) as exc:
            cli(argv)
        assert exc.value.code == 2
    assert snapshot(scratch) == {}


class EmptyConn:
    closed = False
    description = [("symbol",)]

    def cursor(self, **kwargs):
        return self

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return []

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class Telemetry:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def legacy(name, mod):
    fixture = json.loads((ROOT / "tests/fixtures/refactor_shard_01_legacy_cli.json").read_text())
    fragment = fixture["scripts"][name]
    namespace = dict(vars(mod))
    if fragment["main"]:
        exec(compile(fragment["main"], f"legacy:{name}", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("name", PREPARED)
def test_exact_cron_argv_matches_original_entry_with_fakes(name, monkeypatch, scratch):
    """Original source fragments, not a reimplementation of their old argv parser."""
    mod = module(name)
    argv = PREPARED[name][1]
    monkeypatch.setattr(sys, "argv", [str(SCRIPTS / f"{name}.py"), *argv])
    observations = []
    telemetry = types.SimpleNamespace(PipelineRun=Telemetry, run_start=lambda *a: None,
                                      run_complete=lambda *a, **k: None, run_fail=lambda *a: None)
    monkeypatch.setitem(sys.modules, "pipeline_registry", telemetry)
    monkeypatch.setitem(sys.modules, "catalyst_enrichment", types.SimpleNamespace(enrich_ticker=refuse))
    monkeypatch.setitem(sys.modules, "lib.data_source_report", types.SimpleNamespace(report_source=lambda *a, **k: None))
    if name == "finviz_screener_runner":
        def fake(screener_id=None, dry_run=False):
            observations.append((screener_id, dry_run))
            return {"results": [], "screeners_run": 0, "total_new_tickers": 0,
                    "membership_failures": 0, "db_write_failures": 0}
        monkeypatch.setattr(mod, "run_screener", fake)
        fixture = json.loads((ROOT / "tests/fixtures/refactor_shard_01_legacy_cli.json").read_text())
        exec(compile(fixture["scripts"][name]["entry"], "legacy:finviz-entry", "exec"), dict(vars(mod)))
    else:
        if name == "watch_goods_consistency_check":
            monkeypatch.setattr(mod, "_conn", lambda: EmptyConn())
            monkeypatch.setattr(mod, "gather", lambda cur: ({}, []))
            report = {"watchlist_symbols": 0, "symbols_missing_any": 0, "proposals_with_mismatch": 0,
                      "proposal_mismatches": {}}
            monkeypatch.setattr(mod, "summarize", lambda *a: dict(report))
            def fake_backfill(*args):
                observations.append("backfill")
                return 0
            monkeypatch.setattr(mod, "backfill_proposals", fake_backfill)
            monkeypatch.setattr(mod, "RECEIPT", scratch / "legacy-goods.json")
            scratch.mkdir(parents=True, exist_ok=True)
        elif name == "feedback_loop_processor":
            monkeypatch.setattr(mod, "_get_conn", lambda: EmptyConn())
            def fake_step(conn, dry_run=False):
                observations.append(dry_run)
                return 3
            monkeypatch.setattr(mod, "STEPS", (("test_step", "test step", fake_step),))
        elif name == "research_watchlist_discovery":
            monkeypatch.setattr(mod, "_get_conn", lambda: EmptyConn())
            def fake_collect(conn, limit):
                observations.append(limit)
                return {}
            monkeypatch.setattr(mod, "_collect", fake_collect)
        elif name == "daily_incubator_refresh":
            def fake_connect():
                observations.append("connect")
                return EmptyConn()
            monkeypatch.setattr(mod, "get_conn", fake_connect)
        elif name == "resolve_due_checkpoints":
            triage = {key: 0 for key in ("pending_total", "future_dated", "obtainable", "stuck_waiting_data",
                                        "never_resolvable", "applied", "resolved", "expired")}
            triage.update(as_of="2026-10-11T00:00:00Z", root=str(scratch), apply_refused=False,
                          reasons={}, resolve_samples=[], expire_samples=[])
            result = {key: 0 for key in ("due", "resolved", "pending_data", "not_price_resolvable",
                                        "pending_resolved", "pending_expired")}
            result.update(applied=True, samples=[], pending_apply_refused=False, pending_triage=triage,
                          not_resolvable_reasons={})
            def fake_run(**kwargs):
                observations.append(kwargs)
                return result
            monkeypatch.setattr(mod, "run", fake_run)
        old = legacy(name, mod)
        assert old["main"]() in (None, 0)
    old_observations = list(observations)
    observations.clear()
    cli = getattr(mod, "cli", mod.main)
    assert cli(argv) == 0
    assert observations == old_observations
    rec = receipt(scratch, PREPARED[name][0])
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"] is not None


@pytest.mark.parametrize("name", ("finviz_screener_runner", "daily_incubator_refresh", "resolve_due_checkpoints"))
def test_failure_preserves_exit_and_last_success(name, monkeypatch, scratch):
    mod = module(name)
    lane = PREPARED[name][0]
    path = scratch / "data/runtime" / f"{lane}_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    attr = {"finviz_screener_runner": "run_screener", "daily_incubator_refresh": "_run",
            "resolve_due_checkpoints": "_run_cli"}[name]
    monkeypatch.setattr(mod, attr, refuse)
    monkeypatch.setitem(sys.modules, "pipeline_registry", types.SimpleNamespace(run_start=lambda *a: None))
    with pytest.raises(AssertionError):
        mod.main(PREPARED[name][1])
    rec = receipt(scratch, lane)
    assert rec["status"] == "failed" and rec["exit"] == 1 and rec["ok_at"] == "2026-10-01T00:00:00Z"


def test_feedback_env_loading_is_deferred_and_name_scoped(monkeypatch):
    mod = module("feedback_loop_processor")
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("SCHWAB_FAKE_CREDENTIAL", raising=False)
    def fake_read(path, **kwargs):
        assert path.name == ".env"
        return "DB_PASSWORD=fixture\nSCHWAB_FAKE_CREDENTIAL=must-not-load\n"
    monkeypatch.setattr(Path, "read_text", fake_read)
    mod._load_env()
    assert os.environ["DB_PASSWORD"] == "fixture"
    assert "SCHWAB_FAKE_CREDENTIAL" not in os.environ


def test_finviz_soft_write_failure_is_not_fresh_success(monkeypatch, scratch):
    mod = module("finviz_screener_runner")
    path = scratch / "data/runtime/finviz-screener-runner_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    monkeypatch.setitem(sys.modules, "pipeline_registry", types.SimpleNamespace(run_start=lambda *a: None))
    monkeypatch.setattr(mod, "run_screener", lambda **k: {"results": [], "db_write_failures": 1})
    assert mod.main(["--run"]) == 0  # keep legacy exit while admitting failed output
    rec = receipt(scratch, "finviz-screener-runner")
    assert rec["status"] == "failed" and rec["ok_at"] == "2026-10-01T00:00:00Z"


def test_prepared_allowlist_has_no_broker_names_or_live_authority():
    entries = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    rows = {e["lane_id"]: e for e in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    health = {e["id"]: e for e in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}
    policies = json.loads((ROOT / "config/n8n_retry_policies.json").read_text())["policies"]
    for lane, argv in PREPARED.values():
        entry = entries[lane]
        assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
        assert entry["command"][2:] == argv
        assert not any(any(token in name.upper() for token in ("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR"))
                       for name in entry["env_names"])
        assert rows[lane]["scheduler"]["wave"] == "R2-01" and rows[lane]["dispatch"]["wave"] == "W4"
        dispatch = rows[lane]["dispatch"]
        assert dispatch["retry_policy"] == "none"  # transient-2 excludes ingest and learn
        assert dispatch["class"] in policies[dispatch["retry_policy"]]["permitted_classes"]
        assert health[lane]["status"] == "DRAFT" and "reviewer" not in health[lane]
        assert health[lane]["evidence_class"] == "SOURCE_ONLY"
        assert health[lane]["runtime_evidence"] == "NOT_MEASURED"
        assert health[lane]["baseline"]["runs_considered"] is None
        assert "deletedAt" not in health[lane]["evidence"]["never"]
    checkpoint_calendar = health["resolve-due-checkpoints"]["baseline"]["calendar"]
    assert "all seven days including weekends" in checkpoint_calendar


@pytest.mark.parametrize("name", PREPARED)
def test_real_cli_subprocess_has_no_state_writes_or_unknown_flag_fallthrough(name, scratch):
    env = {"PATH": os.defpath, "TRADE_AI_CI": "1", "TRADEAI_STATE_ROOT": str(scratch),
           "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(SCRIPTS / f"{name}.py"), *PREPARED[name][1], "--dry-run"]
    before = snapshot(scratch)
    good = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert good.returncode == 0, good.stderr
    assert "DRY-RUN " + PREPARED[name][0] + ":" in good.stdout
    bad = subprocess.run([*command, "--bogus"], env=env, capture_output=True, text=True, timeout=10)
    assert bad.returncode == 2
    assert snapshot(scratch) == before
