"""Micro-float + RVOL → MANUAL_REVIEW lane (Ross Cameron alignment).

Softens DQ for float <1M with RVOL >5x. Hard-DQ only halt risk (float <0.5M + RVOL>50).
"""
from __future__ import annotations

from squeeze_manual_review import _num, is_halt_risk_hard_block
from high_rvol_manual_review import is_squeeze_row

MICRO_FLOAT_MAX_M = 1.0
MICRO_FLOAT_MIN_RVOL = 5.0


def micro_float_reason(row: dict) -> str | None:
    float_m = _num(row, "float_m", "float")
    rvol = _num(row, "rvol", "relative_volume")
    if 0 < float_m < MICRO_FLOAT_MAX_M and rvol > MICRO_FLOAT_MIN_RVOL:
        if is_halt_risk_hard_block(row):
            return None
        return f"MICRO_FLOAT_RVOL: {float_m:.1f}M float with {rvol:.1f}x RVOL — manual review"
    return None


def qualifies_micro_float_manual(row: dict) -> bool:
    if not row or is_squeeze_row(row):
        return False
    if row.get("awareness_status") == "MICRO_FLOAT":
        return False
    reason = str(row.get("disqualification_reason") or row.get("soft_flag_reason") or "")
    if "MICRO_FLOAT" in reason and not is_halt_risk_hard_block(row):
        return (row.get("decision") or "").upper() in ("AVOID", "WAIT", "NO_GO", "NO-GO", "")
    return micro_float_reason(row) is not None and (row.get("decision") or "").upper() != "GO"


def micro_float_sort_score(row: dict) -> float:
    rvol = _num(row, "rvol", "relative_volume")
    gap = abs(_num(row, "gap_pct", "gap_percent"))
    float_m = _num(row, "float_m", "float")
    return max(rvol * max(gap, 1.0), 100 / max(float_m, 0.1), _num(row, "score"))


def apply_micro_float_manual_fields(row: dict, *, mf_reason: str | None = None) -> dict:
    rvol = _num(row, "rvol", "relative_volume")
    float_m = _num(row, "float_m", "float")
    rvol_s = f"{rvol:.1f}x" if rvol else "—"
    float_s = f"{float_m:.2f}M" if float_m else "—"
    reason = mf_reason or micro_float_reason(row) or f"MICRO_FLOAT_RVOL: {float_s} / {rvol_s}"

    row["disqualified"] = False
    row["decision"] = "MANUAL_REVIEW"
    row["grade"] = row.get("grade") if row.get("grade") not in (None, "", "DISQUALIFIED") else "MICRO"
    row["awareness_status"] = "MICRO_FLOAT"
    row["setup_class"] = "micro_float_runner"
    row["route"] = row.get("route") or "warrior_manual"
    row["route_actionability"] = "MANUAL_REVIEW"
    row["manual_review_required"] = True
    row["not_tradeable"] = True
    row["not_validation_ready"] = True
    row["operator_color_token"] = "microFloat"
    row["operator_subtitle"] = f"Micro-float runner ({float_s} · {rvol_s}) — manual review only"
    row["operator_pill"] = row.get("operator_pill") or f"MICRO · {rvol_s}"
    row["operator_tooltip_hints"] = [
        reason[:120],
        "Not auto GO — Ross-style micro-float momentum; Entry Desk only",
    ]
    row["soft_flag_reason"] = reason
    row["disqualification_reason"] = reason
    row["micro_float_sort_score"] = micro_float_sort_score(row)
    if row.get("score", 0) < 30:
        row["score"] = int(min(43, max(28, row["micro_float_sort_score"] / 12)))
    return row


def attach_micro_float_manual_tags(tickers: list[dict]) -> int:
    n = 0
    for row in tickers:
        if not qualifies_micro_float_manual(row):
            continue
        reason = str(row.get("disqualification_reason") or row.get("soft_flag_reason") or "")
        if "MICRO_FLOAT" not in reason:
            reason = micro_float_reason(row) or reason
        apply_micro_float_manual_fields(row, mf_reason=reason.split("|")[0].strip() if "|" in reason else reason)
        n += 1
    return n