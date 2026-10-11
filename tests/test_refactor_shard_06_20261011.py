"""Offline shard 06 previews and fake-work argv compatibility with frozen entrypoints."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    sys.path.insert(0, str(path))

EXPECTED_ARGV = {
    "finviz-market-movers": ("finviz_market_movers.py", []),
    "proposal-backtest-engine": ("proposal_backtest_engine.py", ["--all-pending", "--apply"]),
    "social-ingest-stocktwits": ("social_ingest.py", ["--source", "stocktwits", "--discover"]),
    "instrument-belief-writer": ("write_instrument_beliefs.py", ["--apply"]),
    "sec-filings-feed": ("sec_filings_feed.py", ["--apply"]),
    "trade-thesis-review-engine": ("trade_thesis_review_engine.py", ["--apply", "--json"]),
}


@pytest.mark.parametrize("lane", EXPECTED_ARGV)
def test_source_admission_retains_observed_cron_parameters_and_draft_evidence(lane):
    frozen = json.loads((ROOT / "tests/fixtures/refactor_shard_06/approved_cron_argv.json").read_text())
    observed = next(row for row in frozen["lanes"] if row["lane_id"] == lane)
    candidates = json.loads((ROOT / "docs/implementation/n8n-maturity/completion-119/candidates-04-06.json").read_text())["rows"]
    candidate = next(item for item in candidates if item["lane_id"] == lane)
    entry = candidate["allowlist_candidate"]
    row = candidate["registry_candidate"]
    contract = candidate["health_contract_candidate"]
    script, expected = EXPECTED_ARGV[lane]
    suffix = observed["cron_line"].split("scripts/" + script, 1)[1].split(">>", 1)[0].strip().rstrip('"').strip()
    assert suffix.split() == expected == observed["expected_argv"]
    assert entry["command"] == ["$PY", "scripts/" + script, *expected]
    # Each actual argument is required; omission must differ from the approved command.
    for index in range(len(expected)):
        assert entry["command"] != ["$PY", "scripts/" + script, *expected[:index], *expected[index + 1:]]
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] is None
    assert entry["lock"] == observed["lock"] and entry["lock_kind"] == "flock"
    assert entry["env_allowlist_mode"] == "report" and entry["env_report_reason"]
    assert not any(any(word in name.upper() for word in ("MOOMOO", "ALPACA", "BROKER", "IBKR"))
                   for name in entry["env_names"])
    assert row["scheduler"]["command_text"] == observed["cron_line"]
    assert row["scheduler"]["stage"] == "shadow" and row["scheduler"]["wave"] == "R2-06"
    assert row["dispatch"]["mode"] == "dry_run" and row["dispatch"]["wave"] == "W4"
    assert row["dispatch"]["class"] in {"ingest", "learn"} and row["dispatch"]["retry_policy"] == "none"
    assert row["dispatch"]["cron"] == [" ".join(observed["cron_line"].split()[:5])]
    if lane == "social-ingest-stocktwits":
        assert row["scheduler"]["match"] == "scripts/social_ingest.py --source stocktwits --discover"
        assert row["scheduler"]["match"] not in "scripts/social_ingest.py --source stocktwits --scalp-list"
    assert row["output_signal"]["path"] == f"data/runtime/{lane}_last.json"
    assert contract["status"] == "DRAFT" and not contract.get("reviewed_by")
    assert contract["baseline"]["basis"] == "CLASS_DEFAULT_PROVISIONAL"
    assert contract["baseline"]["evidence_class"] == "SOURCE_ONLY"
    assert contract["baseline"]["ledger"] == "NOT_MEASURED" and contract["baseline"]["runs_considered"] is None
    assert contract["evidence"]["runtime"] == "NOT_MEASURED"
    assert "NOT_MEASURED" in contract["evidence"]["never"]






@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_WAKE_STATE_ROOT", str(tmp_path / "wake"))
    return tmp_path


def load_script(name):
    spec = importlib.util.spec_from_file_location("shard06_" + name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def legacy_main(mod, script):
    frozen = json.loads((ROOT / "tests/fixtures/refactor_shard_06/legacy_entrypoints.json").read_text())
    namespace = dict(vars(mod))
    exec(compile(frozen[script + ".py"], "frozen-shard06-old-entrypoint", "exec"), namespace)

    def run(argv):
        previous = sys.argv
        sys.argv = [script + ".py", *argv]
        try:
            if script in {"proposal_backtest_engine", "social_ingest", "write_instrument_beliefs", "sec_filings_feed"}:
                return namespace["main"](argv)
            return namespace["main"]()
        finally:
            sys.argv = previous

    return run


class FixedTime:
    @staticmethod
    def now(tz=None):
        value = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)
        return value if tz else value.replace(tzinfo=None)


class FakeConnection:
    def __init__(self, rows=()):
        self.calls = []
        self.rows = rows

    def cursor(self, *a, **k):
        self.calls.append("cursor")
        return self

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return list(self.rows)

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def fake_finviz(mod, state, monkeypatch):
    conn = FakeConnection()
    db = types.ModuleType("db_adapter")
    db._get_conn = lambda: conn
    monkeypatch.setitem(sys.modules, "db_adapter", db)
    auth = types.ModuleType("finviz_auth")
    auth.finviz_secret = lambda name: "synthetic fixture"
    auth.redact = lambda text, *args: str(text)
    monkeypatch.setitem(sys.modules, "finviz_auth", auth)
    mod._cookie = lambda: "synthetic fixture"
    mod.datetime = FixedTime
    mod.SNAP = state / "market_movers_latest.json"
    mod._fetch_signal = lambda *a: [{"symbol": "TEST", "company": "Fixture", "sector": "Other", "last": 2,
                                   "change_pct": 1, "volume": 10}]
    return conn


def test_finviz_dry_run_has_no_auth_database_network_or_write(state, capsys):
    mod = load_script("finviz_market_movers")
    mod._execute = lambda: pytest.fail("preview reached business work")
    before = snapshot(state)
    assert mod.main(["--dry-run"]) == 0
    assert snapshot(state) == before
    assert "DRY-RUN finviz-market-movers: would fetch 10" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry", "--dry-rn", "--unknown"])
def test_finviz_unknown_flag_exits_two_before_work(state, flag):
    mod = load_script("finviz_market_movers")
    mod._execute = lambda: pytest.fail("usage reached business work")
    with pytest.raises(SystemExit) as exc:
        mod.main([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_finviz_frozen_cron_argv_and_receipt(state, monkeypatch, capsys):
    mod = load_script("finviz_market_movers")
    conn = fake_finviz(mod, state, monkeypatch)
    assert legacy_main(mod, "finviz_market_movers")([]) == 0
    old_calls, old_stdout = list(conn.calls), capsys.readouterr().out
    old_snapshot = mod.SNAP.read_bytes()
    conn.calls.clear()
    assert mod.main([]) == 0
    assert conn.calls == old_calls
    assert capsys.readouterr().out == old_stdout
    assert mod.SNAP.read_bytes() == old_snapshot
    receipt = json.loads((state / "data/runtime/finviz-market-movers_last.json").read_text())
    assert receipt["status"] == "ok" and receipt["ok_at"]
    assert receipt["summary"] == {"signals": 10, "rows": 10, "errors": 0}
    previous = receipt["ok_at"]
    mod._execute = lambda: 1
    assert mod.main([]) == 1
    failed = json.loads((state / "data/runtime/finviz-market-movers_last.json").read_text())
    assert failed["status"] == "failed" and failed["ok_at"] == previous and failed["exit"] == 1


def test_proposal_preview_is_offline_and_preserves_parameters(state, capsys):
    mod = load_script("proposal_backtest_engine")
    mod.get_conn = lambda: pytest.fail("preview reached database")
    argv = ["--all-pending", "--strategy", "fixture", "--limit", "3", "--statuses", "EXPIRED", "--apply", "--dry-run"]
    assert mod.cli(argv) == 0 and snapshot(state) == {}
    out = capsys.readouterr().out
    assert "strategy=fixture statuses=EXPIRED limit=3" in out


@pytest.mark.parametrize("flag", ["--dry", "--dry-rn", "--unknown"])
def test_proposal_unknown_flags_exit_two(state, flag):
    mod = load_script("proposal_backtest_engine")
    mod.get_conn = lambda: pytest.fail("usage reached database")
    with pytest.raises(SystemExit) as exc:
        mod.cli(["--all-pending", flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_proposal_frozen_live_argv_and_failure_receipt(state, capsys):
    mod = load_script("proposal_backtest_engine")
    conn = FakeConnection(rows=[(11,)])
    mod.get_conn = lambda: conn
    mod.datetime = FixedTime
    calls = []

    def backtest(c, pid, persist=True):
        calls.append((pid, persist))
        return {"symbol": "TEST", "backtest_quality": "low_sample", "sample_size": 3, "persisted": True}

    mod.backtest_proposal = backtest
    mod._write_strategy_backtest_result = lambda c, result: True
    argv = ["--all-pending", "--apply"]
    assert legacy_main(mod, "proposal_backtest_engine")(argv) == 0
    old_calls, old_sql, old_stdout = list(calls), list(conn.calls), capsys.readouterr().out
    calls.clear()
    conn.calls.clear()
    assert mod.cli(argv) == 0
    assert calls == old_calls and conn.calls == old_sql and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/proposal-backtest-engine_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["ok_at"] and receipt["status"] == "ok" and receipt["summary"]["processed"] == 1
    mod._write_strategy_backtest_result = lambda c, result: False
    assert mod.cli(argv) == 1
    failed = json.loads(path.read_text())
    assert failed["ok_at"] == receipt["ok_at"] and failed["status"] == "failed" and failed["exit"] == 1








def test_social_preview_and_unknown_flags_before_holdings_or_db(state, capsys):
    mod = load_script("social_ingest")
    mod.main = lambda argv: pytest.fail("preview reached social work")
    assert mod.cli(["--source", "stocktwits", "--discover", "--dry-run"]) == 0
    assert snapshot(state) == {}
    assert "discover=True" in capsys.readouterr().out
    for flag in ("--dry", "--dry-rn", "--unknown"):
        with pytest.raises(SystemExit) as exc:
            mod.cli(["--source", "stocktwits", "--discover", flag])
        assert exc.value.code == 2


def test_social_frozen_exact_cron_argv_and_receipt(state, monkeypatch, capsys):
    mod = load_script("social_ingest")
    calls = []
    pipeline = types.ModuleType("pipeline_registry")
    pipeline.run_start = lambda name: calls.append(("start", name)) or "fake-run"
    pipeline.run_complete = lambda *a, **k: calls.append(("complete", a, k))
    pipeline.run_fail = lambda *a, **k: calls.append(("fail", a, k))
    monkeypatch.setitem(sys.modules, "pipeline_registry", pipeline)
    result = {"inserted": 2, "skipped": 1, "errors": []}
    mod.ingest_stocktwits_discovery = lambda: calls.append("discover") or result
    argv = ["--source", "stocktwits", "--discover"]
    assert legacy_main(mod, "social_ingest")(argv) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.cli(argv) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/social-ingest-stocktwits_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["ok_at"] and receipt["summary"]["rows_produced"] == 2
    mod.ingest_stocktwits_discovery = lambda: {"inserted": 0, "skipped": 0, "errors": ["fake unavailable"]}
    assert mod.cli(argv) == 1
    failed = json.loads(path.read_text())
    assert failed["status"] == "failed" and failed["ok_at"] == receipt["ok_at"] and failed["exit"] == 1


def test_belief_preview_and_unknown_flag_do_not_reach_cognition_writer(state, capsys):
    mod = load_script("write_instrument_beliefs")
    mod._execute = lambda argv: pytest.fail("preview reached cognition writer")
    assert mod.main(["--apply", "--dry-run"]) == 0 and snapshot(state) == {}
    assert "existing behavior rail" in capsys.readouterr().out
    for flag in ("--dry", "--dry-rn", "--unknown"):
        with pytest.raises(SystemExit) as exc:
            mod.main(["--apply", flag])
        assert exc.value.code == 2


def test_belief_frozen_exact_cron_argv_and_receipt(state, capsys):
    mod = load_script("write_instrument_beliefs")
    calls = []
    result = {"settled_rows": 2, "groups": 1, "written_beliefs": 1, "would_write_beliefs": 1,
              "noop": 0, "refused": 0, "subjects_written": 1, "skipped": 0, "store": "synthetic"}

    def work(root, **kwargs):
        calls.append((str(root), kwargs))
        return result

    mod.update_beliefs_from_settled = work
    argv = ["--apply"]
    assert legacy_main(mod, "write_instrument_beliefs")(argv) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main(argv) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/instrument-belief-writer_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["ok_at"] and receipt["summary"]["written_beliefs"] == 1
    mod.update_beliefs_from_settled = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fake unavailable"))
    with pytest.raises(RuntimeError):
        mod.main(argv)
    failed = json.loads(path.read_text())
    assert failed["status"] == "failed" and failed["ok_at"] == receipt["ok_at"] and failed["exit"] == 1


def test_sec_feed_preview_precedes_cache_identity_network_and_state(state, capsys):
    mod = load_script("sec_filings_feed")
    mod._execute = lambda argv: pytest.fail("preview reached SEC fetch/cache")
    assert mod.main(["--apply", "--limit", "4", "--since-days", "3", "--dry-run"]) == 0
    assert snapshot(state) == {}
    out = capsys.readouterr().out
    assert "up to 4 symbols" in out and "3 days" in out
    for flag in ("--dry", "--dry-rn", "--unknown"):
        with pytest.raises(SystemExit) as exc:
            mod.main(["--apply", flag])
        assert exc.value.code == 2


def test_sec_feed_frozen_exact_cron_argv_and_receipt(state, monkeypatch, capsys):
    mod = load_script("sec_filings_feed")
    calls = []
    mod._now = lambda: FixedTime.now(timezone.utc)
    mod.universe = lambda root, limit: calls.append(("universe", limit)) or ["TEST"]
    mod.load_ticker_map = lambda root, fetcher, **k: calls.append("ticker_map") or {"TEST": "0000000001"}
    package = types.ModuleType("financial_senses")
    sec = types.ModuleType("financial_senses.sec_companyfacts_reader")
    sec._default_fetcher = lambda url: {}
    sec.get_submissions = lambda *a: calls.append("submissions") or {}
    package.sec_companyfacts_reader = sec
    monkeypatch.setitem(sys.modules, "financial_senses", package)
    ic = types.ModuleType("intelligence_client")
    ic.default_loaders = lambda root, env: types.SimpleNamespace(resolve_subject=lambda sym: {"guid": "fixture-guid"})
    monkeypatch.setitem(sys.modules, "intelligence_client", ic)
    sfe = types.ModuleType("sec_filing_events")
    sfe.filings_from_submissions = lambda *a: []
    monkeypatch.setitem(sys.modules, "sec_filing_events", sfe)
    # No fresh event is an honest no-new-work day; all canonical artifacts still advance.
    mod.events_from_filings = lambda *a, **k: []
    hb = types.ModuleType("supervisor_heartbeat")
    hb.beat = lambda *a, **k: calls.append(("heartbeat", k["work_claimed"], k["work_done"])) or {"pg": None}
    monkeypatch.setitem(sys.modules, "supervisor_heartbeat", hb)
    db = types.ModuleType("db_adapter")
    db._get_conn = lambda: None
    monkeypatch.setitem(sys.modules, "db_adapter", db)
    argv = ["--apply"]
    assert legacy_main(mod, "sec_filings_feed")(argv) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    old_latest = (state / "data/runtime/sec_filings_feed_latest.json").read_bytes()
    calls.clear()
    assert mod.main(argv) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    assert (state / "data/runtime/sec_filings_feed_latest.json").read_bytes() == old_latest
    path = state / "data/runtime/sec-filings-feed_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["ok_at"] and receipt["summary"]["fetched"] == 1 and receipt["summary"]["new"] == 0
    mod._execute = lambda argv: 2
    assert mod.main(argv) == 2
    failed = json.loads(path.read_text())
    assert failed["status"] == "failed" and failed["ok_at"] == receipt["ok_at"] and failed["exit"] == 2


def test_thesis_preview_and_unknown_flags_before_database(state, capsys):
    mod = load_script("trade_thesis_review_engine")
    mod._execute = lambda: pytest.fail("preview reached DB")
    assert mod.main(["--apply", "--json", "--dry-run"]) == 0 and snapshot(state) == {}
    assert "historical trades" in capsys.readouterr().out
    for flag in ("--dry", "--dry-rn", "--unknown"):
        with pytest.raises(SystemExit) as exc:
            mod.main(["--apply", "--json", flag])
        assert exc.value.code == 2


def test_thesis_frozen_exact_cron_argv_and_receipt(state, capsys):
    mod = load_script("trade_thesis_review_engine")
    calls = []
    conn = FakeConnection()
    mod._get_conn = lambda: conn
    mod.get_reviewable = lambda c, **k: calls.append(("load", k)) or [{"id": 11}]
    mod.review = lambda c, trade: {"thesis_validity": "held", "review_id": "fixture", "symbol": "TEST"}
    mod.save = lambda c, rows, **k: calls.append(("save", list(rows), k))
    argv = ["--apply", "--json"]
    assert legacy_main(mod, "trade_thesis_review_engine")(argv) is None
    old_calls, old_conn, old_stdout = list(calls), list(conn.calls), capsys.readouterr().out
    calls.clear()
    conn.calls.clear()
    assert mod.main(argv) == 0
    assert calls == old_calls and conn.calls == old_conn and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/trade-thesis-review-engine_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["ok_at"] and receipt["summary"]["trades_reviewed"] == 1
    mod.save = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fake persist failure"))
    with pytest.raises(RuntimeError):
        mod.main(argv)
    failed = json.loads(path.read_text())
    assert failed["status"] == "failed" and failed["ok_at"] == receipt["ok_at"] and failed["exit"] == 1
