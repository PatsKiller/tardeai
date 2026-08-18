"""Validated research → durable memory candidate. NON_AUTHORITATIVE_CONTEXT.

Never admits price/holdings/cash/orders/stops/risk/credentials.
MEMORY_BEHAVIOR_INFLUENCE remains 0.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
FORBIDDEN = (
    "current price", "place an order", "buy now", "sell now",
    "raise risk", "modify stop", "2fa", "password", "api key",
)


def _forbidden(text: str) -> str | None:
    low = text.lower()
    for tok in FORBIDDEN:
        if tok in low:
            return tok
    return None


def _memory_safe_content(result: dict[str, Any]) -> str:
    """Pick a research observation that does not trip the authoritative-truth lint.

    Plan attach keeps the full summary (gaps about missing holdings/price data).
    Memory may not store those tokens. We do not invent claims — we only skip
    paragraphs that the existing gate would reject.
    """
    try:
        from lib.agent_memory_governance import is_forbidden_authoritative
    except ImportError:
        from scripts.lib.agent_memory_governance import is_forbidden_authoritative  # type: ignore
    candidates: list[str] = []
    for f in result.get("findings") or []:
        if isinstance(f, dict):
            candidates.append(str(f.get("text") or f.get("summary") or ""))
        else:
            candidates.append(str(f))
    for a in result.get("answers") or []:
        if isinstance(a, dict) and str(a.get("status") or "") == "answered":
            candidates.append(str(a.get("summary") or a.get("detail") or ""))
    if result.get("summary"):
        candidates.append(str(result.get("summary") or ""))
    if result.get("content"):
        candidates.append(str(result.get("content") or ""))
    for text in candidates:
        text = str(text or "").strip()
        if not text:
            continue
        if is_forbidden_authoritative(text) or _forbidden(text):
            continue
        return text[:800]
    return ""


def admit_from_research(
    result: dict[str, Any],
    *,
    critique: dict[str, Any] | None = None,
    lineage_id: str | None = None,
) -> dict[str, Any]:
    verdict = str((critique or {}).get("verdict") or "").upper()
    if verdict in {"FAILED", "INSUFFICIENT"}:
        return {"ok": False, "skipped": True, "reason": f"critique_{verdict or 'missing'}"}
    summary = _memory_safe_content(result)
    if not summary:
        return {"ok": False, "skipped": True, "reason": "no_memory_safe_summary"}
    hit = _forbidden(summary)
    if hit:
        return {"ok": False, "skipped": True, "reason": f"forbidden:{hit}"}
    symbol = str(result.get("symbol") or "").upper()
    rid = str(result.get("research_id") or result.get("result_id") or "")
    now = datetime.now(timezone.utc)
    rec = {
        "memory_type": "RESEARCH_REFERENCE",
        "subject": f"Research observation {symbol or 'OFFICE'}".strip(),
        "content": summary,
        "symbols": [symbol] if symbol else [],
        "confidence": float(result.get("confidence_score") or 0.5),
        "as_of": result.get("as_of") or now.isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "source_refs": [x for x in [rid, lineage_id] if x],
        "source_kind": "research_artifact",
        "authority_class": "NON_AUTHORITATIVE_CONTEXT",
        "admission_reason": "validated_research_bridge",
        "research_result_id": rid,
        "research_review_id": (critique or {}).get("verdict"),
        "lineage_id": lineage_id,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    try:
        from lib.agent_durable_memory import get_durable_provider
        from lib.agent_memory_admission import admit_candidate
    except ImportError:
        from scripts.lib.agent_durable_memory import get_durable_provider  # type: ignore
        from scripts.lib.agent_memory_admission import admit_candidate  # type: ignore
    try:
        prov = get_durable_provider()
        out = admit_candidate(rec, provider=prov, admitted_by="research_memory_bridge")
        return {"ok": True, "admission": out, "memory_type": "RESEARCH_REFERENCE"}
    except Exception as exc:
        # fail-soft: persist candidate-shaped receipt without claiming admit
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200], "candidate": rec}
