#!/usr/bin/env python3
"""proposal_alert_enrichment.py — Surface card-level risk/oversight on Telegram proposal alerts.

Mirrors BrokerProposalCardV4 meme/high-risk heuristics and pulls broker intel + oversight
so Telegram matches what the operator sees after opening the proposal card.
"""
from __future__ import annotations

import re
from typing import Any

_MEME_RE = re.compile(
    r"\b(meme|short[ -]?squeeze|heavily shorted|social sentiment|reddit|wsb|"
    r"wallstreetbets|meme[ -]?trader|pump|frenzy|squeeze|social)\b",
    re.I,
)


def assess_high_risk_surface(
    proposal: dict | None = None,
    intel: dict | None = None,
) -> dict[str, Any]:
    """Same rules as BrokerProposalCardV4 high-risk banner (client-side)."""
    proposal = proposal or {}
    intel = intel or {}
    cat = intel.get("catalyst") or {}
    tech = intel.get("technicals") or {}
    oversight = intel.get("oversight") or {}

    reviews = (oversight.get("agents") or {}).get("reviews") or []
    review_text = " ".join(
        str(r.get("summary") or r.get("reasoning") or "")
        for r in reviews
    )

    cat_text = " ".join(
        str(x or "")
        for x in (
            cat.get("text"),
            cat.get("headline"),
            cat.get("title"),
            cat.get("summary"),
            cat.get("social_summary"),
            proposal.get("catalyst"),
        )
    )

    def _num(*vals) -> float | None:
        for v in vals:
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    rvol = _num(proposal.get("rvol"), cat.get("rvol"), tech.get("rvol"))
    gap = _num(proposal.get("gap_pct"), cat.get("gap_pct"), tech.get("gap_pct")) or 0.0

    verified = cat.get("verified")
    if verified is None and proposal.get("catalyst_verified") is not None:
        verified = bool(proposal.get("catalyst_verified"))
    conf = cat.get("confidence")
    cat_unverified = bool(cat) and (verified is False or (conf is not None and float(conf) <= 0))

    social_flag = bool(cat.get("social"))
    meme_flag = social_flag or bool(_MEME_RE.search(cat_text)) or bool(_MEME_RE.search(review_text))
    extreme_rvol = rvol is not None and rvol >= 10
    high_risk = meme_flag or (extreme_rvol and (cat_unverified or abs(gap) >= 15))

    reasons: list[str] = []
    if social_flag:
        src = cat.get("social_sources")
        reasons.append(f"social-momentum ({src} src)" if src else "social-momentum")
    elif meme_flag:
        reasons.append("meme-driven")
    if extreme_rvol and rvol is not None:
        reasons.append(f"RVOL {rvol:.0f}×")
    if abs(gap) >= 10:
        reasons.append(f"gap {'+' if gap > 0 else ''}{gap:.0f}%")
    if cat_unverified:
        reasons.append("unverified catalyst")

    risk_line = ""
    for r in reviews:
        if re.search(r"risk", str(r.get("agent") or ""), re.I):
            risk_line = str(r.get("summary") or "")[:160]
            break
    if not risk_line:
        for r in reviews:
            if _MEME_RE.search(str(r.get("summary") or "")):
                risk_line = str(r.get("summary") or "")[:160]
                break

    return {
        "high_risk": high_risk,
        "high_risk_label": "MEME / HIGH-RISK SPECULATION" if high_risk else None,
        "high_risk_reasons": " · ".join(reasons),
        "high_risk_agent_note": risk_line or None,
        "rvol": rvol,
        "gap_pct": gap if gap else None,
        "catalyst_verified": verified,
        "social_momentum": social_flag,
    }


def enrich_proposal_for_alert(proposal: dict) -> dict[str, Any]:
    """Load broker intel + oversight; return fields to merge into the Telegram alert packet."""
    pid = proposal.get("id")
    if not pid:
        return {}
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return {}

    intel: dict = {}
    try:
        import broker_proposal_intel as bpi
        intel = bpi.get_intel_packet(pid, include_oversight=True) or {}
    except Exception:
        intel = {}

    if not intel.get("ok"):
        return assess_high_risk_surface(proposal, intel)

    oversight = intel.get("oversight") or {}
    company = intel.get("company") or {}
    cat = intel.get("catalyst") or {}

    risk = assess_high_risk_surface(proposal, intel)
    pending = (oversight.get("agents") or {}).get("pending") or []
    violations = list(oversight.get("violations") or [])
    warnings = list(oversight.get("warnings") or [])
    gate_n = len(violations)

    oversight_bits: list[str] = []
    ov_status = str(oversight.get("status") or "").upper()
    if ov_status:
        oversight_bits.append(f"oversight {ov_status}")
    if gate_n:
        oversight_bits.append(f"{gate_n} gate{'s' if gate_n != 1 else ''}")
    if pending:
        oversight_bits.append(f"agents pending: {', '.join(pending[:4])}")
    cloud = oversight.get("cloud_review") or {}
    cloud_st = str(cloud.get("status") or "").lower()
    if cloud_st and cloud_st not in ("not_run", "unknown", ""):
        oversight_bits.append(f"cloud {cloud_st}")

    return {
        **risk,
        "company_description": (company.get("description") or "")[:200] or None,
        "sector": company.get("sector") or proposal.get("sector"),
        "industry": company.get("industry") or proposal.get("industry"),
        "catalyst_verified": cat.get("verified") if cat.get("verified") is not None else risk.get("catalyst_verified"),
        "catalyst_text": (cat.get("text") or proposal.get("catalyst") or "")[:120] or None,
        "oversight_status": ov_status or None,
        "oversight_summary": " · ".join(oversight_bits) if oversight_bits else None,
        "oversight_violations": violations[:3],
        "oversight_warnings": warnings[:2],
        "pending_agents": pending,
        "gate_block_count": gate_n,
    }