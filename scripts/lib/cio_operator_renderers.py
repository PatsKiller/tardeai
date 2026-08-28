"""Morning / EOD / Aegis / Command Center / Telegram renderers.

All consume CIOOperatorProduct@v1. None independently reconstruct investment truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.brief_semantic_dedupe import claim, session_date
from scripts.lib.cio_operator_product import build_operator_product
from scripts.lib.operator_human_renderer import render_decision, render_product
from scripts.lib.research_intelligence_summary import from_research_result, render_human as render_research

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def _product(root: Path | str | None, supplemental: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_operator_product(root=root, persist=False, supplemental=supplemental)


def morning_text(product: dict[str, Any]) -> str:
    if product.get("available") is False:
        return render_product(product)
    lines = ["☀️ MORNING CIO BRIEF", ""]
    if product.get("executive_summary"):
        lines.append(str(product["executive_summary"]).strip())
        lines.append("")
    cash = product.get("cash") or {}
    if cash:
        lines.append(f"Cash: {cash.get('status')} ${cash.get('cash_usd') or 0:,.0f}" if cash.get("cash_usd") is not None else f"Cash: {cash.get('status')}")
    port = product.get("portfolio") or {}
    if port.get("holdings_n"):
        lines.append(f"Holdings: {port.get('holdings_n')} names")
    dq = product.get("data_quality") or {}
    if dq.get("state") and dq.get("state") not in {"OK", "CURRENT"}:
        lines.append(f"Data quality: {dq.get('state')} — {dq.get('note') or ''}".rstrip(" —"))
    lines.append("")
    action_now = product.get("action_now") or []
    if action_now:
        lines.append("ACTION NOW")
        for e in action_now[:8]:
            lines.append(render_decision(e))
            lines.append("")
    else:
        lines.append("No ACT-NOW items. Standing posture below.")
        lines.append("")
        for e in (product.get("standing_decisions") or product.get("entries") or [])[:5]:
            if isinstance(e, dict):
                lines.append(f"- {e.get('symbol') or ''} {e.get('cio_decision')} — {e.get('what_changed')}".strip())
        lines.append("")
    reentry = product.get("reentry") or {}
    if reentry.get("count"):
        counts = reentry.get("counts") or {}
        lines.append(f"Re-entry book: {reentry.get('count')} names {counts}".strip())
    secs = product.get("sector") or []
    if secs:
        lines.append("Sector")
        for sec in secs[:6]:
            if isinstance(sec, dict) and sec.get("prose"):
                lines.append(sec["prose"])
    elif product.get("sector_reason"):
        lines.append(f"Sector: {product.get('sector_reason')}")
    inds = product.get("industry") or []
    if inds:
        lines.append("Industry")
        for ind in inds[:4]:
            if isinstance(ind, dict) and ind.get("prose"):
                lines.append(ind["prose"])
    cats = product.get("catalysts") or []
    if cats:
        lines.append("Catalysts")
        for c in cats[:4]:
            if isinstance(c, dict):
                lines.append(
                    f"- {c.get('entity') or ''} {c.get('catalyst')}: {c.get('why_relevant') or c.get('when') or ''}".strip()
                )
    elif product.get("catalysts_reason"):
        lines.append(f"Catalysts: {product.get('catalysts_reason')}")
    cases = product.get("case_summaries") or product.get("research_cases") or {}
    case_items = cases.get("items") if isinstance(cases, dict) else cases
    if case_items:
        top_syms: list[str] = []
        for it in case_items[:3]:
            if not isinstance(it, dict):
                continue
            for s in (it.get("symbols") or []):
                u = str(s).upper()
                if u and u not in top_syms:
                    top_syms.append(u)
            if not it.get("symbols") and it.get("subject"):
                top_syms.append(str(it["subject"]).split(":")[-1])
        n = cases.get("count") if isinstance(cases, dict) and cases.get("count") is not None else len(case_items)
        bit = f" · {', '.join(top_syms[:3])}" if top_syms else ""
        lines.append(f"Research cases (A-context, not action): {n}{bit}")
    lines.append("Open: Command Center → CIO. READ_ONLY_ADVISORY.")
    return "\n".join(lines).strip()


def eod_text(product: dict[str, Any]) -> str:
    if product.get("available") is False:
        return render_product(product)
    lines = ["🌆 EOD CIO BRIEF", ""]
    if product.get("executive_summary"):
        lines.append(str(product["executive_summary"]).strip())
        lines.append("")
    material = [e for e in (product.get("decisions") or []) if e.get("cio_decision") in {"TRIM", "REENTER", "AVOID", "REVIEW"}]
    if material:
        lines.append("Meaningful changes")
        for e in material[:8]:
            lines.append(render_decision(e))
            lines.append("")
    else:
        lines.append("No material CIO change this session.")
        lines.append("")
    lines.append("Standing overnight posture")
    for e in (product.get("standing_decisions") or [])[:6]:
        lines.append(f"- {e.get('symbol') or 'PORTFOLIO'} {e.get('cio_decision')}: {e.get('what_changed')}")
    dq = product.get("data_quality") or {}
    if dq.get("state") not in (None, "OK", "CURRENT"):
        lines.append(f"Data quality overnight: {dq.get('state')}")
    cases = product.get("case_summaries") or product.get("research_cases") or {}
    case_items = cases.get("items") if isinstance(cases, dict) else cases
    if case_items:
        top_syms: list[str] = []
        for it in case_items[:3]:
            if not isinstance(it, dict):
                continue
            for s in (it.get("symbols") or []):
                u = str(s).upper()
                if u and u not in top_syms:
                    top_syms.append(u)
        n = cases.get("count") if isinstance(cases, dict) and cases.get("count") is not None else len(case_items)
        bit = f" · {', '.join(top_syms[:3])}" if top_syms else ""
        lines.append(f"Research cases (A-context, not action): {n}{bit}")
    lines.append("READ_ONLY_ADVISORY — no order is being placed.")
    return "\n".join(lines).strip()


def aegis_summary(product: dict[str, Any]) -> dict[str, Any]:
    """Aegis may summarize CIO state; it cannot create competing CIO truth."""
    return {
        "role": "PROTECTION_SURVEILLANCE_DATA_HEALTH_OVERNIGHT_RISK",
        "source": "cio.operator_product.current",
        "available": product.get("available"),
        "status": product.get("status"),
        "generation_id": product.get("generation_id"),
        "executive_summary": product.get("executive_summary"),
        "action_now_n": len(product.get("action_now") or []),
        "data_quality": product.get("data_quality"),
        "creates_cio_truth": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def command_center_view(product: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    for e in product.get("decisions") or product.get("entries") or []:
        if not isinstance(e, dict):
            continue
        decisions.append({
            "decision_id": e.get("decision_id"),
            "decision": e.get("decision") or e.get("cio_decision"),
            "urgency": e.get("urgency") or e.get("what_should_i_do"),
            "reason": e.get("why_it_matters") or e.get("why"),
            "confidence": e.get("confidence"),
            "confidence_status": e.get("confidence_status"),
            "counter_evidence": e.get("counter_evidence"),
            "research_provenance": e.get("source"),
            "entity_identity": e.get("entity") or e.get("symbol"),
            "data_quality": e.get("data_quality"),
            "next_review": e.get("next_review_at") or e.get("next_review"),
            "generation_id": e.get("generation_id") or product.get("generation_id"),
        })
    return {
        "source": "cio.operator_product.current",
        "loaded": bool(product.get("available")),
        "status": product.get("status"),
        "generation_id": product.get("generation_id"),
        "product_id": product.get("product_id"),
        "as_of": product.get("as_of"),
        "executive_summary": product.get("executive_summary"),
        "earnings": list(product.get("earnings") or [])[:12],
        "case_summaries": product.get("case_summaries") or product.get("research_cases") or {
            "banner": "A-context · NON_AUTHORITATIVE · does not change action",
            "class": "A",
            "count": 0,
            "items": [],
        },
        "decisions": decisions,
        "history_store": "cio.operator_product.history",
        "hidden_alternative_calculation": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def telegram_text(product: dict[str, Any]) -> str:
    return render_product(product)


def deliver_morning(*, root: Path | str, supplemental_bundle: dict[str, Any] | None = None,
                    send: bool = True, now: datetime | None = None) -> dict[str, Any]:
    product = _product(root, supplemental_bundle)
    gen = str(product.get("generation_id") or product.get("status") or "unavailable")
    sess = session_date(now)
    claim_res = claim(kind="MORNING", session=sess, material_generation=gen, root=root)
    text = morning_text(product)
    published = bool(claim_res.get("published"))
    sent = False
    if published and send:
        try:
            from telegram_alert import send_telegram
            sent = bool(send_telegram(text, bypass_router=True))
        except Exception as exc:
            return {
                "handled": True,
                "published": False,
                "ok": False,
                "reason": f"send_failed:{type(exc).__name__}",
                "text": text,
                "product_status": product.get("status"),
                "key": claim_res.get("key"),
                "consumer": "morning",
                "authority": AUTHORITY,
                "financial_action": False,
            }
    return {
        "handled": True,
        "published": published,
        "ok": True,
        "sent": sent,
        "reason": claim_res.get("reason"),
        "key": claim_res.get("key"),
        "text": text,
        "product_status": product.get("status"),
        "consumer": "morning",
        "source": "cio.operator_product.current",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def deliver_eod(*, root: Path | str, send: bool = False, now: datetime | None = None) -> dict[str, Any]:
    product = _product(root)
    gen = str(product.get("generation_id") or product.get("status") or "unavailable")
    sess = session_date(now)
    claim_res = claim(kind="EOD", session=sess, material_generation=gen, root=root)
    text = eod_text(product)
    published = bool(claim_res.get("published"))
    sent = False
    if published and send:
        try:
            from telegram_alert import send_telegram
            sent = bool(send_telegram(text, bypass_router=True))
        except Exception:
            sent = False
    return {
        "handled": True,
        "published": published,
        "ok": True,
        "sent": sent,
        "reason": claim_res.get("reason"),
        "key": claim_res.get("key"),
        "text": text,
        "consumer": "eod",
        "source": "cio.operator_product.current",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def render_research_message(row: dict[str, Any]) -> str:
    return render_research(from_research_result(row))
