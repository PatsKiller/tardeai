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


def render_decision(entry: dict[str, Any], product: dict[str, Any] | None = None) -> str:
    """Render one operator-facing decision.

    `product` is optional so existing single-argument callers keep working. When
    supplied it carries the product-level verdicts the system already computes
    and previously rendered nowhere (A3).
    """
    entity = entry.get("symbol") or entry.get("entity") or "PORTFOLIO"
    conf = entry.get("confidence_text")
    # The contract stamps confidence_text = "not provided ..." whenever the
    # per-decision score is absent, which pre-empts the product-level label
    # below. Treat that stamp as the absence it describes.
    if isinstance(conf, str) and conf.lstrip().lower().startswith("not provided"):
        pc = (product or {}).get("confidence")
        if pc is not None:
            conf = f"not computed for this decision (product-level: {pc})"
    if conf is None:
        conf = entry.get("confidence")
        if conf is not None:
            conf = str(conf)
        else:
            # A3: a product-level confidence exists even where the per-decision
            # value does not. Name it as product-level rather than implying it was
            # computed for this decision -- and never fabricate one.
            pc = (product or {}).get("confidence")
            conf = (f"not computed for this decision (product-level: {pc})"
                    if pc is not None else
                    "not provided — no numeric score this generation (not fabricated)")
    counter = entry.get("counter_evidence") or "none cited — invalidation condition not in producer payload"
    nxt = entry.get("next_review_at") or entry.get("next_review") or "not provided — standing cadence (next material generation or next session)"
    lines = [
        f"[CIO DECISION] {entity}",
        "",
        f"Decision: {_decision(entry)}",
        f"Urgency: {_urgency(entry)}",
        "",
        f"What changed: {entry.get('what_changed') or 'not provided'}",
        "",
        f"Why it matters: {entry.get('why_it_matters') or entry.get('why') or 'not provided'}",
        "",
        f"Your action: {entry.get('operator_action') or entry.get('what_should_i_do') or 'NONE'}",
        "",
        f"Confidence: {conf}",
        "",
        f"Counterpoint: {counter}",
        "",
        f"Data quality: {_data_quality(entry, product)}",
        "",
        f"Next review: {nxt}",
        "",
        "READ_ONLY_ADVISORY — no order is being placed.",
    ]
    completeness = _completeness_line(entry, product)
    if completeness:
        lines.insert(len(lines) - 1, completeness)
        lines.insert(len(lines) - 1, "")
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
            chunks.append(render_decision(e, product))
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


def _data_quality(entry: dict[str, Any], product: dict[str, Any] | None) -> str:
    """The real verdict, or an honest absence -- never a defaulted "OK".

    A2. The absent case used to render as "OK", an affirmative all-clear
    asserted by a default, printed under all eight decisions in a document whose
    own holdings verdict was ATTENTION with two named defects.
    """
    own = entry.get("data_quality")
    if own:
        return str(own)
    for key in ("holdings_data_quality", "data_quality"):
        block = (product or {}).get(key)
        if isinstance(block, dict) and block.get("state"):
            labels = ", ".join(block.get("labels") or [])
            return f"{block['state']}" + (f" — {labels}" if labels else "")
    return "not computed for this decision"


def _completeness_line(entry: dict[str, Any], product: dict[str, Any] | None) -> str:
    """Say what the system already knows about its own gaps.

    A3. `field_status` and `completeness.grade` are computed on every entry and
    reached no operator surface: the reader saw four confident-looking lines
    while the machine had already recorded them as unpopulated.
    """
    status = entry.get("field_status") or {}
    missing = sorted(k for k, v in status.items() if v == "NOT_PROVIDED")
    grade = ((product or {}).get("completeness") or {}).get("grade")
    if not missing and not grade:
        return ""
    parts = []
    if missing:
        parts.append(f"{len(missing)} of {len(status)} fields unpopulated ({', '.join(missing)})")
    if grade:
        parts.append(str(grade))
    return "Completeness: " + " · ".join(parts)
