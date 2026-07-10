"""Reverse-split squeeze → MANUAL_REVIEW lane (Ross Cameron alignment).

Hard-DQ only on extreme halt risk (sub-500K float + RVOL>50). Other recent reverse
splits route to operator manual review — never auto GO, never invisible AVOID.
"""
from __future__ import annotations

from typing import Any


def _num(row: dict, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        raw = row.get(k)
        if raw is None or raw == "":
            continue
        try:
            return float(str(raw).replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
    return default


def detect_reverse_split_reason(symbol: str) -> str | None:
    """Return REVERSE_SPLIT reason string if split within 60d, else None."""
    try:
        import pandas as pd
        import yfinance as yf
        from datetime import timedelta

        actions = yf.Ticker(symbol).actions
        if actions is None or actions.empty or "Stock Splits" not in actions.columns:
            return None
        cutoff = (
            pd.Timestamp.now(tz=actions.index.tz) - timedelta(days=60)
            if actions.index.tz
            else pd.Timestamp.now() - timedelta(days=60)
        )
        recent = actions[
            (actions.index >= cutoff)
            & (actions["Stock Splits"] > 0)
            & (actions["Stock Splits"] < 1.0)
        ]
        if recent.empty:
            return None
        ratio = recent["Stock Splits"].iloc[-1]
        dt = recent.index[-1].strftime("%Y-%m-%d")
        return f"REVERSE_SPLIT: {ratio:.2f}:1 on {dt} — delisting avoidance"
    except Exception:
        return None


def is_halt_risk_hard_block(row: dict) -> bool:
    float_m = _num(row, "float_m", "float")
    rvol = _num(row, "rvol", "relative_volume")
    return 0 < float_m < 0.5 and rvol > 50.0


def squeeze_sort_score(row: dict) -> float:
    rvol = _num(row, "rvol", "relative_volume")
    gap = abs(_num(row, "gap_pct", "gap_percent"))
    chg = abs(_num(row, "change_pct", "change_percent"))
    return max(rvol * max(gap, 1.0), chg, _num(row, "score"))


def apply_squeeze_manual_fields(row: dict, *, rs_reason: str) -> dict:
    """Mutate row in-place for MANUAL_REVIEW squeeze lane."""
    rvol = _num(row, "rvol", "relative_volume")
    gap = _num(row, "gap_pct", "gap_percent")
    chg = _num(row, "change_pct", "change_percent")
    rvol_s = f"{rvol:.1f}x" if rvol else "—"
    chg_s = f"+{chg:.1f}%" if chg else ""

    row["disqualified"] = False
    row["decision"] = "MANUAL_REVIEW"
    row["grade"] = row.get("grade") if row.get("grade") not in (None, "", "DISQUALIFIED") else "SQUEEZE"
    row["awareness_status"] = "SQUEEZE"
    row["setup_class"] = "squeeze"
    row["route"] = row.get("route") or "warrior_manual"
    row["route_actionability"] = "MANUAL_REVIEW"
    row["manual_review_required"] = True
    row["not_tradeable"] = True
    row["not_validation_ready"] = True
    row["operator_color_token"] = "squeeze"
    row["operator_subtitle"] = "Reverse-split squeeze — manual review only (Path A / Entry Desk)"
    row["operator_pill"] = row.get("operator_pill") or f"SQUEEZE · R/S · {rvol_s}"
    row["operator_tooltip_hints"] = [
        rs_reason[:120],
        "Not auto GO — Ross-style squeeze; use Entry Desk for discretionary entry",
    ]
    row["soft_flag_reason"] = rs_reason
    row["disqualification_reason"] = rs_reason
    row["squeeze_sort_score"] = squeeze_sort_score(row)
    if row.get("score", 0) < 30:
        row["score"] = int(min(45, max(30, row["squeeze_sort_score"] / 10)))
    return row


def classify_ticker_risk(symbol: str, row: dict) -> dict[str, Any]:
    """Classify pre-score risk. action: score | hard_dq | squeeze_manual | standard_dq."""
    reasons: list[str] = []

    rs = detect_reverse_split_reason(symbol)
    if rs:
        reasons.append(rs)

    price = _num(row, "price")
    change = abs(_num(row, "change_pct", "change_percent"))
    if price < 2.0 and change > 30:
        reasons.append(f"LOW_PRICE_SPIKE: ${price:.2f} up {change:.0f}% — pump or split distortion")

    float_m = _num(row, "float_m", "float")
    rvol = _num(row, "relative_volume", "rvol")
    mf_reason = None
    if 0 < float_m < 1.0 and rvol > 5.0:
        mf_reason = f"MICRO_FLOAT_RVOL: {float_m:.1f}M float with {rvol:.1f}x RVOL — manipulation risk"
        reasons.append(mf_reason)

    if rs and is_halt_risk_hard_block(row):
        return {"action": "hard_dq", "reasons": " | ".join(reasons), "reverse_split": rs}

    if rs:
        return {"action": "squeeze_manual", "reasons": rs, "reverse_split": rs}

    if is_halt_risk_hard_block(row):
        return {"action": "hard_dq", "reasons": " | ".join(reasons), "reverse_split": None}

    if mf_reason:
        other = [r for r in reasons if "MICRO_FLOAT" not in r]
        if not other or all("LOW_PRICE_SPIKE" in r for r in other):
            return {"action": "micro_float_manual", "reasons": mf_reason, "reverse_split": None}

    lp_reason = next((r for r in reasons if "LOW_PRICE_SPIKE" in r), None)
    if lp_reason and not is_halt_risk_hard_block(row):
        other = [r for r in reasons if "LOW_PRICE_SPIKE" not in r]
        if not other:
            return {"action": "low_price_manual", "reasons": lp_reason, "reverse_split": None}

    if reasons:
        return {"action": "standard_dq", "reasons": " | ".join(reasons), "reverse_split": None}

    return {"action": "score", "reasons": "", "reverse_split": None}


def is_disqualified_hard(symbol: str, row: dict) -> tuple[bool, str]:
    """Backward-compatible hard disqualification check (excludes squeeze manual path)."""
    risk = classify_ticker_risk(symbol, row)
    if risk["action"] in ("hard_dq", "standard_dq"):
        return True, risk["reasons"]
    return False, ""


def attach_squeeze_manual_tags(tickers: list[dict]) -> int:
    """Upgrade API/DB rows: reverse-split AVOID/DQ → MANUAL_REVIEW squeeze. Returns count."""
    n = 0
    for row in tickers:
        sym = str(row.get("symbol", "")).upper()
        if not sym:
            continue
        reason = str(row.get("disqualification_reason") or row.get("soft_flag_reason") or "")
        rs = "REVERSE_SPLIT" in reason
        if not rs:
            rs_reason = detect_reverse_split_reason(sym)
            if rs_reason:
                rs = True
                reason = rs_reason
        if not rs:
            continue
        if is_halt_risk_hard_block(row):
            continue
        if row.get("awareness_status") == "SQUEEZE" and row.get("decision") == "MANUAL_REVIEW":
            continue
        apply_squeeze_manual_fields(row, rs_reason=reason.split("|")[0].strip() if "|" in reason else reason)
        n += 1
    return n