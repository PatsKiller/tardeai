"""proposal_routing.py — broker-agnostic proposal routing helpers.

Proposals are created without a hardcoded broker. Routing is chosen at promote/approve time.
"""
from __future__ import annotations


def routing_key(proposal: dict) -> str:
    """Normalized account/broker key from a proposal row or API dict."""
    return str(
        proposal.get("intended_broker")
        or proposal.get("target_account")
        or proposal.get("proposed_account")
        or ""
    ).strip().lower()


def is_unassigned(proposal: dict) -> bool:
    return not routing_key(proposal)


def is_broker_routed(proposal: dict) -> bool:
    k = routing_key(proposal)
    return k.startswith("schwab") or k.startswith("fidelity")


def is_broker_desk_watchlist(proposal: dict) -> bool:
    """Watchlist bridge rows on Path B — managed on Broker Proposals, not review cap."""
    return str(proposal.get("origin") or "").lower() == "watchlist" and is_broker_routed(proposal)


def counts_toward_promotion_cap(proposal: dict) -> bool:
    """Whether a pending row consumes the incubator / review-queue ceiling."""
    return not is_broker_desk_watchlist(proposal)


def is_paper_routed(proposal: dict) -> bool:
    k = routing_key(proposal)
    return bool(k) and not is_broker_routed(proposal)


def routing_label(proposal: dict) -> str:
    """UI/API short label for execution path."""
    return execution_path(proposal)


def execution_path(proposal: dict) -> str:
    """unassigned | paper_auto | live_schwab | live_fidelity"""
    k = routing_key(proposal)
    if not k:
        return "unassigned"
    if k.startswith("schwab"):
        return "live_schwab"
    if k.startswith("fidelity"):
        return "live_fidelity"
    return "paper_auto"


def execution_path_display(proposal: dict) -> str:
    p = execution_path(proposal)
    return {
        "unassigned": "Choose path",
        "paper_auto": "Paper auto (test)",
        "live_schwab": "Live · Schwab (2FA auto or manual)",
        "live_fidelity": "Live · FA manual (Active Trader)",
    }.get(p, p)


def resolve_dispatch_broker(proposal: dict) -> tuple[str | None, str | None]:
    """Return (broker_key, error). None broker_key means routing not set yet."""
    broker = str(proposal.get("intended_broker") or "").strip()
    account = str(
        proposal.get("target_account") or proposal.get("proposed_account") or ""
    ).strip()
    key = (broker or account).strip()
    if not key:
        return None, "routing not set — choose paper or broker account before dispatch"
    return key, None