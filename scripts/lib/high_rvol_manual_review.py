"""High-RVOL WAIT → MANUAL_REVIEW lane (Ross Cameron alignment).

Names scoring WAIT with RVOL ≥ threshold surface for operator discretionary review —
not auto GO, not invisible in the WAIT pile. Complements squeeze/R-S lane.
"""
from __future__ import annotations

from typing import Any

# Matches momentum_scalp.yaml premium_rvol
HIGH_RVOL_THRESHOLD = 8.0


def _num(row: dict, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        raw = row.get(k)
        if raw is None or raw == "":
            continue
        try:
            return float(str(raw).replace("%", "").replace(",", "").replace("x", ""))
        except (TypeError, ValueError):
            continue
    return default


def is_squeeze_row(row: dict) -> bool:
    return (
        row.get("awareness_status") == "SQUEEZE"
        or row.get("setup_class") == "squeeze"
        or "REVERSE_SPLIT" in str(row.get("soft_flag_reason") or row.get("disqualification_reason") or "")
    )


def is_social_awareness_lane(row: dict) -> bool:
    """Pre-market StockTwits awareness — keep teal AWARE lane even when RVOL is high."""
    return (
        row.get("awareness_status") == "SOCIAL_AWARENESS"
        or row.get("setup_class") == "social_awareness_only"
        or row.get("catalyst_source") == "premarket_social"
    )


def qualifies_high_rvol_manual(row: dict, *, threshold: float = HIGH_RVOL_THRESHOLD) -> bool:
    """True when a WAIT row should upgrade to MANUAL_REVIEW for operator awareness."""
    if not row or is_squeeze_row(row) or is_social_awareness_lane(row):
        return False
    if row.get("disqualified"):
        return False
    dec = (row.get("decision") or "").upper()
    if dec not in ("WAIT",):
        return False
    if row.get("awareness_status") in ("HIGH_RVOL", "MICRO_FLOAT"):
        return False
    if row.get("setup_class") == "micro_float_runner":
        return False
    rvol = _num(row, "rvol", "relative_volume")
    return rvol >= threshold


def runner_sort_score(row: dict) -> float:
    rvol = _num(row, "rvol", "relative_volume")
    gap = abs(_num(row, "gap_pct", "gap_percent"))
    chg = abs(_num(row, "change_pct", "change_percent"))
    return max(rvol * max(gap, 1.0), chg, _num(row, "score"))


def apply_high_rvol_manual_fields(row: dict) -> dict:
    """Mutate row in-place for HIGH_RVOL MANUAL_REVIEW lane."""
    rvol = _num(row, "rvol", "relative_volume")
    gap = _num(row, "gap_pct", "gap_percent")
    chg = _num(row, "change_pct", "change_percent")
    rvol_s = f"{rvol:.1f}x" if rvol else "—"
    chg_s = f"+{chg:.1f}%" if chg else ""

    row["decision"] = "MANUAL_REVIEW"
    row["grade"] = row.get("grade") if row.get("grade") not in (None, "", "DISQUALIFIED") else "RUNNER"
    row["awareness_status"] = "HIGH_RVOL"
    row["setup_class"] = "high_rvol_runner"
    row["route"] = row.get("route") or "warrior_manual"
    row["route_actionability"] = "MANUAL_REVIEW"
    row["manual_review_required"] = True
    row["not_tradeable"] = True
    row["not_validation_ready"] = True
    row["operator_color_token"] = "runner"
    row["operator_subtitle"] = f"High RVOL runner ({rvol_s}) — manual review only (Entry Desk)"
    row["operator_pill"] = row.get("operator_pill") or f"RUNNER · {rvol_s}"
    row["operator_tooltip_hints"] = [
        f"RVOL {rvol_s} ≥ {HIGH_RVOL_THRESHOLD:.0f}x — Ross-style momentum runner",
        "Was WAIT — upgraded to MANUAL_REVIEW for operator awareness",
        "Not auto GO — use Entry Desk for discretionary entry",
    ]
    if chg_s:
        row["operator_tooltip_hints"].insert(0, f"Change {chg_s}")
    row["soft_flag_reason"] = row.get("soft_flag_reason") or f"HIGH_RVOL_RUNNER: {rvol_s} RVOL (threshold {HIGH_RVOL_THRESHOLD:.0f}x)"
    row["runner_sort_score"] = runner_sort_score(row)
    if row.get("score", 0) < 30:
        row["score"] = int(min(44, max(28, row["runner_sort_score"] / 12)))
    return row


def attach_high_rvol_manual_tags(tickers: list[dict], *, threshold: float = HIGH_RVOL_THRESHOLD) -> int:
    """Upgrade WAIT + high RVOL rows to MANUAL_REVIEW. Returns count upgraded."""
    n = 0
    for row in tickers:
        if not qualifies_high_rvol_manual(row, threshold=threshold):
            continue
        apply_high_rvol_manual_fields(row)
        n += 1
    return n