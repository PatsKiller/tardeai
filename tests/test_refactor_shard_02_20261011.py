"""R2-02 source contracts: structural previews, exact cron argv, and durable run proof.

All real work is replaced with fakes. The archived entrypoint is from the stated
base SHA; the approved cron snapshot proves argv only, never live execution.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = json.loads((ROOT / "tests/fixtures/refactor_shard_02_cron_20261011.json").read_text())
LANES = PROOF["lanes"]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("lane", LANES, ids=lambda r: r["lane_id"])
@pytest.mark.parametrize("bad", [None, "--refactor-unknown", "--app"], ids=["dry_run", "unknown_arg", "abbreviation"])
def test_cli_never_reaches_network_secrets_or_writes(lane, bad, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "existing_receipt.json").write_text('{"ok_at":"prior"}')
    before = _snapshot(state)
    # Audit the actual script import closure as well as main(), including unknown
    # argv. Do not inherit host credentials or run a lane against the real DB.
    runner = """
import os, runpy, sys
def deny(event, args):
    if event == 'open' and str(args[0]).endswith('.env'):
        raise AssertionError('secret-file read reached from structural CLI')
    if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen'):
        raise AssertionError('network/subprocess reached from structural CLI')
    if event == 'open':
        mode = args[1]
        flags = args[2]
        if (isinstance(mode, str) and any(x in mode for x in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)):
            raise AssertionError('file write reached from structural CLI')
