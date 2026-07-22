#!/usr/bin/env python3
"""strategy_ticket_reconciler.py — deterministic release gate over validator +
critic layers. Pure. The hierarchy is non-negotiable:

    deterministic FAIL  →  INVALID, no mechanics, no proposal — no model, local
                           or paid, unanimous or not, can override it.

States: DETERMINISTIC_FAIL · VERIFIED_LOCAL_ONLY · VERIFIED_FREE_REVIEW ·
REVIEW_SPLIT · PREMIUM_CONFIRMED · PREMIUM_REJECTED · REVIEW_UNAVAILABLE ·
STALE_AFTER_REVIEW
"""
from __future__ import annotations

RECONCILER_VERSION = "1.0.0"


def reconcile(validation: dict, reviews: dict | None = None,
              premium: dict | None = None, *,
              current_ticket_hash: str | None = None) -> dict:
    v = validation or {}
    reviews = reviews or {}
    verdicts = {k: r.get("verdict") for k, r in reviews.items()
                if isinstance(r, dict) and not k.startswith("_")}
    out = {"reconciler_version": RECONCILER_VERSION,
           "deterministic": v.get("state"), "reviews": verdicts,
           "premium": (premium or {}).get("verdict"),
           "proposal_allowed": False, "display_mechanics": False,
           "detail": ""}

    if v.get("state") == "FAIL":
        out.update(state="DETERMINISTIC_FAIL",
                   detail="; ".join(v.get("hard_failures", [])[:2]))
        return out
    if current_ticket_hash and v.get("ticket_hash") \
            and current_ticket_hash != v.get("ticket_hash"):
        out.update(state="STALE_AFTER_REVIEW",
                   detail="ticket changed after validation — all reviews void")
        return out
    # deterministic PASS/REVIEW_REQUIRED from here
    stale_reviews = [k for k, r in reviews.items()
                     if isinstance(r, dict) and not k.startswith("_")
                     and r.get("ticket_hash_reviewed")
                     and v.get("ticket_hash")
                     and r["ticket_hash_reviewed"] != v["ticket_hash"]]
    live = {k: r for k, r in reviews.items()
            if isinstance(r, dict) and not k.startswith("_") and k not in stale_reviews}
    completed = {k: r for k, r in live.items() if r.get("verdict") not in (None, "UNAVAILABLE")}
    rejects = [k for k, r in completed.items() if r["verdict"] == "REJECT"]
    cautions = [k for k, r in completed.items() if r["verdict"] == "CAUTION"]
    passes = [k for k, r in completed.items() if r["verdict"] == "PASS"]

    if premium and premium.get("verdict") == "REJECT":
        out.update(state="PREMIUM_REJECTED", display_mechanics=True,
                   detail="premium expert rejected — operator review required")
        return out
    if rejects and passes:
        out.update(state="REVIEW_SPLIT", display_mechanics=True,
                   detail=f"split: {', '.join(rejects)} REJECT vs {', '.join(passes)} PASS — do not propose")
        return out
    if rejects:
        out.update(state="REVIEW_SPLIT", display_mechanics=True,
                   detail=f"{', '.join(rejects)} REJECT — operator review required")
        return out
    if premium and premium.get("verdict") == "PASS":
        out.update(state="PREMIUM_CONFIRMED", proposal_allowed=True,
                   display_mechanics=True, detail="premium confirmed")
        return out
    if not completed:
        out.update(state="REVIEW_UNAVAILABLE", display_mechanics=True,
                   detail="deterministically verified — independent model review unavailable")
        return out
    fams = {r.get("provider_family") for r in completed.values()}
    if len(fams) >= 2 and not cautions:
        out.update(state="VERIFIED_FREE_REVIEW", proposal_allowed=True,
                   display_mechanics=True,
                   detail=f"{len(completed)} independent critics pass")
        return out
    out.update(state="VERIFIED_LOCAL_ONLY", display_mechanics=True,
               detail=("single lane" if len(completed) == 1 else "cautions present")
               + " — proposal needs a second independent PASS")
    return out
