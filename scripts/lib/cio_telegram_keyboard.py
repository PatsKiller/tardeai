"""CIO Telegram inline keyboard for material decisions + intelligence cards.

Decision cards:
[ ACK ] [ DEFER ]
[ DONE ] [ REJECT ]
[ RATE ] [ OPEN CIO ]
[ EVIDENCE ] [ RESEARCH ]

Investment Intelligence Cards:
[ Agree ] [ Disagree ]
[ Interested ] [ Defer ]
[ Need data ] [ Dismiss ]
[ OPEN CIO ] [ Thesis ]

URL buttons only — no unsigned mutation. Tailscale HTTPS via action-link builder.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.cio_action_links import (
    AUTHORITY,
    build_cio_evidence_url,
    build_cio_hub_url,
    build_cio_research_url,
    build_signed_action_url,
    reject_lan_url,
)


def build_decision_inline_keyboard(
    decision: dict[str, Any],
    *,
    key: Optional[bytes] = None,
) -> dict[str, Any]:
    did = str(decision.get("decision_id") or "").strip()
    if not did:
        raise ValueError("decision_id required for keyboard")
    inp = str(decision.get("decision_input_digest") or "")
    evd = str(decision.get("decision_evidence_digest") or "")
    sym = str(decision.get("symbol") or "")

    def signed(action: str) -> str:
        url = build_signed_action_url(
            decision_id=did,
            action=action,
            decision_input_digest=inp,
            decision_evidence_digest=evd,
            key=key,
        )
        if reject_lan_url(url):
            raise ValueError(f"LAN/localhost URL rejected: {url}")
        return url

    open_url = build_cio_hub_url()
    if reject_lan_url(open_url):
        raise ValueError(f"LAN/localhost URL rejected: {open_url}")
    rows = [
        [
            {"text": "ACK", "url": signed("ack")},
            {"text": "DEFER", "url": signed("defer")},
        ],
        [
            {"text": "DONE", "url": signed("done")},
            {"text": "REJECT", "url": signed("reject")},
        ],
        [
            {"text": "RATE", "url": signed("rate")},
            {"text": "OPEN CIO", "url": open_url},
        ],
        [
            {"text": "EVIDENCE", "url": build_cio_evidence_url(did)},
            {"text": "RESEARCH", "url": build_cio_research_url(sym)},
        ],
    ]
    return {
        "inline_keyboard": rows,
        "authority": AUTHORITY,
        "decision_id": did,
    }


def build_intelligence_inline_keyboard(
    card: dict[str, Any],
    *,
    key: Optional[bytes] = None,
) -> dict[str, Any]:
    """Inline URL keyboard for Investment Intelligence Cards (READ_ONLY).

    Uses ``object_id`` as the signed-action decision_id. Symbol is bound into
    ``decision_input_digest`` as ``iic:{SYMBOL}`` so POST can append feedback
    without a capital-plan catalog entry.
    """
    did = str(card.get("object_id") or card.get("decision_id") or "").strip()
    if not did:
        raise ValueError("object_id required for intelligence keyboard")
    sym = str(card.get("symbol") or "").strip().upper()
    inp = str(card.get("decision_input_digest") or (f"iic:{sym}" if sym else "iic:"))
    evd = str(
        card.get("decision_evidence_digest")
        or card.get("card_schema")
        or "InvestmentIntelligenceCard@v1"
    )

    def signed(action: str) -> str:
        url = build_signed_action_url(
            decision_id=did,
            action=action,
            decision_input_digest=inp,
            decision_evidence_digest=evd,
            key=key,
        )
        if reject_lan_url(url):
            raise ValueError(f"LAN/localhost URL rejected: {url}")
        return url

    open_url = build_cio_hub_url()
    if reject_lan_url(open_url):
        raise ValueError(f"LAN/localhost URL rejected: {open_url}")
    thesis_url = build_cio_research_url(sym) if sym else open_url
    if reject_lan_url(thesis_url):
        raise ValueError(f"LAN/localhost URL rejected: {thesis_url}")

    rows = [
        [
            {"text": "Agree", "url": signed("agree")},
            {"text": "Disagree", "url": signed("disagree")},
        ],
        [
            {"text": "Interested", "url": signed("interested")},
            {"text": "Defer", "url": signed("defer")},
        ],
        [
            {"text": "Need data", "url": signed("need_data")},
            {"text": "Dismiss", "url": signed("dismiss")},
        ],
        [
            {"text": "OPEN CIO", "url": open_url},
            {"text": "Thesis", "url": thesis_url},
        ],
    ]
    return {
        "inline_keyboard": rows,
        "authority": AUTHORITY,
        "decision_id": did,
        "object_id": did,
        "symbol": sym,
        "card_schema": "InvestmentIntelligenceCard@v1",
    }