sys.addaudithook(deny)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    env = {
        "PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
        "TRADE_AI_CI": "1", "TRADEAI_STATE_ROOT": str(state),
        "TRADEAI_PERSISTENT_STATE_ROOT": str(state), "HOME": str(tmp_path),
    }
    args = [*lane["argv"], bad or "--dry-run"]
    proc = subprocess.run([sys.executable, "-B", "-c", runner, str(ROOT / lane["script"]), *args],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    assert proc.returncode == (2 if bad else 0), proc.stdout + proc.stderr
    if not bad:
        assert proc.stdout.startswith(f"DRY-RUN {lane['lane_id']}: would ")
        assert len(proc.stdout.splitlines()) == 1
    assert _snapshot(state) == before


def _module(lane):
    spec = importlib.util.spec_from_file_location("r202_" + lane["lane_id"].replace("-", "_"), ROOT / lane["script"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeConn:
    def __init__(self):
        self.calls = []

    def cursor(self, **_kw):
        conn = self

        class Cursor:
            def execute(self, sql, _params=None):
                conn.calls.append(" ".join(sql.split()))

            def fetchone(self):
                return (0,)

            def fetchall(self):
                return []

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        return Cursor()

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def _fake_work(module, lane, monkeypatch, failure=False):
    def fail(*_a, **_k):
        raise RuntimeError("fake-work-failure")

    monkeypatch.setattr(module, "_load_env", lambda: None, raising=False)
    name = lane["lane_id"]
    if name == "build-lesson-candidates":
        result = dict(observation_store_present=True, observations_read=2, candidates=1,
                      case_summary_support_added=0, written=1, amended=0, applied=True,
                      would_amend=[], detail=[], new_candidates=1, path="fake")
        monkeypatch.setattr(module, "run", fail if failure else lambda **_kw: result)
    elif name == "market-regime-collector":
        conn = FakeConn()
        monkeypatch.setattr(module, "_get_conn", lambda: conn)
        monkeypatch.setattr(module, "_uid", lambda *_a: "SYNTHETIC")
        monkeypatch.setattr(module, "collect_scan_based_indicators", lambda *_a: [{"indicator_key": "breadth"}])
        monkeypatch.setattr(module, "collect_market_session", lambda *_a: {"indicator_key": "session"})
        monkeypatch.setattr(module, "collect_vix", lambda *_a: None)
        monkeypatch.setattr(module, "save_indicators", fail if failure else lambda *_a, **_k: None)
    elif name == "research-intelligence-materialize":
        monkeypatch.setattr(module, "materialize", fail if failure else lambda *_a: {"ok": True, "lanes": {"top": {"ok": True}}})
    elif name == "source-outcome-attribution":
        def report(**_kw):
            out = {"sources": 2, "upserted": 2, "with_matched_trades": 1}
            print(json.dumps(out, indent=2))
            return out
        monkeypatch.setattr(module, "run", fail if failure else report)
    elif name == "sync-social-to-intelligence":
        monkeypatch.setattr(module, "resolve_universe", fail if failure else lambda: [])
    elif name == "weekly-incubator-builder":
        conn = FakeConn()
        monkeypatch.setattr(module, "_load_runtime", lambda: None)
        monkeypatch.setattr(module, "PipelineRun", lambda *_a: contextlib.nullcontext(), raising=False)
        monkeypatch.setattr(module, "get_conn", lambda: conn, raising=False)
        monkeypatch.setattr(module, "load_all_strategies", lambda: [], raising=False)
        monkeypatch.setattr(module, "load_enrichment_cache", lambda: {}, raising=False)
        monkeypatch.setattr(module, "fetch_qualifying_tickers", fail if failure else lambda *_a: [])
        monkeypatch.setattr(module, "fetch_multi_source_symbols", lambda *_a: {})
    elif name == "sec-fundamentals-ingest":
        pg = types.ModuleType("psycopg2")
        pg.extras = types.ModuleType("psycopg2.extras")
        pg.extras.RealDictCursor = object
        pg.connect = lambda **_kw: FakeConn()
        monkeypatch.setitem(sys.modules, "psycopg2", pg)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)
        import lib.fundamentals_feed as ff
        import lib.financial_senses.sec_companyfacts_reader as sec
        monkeypatch.setattr(ff, "settings", lambda: {"max_symbols_per_run": 1})
        monkeypatch.setattr(module, "universe", lambda *_a: ["SYNTHETIC"])
        monkeypatch.setattr(module, "is_fund", fail if failure else lambda *_a: True)
        monkeypatch.setattr(sec, "resolve_cik", fail)


def _call(function, argv, monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["fake_script", *argv])
    with contextlib.redirect_stdout(output):
        try:
            rc = function(argv) if "argv" in function.__code__.co_varnames[:function.__code__.co_argcount] else function()
        except (RuntimeError, SystemExit) as exc:
            rc = exc.code if isinstance(exc, SystemExit) else 1
    return (0 if rc is None else rc), output.getvalue()


@pytest.mark.parametrize("lane", LANES, ids=lambda r: r["lane_id"])
def test_exact_cron_argv_matches_archived_entrypoint(lane, monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    module = _module(lane)
    _fake_work(module, lane, monkeypatch)
    namespace = dict(module.__dict__)
    exec(compile(lane["old_entrypoint"], "archived-cron-entrypoint", "exec"), namespace)
    old = _call(namespace["main"], lane["argv"], monkeypatch)
    current = _call(module.main, lane["argv"], monkeypatch)
    assert current == old
    assert current[0] == 0


@pytest.mark.parametrize("lane", LANES, ids=lambda r: r["lane_id"])
def test_fake_real_run_receipt_failure_carries_prior_ok_at(lane, monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    module = _module(lane)
    _fake_work(module, lane, monkeypatch)
    assert _call(module.main, lane["argv"], monkeypatch)[0] == 0
    receipt = tmp_path / "data/runtime" / (lane["lane_id"] + "_last.json")
    before = json.loads(receipt.read_text())
    assert before["schema"] == "LaneRunReceipt@v1" and before["ok_at"] and before["status"] == "ok"
    assert before["summary"]
    _fake_work(module, lane, monkeypatch, failure=True)
    assert _call(module.main, lane["argv"], monkeypatch)[0] == 1
    after = json.loads(receipt.read_text())
    assert after["status"] == "failed" and after["ok_at"] == before["ok_at"] and after["exit"] == 1


# Operator ruling 2026-10-11 ("yes to all 4 for train 3"): lanes another wave already owns (SW4 in train 2, with
# operator-REVIEWED contracts) or that the train held back keep their owner's rows; shard assertions apply only to
# rows this shard actually admitted. A contract may be DRAFT or operator-REVIEWED.
def _owned_here(row, wave):
    return (row or {}).get("scheduler", {}).get("wave") == wave


def _contract_ok(contract):
    if contract.get("status") == "DRAFT":
        return "reviewer" not in contract
    review = contract.get("review") or {}
    return contract.get("status") == "REVIEWED" and "operator" in str(review.get("reviewed_by", "")).lower()


def test_registry_admission_is_shadow_only_and_contracts_are_draft():
    from scripts.lib.lane_dispatch import validate_dispatch_block
    registry = {r["lane_id"]: r for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    allow = {r["lane_id"]: r for r in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    contracts = {r["id"]: r for r in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}
    forbidden = ("ALPACA", "MOOMOO", "BROKER", "TELEGRAM", "TOKEN", "OPENAI", "DEEPSEEK", "GROK", "OAUTH")
    for lane in LANES:
        name = lane["lane_id"]
        if name not in allow or not _owned_here(registry.get(name), "R2-02"):
            continue
        if name in _CW_PROMOTED:
            continue  # 2026-10-15: promoted to canary by a cutover wave (tests/test_n8n_cutover_wave_20261015.py pins it)
        row, entry, contract = registry[name], allow[name], contracts[name]
        assert row["dispatch"]["retry_policy"] == "none"
        assert validate_dispatch_block(row, known_lane_ids=registry, retry_policy_names={"none"}) == []
        assert row["scheduler"]["kind"] == "cron" and row["scheduler"]["stage"] == "shadow"
        assert len(row["scheduler"]["expression"].split()) == 5
        assert row["scheduler"]["wave"] == "R2-02" and row["dispatch"]["wave"] == "W4"
        assert row["dispatch"]["mode"] == "dry_run"
        assert row["scheduler"]["command_text"].splitlines() == lane["cron"]
        assert entry["command"] == ["$PY", lane["script"], *lane["argv"]]
        assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] is None
        assert not any(any(word in name.upper() for word in forbidden) for name in entry["env_names"])
        assert _contract_ok(contract)
        assert contract["baseline"]["ledger_evidence_class"] == "NOT_MEASURED"
        assert contract["baseline"]["runs_considered"] is None
        assert "UNKNOWN" not in json.dumps(contract)


def test_ri_component_failure_is_not_success_and_lock_is_released(monkeypatch, tmp_path):
    lane = next(r for r in LANES if r["lane_id"] == "research-intelligence-materialize")
    module = _module(lane)
    monkeypatch.setattr(module, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(module, "SNAP_DIR", None)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=lambda *_a, **_k: []))
    import lib.research_intelligence as ri
    def build_feed(**kwargs):
        if kwargs["lane"] == "retirement":
            raise RuntimeError("synthetic-component-failure")
        return {"items": []}
    monkeypatch.setattr(ri, "build_feed", build_feed)
    monkeypatch.setitem(sys.modules, "research_intelligence_qa_lint", types.SimpleNamespace(
        known_symbol_universe=lambda *_a: set(), lint_feed=lambda *_a, **_k: {}))
    result = module.materialize(("top", "retirement"), log=lambda *_a: None)
    assert result["ok"] is False and result["lanes"]["top"]["ok"]
    assert result["lanes"]["retirement"]["ok"] is False
    assert (tmp_path / "state/data/runtime/ri_snapshots/top.json").is_file()
    # A second same-process call would lock-skip if the first leaked its flock fd.
    assert module.materialize(("top",), log=lambda *_a: None)["ok"] is True


def test_market_connection_failure_writes_failed_receipt(monkeypatch, tmp_path):
    lane = next(r for r in LANES if r["lane_id"] == "market-regime-collector")
    module = _module(lane)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "_load_env", lambda: None)
    def fail():
        raise RuntimeError("synthetic-connect-failure")
    monkeypatch.setattr(module, "_get_conn", fail)
    with pytest.raises(RuntimeError):
        module.main(["--apply"])
    receipt = json.loads((tmp_path / "data/runtime/market-regime-collector_last.json").read_text())
    assert receipt["status"] == "failed" and receipt["ok_at"] is None and receipt["exit"] == 1


def test_sec_document_failure_is_not_green(monkeypatch, tmp_path):
    lane = next(r for r in LANES if r["lane_id"] == "sec-fundamentals-ingest")
    module = _module(lane)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    _fake_work(module, lane, monkeypatch)
    import lib.fundamentals_feed as ff
    import lib.financial_senses.sec_companyfacts_reader as sec
    import lib.sec_filing_events as sfe
    monkeypatch.setattr(module, "is_fund", lambda *_a: False)
    monkeypatch.setattr(sec, "resolve_cik", lambda *_a: "0000000001")
    monkeypatch.setattr(sec, "get_company_facts", lambda *_a: {})
    monkeypatch.setattr(sec, "get_submissions", lambda *_a: {})
    monkeypatch.setattr(ff, "extract_rows", lambda *_a: [])
    monkeypatch.setattr(ff, "summarize", lambda *_a: {"latest_quarter_end": None})
    monkeypatch.setattr(ff, "freshness", lambda *_a: "NO_FACTS")
    monkeypatch.setattr(sfe, "filings_from_submissions", lambda *_a: [])
    monkeypatch.setattr(sfe, "events_from_filings", lambda *_a, **_k: [])
    monkeypatch.setattr(module, "ingest_documents", lambda *_a, **_k: {"filing_documents_error": "SyntheticError: fake"})
    assert module.main(["--apply"]) == 1
    receipt = json.loads((tmp_path / "data/runtime/sec-fundamentals-ingest_last.json").read_text())
    assert receipt["status"] == "failed" and receipt["ok_at"] is None and receipt["summary"]["failed"] == 1


@pytest.mark.parametrize("name", ["market-regime-collector", "research-intelligence-materialize", "source-outcome-attribution", "sync-social-to-intelligence"])
def test_named_loader_rejects_unrelated_secret_names(name, monkeypatch):
    module = _module(next(r for r in LANES if r["lane_id"] == name))
    fake = {"DB_HOST": "synthetic-host", "UNRELATED_SECRET_TOKEN": "synthetic-value"}
    monkeypatch.delenv("UNRELATED_SECRET_TOKEN", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(dotenv_values=lambda *_a: fake))
    module._load_env()
    assert os.environ["DB_HOST"] == "synthetic-host"
    assert "UNRELATED_SECRET_TOKEN" not in os.environ


def test_sec_named_loader_rejects_unrelated_secret_names(monkeypatch):
    module = _module(next(r for r in LANES if r["lane_id"] == "sec-fundamentals-ingest"))
    # A memory-only path fake: this test never creates or reads an env file.
    class FakeRoot:
        def __truediv__(self, _other):
            return types.SimpleNamespace(is_file=lambda: True, read_text=lambda **_k: "DB_HOST=synthetic-host\nUNRELATED_SECRET_TOKEN=synthetic-value\n")
    monkeypatch.setattr(module, "ROOT", FakeRoot())
    monkeypatch.delenv("UNRELATED_SECRET_TOKEN", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    module._load_env()
    assert os.environ["DB_HOST"] == "synthetic-host" and "UNRELATED_SECRET_TOKEN" not in os.environ


from tests.support.n8n_cutover_waves import PROMOTED as _CW_PROMOTED  # noqa: E402  2026-10-15 cutover waves
