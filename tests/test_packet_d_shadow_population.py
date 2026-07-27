"""Packet D SHADOW population loop: counts, independence, no promotion."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD_PATH = ROOT / "scripts" / "operator_packets" / "packet_d_shadow_acceptance.py"


def _load():
    spec = importlib.util.spec_from_file_location("packet_d_shadow_population", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _stub_source(n_good: int = 100, n_bad: int = 20):
    def _src():
        rows = []
        for i in range(n_good):
            rows.append({
                "artifact_id": f"good-{i}",
                "symbol": f"G{i}",
                "producer_agent_id": mod.PRODUCER_AGENT_ID,
                "is_known_bad": False,
                "stale_input": False,
            })
        for i in range(n_bad):
            rows.append({
                "artifact_id": f"bad-{i}",
                "symbol": f"B{i}",
                "producer_agent_id": mod.PRODUCER_AGENT_ID,
                "is_known_bad": True,
                "stale_input": False,
            })
        return rows
    return _src


def test_run_shadow_stub_source_meets_thresholds():
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    report = mod.run_shadow(dsn, source=_stub_source(100, 20))
    assert report.environment == "SHADOW"
    assert report.agents_marked_operational == 0
    assert report.watch_artifacts_processed == 100
    assert report.known_bad_fixtures_processed == 20
    assert len(report.reviews) == 120
    assert len(report.scores) == 120
    # Independence
    assert all(r.reviewer_agent_id != r.producer_agent_id for r in report.reviews)
    assert all(s.scorer_agent_id != s.producer_agent_id for s in report.scores)
    ok, fails = report.evaluate()
    assert ok, fails
    m = report.metrics()
    assert m["retrieval_recorded_rate"] >= 0.95
    assert m["darwin_score_coverage"] >= 0.95
    assert m["reviewer_independence"] == 1.0
    assert m["scorer_independence"] == 1.0


def test_run_shadow_refuses_production_dbname():
    with pytest.raises(mod.ShadowGuardError, match="production"):
        mod.run_shadow(
            "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5432/trade_ai",
            source=_stub_source(5, 2),
        )


def test_run_shadow_refuses_reader_role():
    with pytest.raises(mod.ShadowGuardError, match="agentic_runtime_shadow_rw"):
        mod.run_shadow(
            "postgresql://agentic_runtime_reader:pw@127.0.0.1:5433/trade_ai_agentic_lab",
            source=_stub_source(5, 2),
        )


def test_build_corpus_pads_to_mins_without_db():
    watch, bad = mod.build_acceptance_corpus(None, source=None)
    assert len(watch) >= mod.MIN_WATCH_ARTIFACTS
    assert len(bad) >= mod.MIN_KNOWN_BAD_FIXTURES
    assert any(r.get("source_kind") == "synthetic_shadow_pad" for r in watch) or len(watch) >= 100
    assert all(r.get("is_known_bad") for r in bad)


def test_known_bad_not_counted_as_false_positive():
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    report = mod.run_shadow(dsn, source=_stub_source(100, 20))
    m = report.metrics()
    # All rejects/quarantines on known-bad only → FP rate 0 on good set
    assert m["sentinel_false_positive_rate"] == 0.0


def test_self_check_still_ok():
    assert mod.main(["--self-check"]) == 0
