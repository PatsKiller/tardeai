"""sec_filing_diff — deterministic like-for-like comparison of SEC XBRL facts.

Two facts are comparable only when their reporting *context* is equivalent.
For duration facts (revenue, net income, operating cash flow, capex, ...) this
means the same duration kind (annual vs quarterly vs YTD) and, where present,
the same fiscal period (fp) and frame type. Instantaneous facts (cash, debt,
shares) use point-in-time semantics keyed by end date.

When equivalence cannot be established the result is COMPARISON_UNAVAILABLE,
never a silently mismatched delta.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any

COMPARISON_OK = "OK"
COMPARISON_UNAVAILABLE = "COMPARISON_UNAVAILABLE"
COMPARISON_NOT_APPLICABLE = "NOT_APPLICABLE"

# Canonical financial-advisory keys -> US-GAAP tags.
FACT_TAGS = {
    "revenue": "Revenues",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "debt": "LongTermDebtNoncurrent",
    "shares": "EntityCommonStockSharesOutstanding",
    "segment_metrics": "SegmentReportingInformation",
}

# Nature of each canonical fact: duration (flow) or instantaneous (stock).
FACT_KINDS = {
    "revenue": "DURATION",
    "operating_income": "DURATION",
    "net_income": "DURATION",
    "operating_cash_flow": "DURATION",
    "capex": "DURATION",
    "segment_metrics": "DURATION",
    "cash": "INSTANT",
    "debt": "INSTANT",
    "shares": "INSTANT",
}

# Sign conventions so a delta is meaningful even when one period is negative.
SIGN_FLIP_KEYS = {"net_income", "operating_income", "operating_cash_flow"}

MATERIALITY_THRESHOLDS = {
    "revenue": 5.0,
    "operating_income": 10.0,
    "net_income": 10.0,
    "operating_cash_flow": 10.0,
    "capex": 15.0,
    "cash": 10.0,
    "debt": 10.0,
    "shares": 5.0,
    "segment_metrics": 10.0,
}

_QTRS = ("Q1", "Q2", "Q3", "Q4")


def _frame_type(frame: Any) -> str | None:
    """Classify an SEC `frame` string (e.g. CY2024, Q3CY2024) where possible."""
    if not frame:
        return None
    f = str(frame).upper()
    if f.startswith("CY") and len(f) == 6 and f[2:].isdigit():
        return "ANNUAL"
    if f.startswith("Q") and "CY" in f:
        return "QUARTERLY"
    if "YTD" in f or "YTD" in str(frame).upper():
        return "YTD"
    return None


def duration_kind(fact: Any) -> str | None:
    """Return the duration kind of a fact, or None if it cannot be established.

    Returns ANNUAL / QUARTERLY / YTD / INSTANT / None (unknown).
    """
    if not isinstance(fact, dict):
        return None
    start = fact.get("start")
    if not start:
        # No start date means an instantaneous (point-in-time) fact.
        return "INSTANT"
    ft = _frame_type(fact.get("frame"))
    if ft:
        return ft
    fp = str(fact.get("fp") or "").upper()
    if fp == "FY":
        return "ANNUAL"
    if fp in _QTRS:
        return "QUARTERLY"
    end = fact.get("end")
    if end:
        try:
            days = (_date.fromisoformat(str(end)) - _date.fromisoformat(str(start))).days
            if days >= 270:
                return "ANNUAL"
            if days >= 120:
                return "YTD"
            if days >= 60:
                return "QUARTERLY"
        except ValueError:
            pass
    return None


def _fp(fact: Any) -> str | None:
    if not isinstance(fact, dict):
        return None
    fp = str(fact.get("fp") or "").strip().upper()
    return fp or None


def _numeric(fact: Any):
    if not isinstance(fact, dict):
        return None
    try:
        return float(fact.get("value"))
    except (TypeError, ValueError):
        return None


def _select_by_key(facts: dict, key: str):
    """Look up a fact by canonical key then by tag."""
    if not isinstance(facts, dict):
        return None
    if key in facts:
        return facts[key]
    tag = FACT_TAGS.get(key)
    if tag and tag in facts:
        return facts[tag]
    return None


def compare_filing_facts(facts_a: dict, facts_b: dict) -> dict:
    """Compare two filing fact sets with like-for-like context enforcement."""
    out: dict = {
        "comparisons": {},
        "comparison_status": COMPARISON_OK,
        "unavailable_keys": [],
        "notes": [],
    }

    for key in FACT_TAGS:
        fact_a = _select_by_key(facts_a, key)
        fact_b = _select_by_key(facts_b, key)
        entry: dict[str, Any] = {
            "key": key,
            "tag": FACT_TAGS[key],
            "a": _numeric(fact_a),
            "b": _numeric(fact_b),
            "comparison_status": COMPARISON_OK,
            "reason": None,
            "delta": None,
            "delta_pct": None,
            "material": None,
        }

        if fact_a is None and fact_b is None:
            # Absent from both periods: not a comparison failure.
            entry["comparison_status"] = COMPARISON_NOT_APPLICABLE
            entry["reason"] = "not_present_either_period"
            out["comparisons"][key] = entry
            continue

        if fact_a is None or fact_b is None:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = "missing_fact"
            out["unavailable_keys"].append(key)
            out["comparisons"][key] = entry
            continue

        # Unit must match.
        unit_a = (fact_a.get("units") if isinstance(fact_a, dict) else None)
        unit_b = (fact_b.get("units") if isinstance(fact_b, dict) else None)
        if unit_a and unit_b and unit_a != unit_b:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = f"unit_mismatch {unit_a} vs {unit_b}"
            out["unavailable_keys"].append(key)
            out["comparisons"][key] = entry
            continue

        # Duration facts require like-for-like duration context.
        if FACT_KINDS.get(key) == "DURATION":
            ka = duration_kind(fact_a)
            kb = duration_kind(fact_b)
            if ka is None or kb is None or ka == "INSTANT" or kb == "INSTANT":
                entry["comparison_status"] = COMPARISON_UNAVAILABLE
                entry["reason"] = f"duration_context_unavailable ({ka} vs {kb})"
                out["unavailable_keys"].append(key)
                out["comparisons"][key] = entry
                continue
            if ka != kb:
                entry["comparison_status"] = COMPARISON_UNAVAILABLE
                entry["reason"] = f"duration_context_mismatch {ka} vs {kb}"
                out["unavailable_keys"].append(key)
                out["comparisons"][key] = entry
                continue
            if ka == "QUARTERLY":
                fpa = _fp(fact_a)
                fpb = _fp(fact_b)
                if fpa and fpb and fpa != fpb:
                    entry["comparison_status"] = COMPARISON_UNAVAILABLE
                    entry["reason"] = f"fiscal_period_mismatch {fpa} vs {fpb}"
                    out["unavailable_keys"].append(key)
                    out["comparisons"][key] = entry
                    continue

        a = entry["a"]
        b = entry["b"]
        if a is None or b is None:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = "non_numeric_value"
            out["unavailable_keys"].append(key)
            out["comparisons"][key] = entry
            continue

        delta = round(b - a, 6)
        entry["delta"] = delta
        if a != 0:
            entry["delta_pct"] = round((delta / abs(a)) * 100.0, 4)
        else:
            entry["delta_pct"] = None
        threshold = MATERIALITY_THRESHOLDS.get(key)
        if threshold is not None and entry["delta_pct"] is not None:
            entry["material"] = abs(entry["delta_pct"]) >= threshold
        out["comparisons"][key] = entry

    if out["unavailable_keys"]:
        out["comparison_status"] = COMPARISON_UNAVAILABLE
        out["notes"].append(
            f"{len(out['unavailable_keys'])} keys unavailable for like-for-like comparison"
        )
    return out
