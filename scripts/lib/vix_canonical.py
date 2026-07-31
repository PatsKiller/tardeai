"""Canonical VIX read path for CC-facing and batch consumers.

Single source: market_regime_indicators.vix_close (fresh within 48h), with optional
run-summary override when the orchestrator supplies a positive value.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

FetchOne = Callable[[str, tuple[Any, ...] | None], dict[str, Any] | None]


def vix_effective(
    run_vix: Any = None,
    *,
    db_fetch_one: FetchOne | None = None,
) -> float | None:
    """Return the effective VIX for display/scoring, or None when unavailable."""
    try:
        v = float(run_vix or 0)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    if db_fetch_one is None:
        return None
    try:
        row = db_fetch_one(
            """SELECT value FROM market_regime_indicators
               WHERE indicator_key='vix_close' AND created_at > now() - interval '48 hours'
               ORDER BY created_at DESC LIMIT 1""",
            None,
        )
        return float(row["value"]) if row and row.get("value") is not None else None
    except Exception:
        return None
