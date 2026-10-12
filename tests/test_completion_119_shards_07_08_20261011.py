"""Offline entrypoints and truthful receipts for the 07–08 completion tranche.

All real-run tests inject business functions; subprocess checks use explicit
--dry-run under the repository hermetic launcher. No production capability.
"""
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
CASES = (
    ("backfill_document_mentions.py", ["--all", "--apply"], "document-mentions-backfill"),
    ("aegis_evening_packet.py", [], "aegis-evening-packet"),
    ("hermes_scope_governor.py", ["--apply", "--reaction-review"], "hermes-scope-governor"),
    ("agent_recommendation_normalizer.py", ["--apply", "--json"], "agent-recommendation-normalizer"),
    ("hermes_score_event_feeder.py", ["--apply"], "hermes-score-event-feeder"),
    ("check_hermes_update_available.py", [], "hermes-update-check"),
    ("contradiction_adjudicator.py", ["--apply", "--max-pairs", "20"], "contradiction-adjudicator"),
    ("run_watch_review_workers.py", ["--mode", "execute", "--allow-execute", "--role", "maria"], "watch-review-workers"),
    ("run_watch_review_workers.py", ["--mode", "execute", "--allow-execute", "--role", "cio"], "watch-review-workers"),
    ("drain_llm_deferred.py", [], "llm-deferred-drain"),
    ("symbol_enrichment.py", [], "symbol-enrichment"),
    ("topic_curator.py", ["--improve-queries"], "topic-curator-at-30-9-13"),
    ("topic_curator.py", ["--ensemble"], "topic-curator-ensemble"),
    ("hermes_top20_external_intel.py", ["--apply", "--top", "20"], "hermes-top20-external-intel"),
    ("hermes_external_feedback_loop.py", ["--apply", "--max-rows", "2000"], "hermes-usefulness-backfill"),
    ("rag_indexer.py", [], "rag-indexer"),
    ("due_diligence_questions.py", ["--apply", "--route"], "due-diligence-questions"),
    ("report_slo_burn_rate.py", [], "slo-burn-rate"),
    ("run_scheduled_two_way_curation.sh", ["options-edge"], "two-way-curation"),
    ("run_scheduled_two_way_curation.sh", ["desk-emit"], "two-way-curation"),
    ("run_watchlist_agent_jobs_offpeak.sh", [], "run-watchlist-agent-jobs-offpeak"),
)


