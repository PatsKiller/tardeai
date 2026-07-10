"""Shared awareness / operator fields for trade_ai_scans persistence (P2-4)."""

from __future__ import annotations

from typing import Any


AWARENESS_PERSIST_COLUMNS = (
    "awareness_status",
    "setup_class",
    "symbol_candidate",
    "symbol_alias_confidence",
    "manual_review_required",
    "operator_pill",
    "operator_subtitle",
    "operator_color_token",
    "not_validation_ready",
    "not_tradeable",
)


def awareness_persist_values(t: dict[str, Any]) -> tuple:
    """Extract DB-ready values from a scored ticker dict."""
    conf = t.get("symbol_alias_confidence")
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None
    return (
        t.get("awareness_status"),
        t.get("setup_class"),
        t.get("symbol_candidate"),
        conf_f,
        bool(t.get("manual_review_required")),
        (t.get("operator_pill") or "")[:120] or None,
        (t.get("operator_subtitle") or "")[:200] or None,
        (t.get("operator_color_token") or "")[:40] or None,
        bool(t.get("not_validation_ready")),
        bool(t.get("not_tradeable")),
    )


def awareness_persist_update_clause() -> str:
    """ON CONFLICT SET fragment for awareness columns."""
    return ", ".join(
        f"{col} = EXCLUDED.{col}" for col in AWARENESS_PERSIST_COLUMNS
    )