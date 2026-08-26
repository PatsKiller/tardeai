"""Canonical human renderer for CIOOperatorProduct@v1.

Do NOT send raw product JSON to the operator.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"

_DECISIONS = (
    "HOLD", "WAIT", "WATCH", "REVIEW", "TRIM", "REENTER", "AVOID", "NO_ACTION", "HOLD_CASH",
)
_URGENCY = ("NOW", "TODAY", "NEXT_SESSION", "WATCH_ONLY", "NONE")


def _urgency(entry: dict[str, Any]) -> str:
    raw = str(entry.get("what_should_i_do") or entry.get("urgency") or "NONE").upper()
    aliases = {"NOTHING": "NONE", "WATCH": "WATCH_ONLY"}
    raw = aliases.get(raw, raw)
    return raw if raw in _URGENCY else "NONE"


def _decision(entry: dict[str, Any]) -> str:
    raw = str(entry.get("cio_decision") or entry.get("decision") or "NO_ACTION").upper()
    aliases = {"RE_ENTER": "REENTER", "HOLD_POSTURE": "HOLD", "HOLD_CASH": "HOLD"}
    raw = aliases.get(raw, raw)
    return raw if raw in _DECISIONS else "REVIEW"


def render_decision(entry: dict[str, Any]) -> str:
    entity = entry.get("symbol") or entry.get("entity") or "PORTFOLIO"
    lines = [
        f"[CIO DECISION] {entity}",
        "",
        f"Decision: {_decision(entry)}",
        f"Urgency: {_urgency(entry)}",
        "",
        f"What changed: {entry.get('what_changed') or '—'}",
        "",
        f"Why it matters: {entry.get('why_it_matters') or entry.get('why') or '—'}",
        "",
        f"Operator action: {entry.get('operator_action') or entry.get('what_should_i_do') or 'NONE'}",
        "",
        f"Confidence: {entry.get('confidence') if entry.get('confidence') is not None else '—'}",
        "",
        f"Counter-evidence: {entry.get('counter_evidence') or 'none cited'}",
        "",
        f"Data quality: {entry.get('data_quality') or 'OK'}",
        "",
        f"Next review: {entry.get('next_review') or 'unscheduled'}",
        "",
        "READ_ONLY_ADVISORY — no order is being placed.",
    ]
    return "\n".join(lines)


def render_product(product: dict[str, Any]) -> str:
    if not product:
        return "CIO_PRODUCT_UNAVAILABLE\nreason: PRODUCER_NOT_RUN"
    status = product.get("status") or product.get("reason")
    if product.get("available") is False or status not in (None, "AVAILABLE"):
        last = product.get("last_valid_product") or {}
        lines = [
            "CIO_PRODUCT_UNAVAILABLE",
            f"status: {status or 'PRODUCER_NOT_RUN'}",
            f"data quality: {product.get('operator_data_quality') or 'UNAVAILABLE'}",
        ]
        if product.get("detail"):
            lines.append(str(product.get("detail")))
        if last:
            lines.append(
                f"last valid product: {last.get('product_id') or last.get('generation_id') or 'ref'}"
            )
        return "\n".join(lines)
    chunks = []
    summary = product.get("executive_summary")
    if summary:
        chunks.append("CIO OPERATOR PRODUCT")
        chunks.append(str(summary).strip())
    for e in product.get("entries") or product.get("decisions") or []:
        if isinstance(e, dict):
            chunks.append(render_decision(e))
    if not chunks:
        chunks.append("CIO OPERATOR PRODUCT")
        chunks.append("No material operator decisions in this generation.")
        chunks.append("Standing posture: HOLD unless a later material generation says otherwise.")
    return "\n\n".join(chunks).strip()


def looks_like_raw_json(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("{") and t.endswith("}") and ("schema" in t or "\"error\"" in t):
        return True
    if t.startswith("[") and '"symbol"' in t and '"rationale"' in t:
        return True
    if "COST_CONFIGURATION_INVALID" in t and t.startswith("{"):
        return True
    return False
