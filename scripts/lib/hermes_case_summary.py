"""CASE_SUMMARY producer from attached VALID/PARTIAL Hermes research.

READ_ONLY_ADVISORY. Memory is NON_AUTHORITATIVE_CONTEXT. Completeness only —
never action, never notify, never a second research worker.

Mint only when the originating plan already joined a successful result
(hermes_result_id). Idempotent on (plan_id, hermes_result_id).
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.agent_memory_governance import (
    MEMORY_TYPE_CASE_SUMMARY,
    STATUS_ACTIVE,
    is_forbidden_authoritative,
)
from scripts.lib.hermes_research_loop import research_complete_is_attachable

AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE_KIND = "HERMES_VALID_COMPLETE"
PRODUCER = "hermes_case_summary"


def _syms(plan: dict[str, Any], result: dict[str, Any]) -> list[str]:
    raw = list(plan.get("symbols") or [])
    if result.get("symbol"):
        raw.append(result.get("symbol"))
    out: list[str] = []
    seen: set[str] = set()
    for s in raw:
        u = str(s or "").strip().upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def safe_case_subject(plan: dict[str, Any], result: dict[str, Any]) -> str:
    """Qualitative subject. Never a price/holding/cash/stop/order field name."""
    syms = _syms(plan, result)
    pid = str(plan.get("plan_id") or result.get("plan_id") or "")
    if len(syms) == 1:
        subj = f"research_case:{syms[0]}"
    elif pid:
        subj = f"hermes_case:{pid}"
    else:
        subj = "research_case:OFFICE"
    if is_forbidden_authoritative(subj):
        subj = f"hermes_case:{pid or 'unknown'}"
    return subj


def _answered_count(result: dict[str, Any]) -> tuple[int, int]:
    answers = result.get("answers") or []
    if not isinstance(answers, list):
        return 0, 0
    n = len(answers)
    ok = 0
    for a in answers:
        if isinstance(a, dict) and str(a.get("status") or "").lower() in {"answered", "ok", "complete"}:
            ok += 1
        elif not isinstance(a, dict) and a:
            ok += 1
    return ok, n


def safe_case_content(
    plan: dict[str, Any],
    result: dict[str, Any],
    critique: dict[str, Any] | None,
) -> str:
    """Qualitative case note. Strips paragraphs that name canonical financial truth."""
    verdict = str((critique or {}).get("verdict") or "").upper() or "UNKNOWN"
    rid = str(result.get("result_id") or plan.get("hermes_result_id") or "")
    research_id = str(result.get("research_id") or plan.get("hermes_research_id") or plan.get("research_id") or "")
    answered, total = _answered_count(result)
    qbit = f" Questions answered {answered}/{total}." if total else ""
    sit = str(plan.get("situation_type") or "").replace("_", " ").strip()
    sit_bit = f" Situation {sit}." if sit else ""
    body = (
        f"Hermes research {verdict} for this case. Result {rid} closed the research gap"
        f"{sit_bit}{qbit} Thesis tension remains advisory-only; no order or stop implied."
    )
    # Drop any accidental forbidden tokens from optional qualitative extras.
    extras: list[str] = []
    for blob in (result.get("desk_implications") or {},):
        if isinstance(blob, dict):
            for k in ("thesis_tension", "gap_closed", "note"):
                t = str(blob.get(k) or "").strip()
                if t and not is_forbidden_authoritative(t):
                    extras.append(t[:160])
    text = " ".join([body] + extras)[:800]
    if is_forbidden_authoritative(text):
        text = (
            f"Hermes research {verdict}. Result {rid} / request {research_id} "
            f"attached to the case. Advisory completeness only."
        )
    return text


def _refs(plan_id: str, research_id: str, result_id: str) -> list[str]:
    refs = [plan_id, research_id, result_id]
    return [r for r in refs if r]


def existing_case_summary(provider: Any, plan_id: str, result_id: str) -> Optional[dict[str, Any]]:
    pid, rid = str(plan_id or ""), str(result_id or "")
    if not pid or not rid:
        return None
    store = getattr(provider, "_store", {}) or {}
    for rec in store.values():
        if not isinstance(rec, dict):
            continue
        if rec.get("memory_type") != MEMORY_TYPE_CASE_SUMMARY:
            continue
        blob = " ".join(
            str(x) for x in (
                rec.get("plan_ids") or [],
                rec.get("source_refs") or [],
                rec.get("source_event_ids") or [],
            )
        )
        if pid in blob and rid in blob:
            return rec
    return None


def mint_case_summary_from_attached_research(
    plan: dict[str, Any] | None,
    result: dict[str, Any] | None,
    *,
    critique: dict[str, Any] | None = None,
    provider: Any = None,
) -> dict[str, Any]:
    """Admit one CASE_SUMMARY for a joined successful research result. Fail-soft."""
    out: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "memory_id": None,
        "authority": AUTHORITY,
        "memory_type": MEMORY_TYPE_CASE_SUMMARY,
        "notify": False,
        "financial_action": False,
    }
    plan = plan or {}
    result = result or {}
    if not research_complete_is_attachable(result, critique if isinstance(critique, dict) else None):
        out["skipped"] = True
        out["reason"] = "not_attachable"
        return out
    plan_id = str(plan.get("plan_id") or result.get("plan_id") or "")
    result_id = str(result.get("result_id") or plan.get("hermes_result_id") or "")
    research_id = str(result.get("research_id") or plan.get("hermes_research_id") or plan.get("research_id") or "")
    if not plan_id or not result_id or not research_id:
        out["skipped"] = True
        out["reason"] = "missing_join_ids"
        return out
    if str(plan.get("hermes_result_id") or "") not in {"", result_id}:
        # Plan is joined to a different result; this complete is not the live join.
        out["skipped"] = True
        out["reason"] = "plan_result_mismatch"
        return out

    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        from scripts.lib.agent_memory_admission import admit_candidate
    except Exception:
        from lib.agent_durable_memory import get_durable_provider  # type: ignore
        from lib.agent_memory_admission import admit_candidate  # type: ignore

    prov = provider or get_durable_provider()
    prior = existing_case_summary(prov, plan_id, result_id)
    if prior:
        out["ok"] = True
        out["skipped"] = True
        out["reason"] = "idempotent"
        out["memory_id"] = prior.get("memory_id")
        out["status"] = prior.get("status")
        return out

    subject = safe_case_subject(plan, result)
    content = safe_case_content(plan, result, critique)
    if is_forbidden_authoritative(subject) or is_forbidden_authoritative(content):
        out["skipped"] = True
        out["reason"] = "forbidden_authoritative_truth"
        return out

    refs = _refs(plan_id, research_id, result_id)
    raw = {
        "memory_type": MEMORY_TYPE_CASE_SUMMARY,
        "subject": subject,
        "content": content,
        "symbols": _syms(plan, result),
        "plan_ids": [plan_id],
        "case_ids": [plan_id],
        "source_refs": refs,
        "source_event_ids": refs,
        "source_kind": SOURCE_KIND,
        "confidence": 0.7,
        "producer": PRODUCER,
        "agent": PRODUCER,
        "admission_reason": "hermes_valid_complete_case_summary",
        "metadata": {
            "producer": PRODUCER,
            "source_kind_detail": SOURCE_KIND,
            "critique_verdict": str((critique or {}).get("verdict") or ""),
        },
    }
    receipt = admit_candidate(raw, provider=prov, admitted_by=PRODUCER)
    out["receipt"] = receipt
    out["subject"] = subject
    if receipt.get("accepted"):
        out["ok"] = True
        out["memory_id"] = receipt.get("memory_id")
        out["status"] = receipt.get("display_status") or STATUS_ACTIVE
        out["promotable"] = receipt.get("promotable")
    else:
        out["reason"] = receipt.get("reason") or "admit_rejected"
    return out
