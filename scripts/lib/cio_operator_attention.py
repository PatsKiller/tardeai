"""Interactive CIO answers from actual notification/suppression state.

"Why haven't you told me anything today?" and "What should I be paying attention to?"
must use the same office scan + envelope. Never hallucinate a situation.
"""
from __future__ import annotations

import re
from typing import Any

from scripts.lib.cio_advisory_message import render_advisory_message
from scripts.lib.cio_situation_state import detect_office_situations

AUTHORITY = "READ_ONLY_ADVISORY"

WHY_NOTHING_RE = re.compile(
    r"(?is)\bwhy\s+(haven'?t|have\s+not|didn'?t|did\s+not)\s+you\s+(?:tell|told)|"
    r"\banything\s+today\b|"
    r"\bnothing\s+today\b|"
    r"\bno\s+(?:alerts?|notifications?|updates?)\b|"
    r"\bwhy\s+so\s+quiet\b"
)
ATTENTION_RE = re.compile(
    r"(?is)\bwhat\s+should\s+i\s+be\s+paying\s+attention\s+to\b|"
    r"\bwhat\s+matters\s+now\b|"
    r"\bwhat'?s\s+(?:material|important)\s+(?:now|today)\b"
)


def looks_like_why_nothing(text: str) -> bool:
    return bool(WHY_NOTHING_RE.search(text or ""))


def looks_like_attention_query(text: str) -> bool:
    t = text or ""
    return looks_like_why_nothing(t) or bool(ATTENTION_RE.search(t))


def _reason_from_scan(scan: dict[str, Any]) -> str:
    if scan.get("notify"):
        return "MATERIAL_SITUATION"
    defer = scan.get("defer") or []
    if defer:
        return str(defer[0].get("suppression_reason") or "NEED_DATA")
    suppress = scan.get("suppress") or []
    if suppress:
        return str(suppress[0].get("suppression_reason") or "NO_MATERIAL_CHANGE")
    return "NO_MATERIAL_CHANGE"


def answer_attention_query(
    text: str,
    *,
    office: dict[str, Any] | None = None,
    scan: dict[str, Any] | None = None,
    envelope: dict[str, Any] | None = None,
    delivery_failure: str | None = None,
) -> dict[str, Any]:
    office = office or {}
    scan = scan or detect_office_situations(office)
    reason = _reason_from_scan(scan)
    if delivery_failure:
        reason = "DELIVERY_FAILURE"
    why_nothing = looks_like_why_nothing(text)
    primary = (scan.get("notify") or scan.get("defer") or scan.get("situations") or [{}])[0]
    if why_nothing:
        copy = {
            "NO_MATERIAL_CHANGE": "Nothing material changed in verified portfolio truth, so I did not page you.",
            "CASH_WITHIN_POLICY": "Cash is inside the confirmed policy range. No page.",
            "POLICY_REQUIRED_IMMATERIAL": "Policy is missing, but the book is not independently material enough to ask yet.",
            "SEMANTIC_DEDUPE": "I already told you this situation. I will not repeat it until something changes.",
            "NEED_DATA": "A situation exists but critical evidence is missing, so I deferred instead of paging.",
            "STALE_FINANCIAL_TRUTH": "Financial truth is stale, so I deferred rather than inventing a call.",
            "DELIVERY_FAILURE": "A notification was prepared but delivery failed. I did not hide a situation.",
            "MATERIAL_SITUATION": "There is a material situation. I should have told you — here is the current view.",
            "LESSON_CANDIDATE_NOT_POLICY": "An outcome matured into a lesson candidate. That is not a page.",
        }.get(reason, f"Notification state: {reason}.")
        if reason == "MATERIAL_SITUATION":
            body = render_advisory_message(primary)
        else:
            body = (
                "Alex · CIO NOW\n\n"
                "WHY YOU WERE NOT PAGED\n"
                f"{copy}\n\n"
                f"Suppression/decision: {reason}.\n"
                "I am not inventing a situation.\n\n"
                "No orders or stops. READ_ONLY_ADVISORY."
            )
    else:
        if scan.get("notify"):
            body = render_advisory_message(primary)
        else:
            body = (
                "Alex · CIO NOW\n\n"
                "WHAT TO PAY ATTENTION TO\n"
                f"{_reason_from_scan(scan)} — no new material operator page.\n"
                "Same CIO brain as the proactive loop; nothing was invented for chat.\n\n"
                "No orders or stops. READ_ONLY_ADVISORY."
            )
    return {
        "schema": "CIOAttentionAnswer@v1",
        "authority": AUTHORITY,
        "kind": "why_nothing" if why_nothing else "attention",
        "reason": reason,
        "text": body,
        "used_scan": True,
        "same_brain": envelope is not None or bool(office),
        "envelope_present": envelope is not None,
        "financial_action": False,
        "hallucinated": False,
        "situation_id": primary.get("situation_id"),
    }
