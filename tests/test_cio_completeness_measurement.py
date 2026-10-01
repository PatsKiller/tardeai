from __future__ import annotations

from scripts.cio_completeness_measurement import build_measurement


def test_completeness_measurement_is_machine_readable_and_does_not_hide_unproven_edges():
    report = build_measurement(now="2026-10-01T20:00:00+00:00")
    assert report["schema"] == "CIOCompletenessMeasurement@v1"
    assert "decision_lineage" in report["cio_capabilities_produced"]
    assert "capability_coverage" in report["cio_capabilities_operator_visible"]
    assert report["source_acceptance"]["produced_not_surfaced_zero"] is True
    assert report["source_acceptance"]["runtime_unproven_items_labelled"] is True
    assert report["critical_edges_live"] >= 0
    assert report["critical_edges_partial"] >= 0
    assert report["critical_edges_dark"] >= 0
    assert report["critical_edges_unknown"] >= 0


def test_measurement_names_each_unproven_item_and_never_calls_it_live():
    report = build_measurement(now="2026-10-01T20:00:00+00:00")
    for item in report["surfaced_not_runtime_proven"]:
        assert item["name"]
        assert item["runtime_state"] != "LIVE"
        assert item["ui_label"] in {"SHADOW", "PREVIEW", "SOURCE_ONLY", "UNKNOWN", "RETRIEVED", "REJECTED"}
