"""UNENRICHED_INJECT → MANUAL_REVIEW lane (2026-09-28, plan root cause 3).

Universe injects (Finviz top gainers) arrive without RVOL / gap / float when the screener export
did not carry the symbol. They used to be scored on empty data (11–13) and shown as NOGO. A row
with no data is not a NOGO; it is unscored. It surfaces for the desk and never reaches GO/WAIT.
"""
from __future__ import annotations


def _num(row: dict, *keys) -> float:
    for k in keys:
        try:
            v = float(row.get(k) or 0)
        except (TypeError, ValueError):
            continue
        if v:
            return v
    return 0.0


def qualifies_unenriched_inject(row: dict, scored: dict) -> bool:
    if not row.get("_enrichment_missing"):
        return False
    if (scored.get("decision") or "").upper() == "GO":
        return False
    return _num(scored, "rvol", "relative_volume") == 0 and _num(scored, "float_m", "float_shares") == 0


def apply_unenriched_inject_fields(row: dict) -> dict:
    sym = row.get("symbol", "")
    row["disqualified"] = False
    row["decision"] = "MANUAL_REVIEW"
    row["grade"] = row.get("grade") if row.get("grade") not in (None, "", "DISQUALIFIED") else "LOW"
    row["awareness_status"] = "UNENRICHED"
    row["setup_class"] = "unenriched_inject"
    row["route"] = row.get("route") or "warrior_manual"
    row["route_actionability"] = "MANUAL_REVIEW"
    row["manual_review_required"] = True
    row["manual_review_reason"] = "UNENRICHED_INJECT"
    row["not_tradeable"] = True
    row["not_validation_ready"] = True
    row["operator_color_token"] = row.get("operator_color_token") or "lowPrice"
    row["operator_subtitle"] = f"{sym}: injected without RVOL/gap/float — not scored, verify data before review"
    row["operator_pill"] = row.get("operator_pill") or "UNENRICHED"
    return row
