"""Join job log + durable output + CC status by run_id."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.research_observation import (
    EntitlementStatus,
    FreshnessStatus,
    join_run_artifacts,
    correlate_run,
    payload_source_hash,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research_observation"

# Fixed "now" epoch: 2026-09-02T18:30:00Z
NOW_EPOCH = 1788373800.0  # 2026-09-02T18:30:00Z


def test_correlate_run_ids():
    corr = correlate_run(
        run_id="run-a",
        log_record={"run_id": "run-a", "success": True},
        durable_output={"run_id": "run-a", "payload": {"x": 1}},
        cc_status={"correlation_id": "run-a", "status": "ok"},
    )
    assert corr["log_match"] and corr["durable_match"] and corr["cc_match"]


def test_join_success_with_durable():
    durable = {
        "run_id": "run-ok",
        "provider_at": "2026-09-02T18:00:00+00:00",
        "observed_at": "2026-09-02T18:00:00+00:00",
        "received_at": "2026-09-02T18:00:05+00:00",
        "normalized_at": "2026-09-02T18:00:06+00:00",
        "quality_status": "OK",
        "sequence_or_version": "1",
        "calculation_or_model_version": "m@1",
        "payload": {"summary": "joined"},
        "trace_id": "trace:run-ok",
        "symbol": "AAPL",
    }
    expected_hash = payload_source_hash(durable["payload"])
    durable["source_hash"] = expected_hash
    result = join_run_artifacts(
        run_id="run-ok",
        source_identity="hermes_research_results",
        provider="hermes_worker",
        log_record={"run_id": "run-ok", "success": True, "ts": "2026-09-02T18:00:05+00:00"},
        durable_output=durable,
        cc_status={"run_id": "run-ok", "status": "published"},
        expected_source_hash=expected_hash,
        entitlement_status=EntitlementStatus.INTERNAL,
        now_epoch=NOW_EPOCH,
    )
    assert result.ok
    assert result.durable_present
    assert result.observation is not None
    assert result.observation.freshness_status is FreshnessStatus.FRESH
    assert result.observation.run_id == "run-ok"


def test_log_only_success_not_success():
    log = json.loads((FIXTURES / "log_success.json").read_text())
    result = join_run_artifacts(
        run_id="run-log-only-001",
        source_identity="flash_llm_intelligence_runtime",
        provider="llm_enrichment",
        log_record=log,
        durable_output=None,
        received_at="2026-09-02T18:10:01+00:00",
        normalized_at="2026-09-02T18:10:02+00:00",
    )
    assert not result.ok
    assert "LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT" in result.reasons
    assert result.observation is not None
    assert result.observation.freshness_status is FreshnessStatus.ERROR
    assert result.observation.durable_output_present is False


def test_wrong_run_id_on_durable():
    result = join_run_artifacts(
        run_id="run-expected",
        source_identity="hermes_research_results",
        provider="hermes_worker",
        log_record={"run_id": "run-expected", "success": True},
        durable_output={
            "run_id": "run-WRONG",
            "provider_at": "2026-09-02T18:00:00+00:00",
            "payload": {"x": 1},
            "quality_status": "OK",
            "sequence_or_version": "1",
            "calculation_or_model_version": "m",
        },
        now_epoch=NOW_EPOCH,
    )
    assert not result.ok
    assert any(r.startswith("WRONG_RUN_ID:durable") for r in result.reasons)


def test_wrong_source_hash_on_join():
    payload = {"summary": "hash-me"}
    durable = {
        "run_id": "run-hash",
        "provider_at": "2026-09-02T18:00:00+00:00",
        "payload": payload,
        "quality_status": "OK",
        "sequence_or_version": "1",
        "calculation_or_model_version": "m",
        "source_hash": payload_source_hash(payload),
    }
    result = join_run_artifacts(
        run_id="run-hash",
        source_identity="hermes_research_results",
        provider="hermes_worker",
        log_record={"run_id": "run-hash", "success": True},
        durable_output=durable,
        expected_source_hash="deadbeef" * 8,
        now_epoch=NOW_EPOCH,
    )
    assert not result.ok
    assert any(r.startswith("WRONG_SOURCE_HASH") for r in result.reasons)


def test_stale_join_from_age():
    durable = json.loads((FIXTURES / "durable_stale.json").read_text())
    result = join_run_artifacts(
        run_id="run-stale-001",
        source_identity="flash_llm_intelligence_runtime",
        provider="llm_enrichment",
        log_record={"run_id": "run-stale-001", "success": True},
        durable_output=durable,
        now_epoch=NOW_EPOCH,
        max_freshness_age_seconds=86_400.0,
    )
    assert not result.ok
    assert result.observation is not None
    assert result.observation.freshness_status is FreshnessStatus.STALE
    assert any(r.startswith("STALE_AGE") for r in result.reasons)


def test_missing_both_is_no_data():
    result = join_run_artifacts(
        run_id="run-empty",
        source_identity="cio_council_synthesis",
        provider="none",
        log_record=None,
        durable_output=None,
        received_at="2026-09-02T18:00:00+00:00",
        normalized_at="2026-09-02T18:00:00+00:00",
    )
    assert not result.ok
    assert "NO_DATA" in result.reasons
    assert result.observation.freshness_status is FreshnessStatus.NO_DATA


def test_gap_when_log_without_success_and_no_durable():
    result = join_run_artifacts(
        run_id="run-gap",
        source_identity="research_intelligence_feed",
        provider="ri",
        log_record={"run_id": "run-gap", "success": False, "ts": "2026-09-02T18:00:00+00:00"},
        durable_output=None,
        received_at="2026-09-02T18:00:00+00:00",
        normalized_at="2026-09-02T18:00:00+00:00",
    )
    assert not result.ok
    assert result.observation.freshness_status is FreshnessStatus.GAP
