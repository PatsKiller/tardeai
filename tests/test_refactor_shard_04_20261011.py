"""Shard 04 previews are offline; live compatibility is exercised with fake work only."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def load_script(name):
    spec = importlib.util.spec_from_file_location("shard04_" + name, ROOT / "scripts" / (name + ".py"))
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


def legacy_main(mod, script, replacements):
    fixtures = json.loads((ROOT / "tests/fixtures/refactor_shard_04/legacy_entrypoints.json").read_text())
    namespace = dict(vars(mod))
    namespace.update(replacements)
    exec(compile(fixtures[script], "frozen-pre-refactor-main", "exec"), namespace)
    def run(argv):
        previous = sys.argv
        try:
            return namespace.get("cli", namespace["main"])(argv)
        finally:
            sys.argv = previous
    return run


def fake_identity_work(mod):
    calls = []

    class Conn:
        def cursor(self):
            calls.append("cursor")
            return object()

        def commit(self):
            calls.append("commit")

        def close(self):
            calls.append("close")

    def db():
        calls.append("connect")
        return Conn()

    def backfill(cur, table, symbol_col, *, apply, limit):
        calls.append((table, symbol_col, apply, limit))
        return {"table": table, "symbols_seen": 1, "resolved": 1,
                "unresolved": 0, "not_applicable": 0, "rows_stamped": 1}

    replacements = {"_db": db, "backfill": backfill,
                    "classify_remainder": lambda *a, **k: {}, "add_columns": lambda *a, **k: []}
    for name, value in replacements.items():
        setattr(mod, name, value)
    return replacements, calls


def test_identity_preview_rejects_prior_database_reach(state, capsys):
    mod = load_script("backfill_subject_identity")
    calls = []

    def forbidden():
        calls.append("database")
        raise AssertionError("preview reached credential/DB boundary")

    mod._db = forbidden
    old = legacy_main(mod, "backfill_subject_identity.py", {"_db": forbidden})
    assert old(["--all", "--apply", "--dry-run"]) != 0
    assert calls == ["database"]  # reproduces the previous defect, with no actual DB/secret access
    calls.clear()
    before = snapshot(state)
    assert mod.main(["--all", "--apply", "--dry-run"]) == 0
    assert calls == [] and snapshot(state) == before
    assert "DRY-RUN identity-sweep-stage0: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_identity_unknown_flags_exit_two_before_work(state, flag):
    mod = load_script("backfill_subject_identity")
    mod._db = lambda: pytest.fail("usage error reached database")
    with pytest.raises(SystemExit) as exc:
        mod.main(["--all", flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_identity_cron_argv_matches_frozen_entrypoint_and_writes_receipt(state, capsys):
    mod = load_script("backfill_subject_identity")
    replacements, calls = fake_identity_work(mod)
    old = legacy_main(mod, "backfill_subject_identity.py", replacements)
    argv = ["--all", "--apply"]
    assert old(argv) == 0
    old_calls = list(calls)
    old_stdout = capsys.readouterr().out
    path = state / "data/runtime/identity-sweep-stage0_last.json"
    old_receipt = json.loads(path.read_text())
    calls.clear()
    assert mod.main(argv) == 0
    new_receipt = json.loads(path.read_text())
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    assert new_receipt["status"] == "ok" and new_receipt["ok_at"]
    assert new_receipt["summary"] == old_receipt["summary"]


def test_identity_failure_preserves_previous_ok_at_and_exit(state):
    mod = load_script("backfill_subject_identity")
    fake_identity_work(mod)
    assert mod.main(["--all", "--apply"]) == 0
    path = state / "data/runtime/identity-sweep-stage0_last.json"
    previous = json.loads(path.read_text())["ok_at"]

    def failure():
        raise RuntimeError("fake database unavailable")

    mod._db = failure
    with pytest.raises(RuntimeError):
        mod.main(["--all", "--apply"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    assert receipt["ok_at"] == previous


def test_shard04_allowlist_does_not_carry_broker_names():
    entries = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]
    rows = json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
    own = {r["lane_id"] for r in rows if r.get("scheduler", {}).get("wave") == "R2-04"}
    assert own
    for entry in entries:
        if entry["lane_id"] not in own:
            continue
        assert entry["live_arg"] is None or entry["lane_id"] in _CANARY_WAVE
        assert entry["dry_run_arg"] == ["--dry-run"]
        assert not any(any(token in name.upper() for token in
                           ("ALPACA", "SCHWAB", "MOOMOO", "BROKER", "IBKR", "ROBINHOOD"))
                       for name in entry["env_names"])


def fake_hermes_work(mod):
    calls = []

    def candidates(max_tickers, *, read_errors=None):
        calls.append(("candidates", max_tickers))
        return ["TEST"]

    def research(candidates, **kwargs):
        calls.append((tuple(candidates), kwargs))
        return [{"source_count": 2, "catalyst_type": "earnings"}]

    replacements = {"_load_env": lambda: None, "_hot_research_on": lambda: False,
                    "get_scalp_candidates": candidates, "run": research}
    for name, value in replacements.items():
        setattr(mod, name, value)
    return replacements, calls


def test_hermes_preview_stops_prior_paid_search_path(state, capsys):
    mod = load_script("hermes_momentum_catalyst_researcher")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("candidate/search boundary")
        raise AssertionError("preview reached live dependency")

    replacements = {"_load_env": forbidden, "_hot_research_on": lambda: False,
                    "get_scalp_candidates": forbidden}
    for name, value in replacements.items():
        setattr(mod, name, value)
    old = legacy_main(mod, "hermes_momentum_catalyst_researcher.py", replacements)
    with pytest.raises(AssertionError):
        old(["--source", "scalp", "--apply", "--dry-run"])
    calls.clear()
    before = snapshot(state)
    assert mod.main(["--source", "scalp", "--apply", "--dry-run"]) == 0
    assert not calls and snapshot(state) == before
    assert "DRY-RUN hermes-momentum-catalyst-scalp: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_hermes_unknown_flags_exit_two(state, flag):
    mod = load_script("hermes_momentum_catalyst_researcher")
    mod._load_env = lambda: pytest.fail("unknown flag reached credential boundary")
    with pytest.raises(SystemExit) as exc:
        mod.main(["--source", "scalp", flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_hermes_cron_argv_matches_old_entrypoint_and_receipts(state, capsys):
    mod = load_script("hermes_momentum_catalyst_researcher")
    replacements, calls = fake_hermes_work(mod)
    old = legacy_main(mod, "hermes_momentum_catalyst_researcher.py", replacements)
    assert old(["--source", "scalp", "--apply"]) is None
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main(["--source", "scalp", "--apply"]) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/hermes-momentum-catalyst-scalp_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["ok_at"]
    assert receipt["summary"]["tickers"] == 1 and receipt["summary"]["sources"] == 2
    previous = receipt["ok_at"]

    def failure(args):
        raise RuntimeError("fake research unavailable")

    mod._execute = failure
    with pytest.raises(RuntimeError):
        mod.main(["--source", "scalp", "--apply"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    assert receipt["ok_at"] == previous


def test_aegis_preview_rejects_previous_database_reach(state, capsys):
    mod = load_script("aegis_transcript_discovery")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("corpus/credentials")
        raise AssertionError("preview reached database boundary")

    mod.main = forbidden
    old = legacy_main(mod, "aegis_transcript_discovery.py", {"main": forbidden})
    with pytest.raises(AssertionError):
        old(["--dry-run"])
    calls.clear()
    before = snapshot(state)
    assert mod.cli(["--dry-run"]) == 0
    assert calls == [] and snapshot(state) == before
    assert "DRY-RUN aegis-transcript-discovery: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_aegis_unknown_flags_exit_two(state, flag):
    mod = load_script("aegis_transcript_discovery")
    mod.main = lambda *a, **k: pytest.fail("usage error reached work")
    with pytest.raises(SystemExit) as exc:
        mod.cli([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_aegis_original_cron_argv_and_failure_receipt(state, capsys):
    mod = load_script("aegis_transcript_discovery")
    calls = []

    def fake_work():
        calls.append("transcript/discovery")
        print("fake transcript run")
        return {"transcripts": 2, "discovery": 1, "youtube": 2, "articles": 0, "to_write": 3}

    mod.main = fake_work
    old = legacy_main(mod, "aegis_transcript_discovery.py", {"main": fake_work})
    assert old([]) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.cli([]) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/aegis-transcript-discovery_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["summary"]["transcripts"] == 2
    previous = receipt["ok_at"]
    mod.main = lambda: {"error": "db_unavailable"}
    assert mod.cli([]) == 1
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous


def test_candidate_preview_rejects_old_corpus_access(state, capsys):
    mod = load_script("candidate_discovery_orchestrator")
    calls = []

    def forbidden(args):
        calls.append("corpus")
        raise AssertionError("dry run reached corpus")

    mod._dry_run = forbidden
    old = legacy_main(mod, "candidate_discovery_orchestrator.py", {"_dry_run": forbidden})
    with pytest.raises(AssertionError):
        old(["--apply", "--dry-run"])
    calls.clear()
    assert mod.main(["--apply", "--dry-run"]) == 0
    assert calls == [] and snapshot(state) == {}
    assert "DRY-RUN candidate-discovery-orchestrator: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_candidate_unknown_flags_exit_two(state, flag):
    mod = load_script("candidate_discovery_orchestrator")
    mod._dry_run = lambda *a: pytest.fail("unknown flag reached corpus")
    with pytest.raises(SystemExit) as exc:
        mod.main([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_candidate_original_cron_argv_and_receipt(state, monkeypatch, capsys):
    import types
    mod = load_script("candidate_discovery_orchestrator")
    calls = []

    class Conn:
        def close(self):
            calls.append("close")

    report = types.ModuleType("lib.data_source_report")
    report.report_source = lambda *a, **k: calls.append(("source", a, k))
    monkeypatch.setitem(sys.modules, "lib.data_source_report", report)
    replacements = {"_get_conn": lambda: Conn(), "_all_sources": lambda: ["fake-source"],
                    "_poll": lambda *a, **k: ([{"symbol": "TEST"}], {"news_catalyst": 1}, {}, []),
                    "_record_events": lambda *a, **k: 1}
    for name, value in replacements.items():
        setattr(mod, name, value)
    old = legacy_main(mod, "candidate_discovery_orchestrator.py", replacements)
    assert old(["--apply"]) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main(["--apply"]) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/candidate-discovery-orchestrator_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["summary"]["recorded"] == 1
    previous = receipt["ok_at"]

    def failure():
        raise RuntimeError("fake corpus unavailable")

    mod._get_conn = failure
    with pytest.raises(RuntimeError):
        mod.main(["--apply"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous


def test_finviz_preview_rejects_prior_paid_fetch(state, capsys):
    mod = load_script("finviz_proactive_research")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("fetch")
        raise AssertionError("preview reached paid fetch")

    mod.run = forbidden
    mod._load_env = forbidden
    old = legacy_main(mod, "finviz_proactive_research.py", {"run": forbidden})
    with pytest.raises(AssertionError):
        old(["--dry-run"])
    calls.clear()
    assert mod.main(["--dry-run"]) == 0
    assert calls == [] and snapshot(state) == {}
    assert "DRY-RUN finviz-proactive-research: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_finviz_unknown_flag_exit_two(state, flag):
    mod = load_script("finviz_proactive_research")
    mod._load_env = lambda: pytest.fail("usage error reached credentials")
    with pytest.raises(SystemExit) as exc:
        mod.main([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


@pytest.mark.parametrize("argv", [[], ["--max", "400", "--lookback-hours", "12"]])
def test_finviz_cron_argv_fake_receipt_and_soft_error(state, capsys, argv):
    mod = load_script("finviz_proactive_research")
    calls = []
    result = {"failed_writes": 0, "saved": 2}

    def run(max_n, lookback_hours, dry_run, summary=None):
        calls.append((max_n, lookback_hours, dry_run))
        if summary is not None:
            summary.update(result)
        print("fake Finviz ingestion")
        return 0

    mod.run = run
    mod._load_env = lambda: None
    old = legacy_main(mod, "finviz_proactive_research.py", {"run": run})
    with pytest.raises(SystemExit) as exc:
        old(argv)
    assert exc.value.code == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main(argv) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/finviz-proactive-research_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["summary"]["saved"] == 2
    previous = receipt["ok_at"]
    result.update(failed_writes=1, saved=0)
    assert mod.main(argv) == 0  # established soft-failure exit is preserved
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 0 and receipt["ok_at"] == previous


def test_scorecard_preview_rejects_old_database_and_host_access(state, capsys):
    mod = load_script("hermes_discovery_scorecard")
    calls = []

    def forbidden():
        calls.append("database/host")
        raise AssertionError("preview reached live dependency")

    mod._readonly_db_session = forbidden
    mod._db_available = forbidden
    old = legacy_main(mod, "hermes_discovery_scorecard.py", {"_readonly_db_session": forbidden})
    with pytest.raises(AssertionError):
        old(["--dry-run"])
    calls.clear()
    assert mod.main(["--dry-run"]) == 0
    assert calls == [] and snapshot(state) == {}
    assert "DRY-RUN hermes-discovery-scorecard: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_scorecard_unknown_flags_exit_two(state, flag):
    mod = load_script("hermes_discovery_scorecard")
    mod._db_available = lambda: pytest.fail("usage error reached database")
    with pytest.raises(SystemExit) as exc:
        mod.main([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_scorecard_cron_argv_and_failure_receipt(state, capsys):
    mod = load_script("hermes_discovery_scorecard")
    calls = []
    card = {"totals": {"candidates": 3}, "intake": {"new_candidates_7d": 2},
            "do_no_harm": {"recommendation": "steady"}}
    replacements = {"_db_available": lambda: True, "build_scorecard": lambda: card,
                    "_atomic_write": lambda path, value: calls.append((str(path), value)),
                    "write_outcome_feed": lambda value: "fake-feed"}
    for name, value in replacements.items():
        setattr(mod, name, value)
    old = legacy_main(mod, "hermes_discovery_scorecard.py", replacements)
    assert old([]) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main([]) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/hermes-discovery-scorecard_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["summary"]["candidates_total"] == 3
    previous = receipt["ok_at"]
    mod._db_available = lambda: False
    assert mod.main([]) == 1
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous


def test_agenda_preview_rejects_prior_database_reach(state, capsys):
    mod = load_script("hermes_research_agenda")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("agenda/database")
        raise AssertionError("preview reached corpus")

    mod.run_agenda = forbidden
    old = legacy_main(mod, "hermes_research_agenda.py", {"run_agenda": forbidden})
    with pytest.raises(AssertionError):
        old(["--apply", "--json", "--dry-run"])
    calls.clear()
    assert mod.main(["--apply", "--json", "--dry-run"]) == 0
    assert calls == [] and snapshot(state) == {}
    assert "DRY-RUN hermes-research-agenda-at-45-7: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_agenda_unknown_flags_exit_two(state, flag):
    mod = load_script("hermes_research_agenda")
    mod.run_agenda = lambda *a, **k: pytest.fail("unknown flag reached DB")
    with pytest.raises(SystemExit) as exc:
        mod.main([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_agenda_cron_argv_and_failure_receipts(state, capsys):
    mod = load_script("hermes_research_agenda")
    calls = []
    result = {"status": "ok", "creates": 1, "retires": 0, "boosts": 0, "candidates_found": 2}

    def run_agenda(**kwargs):
        calls.append(kwargs)
        return dict(result)

    mod.run_agenda = run_agenda
    old = legacy_main(mod, "hermes_research_agenda.py", {"run_agenda": run_agenda})
    assert old(["--apply", "--json"]) is None
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main(["--apply", "--json"]) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/hermes-research-agenda-at-45-7_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["summary"]["creates"] == 1
    previous = receipt["ok_at"]
    result.update(status="blocked", reason="HERMES_DISABLED", creates=0)
    assert mod.main(["--apply", "--json"]) == 0
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 0 and receipt["ok_at"] == previous

    def failure(**kwargs):
        raise RuntimeError("fake agenda database failure")

    mod.run_agenda = failure
    with pytest.raises(RuntimeError):
        mod.main(["--apply", "--json"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous


def test_pool_preview_rejects_old_worker_access(state, capsys):
    import types
    mod = load_script("hermes_research_worker_pool")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("pool/database")
        raise AssertionError("preview reached live pool")

    pool = types.SimpleNamespace(run_pool=forbidden)
    mod.worker_pool = pool
    mod._load_dependencies = forbidden
    old = legacy_main(mod, "hermes_research_worker_pool.py", {"worker_pool": pool})
    with pytest.raises(AssertionError):
        old(["--run", "--json", "--dry-run"])
    calls.clear()
    assert mod.main(["--run", "--json", "--dry-run"]) == 0
    assert calls == [] and snapshot(state) == {}
    assert "DRY-RUN hermes-research-worker-pool: would" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-rn", "--dry", "--unknown"])
def test_pool_unknown_flags_exit_two(state, flag):
    mod = load_script("hermes_research_worker_pool")
    mod._load_dependencies = lambda: pytest.fail("usage error imported live worker dependencies")
    with pytest.raises(SystemExit) as exc:
        mod.main([flag])
    assert exc.value.code == 2 and snapshot(state) == {}


def test_pool_cron_argv_receipts_and_incomplete_pool(state, capsys):
    import types
    mod = load_script("hermes_research_worker_pool")
    calls = []
    report = {"lanes": {"research": {"scanned": 2, "upserted": 1}},
              "lane_outcomes": {"research": {"outcome": "produced", "ok": True}},
              "failures": [], "ok": True}

    def run_pool(*args, **kwargs):
        calls.append((args, kwargs))
        return report

    pool = types.SimpleNamespace(run_pool=run_pool)
    mod.worker_pool = pool
    mod._load_dependencies = lambda: None
    old = legacy_main(mod, "hermes_research_worker_pool.py", {"worker_pool": pool})
    assert old(["--run", "--json"]) == 0
    old_calls, old_stdout = list(calls), capsys.readouterr().out
    calls.clear()
    assert mod.main(["--run", "--json"]) == 0
    assert calls == old_calls and capsys.readouterr().out == old_stdout
    path = state / "data/runtime/hermes-research-worker-pool_last.json"
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "ok" and receipt["summary"]["upserted"] == 1
    assert receipt["summary"]["lane_outcomes"] == {"research": "produced"}
    previous = receipt["ok_at"]
    # 2026-10-15 intentional change (hermes-worker-pool-wire): an enabled lane
    # with no runner used to exit 0 with a failed receipt; it is now a lane
    # FAILURE — exit 3, receipt failed, ok_at preserved.
    report.update(lanes={"research": {"skipped": "no_runner"}},
                  lane_outcomes={"research": {"outcome": "no_runner", "ok": False}},
                  failures=[{"lane": "research", "outcome": "no_runner", "reason": "x"}],
                  ok=False)
    assert mod.main(["--run", "--json"]) == 3
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 3 and receipt["ok_at"] == previous
    assert receipt["summary"]["failures"] == [{"lane": "research", "outcome": "no_runner"}]
    # a report without an ok verdict is never healthy (fail closed)
    report.update(lanes={"research": {"scanned": 1}}, lane_outcomes={}, failures=[])
    report.pop("ok")
    assert mod.main(["--run", "--json"]) == 3
    report.update(error="fake pool failure")
    assert mod.main(["--run", "--json"]) == 1
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous


def test_hermes_read_failure_does_not_publish_empty_success(state):
    mod = load_script("hermes_momentum_catalyst_researcher")
    fake_hermes_work(mod)
    assert mod.main(["--source", "scalp", "--apply"]) == 0
    path = state / "data/runtime/hermes-momentum-catalyst-scalp_last.json"
    previous = json.loads(path.read_text())["ok_at"]

    def failed_read(max_tickers, *, read_errors=None):
        read_errors.append("OperationalError")
        return []

    mod.get_scalp_candidates = failed_read
    assert mod.main(["--source", "scalp", "--apply"]) == 0
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 0
    assert receipt["ok_at"] == previous and receipt["summary"]["candidate_read_failures"] == 1


def test_shard04_dispatch_rows_obey_current_policy_and_lock_proof():
    from scripts.lib.lane_dispatch import validate_dispatch_block
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    allow = {r["lane_id"]: r for r in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    own = [r for r in reg["lanes"] if r.get("scheduler", {}).get("wave") == "R2-04"]
    # Train 3: 8 R2-04 proposals - 2 already onboarded by SW4 (identity-sweep-stage0, aegis-transcript-discovery;
    # train 2's rows kept) - 2 held off the dispatcher (candidate-discovery-orchestrator, hermes-discovery-scorecard;
    # pinned EXCLUDED by tests/test_sw4_shadow_wave4_20261011.py) = 4.
    assert len(own) == 4
    for row in own:
        assert validate_dispatch_block(row) == []
        assert row["dispatch"]["retry_policy"] == "none"
        assert row["output_signal"]["path"] == allow[row["lane_id"]]["output_signal"]
        assert (row["scheduler"]["stage"], row["dispatch"]["mode"]) in (
            {("shadow", "dry_run"), ("canary", "live")} if row["lane_id"] in _CANARY_WAVE else {("shadow", "dry_run")}
        )


@pytest.mark.parametrize("script,args", [
    ("backfill_subject_identity", ["--all", "--apply"]),
    ("hermes_momentum_catalyst_researcher", ["--source", "scalp", "--apply"]),
    ("aegis_transcript_discovery", []),
    ("candidate_discovery_orchestrator", ["--apply"]),
    ("finviz_proactive_research", ["--max", "400", "--lookback-hours", "12"]),
    ("hermes_discovery_scorecard", []),
    ("hermes_research_agenda", ["--apply", "--json"]),
    ("hermes_research_worker_pool", ["--run", "--json"]),
])
def test_real_cli_import_closure_is_offline_and_writes_nothing(state, script, args):
    import os
    import subprocess
    bootstrap = r'''
import json, os, runpy, sys
from pathlib import Path
attempts = []
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0]))
        if path.name.startswith(".env") or (path.name == "env" and "/tradeai/" in str(path)):
            attempts.append("secret_file")
            raise AssertionError("offline preview attempted a secret file")
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            attempts.append("file_write")
            raise AssertionError("offline preview attempted a file write")
    if event in {"socket.connect", "subprocess.Popen", "urllib.Request"}:
        attempts.append(event)
        raise AssertionError("offline preview attempted a live dependency")
sys.addaudithook(audit)
sys.argv = [sys.argv[1]] + sys.argv[2:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as exc:
    if exc.code not in (None, 0):
        raise
finally:
    print("PREVIEW_CAPABILITY_ATTEMPTS=" + json.dumps(attempts))
    if attempts:
        raise AssertionError("preview capability attempt, even if swallowed")
'''
    env = {"PATH": os.defpath, "TRADE_AI_CI": "1", "M2_SKIP_DOCKER": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "TRADEAI_STATE_ROOT": str(state),
           "TRADEAI_PERSISTENT_STATE_ROOT": str(state)}
    result = subprocess.run([sys.executable, "-B", "-c", bootstrap,
                             str(ROOT / "scripts" / (script + ".py")), *args, "--dry-run"],
                            cwd=ROOT, env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREVIEW_CAPABILITY_ATTEMPTS=[]" in result.stdout
    assert "DRY-RUN " in result.stdout and snapshot(state) == {}


@pytest.mark.parametrize("script,lane,loader,argv", [
    ("hermes_momentum_catalyst_researcher", "hermes-momentum-catalyst-scalp", "_load_env",
     ["--source", "scalp", "--apply"]),
    ("hermes_research_worker_pool", "hermes-research-worker-pool", "_load_dependencies",
     ["--run", "--json"]),
])
def test_startup_failure_is_receipted_before_business_work(state, script, lane, loader, argv):
    from lib.lane_last_receipt import write_lane_receipt
    mod = load_script(script)
    write_lane_receipt(lane, ok=True, exit_code=0, summary={"completed": 1})
    path = state / "data/runtime" / (lane + "_last.json")
    previous = json.loads(path.read_text())["ok_at"]

    def failed_startup():
        raise RuntimeError("fake dependency initialization failed")

    setattr(mod, loader, failed_startup)
    with pytest.raises(RuntimeError, match="fake dependency initialization failed"):
        mod.main(argv)
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    assert receipt["ok_at"] == previous


def test_allowlist_preserves_exact_observed_cron_script_arguments():
    import shlex
    registry = json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
    allow = {r["lane_id"]: r for r in
             json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    own = [r for r in registry if r.get("scheduler", {}).get("wave") == "R2-04"]
    assert len(own) == 4  # train 3 recount: see test_shard04_dispatch_rows_obey_current_policy_and_lock_proof
    for row in own:
        command = allow[row["lane_id"]]["command"]
        tokens = shlex.split(row["scheduler"]["command_text"])
        script_index = tokens.index(command[1])
        observed = []
        for token in tokens[script_index + 1:]:
            if token in {">", ">>", "2>&1", "&&", ";", "#"}:
                break
            if token != "--apply":
                observed.append(token)
        assert command[2:] == observed, row["lane_id"]

from tests.test_canary_wave_20261014 import CANARY_WAVE_20261014 as _CANARY_WAVE  # noqa: E402  canary-wave-20261014
