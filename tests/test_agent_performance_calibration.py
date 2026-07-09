#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
from agent_performance_api import calibration_row_to_performance, calibration_windows_as_performance  # noqa: E402


def test_maps_accuracy_to_pct():
    row = {
        "window_id": "w1",
        "agent_name": "maria",
        "window_start": "2026-07-01",
        "window_end": "2026-07-05",
        "recommendations": 41,
        "resolved": 38,
        "correct": 7,
        "incorrect": 2,
        "accuracy": 0.1707,
        "avg_confidence": 0.62,
        "sample_size_status": "shadow_only",
        "created_at": "2026-07-05T12:00:00Z",
    }
    out = calibration_row_to_performance(row)
    assert out["agent"] == "maria"
    assert out["accuracy_pct"] == 17.1
    assert out["total_recommendations"] == 41
    assert out["resolved"] == 38
    assert out["sample_size_status"] == "shadow_only"
    assert out["source"] == "agent_calibration_windows"


def test_batch_mapping():
    rows = [{"window_id": "a", "agent_name": "steph", "accuracy": 0.5, "recommendations": 10}]
    assert len(calibration_windows_as_performance(rows)) == 1