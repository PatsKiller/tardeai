from __future__ import annotations

from scripts.cio_completeness_measurement import build_measurement


def _census(consumed_brain: bool = True) -> dict:
    backend = [
        {"route": "/api/v3/cio/brain", "kind": "EXACT", "method": "GET", "producer": "api_v3_cio.py::get_brain",
         "dispatch_ref": "scripts/api_v2.py:10", "family": "CIO"},
        {"route": "/api/v3/cio/operator-evidence", "kind": "EXACT", "method": "GET", "producer": "api_v3_cio.py::ev",
         "dispatch_ref": "scripts/api_v2.py:20", "family": "CIO"},
        {"route": "/api/v3/cio/operator_evidence", "kind": "EXACT", "method": "GET", "producer": "api_v3_cio.py::ev",
         "dispatch_ref": "scripts/api_v2.py:20", "family": "CIO"},
        # injected: produced but no component consumes it
        {"route": "/api/v3/cio/injected-orphan", "kind": "EXACT", "method": "GET", "producer": "api_v3_cio.py::orphan",
         "dispatch_ref": "scripts/api_v2.py:30", "family": "CIO"},
    ]
    endpoints = [{"route": "/api/v3/cio/operator-evidence", "method": "GET", "dispatch_ref": "scripts/api_v2.py:20",
                  "match": "EXACT", "consumer_ref": "missing/Panel.tsx:1", "response_schemas": ["CIOOperatorEvidence@v1"]}]
    if consumed_brain:
        endpoints.append({"route": "/api/v3/cio/brain", "method": "GET", "dispatch_ref": "scripts/api_v2.py:10",
                          "match": "EXACT", "consumer_ref": "missing/Brain.tsx:1", "response_schemas": ["CIOBrainSnapshot@v1"]})
    return {"schema": "CIOApiContractCensus@v2", "endpoints": endpoints, "backend_routes": backend}


EVIDENCE = {"blocks": {
    "capability_coverage": {"rows": [{"capability": "judgment", "state": "PARTIAL", "reason": "no receipt"},
                                     {"capability": "lesson", "state": "LIVE"}]},
    "research": {"artifacts": [{"artifact_id": "rr_1", "status": "RETRIEVED"}]},
}}
SCHEMAS = {"CIOBrainSnapshot@v1": ["scripts/lib/cio_brain.py"], "CIOInjectedOrphan@v1": ["scripts/lib/cio_x.py"]}


def test_completeness_names_injected_produced_not_surfaced_items():
    report = build_measurement(now="2026-10-02T16:00:00+00:00", census=_census(), evidence=EVIDENCE, schemas=SCHEMAS)
    assert report["schema"] == "CIOCompletenessMeasurement@v2"
    assert "route:/api/v3/cio/injected-orphan" in report["produced_not_surfaced"]
    assert "schema:CIOInjectedOrphan@v1" in report["produced_not_surfaced"]
    assert "route:/api/v3/cio/brain" in report["cio_capabilities_operator_visible"]
    assert "schema:CIOBrainSnapshot@v1" in report["cio_capabilities_operator_visible"]
    # alias spellings collapse into one produced item
    assert "route:/api/v3/cio/operator_evidence" not in report["cio_capabilities_produced"]
    assert report["source_acceptance"]["produced_not_surfaced_zero"] is False


def test_unconsumed_route_flips_from_visible_to_not_surfaced():
    report = build_measurement(now="2026-10-02T16:00:00+00:00", census=_census(consumed_brain=False), evidence=EVIDENCE, schemas=SCHEMAS)
    assert "route:/api/v3/cio/brain" in report["produced_not_surfaced"]
    assert "schema:CIOBrainSnapshot@v1" in report["produced_not_surfaced"]


def test_capability_rows_are_not_visible_without_a_rendering_consumer():
    # The fixture consumer file does not exist, so nothing proves capability rows are rendered.
    report = build_measurement(now="2026-10-02T16:00:00+00:00", census=_census(), evidence=EVIDENCE, schemas=SCHEMAS)
    assert "capability:judgment" in report["produced_not_surfaced"]
    assert report["surfaced_not_runtime_proven"][-1]["name"] == "research:rr_1"


def test_real_tree_measurement_names_unproven_items_and_never_calls_them_live():
    report = build_measurement(now="2026-10-02T16:00:00+00:00")
    assert report["counts"]["produced"] == len(report["cio_capabilities_produced"])
    assert set(report["produced_not_surfaced"]) <= set(report["cio_capabilities_produced"])
    assert "route:/api/v3/cio/operator-evidence" in report["cio_capabilities_operator_visible"]
    for item in report["surfaced_not_runtime_proven"]:
        assert item["name"]
        assert item["runtime_state"] != "LIVE"
        assert item["ui_label"]
