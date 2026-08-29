"""Governed research quality / critique. No future outcomes as inputs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
VERDICTS = ("VALID", "PARTIAL", "STALE", "CONFLICTED", "INSUFFICIENT", "FAILED")

# The tighter imperative gate (execution_language.find_imperative) applies to
# results completed from here on. Artifacts already in the store keep the verdict
# they were admitted under: re-running critique must not silently detach research
# a plan is already relying on. Exactly one stored result would have flipped, an
# SRNE artifact reading "exit the position" whose plan is already cancelled — the
# grandfather is a rule, not a rescue.
#
# The legacy floor below still applies to every result, new or old, so nothing is
# loosened for the grandfathered set.
IMPERATIVE_GATE_EFFECTIVE = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
LEGACY_FORBIDDEN = ("ignore all rules", "place an order")


def _completed_at(result: dict[str, Any]) -> Any:
    for key in ("completed_ts", "as_of", "created_ts", "freshness_date"):
        raw = str(result.get(key) or "").strip()
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def imperative_gate_applies(result: dict[str, Any]) -> bool:
    """New completes only. An undated artifact is treated as pre-existing."""
    at = _completed_at(result)
    return at is not None and at >= IMPERATIVE_GATE_EFFECTIVE


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
    if any(p in text for p in LEGACY_FORBIDDEN):
        # Legacy floor — applies to every result, new or grandfathered.
        reasons.append("forbidden_authority")
    elif imperative_gate_applies(result):
        # One shared matcher with the ingest gate; grammatical, not a word list.
        try:
            from scripts.lib.execution_language import find_imperative
        except Exception:
            find_imperative = None      # fail open to the legacy floor
        if find_imperative is not None and find_imperative(result):
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
