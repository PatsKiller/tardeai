from __future__ import annotations

from scripts.cio_api_contract_census import build_census


def test_census_covers_requested_surfaces_and_is_honest_about_runtime_unknowns():
    report = build_census()
    assert report["schema"] == "CIOApiContractCensus@v1"
    assert {"CIO", "Advisory", "Agents", "Hermes", "Research Intelligence"} <= set(report["scope"])
    assert report["endpoint_count"] > 0
    for row in report["endpoints"]:
        assert row["route"].startswith("/api/v")
        assert row["producer"]
        assert row["response_schema"] == "UNKNOWN_SOURCE_CONTRACT"
        assert row["source_clock"] == "UNKNOWN_RUNTIME_CLOCK"
        assert row["composition_clock"] == "UNKNOWN_RUNTIME_CLOCK"
        assert row["evidence_class"] == "SOURCE_ONLY"
        assert row["error_behavior"] == "UNKNOWN_RUNTIME_BEHAVIOR"
    assert report["machine_claims"]["runtime_complete"] is False
    assert report["machine_claims"]["dead_calls_proven"] is False


def test_census_does_not_report_duplicate_or_version_mixing_without_evidence():
    report = build_census()
    assert report["v2_v3_accidental_mixing"] == []
    assert report["unused_fetches"] == []
    assert report["dead_endpoints"] == []
