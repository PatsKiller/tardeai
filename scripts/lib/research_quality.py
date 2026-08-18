"""Governed research quality / critique. No future outcomes as inputs."""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
VERDICTS = ("VALID", "PARTIAL", "STALE", "CONFLICTED", "INSUFFICIENT", "FAILED")


def critique(result: dict[str, Any]) -> dict[str, Any]:
    sources = result.get("sources") or result.get("source_urls") or []
    if isinstance(sources, str):
        sources = [sources]
    claims = result.get("claims") or result.get("summary") or ""
    text = str(claims).lower()
    as_of = str(result.get("as_of") or result.get("freshness_date") or "")
    symbol = str(result.get("symbol") or "")
    reasons: list[str] = []
    if not text or text.strip() in {"", "n/a", "todo"}:
        reasons.append("empty_summary")
    if not sources:
        reasons.append("no_sources")
    if "ignore all rules" in text or "place an order" in text:
        reasons.append("forbidden_authority")
    if symbol and symbol.lower() not in text and symbol not in str(result):
        reasons.append("symbol_not_grounded")
    if "as of 20" not in text and not as_of:
        reasons.append("no_as_of")
    if "however" in text and "contradict" in text:
        reasons.append("unresolved_contradiction")
    if "forbidden_authority" in reasons:
        verdict = "FAILED"
    elif "empty_summary" in reasons:
        verdict = "INSUFFICIENT"
    elif "no_sources" in reasons:
        verdict = "PARTIAL"
    elif "unresolved_contradiction" in reasons:
        verdict = "CONFLICTED"
    elif reasons:
        verdict = "PARTIAL"
    else:
        verdict = "VALID"
    return {
        "schema": "ResearchCritique@v1",
        "verdict": verdict,
        "reasons": reasons,
        "source_count": len(sources),
        "authority": AUTHORITY,
        "financial_action": False,
        "research_id": result.get("research_id") or result.get("result_id"),
        "symbol": symbol,
    }
