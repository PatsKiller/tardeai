"""Shard 07 offline plans, exact cron argv compatibility, and durable failure receipts.

Frozen entrypoints are source from 9f602186a, before this shard's changes. Business
boundaries are replaced before invocation; these tests use no real DB, provider,
secret file, scheduler or operator surface.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "refactor_shard_07_20261011"
SPECS = [
    ("document-mentions-backfill", "backfill_document_mentions", ["--all", "--limit", "4000", "--apply"]),
    ("aegis-evening-packet", "aegis_evening_packet", []),
    ("hermes-scope-governor", "hermes_scope_governor", ["--apply"]),
    ("iris-proposal-curator", "iris_proposal_curator", ["--apply"]),
    ("price-db-sync", "price_db_sync", []),
    ("sync-dividend-data", "sync_dividend_data", []),
    ("watch-valuation-backfill", "watch_valuation_backfill", ["--limit", "400"]),
]


def _boom(*args, **kwargs):
    raise AssertionError("a test reached an unmocked business boundary")


def _load(name, old=False):
    key = f"refactor07_{'old' if old else 'new'}_{name}"
    path = ROOT / "scripts" / f"{name}.py"
    if old:
        module = types.ModuleType(key)
        module.__file__ = str(path)
        sys.modules[key] = module
        exec(compile((FIXTURES / f"{name}.py.txt").read_bytes(), str(path), "exec"), module.__dict__)
    else:
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("M2_SKIP_DOCKER", "1")
    for path in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
        monkeypatch.syspath_prepend(str(path))
    # Old valuation source imports db_adapter eagerly. Make the dependency a fixture
    # before module load so the frozen baseline cannot load a host environment.
    db = types.ModuleType("db_adapter")
    db._execute = _boom
    db.get_connection = _boom
    db._get_conn = _boom
    db.USE_DB = True
    monkeypatch.setitem(sys.modules, "db_adapter", db)


def _snapshot(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("lane,name,argv", SPECS)
def test_cron_dry_run_is_offline_and_unknown_flags_fail(lane, name, argv, tmp_path):
    env = {"PATH": os.defpath, "TRADE_AI_CI": "1", "M2_SKIP_DOCKER": "1",
           "TRADEAI_STATE_ROOT": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    # The untracked host harness propagates its pre-import barriers to this child.
    before = _snapshot(tmp_path)
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{name}.py"), *argv, "--dry-run"],
                            cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert f"DRY-RUN {lane}: would" in result.stdout
    assert _snapshot(tmp_path) == before
    bad = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{name}.py"), *argv, "--not-a-real-flag"],
                         cwd=tmp_path, env=env, text=True, capture_output=True)
    assert bad.returncode == 2, bad.stdout + bad.stderr
    abbreviated = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{name}.py"), "--dry-r"],
                                 cwd=tmp_path, env=env, text=True, capture_output=True)
    assert abbreviated.returncode == 2
    assert _snapshot(tmp_path) == before


def _fake_business(module, name, trace, tmp_path, monkeypatch, *, failed=False):
    def call(*args, **kwargs):
        trace.append((args, kwargs))
        if failed:
            raise RuntimeError("fake business failure")
    if name == "backfill_document_mentions":
        monkeypatch.setattr(module.time, "monotonic", lambda: 123.0)
        monkeypatch.setattr(module.time, "strftime", lambda *a: "FROZEN_CLOCK")
        module.load_watermarks = lambda: {"news_articles": 10}
        module.save_watermarks = lambda marks: trace.append(("watermarks", dict(marks)))
        def run(table, limit, apply, **kwargs):
            call(table, limit, apply, **kwargs)
            return dict(table=table, documents=3, subject=1, mentioned=1, undecided_docs=0,
                        no_mention=1, written=2 if apply else 0, multi=0, scanned=3, max_id=20, budget_hit=False)
        module.run = run
    elif name == "aegis_evening_packet":
        def packet():
            call()
            return {"schema": "aegis_evening_packet@v1", "packet_chars": 123, "findings": []}
        module.build_packet = packet
        module.evening_packet_targets = lambda: [tmp_path / "packet.json"]
    elif name == "hermes_scope_governor":
        def run(**kwargs):
            call(**kwargs)
            result = {"ok": True, "evaluated": 3}
            print(json.dumps(result, indent=2))
            return result
        module.run = run
    elif name == "iris_proposal_curator":
        class Cursor:
            def execute(self, sql, params=None):
                call(" ".join(sql.split()), params)
                self.sql = sql
                self.rowcount = 2
            def fetchone(self):
                return (2,)
            def fetchall(self):
                return [(1,), (2,)] if "SELECT id " in self.sql else [("add_channel", 2)]
        class Conn:
            def cursor(self):
                return Cursor()
            def commit(self):
                call("commit")
            def close(self):
                call("close")
        monkeypatch.setattr(sys.modules["db_adapter"], "get_connection", lambda: Conn())
        iris = types.ModuleType("iris_taxonomy_agent")
        iris.apply_proposal = lambda pid: trace.append(("apply_proposal", pid)) or {"ok": True}
        monkeypatch.setitem(sys.modules, "iris_taxonomy_agent", iris)
    elif name == "price_db_sync":
        def run():
            call()
            print("FROZEN_PRICE_SYNC")
            return 3
        module.sync_daily_prices = run
    elif name == "sync_dividend_data":
        def run():
            call()
            print("FROZEN_DIVIDEND_SYNC")
            return {"symbols_checked": 3, "updated": 2, "fetch_errors": 0}
        module.sync = run
    elif name == "watch_valuation_backfill":
        module.FINVIZ_CACHE = tmp_path / "finviz.json"
        module.SUPPLEMENT = tmp_path / "supplement.json"
        module._load = lambda *a: {}
        def universe():
            call()
            return []
        module.watch_universe = universe
        module.priority_order = lambda syms: syms
        monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_boom))
    else:
        raise AssertionError(name)


def _invoke(module, name, argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(ROOT / "scripts" / f"{name}.py"), *argv])
    if name == "price_db_sync" and not hasattr(module, "main"):
        module.sync_daily_prices()
        return 0
    rc = module.main()
    return 0 if rc is None else rc


@pytest.mark.parametrize("lane,name,argv", SPECS)
def test_frozen_entrypoint_preserves_exact_cron_business_argv(lane, name, argv, tmp_path, monkeypatch, capsys):
    observed = []
    for old in (True, False):
        module = _load(name, old=old)
        trace = []
        _fake_business(module, name, trace, tmp_path, monkeypatch)
        rc = _invoke(module, name, argv, monkeypatch)
        output = capsys.readouterr().out
        observed.append((rc, output, trace))
    assert observed[0] == observed[1]
    path = tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"
    receipt = json.loads(path.read_bytes())
    assert receipt["schema"] == "LaneRunReceipt@v1" and receipt["status"] == "ok"
    assert receipt["ok_at"] and receipt["exit"] == 0 and isinstance(receipt["summary"], dict)


@pytest.mark.parametrize("lane,name,argv", SPECS)
def test_fake_real_failure_preserves_previous_success_and_exception(lane, name, argv, tmp_path, monkeypatch):
    path = tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    module = _load(name)
    _fake_business(module, name, [], tmp_path, monkeypatch, failed=True)
    with pytest.raises(RuntimeError, match="fake business failure"):
        _invoke(module, name, argv, monkeypatch)
    receipt = json.loads(path.read_bytes())
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    assert receipt["ok_at"] == "2026-10-01T00:00:00Z"
    assert receipt["error"] == "RuntimeError"


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


@pytest.mark.parametrize("lane,name,argv", SPECS)
def test_allowlist_exact_arguments_and_no_broker_environment(lane, name, argv):
    doc = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_bytes())
    rows = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_bytes())["lanes"]}
    if not _owned_here(rows.get(lane), "R2-07"):
        assert not any(row["lane_id"] == lane for row in doc["lanes"]), lane  # held: owner's row, no entry
        return
    entry = next(row for row in doc["lanes"] if row["lane_id"] == lane)
    assert entry["command"] == ["$PY", f"scripts/{name}.py", *argv]
    assert entry["dry_run_arg"] == ["--dry-run"] and (entry["live_arg"] is None or entry["lane_id"] in _CANARY_WAVE)
    assert not any(token in key.upper() for key in entry["env_names"]
                   for token in ("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR", "BROKER"))
    # Real cron arguments are literal test inputs and the approved source lines are
    # committed in the runbook; deleting any argument from the entry must fail here.


def test_plan_varies_with_selected_parameters(monkeypatch, capsys):
    module = _load("watch_valuation_backfill")
    module.main(["--dry-run", "--limit", "3", "--max-age-days", "2"])
    first = capsys.readouterr().out
    module.main(["--dry-run", "--limit", "9", "--max-age-days", "5"])
    second = capsys.readouterr().out
    assert "limit=3 max_age_days=2" in first and "limit=9 max_age_days=5" in second
    assert first != second


@pytest.mark.parametrize("lane,name,argv", [SPECS[2], SPECS[3]])
def test_reported_business_failure_is_nonzero_and_keeps_prior_success(lane, name, argv, tmp_path, monkeypatch):
    path = tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    module = _load(name)
    _fake_business(module, name, [], tmp_path, monkeypatch)
    if name == "hermes_scope_governor":
        module.run = lambda **kwargs: {"ok": False, "evaluated": 3, "error": "fixture rejection"}
    else:
        sys.modules["iris_taxonomy_agent"].apply_proposal = lambda pid: {"ok": False, "error": "fixture rejection"}
    assert _invoke(module, name, argv, monkeypatch) == 1
    receipt = json.loads(path.read_bytes())
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    assert receipt["ok_at"] == "2026-10-01T00:00:00Z"


def test_packet_primary_write_failure_cannot_refresh_success(tmp_path, monkeypatch):
    lane, name, argv = SPECS[1]
    path = tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    module = _load(name)
    _fake_business(module, name, [], tmp_path, monkeypatch)
    primary = tmp_path / "packet.json"
    real_write = Path.write_text
    def write(destination, *args, **kwargs):
        if destination == primary:
            raise OSError("fixture destination unavailable")
        return real_write(destination, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", write)
    assert _invoke(module, name, argv, monkeypatch) == 1
    receipt = json.loads(path.read_bytes())
    assert receipt["ok_at"] == "2026-10-01T00:00:00Z"
    assert receipt["status"] == "failed" and receipt["summary"]["targets_written"] == 0


def test_all_failed_valuation_fetches_preserve_cached_rows_and_success(tmp_path, monkeypatch):
    lane, name, _ = SPECS[6]
    path = tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00Z"}))
    module = _load(name)
    _fake_business(module, name, [], tmp_path, monkeypatch)
    cached = {"KO": {"pe": 24, "cached_at": "2020-01-01T00:00:00+00:00", "source": "fixture"}}
    module._load = lambda source: {} if source == module.FINVIZ_CACHE else dict(cached)
    module.watch_universe = lambda: ["KO"]
    def failed_ticker(symbol):
        raise RuntimeError("fixture provider unavailable")
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=failed_ticker))
    assert module.main(["--limit", "400", "--sleep", "0"]) == 1
    assert json.loads(module.SUPPLEMENT.read_bytes()) == cached
    receipt = json.loads(path.read_bytes())
    assert receipt["ok_at"] == "2026-10-01T00:00:00Z" and receipt["status"] == "failed"
    assert receipt["summary"]["fetched"] == 0 and receipt["summary"]["errors"] == 1

from tests.test_canary_wave_20261014 import CANARY_WAVE_20261014 as _CANARY_WAVE  # noqa: E402  canary-wave-20261014
from tests.test_canary_wave_1b_20261014 import CANARY_WAVE_1B as _CANARY_WAVE_1B  # noqa: E402  canary-wave-1b-20261014
_CANARY_WAVE = {**_CANARY_WAVE, **_CANARY_WAVE_1B}