def _cli(script, args, tmp_path):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    sentinel = state / "sentinel.json"
    sentinel.write_text('{"keep": true}')
    before = {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    env = dict(os.environ)
    env.update(TRADE_AI_CI="1", TRADEAI_STATE_ROOT=str(state), PYTHONDONTWRITEBYTECODE="1")
    command = ["bash" if script.endswith(".sh") else sys.executable, str(ROOT / "scripts" / script), *args]
    result = subprocess.run(command, cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    after = {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    assert after == before
    return result


@pytest.mark.parametrize("script,args,lane", CASES)
def test_explicit_preview_precedes_every_runtime_capability(script, args, lane, tmp_path):
    result = _cli(script, [*args, "--dry-run"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN " in result.stdout and lane in result.stdout


@pytest.mark.parametrize("script,args,lane", CASES)
def test_unknown_flags_exit_usage_even_with_preview(script, args, lane, tmp_path):
    result = _cli(script, [*args, "--dry-run", "--unexpected-completion-flag"], tmp_path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "DRY-RUN " not in result.stdout


def _module(name):
    spec = importlib.util.spec_from_file_location("completion_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt(state, lane):
    return json.loads((state / "data" / "runtime" / (lane + "_last.json")).read_text())


def _seed(state, lane):
    path = state / "data" / "runtime" / (lane + "_last.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ok_at": "2026-10-01T00:00:00+00:00"}))
    return "2026-10-01T00:00:00+00:00"


@pytest.mark.parametrize("name,lane,argv", (
    ("backfill_document_mentions", "document-mentions-backfill", ["--all", "--apply"]),
    ("aegis_evening_packet", "aegis-evening-packet", []),
))
def test_owned_business_failure_preserves_success_timestamp(name, lane, argv, monkeypatch, tmp_path):
    module = _module(name)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    previous = _seed(tmp_path, lane)
    monkeypatch.setattr(module, "_run", lambda *a: 1)
    assert module.main(argv) == 1
    receipt = _receipt(tmp_path, lane)
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous
    monkeypatch.setattr(module, "_run", lambda *a: 0)
    assert module.main(argv) == 0
    assert _receipt(tmp_path, lane)["ok_at"] != previous


@pytest.mark.parametrize("name,lane", (
    ("hermes_scope_governor", "hermes-scope-governor"),
    ("hermes_score_event_feeder", "hermes-score-event-feeder"),
))
def test_governor_feeder_soft_result_never_marks_success(name, lane, monkeypatch, tmp_path):
    module = _module(name)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    previous = _seed(tmp_path, lane)
    monkeypatch.setattr(module, "run", lambda **kw: {"ok": False, "reason": "disabled"})
    expected_exit = 1 if name == "hermes_scope_governor" else 0
    assert module.main(["--apply"]) == expected_exit
    receipt = _receipt(tmp_path, lane)
    assert receipt["status"] == "failed" and receipt["ok_at"] == previous and receipt["exit"] == expected_exit
    monkeypatch.setattr(module, "run", lambda **kw: {"ok": True})
    assert module.main(["--apply"]) == 0
    assert _receipt(tmp_path, lane)["status"] == "ok"


def test_update_check_missing_versions_is_not_healthy(monkeypatch, tmp_path):
    module = _module("check_hermes_update_available")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    previous = _seed(tmp_path, "hermes-update-check")
    monkeypatch.setattr(module, "OUT", tmp_path / "hermes_status.json")
    monkeypatch.setattr(module, "CAP", tmp_path / "capabilities.json")
    monkeypatch.setattr(module, "installed_version", lambda: None)
    monkeypatch.setattr(module, "available_versions", lambda: [])
    assert module.main([]) == 1
    assert json.loads(module.OUT.read_text())["status"] == "not_measured"
    assert _receipt(tmp_path, "hermes-update-check")["ok_at"] == previous
    monkeypatch.setattr(module, "installed_version", lambda: "1.2.0")
    monkeypatch.setattr(module, "available_versions", lambda: ["1.2.0"])
    assert module.main([]) == 0
    assert _receipt(tmp_path, "hermes-update-check")["status"] == "ok"


def test_deferred_preview_never_imports_queue_or_reclaims(monkeypatch, capsys):
    module = _module("drain_llm_deferred")
    trap = types.ModuleType("lib.llm_deferral")
    def fail(*a, **k):
        raise AssertionError("preview reached queue")
    trap.reclaim_stale = trap.expire_stale = trap.queue_summary = trap.claim_due = fail
    monkeypatch.setitem(sys.modules, "lib.llm_deferral", trap)
    assert module.main(["--dry-run", "--force"]) == 0
    assert "no DB, reclaim, expiry, claim" in capsys.readouterr().out


def test_deferred_failed_batch_exits_nonzero_preserving_success(monkeypatch, tmp_path):
    module = _module("drain_llm_deferred")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    previous = _seed(tmp_path, "llm-deferred-drain")
    import lib
    queue = types.ModuleType("lib.llm_deferral")
    queue.reclaim_stale = queue.expire_stale = lambda: 0
    queue.queue_summary = lambda: {"pending": 1}
    queue.claim_due = lambda **kw: [{"id": "fixture-request", "process_id": "fixture-process"}]
    finished = []
    queue.complete = lambda request, **kw: finished.append((request, kw))
    window = types.ModuleType("lib.deepseek_offpeak")
    window.is_scheduled_deepseek_window = lambda: True
    monkeypatch.setitem(sys.modules, "lib.llm_deferral", queue)
    monkeypatch.setattr(lib, "llm_deferral", queue, raising=False)
    monkeypatch.setitem(sys.modules, "lib.deepseek_offpeak", window)
    monkeypatch.setattr(module, "_run_one", lambda row: (False, "fixture failure"))
    assert module.main([]) == 1
    receipt = _receipt(tmp_path, "llm-deferred-drain")
    assert receipt["status"] == "failed" and receipt["exit"] == 1 and receipt["ok_at"] == previous
    assert receipt["summary"]["failed"] == 1 and finished[0][1]["ok"] is False


def test_usefulness_failures_preserve_receipt_and_exit(monkeypatch, tmp_path):
    module = _module("hermes_external_feedback_loop")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "_load_env", lambda: None)
    previous = _seed(tmp_path, "hermes-usefulness-backfill")
    monkeypatch.setattr(module, "_run_feedback", lambda args: {"selected": 2, "scored": 1, "failed": 1, "aborted": False})
    assert module.main(["--apply"]) == 1
    receipt = _receipt(tmp_path, "hermes-usefulness-backfill")
    assert receipt["exit"] == 1 and receipt["status"] == "failed" and receipt["ok_at"] == previous


def test_narrowed_feedback_loader_copies_only_declared_names(monkeypatch):
    module = _module("hermes_external_feedback_loop")
    import lib.env_bootstrap
    calls = []
    monkeypatch.setattr(lib.env_bootstrap, "load_env", lambda **kw: calls.append(kw))
    module._load_env()
    assert calls == [{"names": ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")}]


@pytest.mark.parametrize("name,argv", (
    ("backfill_document_mentions", ["--all", "--apply", "--limit", "5000", "--budget-s", "1200"]),
    ("aegis_evening_packet", []),
    ("hermes_scope_governor", ["--apply"]),
    ("agent_recommendation_normalizer", ["--apply"]),
    ("hermes_score_event_feeder", ["--apply"]),
))
def test_frozen_business_argv_preserves_output_and_calls(name, argv, monkeypatch, tmp_path, capsys):
    """Compare actual legacy and candidate entrypoints against injected business callbacks."""
    frozen = json.loads((ROOT / "tests" / "fixtures" / "completion_119_07_08" / "legacy_entrypoints.json").read_text())
    observed = []
    for old in (True, False):
        module = _module(name)
        trace = []
        monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
        monkeypatch.setattr(sys, "argv", [name + ".py", *argv])
        if name == "backfill_document_mentions":
            monkeypatch.setattr(module.time, "monotonic", lambda: 123.0)
            monkeypatch.setattr(module.time, "strftime", lambda *a: "FROZEN_CLOCK")
            module.load_watermarks = lambda: {"news_articles": 10}
            module.save_watermarks = lambda marks: trace.append(("watermarks", dict(marks)))
            def run(table, limit, apply, **kwargs):
                trace.append((table, limit, apply, kwargs))
                return dict(table=table, documents=3, subject=1, mentioned=1, undecided_docs=0,
                            no_mention=1, written=2 if apply else 0, multi=0, scanned=3, max_id=20, budget_hit=False)
            module.run = run
        elif name == "aegis_evening_packet":
            def build():
                trace.append("build")
                return {"schema": "aegis_evening_packet@v1", "packet_chars": 123, "findings": []}
            module.build_packet = build
            module.evening_packet_targets = lambda: [tmp_path / "packet.json"]
        elif name in ("hermes_scope_governor", "hermes_score_event_feeder"):
            def run(**kwargs):
                trace.append(kwargs)
                result = {"ok": True, "evaluated": 3}
                print(json.dumps(result, indent=2))
                return result
            module.run = run
        else:
            class Conn:
                def close(self):
                    trace.append("close")
            module._load_env = lambda: None
            module._get_conn = lambda: trace.append("connect") or Conn()
            def extract(conn, agent, symbol):
                trace.append(("extract", agent, symbol))
                return [{"source_table": "watchlist_agent_results", "source_id": "fixture-1", "agent_name": "fixture-reviewer"}]
            module.normalize_watchlist_results = extract
            module.normalize_cio_decisions = module.normalize_debates = lambda *a: []
            module.save_recommendations = lambda conn, recs, dry_run: trace.append(("save", recs, dry_run)) or len(recs)
        if old:
            namespace = dict(vars(module))
            exec(compile(frozen[name], "frozen-legacy-entrypoint", "exec"), namespace)
            entry = namespace["main"]
        else:
            entry = module.main
        code = entry()
        observed.append((0 if code is None else code, capsys.readouterr().out, list(trace)))
    assert observed[0] == observed[1]
