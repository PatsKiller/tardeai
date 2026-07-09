"""Map agent_calibration_windows rows to legacy /api/v2/agent-performance shape."""
from __future__ import annotations

from typing import Any


def _pct_scale(val: Any) -> float | None:
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    return round(v * 100, 1) if v <= 1 else round(v, 1)


def calibration_row_to_performance(row: dict) -> dict:
    """One calibration window → Performance tab row."""
    acc = _pct_scale(row.get("accuracy"))
    conf_raw = row.get("avg_confidence")
    avg_conf = None
    if conf_raw is not None:
        try:
            c = float(conf_raw)
            avg_conf = c if c > 1 else c
        except (TypeError, ValueError):
            pass
    return {
        "id": row.get("window_id") or row.get("id"),
        "agent": row.get("agent_name"),
        "period_start": row.get("window_start") or row.get("created_at"),
        "period_end": row.get("window_end") or row.get("created_at"),
        "total_recommendations": row.get("recommendations"),
        "accuracy_pct": acc,
        "avg_confidence": avg_conf,
        "rule_violations": 0,
        "human_overrides": row.get("incorrect") or 0,
        "resolved": row.get("resolved"),
        "correct": row.get("correct"),
        "incorrect": row.get("incorrect"),
        "sample_size_status": row.get("sample_size_status"),
        "calibration_error": row.get("calibration_error"),
        "domain": row.get("domain"),
        "scored_at": row.get("created_at"),
        "source": "agent_calibration_windows",
    }


def calibration_windows_as_performance(rows: list[dict]) -> list[dict]:
    return [calibration_row_to_performance(r) for r in (rows or [])]