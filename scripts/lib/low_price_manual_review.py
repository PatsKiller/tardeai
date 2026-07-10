"""P4 low-price spike → MANUAL_REVIEW lane (Ross Cameron alignment).

Sub-$2 names with extreme % change surface for operator review — not hard DQ,
unless halt-risk block applies.
"""
from __future__ import annotations

from squeeze_manual_review import _num, is_halt_risk_hard_block
from high_rvol_manual_review import is_squeeze_row

LOW_PRICE_MAX = 2.0
LOW_PRICE_MIN_CHANGE = 30.0


def low_price_spike_reason(row: dict) -> str | None:
    price = _num(row, "price")
    change = abs(_num(row, "change_pct", "change_percent"))
    if 0 < price < LOW_PRICE_MAX and change > LOW_PRICE_MIN_CHANGE:
        if is_halt_risk_hard_block(row):
            return None
        return f"LOW_PRICE_SPIKE: ${price:.2f} up {change:.0f}% — pump or split distortion"
    return None


def qualifies_low_price_manual(row: dict) -> bool:
    if not row or is_squeeze_row(row):
        return False
    if row.get("awareness_status") == "LOW_PRICE":
        return False
    reason = str(row.get("disqualification_reason") or row.get("soft_flag_reason") or "")
    if "LOW_PRICE_SPIKE" in reason and not is_halt_risk_hard_block(row):
        return (row.get("decision") or "").upper() in ("AVOID", "WAIT", "NO_GO", "NO-GO", "")
    return low_price_spike_reason(row) is not None and (row.get("decision") or "").upper() != "GO"


def low_price_sort_score(row: dict) -> float:
    chg = abs(_num(row, "change_pct", "change_percent"))
    rvol = _num(row, "rvol", "relative_volume")
    return max(chg, rvol * 5, _num(row, "score"))


def apply_low_price_manual_fields(row: dict, *, lp_reason: str | None = None) -> dict:
    price = _num(row, "price")
    change = abs(_num(row, "change_pct", "change_percent"))
    reason = lp_reason or low_price_spike_reason(row) or f"LOW_PRICE_SPIKE: ${price:.2f}"

    row["disqualified"] = False
    row["decision"] = "MANUAL_REVIEW"
    row["grade"] = row.get("grade") if row.get("grade") not in (None, "", "DISQUALIFIED") else "LOW"
    row["awareness_status"] = "LOW_PRICE"
    row["setup_class"] = "low_price_runner"
    row["route"] = row.get("route") or "warrior_manual"
    row["route_actionability"] = "MANUAL_REVIEW"
    row["manual_review_required"] = True
    row["not_tradeable"] = True
    row["not_validation_ready"] = True
    row["operator_color_token"] = "lowPrice"
    row["operator_subtitle"] = f"Low-price spike (${price:.2f} · +{change:.0f}%) — manual review only"
    row["operator_pill"] = row.get("operator_pill") or f"LOW · +{change:.0f}%"
    row["operator_tooltip_hints"] = [
        reason[:120],
        "Not auto GO — Ross-style sub-$2 squeeze; Entry Desk only",
    ]
    row["soft_flag_reason"] = reason
    row["disqualification_reason"] = reason
    row["low_price_sort_score"] = low_price_sort_score(row)
    if row.get("score", 0) < 28:
        row["score"] = int(min(40, max(26, row["low_price_sort_score"] / 8)))
    return row


def attach_low_price_manual_tags(tickers: list[dict]) -> int:
    n = 0
    for row in tickers:
        if not qualifies_low_price_manual(row):
            continue
        reason = str(row.get("disqualification_reason") or row.get("soft_flag_reason") or "")
        if "LOW_PRICE_SPIKE" not in reason:
            reason = low_price_spike_reason(row) or reason
        apply_low_price_manual_fields(row, lp_reason=reason.split("|")[0].strip() if "|" in reason else reason)
        n += 1
    return n