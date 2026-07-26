#!/usr/bin/env python3
"""Deterministic release gate over independent ticket critics.

Hierarchy is non-negotiable:

    deterministic FAIL / missing quality / quality refusal → no mechanics,
    no proposal; no local, OAuth or paid model may override it.

A paid review is never called here. The reconciler may only state that an
operator-selected paid escalation is recommended to resolve a deterministic
warning, unavailable independent review, or critic disagreement.
"""
from __future__ import annotations

RECONCILER_VERSION = "1.1.1"


def _base(validation: dict, reviews: dict, premium: dict | None) -> dict:
    verdicts = {
        key: value.get("verdict")
        for key, value in reviews.items()
        if isinstance(value, dict) and not key.startswith("_")
    }
    quality = validation.get("quality_admission") or {}
    return {
        "reconciler_version": RECONCILER_VERSION,
        "deterministic": validation.get("state"),
        "quality_admission": quality.get("state"),
        "reviews": verdicts,
        "premium": (premium or {}).get("verdict"),
        "proposal_allowed": False,
        "display_mechanics": False,
        "premium_recommended": False,
        "premium_reason": None,
        "paid_lane_called": False,
        "detail": "",
    }


def reconcile(validation: dict, reviews: dict | None = None,
              premium: dict | None = None, *,
              current_ticket_hash: str | None = None) -> dict:
    validation = validation or {}
    reviews = reviews or {}
    out = _base(validation, reviews, premium)
    deterministic = str(validation.get("state") or "NOT_RUN").upper()
    quality = validation.get("quality_admission") or {}

    if deterministic == "FAIL":
        out.update(
            state="DETERMINISTIC_FAIL",
            detail="; ".join(validation.get("hard_failures", [])[:2])
                   or "deterministic or quality gate failed",
        )
        return out

    if deterministic not in {"PASS", "REVIEW_REQUIRED"}:
        out.update(
            state="DETERMINISTIC_NOT_RUN",
            detail="mandatory deterministic validation did not complete",
        )
        return out

    # An old packet path supplied {state: PASS} when no ticket had actually been
    # validated. Reconciliation must require the new quality record as proof that
    # deterministic admission ran; otherwise PASS is synthetic/incomplete.
    if not quality or not quality.get("state"):
        out.update(
            state="QUALITY_NOT_ASSESSED",
            detail="deterministic result lacks mandatory quality-admission evidence",
        )
        return out

    if quality.get("state") != "ADMITTED" or quality.get("new_entry_allowed") is False:
        out.update(
            state="QUALITY_NOT_ADMITTED",
            detail="; ".join(quality.get("reasons", [])[:2])
                   or "instrument is not admitted for a current new entry",
        )
        return out

    if current_ticket_hash and validation.get("ticket_hash") \
            and current_ticket_hash != validation.get("ticket_hash"):
        out.update(
            state="STALE_AFTER_REVIEW",
            detail="ticket changed after validation — all reviews void",
            premium_recommended=False,
        )
        return out

    # REVIEW_REQUIRED is not PASS. Independent critics can add evidence, but
    # they cannot silently promote a deterministic warning into permission.
    if deterministic == "REVIEW_REQUIRED":
        warnings = validation.get("warnings") or []
        out.update(
            state="DETERMINISTIC_REVIEW_REQUIRED",
            display_mechanics=True,
            detail="; ".join(warnings[:2]) or "deterministic review is required",
            premium_recommended=True,
            premium_reason="resolve deterministic warnings with an independent expert review",
        )
        if premium and premium.get("verdict") == "REJECT":
            out.update(
                state="PREMIUM_REJECTED",
                detail="premium expert rejected after deterministic review warning",
                premium_recommended=False,
            )
        elif premium and premium.get("verdict") == "PASS":
            out.update(
                state="PREMIUM_REVIEWED",
                detail="premium critic passed, but deterministic warning still requires operator adjudication",
                premium_recommended=False,
            )
        return out

    stale_reviews = [
        key for key, review in reviews.items()
        if isinstance(review, dict) and not key.startswith("_")
        and review.get("ticket_hash_reviewed")
        and validation.get("ticket_hash")
        and review["ticket_hash_reviewed"] != validation["ticket_hash"]
    ]
    live = {
        key: review for key, review in reviews.items()
        if isinstance(review, dict) and not key.startswith("_")
        and key not in stale_reviews
    }
    completed = {
        key: review for key, review in live.items()
        if review.get("verdict") not in (None, "UNAVAILABLE")
    }
    rejects = [key for key, review in completed.items()
               if review["verdict"] == "REJECT"]
    cautions = [key for key, review in completed.items()
                if review["verdict"] == "CAUTION"]
    passes = [key for key, review in completed.items()
              if review["verdict"] == "PASS"]

    if premium and premium.get("verdict") == "REJECT":
        out.update(
            state="PREMIUM_REJECTED",
            display_mechanics=True,
            detail="premium expert rejected — operator review required",
        )
        return out

    if rejects and passes:
        out.update(
            state="REVIEW_SPLIT",
            display_mechanics=True,
            detail=f"split: {', '.join(rejects)} REJECT vs {', '.join(passes)} PASS — do not propose",
            premium_recommended=True,
            premium_reason="independent critics disagree on the exact validated ticket",
        )
        return out

    if rejects:
        out.update(
            state="REVIEW_SPLIT",
            display_mechanics=True,
            detail=f"{', '.join(rejects)} REJECT — operator review required",
            premium_recommended=True,
            premium_reason="a completed independent critic rejected the exact ticket",
        )
        return out

    if premium and premium.get("verdict") == "PASS":
        out.update(
            state="PREMIUM_CONFIRMED",
            proposal_allowed=True,
            display_mechanics=True,
            detail="deterministic PASS plus operator-selected premium confirmation",
        )
        return out

    if not completed:
        out.update(
            state="REVIEW_UNAVAILABLE",
            display_mechanics=True,
            detail="deterministic PASS; no independent critic completed",
            premium_recommended=True,
            premium_reason="free independent review is unavailable for this validated ticket",
        )
        return out

    families = {review.get("provider_family") for review in completed.values()
                if review.get("provider_family")}
    if len(families) >= 2 and not cautions and len(passes) == len(completed):
        out.update(
            state="VERIFIED_FREE_REVIEW",
            proposal_allowed=True,
            display_mechanics=True,
            detail=f"deterministic PASS plus {len(completed)} independent critic PASS verdicts",
        )
        return out

    out.update(
        state="VERIFIED_LOCAL_ONLY",
        display_mechanics=True,
        detail=("single completed provider family" if len(families) <= 1
                else "one or more independent critics returned CAUTION")
               + " — proposal needs another independent PASS or operator adjudication",
        premium_recommended=True,
        premium_reason=("obtain a second independent provider-family PASS"
                        if len(families) <= 1
                        else "resolve critic caution before proposal review"),
    )
    return out
