"""Deterministic filing-fact comparison (filing diff intelligence).

Compares two periods of SEC company facts and returns structured changed_facts,
not prose. If a fact cannot be safely mapped across taxonomy/unit changes it is
reported as COMPARISON_UNAVAILABLE rather than silently compared. Pure module:
no network, no database.
"""
from __future__ import annotations

from typing import Optional

COMPARISON_UNAVAILABLE = "COMPARISON_UNAVAILABLE"
COMPARISON_OK = "OK"
MISSING = "MISSING"

# Canonical financial-advisory fact keys -> representative US-GAAP XBRL tags.
# These are display keys for structured comparison only; they carry no
# directional trade authority.
FACT_TAGS: dict[str, str] = {
    "revenue": "Revenues",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "debt": "LongTermDebtNoncurrent",
    "shares": "CommonStockSharesOutstanding",
}

# Relative-change thresholds (%) above which a change is flagged material.
MATERIALITY_THRESHOLDS: dict[str, float] = {
    "revenue": 5.0,
    "operating_income": 10.0,
    "net_income": 10.0,
    "operating_cash_flow": 10.0,
    "capex": 15.0,
    "cash": 10.0,
    "debt": 10.0,
    "shares": 2.0,
}


def _as_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _units_of(fact) -> Optional[str]:
    if isinstance(fact, dict):
        return fact.get("units")
    return None


def _value_of(fact):
    if isinstance(fact, dict):
        return fact.get("value")
    return fact


def compare_filing_facts(
    facts_a: dict,
    facts_b: dict,
    fact_map: Optional[dict[str, str]] = None,
) -> dict:
    """Compare flattened fact dicts for two periods.

    facts_a/facts_b may be keyed either by XBRL tag (default) or by canonical
    fact key (when `fact_map` is provided mapping canonical key -> tag).

    Returns:
        changed_facts: {key: {period_a, period_b, delta, delta_pct, units,
                              comparison_status}}
        materiality:    {key: bool}
        unmapped:       [tags present but without a canonical mapping]
        source_refs:    []
        quality:        "HIGH" | "MEDIUM" | "LOW"
    """
    fact_map = fact_map or FACT_TAGS
    changed: dict = {}
    materiality: dict = {}
    unmapped: list[str] = []

    # Determine whether inputs are tag-keyed or canonical-key-keyed.
    tag_keys = set(fact_map.values())
    a_keys = set(facts_a or {})
    b_keys = set(facts_b or {})

    for key, tag in fact_map.items():
        a_fact = None
        b_fact = None
        if key in a_keys:
            a_fact = facts_a[key]
        elif tag in a_keys:
            a_fact = facts_a[tag]
        if key in b_keys:
            b_fact = facts_b[key]
        elif tag in b_keys:
            b_fact = facts_b[tag]

        a_val = _value_of(a_fact)
        b_val = _value_of(b_fact)
        a_units = _units_of(a_fact)
        b_units = _units_of(b_fact)

        entry: dict = {
            "period_a": a_val,
            "period_b": b_val,
            "delta": None,
            "delta_pct": None,
            "units": a_units or b_units,
            "comparison_status": COMPARISON_OK,
        }

        if a_val is None and b_val is None:
            entry["comparison_status"] = MISSING
        elif a_val is None or b_val is None:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = "one period missing"
        elif a_units is not None and b_units is not None and a_units != b_units:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = f"unit mismatch: {a_units} vs {b_units}"
        else:
            fa = _as_float(a_val)
            fb = _as_float(b_val)
            if fa is None or fb is None:
                entry["comparison_status"] = COMPARISON_UNAVAILABLE
                entry["reason"] = "non-numeric value"
            else:
                entry["delta"] = fb - fa
                if fa != 0:
                    entry["delta_pct"] = round(((fb - fa) / abs(fa)) * 100.0, 4)

        is_material = False
        if entry["comparison_status"] == COMPARISON_OK and entry["delta_pct"] is not None:
            thr = MATERIALITY_THRESHOLDS.get(key, 10.0)
            is_material = abs(entry["delta_pct"]) >= thr
            # net income sign flip is always material
            fa = _as_float(a_val)
            fb = _as_float(b_val)
            if key == "net_income" and fa is not None and fb is not None and (fa < 0) != (fb < 0):
                is_material = True
        materiality[key] = is_material
        changed[key] = entry

    # Unmapped tags: present in either input but without a canonical mapping.
    all_input_keys = a_keys | b_keys
    mapped = set(fact_map.keys()) | tag_keys
    unmapped = sorted(all_input_keys - mapped)

    return {
        "changed_facts": changed,
        "materiality": materiality,
        "unmapped": unmapped,
        "source_refs": [],
        "quality": "HIGH" if not unmapped else "MEDIUM",
    }
