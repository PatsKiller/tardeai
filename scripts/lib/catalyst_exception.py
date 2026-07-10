"""P3 catalyst exception — warrior runner lanes skip catalyst requirement.

For squeeze / high-RVOL / micro-float / momentum runners: catalyst is optional,
grade capped at B, ceiling MANUAL_REVIEW (never auto-GO).
"""
from __future__ import annotations

from typing import Any

WARRIOR_SETUP_CLASSES = frozenset({
    "squeeze",
    "high_rvol_runner",
    "micro_float_runner",
    "momentum_runner",
    "low_price_runner",
})

_GRADE_CAP_ORDER = ("A+", "A", "B", "C", "D", "DISQUALIFIED", "SQUEEZE", "RUNNER", "MICRO")


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


def _cap_grade(grade: str, cap: str = "B") -> str:
    g = (grade or "C").upper()
    cap_u = cap.upper()
    try:
        if _GRADE_CAP_ORDER.index(g) < _GRADE_CAP_ORDER.index(cap_u):
            return g
    except ValueError:
        pass
    return cap


def is_warrior_setup(row: dict) -> bool:
    return (row.get("setup_class") or "") in WARRIOR_SETUP_CLASSES or (
        row.get("awareness_status") in ("SQUEEZE", "HIGH_RVOL", "MICRO_FLOAT", "MOMENTUM_RUNNER", "LOW_PRICE")
    )


def _momentum_runner_signal(row: dict) -> bool:
    rvol = _num(row, "rvol", "relative_volume")
    gap = abs(_num(row, "gap_pct", "gap_percent"))
    chg = abs(_num(row, "change_pct", "change_percent"))
    if rvol >= 5.0:
        return True
    return rvol >= 3.0 and (gap >= 20.0 or chg >= 25.0)


def qualifies_catalyst_exception(row: dict) -> bool:
    """True when catalyst should not block operator awareness."""
    if not row or row.get("disqualified"):
        return False
    dec = (row.get("decision") or "").upper()
    if dec == "MANUAL_REVIEW":
        return is_warrior_setup(row)
    if dec not in ("WAIT", "AVOID", "NO_GO", "NO-GO"):
        return False
    if is_warrior_setup(row):
        return True
    score = _num(row, "score")
    if score < 28:
        return False
    if not _momentum_runner_signal(row):
        return False
    cat_ok = row.get("catalyst_verified")
    if cat_ok is True and dec == "WAIT" and score >= 40:
        return False
    return True


def apply_catalyst_exception_fields(row: dict) -> dict:
    """Upgrade warrior runners: catalyst optional, grade cap B, MANUAL_REVIEW only."""
    rvol = _num(row, "rvol", "relative_volume")
    gap = abs(_num(row, "gap_pct", "gap_percent"))
    chg = abs(_num(row, "change_pct", "change_percent"))
    rvol_s = f"{rvol:.1f}x" if rvol else "—"

    existing_class = row.get("setup_class") or ""
    if existing_class not in WARRIOR_SETUP_CLASSES:
        row["awareness_status"] = row.get("awareness_status") or "MOMENTUM_RUNNER"
        row["setup_class"] = "momentum_runner"
        row["operator_color_token"] = row.get("operator_color_token") or "runner"
        row["operator_pill"] = row.get("operator_pill") or f"RUNNER · {rvol_s}"
        row["operator_subtitle"] = (
            row.get("operator_subtitle")
            or f"Momentum runner (catalyst optional) — manual review only"
        )
        row["soft_flag_reason"] = row.get("soft_flag_reason") or (
            f"MOMENTUM_RUNNER: RVOL {rvol_s}, gap {gap:.0f}%, chg {chg:.0f}% — catalyst optional"
        )

    row["decision"] = "MANUAL_REVIEW"
    row["grade"] = _cap_grade(str(row.get("grade") or "C"), "B")
    row["route"] = row.get("route") or "warrior_manual"
    row["route_actionability"] = "MANUAL_REVIEW"
    row["manual_review_required"] = True
    row["not_tradeable"] = True
    row["not_validation_ready"] = True
    row["catalyst_optional"] = True
    if row.get("score", 0) < 30:
        row["score"] = int(min(42, max(30, _num(row, "score") + 8)))
    return row


def attach_catalyst_exception_tags(tickers: list[dict]) -> int:
    n = 0
    for row in tickers:
        if not qualifies_catalyst_exception(row):
            continue
        if (row.get("decision") or "").upper() == "MANUAL_REVIEW" and is_warrior_setup(row):
            preserved = row.get("setup_class") in (
                "squeeze", "high_rvol_runner", "micro_float_runner", "low_price_runner",
            )
            row["grade"] = _cap_grade(str(row.get("grade") or "C"), "B")
            if not preserved:
                row["catalyst_optional"] = True
            continue
        apply_catalyst_exception_fields(row)
        n += 1
    return n