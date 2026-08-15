"""CIO Telegram inline keyboard for material decisions.

[ ACK ] [ DEFER ]
[ DONE ] [ REJECT ]
[ RATE ] [ OPEN CIO ]
[ EVIDENCE ] [ RESEARCH ]

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
