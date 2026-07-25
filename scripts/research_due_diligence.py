#!/usr/bin/env python3
"""Shared deterministic due-diligence envelope for specialized research.

This module standardizes evidence maturity without flattening domain expertise.
Proposal, Watch, Defense, sector and industry adapters supply their own checks;
this core supplies one immutable contract for provenance, freshness, coverage,
contradictions and downstream authority.

The contract is pure and model-free. Model reviews are optional critiques that
may be attached later, but they never change ``deterministic_state`` and cannot
create evidence, repair arithmetic, grant proposal eligibility or authorize an
order, approval or 2FA action.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

CONTRACT_VERSION = "research-due-diligence-v1"

PASS = "PASS"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
BLOCKED = "BLOCKED"

CHECK_PASS = "PASS"
CHECK_WARN = "WARN"
CHECK_FAIL = "FAIL"
CHECK_STATES = {CHECK_PASS, CHECK_WARN, CHECK_FAIL}

DOMAINS = {"watch", "proposal", "defense", "sector", "industry"}

_BAD_QUALITY_TOKENS = (
    "missing", "stale", "quarantined", "failed", "error", "unknown",
    "unavailable", "invalid", "incomplete", "insufficient",
)
_WARN_QUALITY_TOKENS = (
    "partial", "thin", "capped", "sample", "intraday", "research_only",
    "refresh", "unconfirmed", "narrow",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_ref(
    *,
    source_id: str,
    provider: str | None = None,
    as_of: Any = None,
    calculation_version: str | None = None,
    quality: str = "ok",
    cadence: str | None = None,
    required: bool = True,
    stale: bool = False,
    coverage_n: int | None = None,
    coverage_total: int | None = None,
    payload: Any = None,
    payload_hash: str | None = None,
    notes: Iterable[str] | None = None,
) -> dict:
    """Build a normalized source ledger entry.

    ``payload`` is never retained.  It is used only to derive a stable content
    hash so large or sensitive evidence does not leak into the ledger.
    """
    out = {
        "source_id": str(source_id or "").strip(),
        "provider": provider,
        "as_of": str(as_of) if as_of is not None else None,
        "calculation_version": calculation_version,
        "quality": str(quality or "unknown"),
        "cadence": cadence,
        "required": bool(required),
        "stale": bool(stale),
        "content_hash": payload_hash or (content_hash(payload) if payload is not None else None),
    }
    if coverage_n is not None:
        out["coverage_n"] = int(coverage_n)
    if coverage_total is not None:
        out["coverage_total"] = int(coverage_total)
        out["coverage_pct"] = (
            round(int(coverage_n or 0) / int(coverage_total) * 100, 2)
            if int(coverage_total) > 0 else 0.0
        )
    if notes:
        out["notes"] = [str(note) for note in notes]
    return out


def check(
    check_id: str,
    state: str,
    reason: str,
    *,
    evidence_refs: Iterable[str] | None = None,
    details: dict | None = None,
) -> dict:
    normalized = str(state or "").upper()
    if normalized not in CHECK_STATES:
        raise ValueError(f"invalid due-diligence check state: {state!r}")
    return {
        "check_id": str(check_id or "").strip(),
        "state": normalized,
        "reason": str(reason or "").strip(),
        "evidence_refs": sorted({str(ref) for ref in (evidence_refs or []) if ref}),
        "details": details or {},
        "authority": "deterministic",
    }


def _source_disposition(source: dict) -> tuple[str, str | None]:
    source_id = str(source.get("source_id") or "").strip()
    quality = str(source.get("quality") or "unknown").lower()
    required = bool(source.get("required", True))
    missing_identity = not source_id
    missing_as_of = required and not source.get("as_of")
    missing_hash = required and not source.get("content_hash")
    bad_quality = any(token in quality for token in _BAD_QUALITY_TOKENS)
    warn_quality = any(token in quality for token in _WARN_QUALITY_TOKENS)

    if missing_identity:
        return CHECK_FAIL if required else CHECK_WARN, "source identity missing"
    if bool(source.get("stale")):
        return CHECK_FAIL if required else CHECK_WARN, f"{source_id} is stale"
    if missing_as_of:
        return CHECK_FAIL, f"{source_id} has no as-of time"
    if missing_hash:
        return CHECK_FAIL, f"{source_id} has no content hash"
    if bad_quality:
        return CHECK_FAIL if required else CHECK_WARN, f"{source_id} quality={quality}"
    if warn_quality:
        return CHECK_WARN, f"{source_id} quality={quality}"
    return CHECK_PASS, None


def evaluate(
    *,
    domain: str,
    subject: dict,
    checks: Iterable[dict],
    sources: Iterable[dict],
    evidence: dict | None = None,
    policy_version: str | None = None,
    calculation_version: str | None = None,
    generated_at: str | None = None,
) -> dict:
    """Evaluate one domain-specific research packet deterministically."""
    domain_name = str(domain or "").lower()
    if domain_name not in DOMAINS:
        raise ValueError(f"unsupported due-diligence domain: {domain!r}")
    if not isinstance(subject, dict) or not subject:
        raise ValueError("due-diligence subject must be a non-empty dict")

    normalized_checks = []
    seen_checks = set()
    for item in checks:
        if not isinstance(item, dict):
            raise ValueError("due-diligence checks must be dicts")
        check_id = str(item.get("check_id") or "").strip()
        state = str(item.get("state") or "").upper()
        if not check_id or state not in CHECK_STATES:
            raise ValueError("each due-diligence check requires check_id and PASS/WARN/FAIL")
        if check_id in seen_checks:
            raise ValueError(f"duplicate due-diligence check_id: {check_id}")
        seen_checks.add(check_id)
        normalized_checks.append({
            "check_id": check_id,
            "state": state,
            "reason": str(item.get("reason") or ""),
            "evidence_refs": sorted({str(ref) for ref in item.get("evidence_refs") or [] if ref}),
            "details": item.get("details") or {},
            "authority": "deterministic",
        })

    normalized_sources = []
    source_ids = set()
    source_failures: list[str] = []
    source_warnings: list[str] = []
    required_sources = good_required_sources = 0
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("due-diligence sources must be dicts")
        normalized = dict(item)
        source_id = str(normalized.get("source_id") or "").strip()
        if source_id and source_id in source_ids:
            raise ValueError(f"duplicate due-diligence source_id: {source_id}")
        if source_id:
            source_ids.add(source_id)
        disposition, note = _source_disposition(normalized)
        normalized["disposition"] = disposition
        normalized_sources.append(normalized)
        if normalized.get("required", True):
            required_sources += 1
            if disposition == CHECK_PASS:
                good_required_sources += 1
        if disposition == CHECK_FAIL and note:
            source_failures.append(note)
        elif disposition == CHECK_WARN and note:
            source_warnings.append(note)

    unknown_refs = sorted({
        ref
        for item in normalized_checks
        for ref in item.get("evidence_refs") or []
        if ref not in source_ids
    })
    if unknown_refs:
        source_failures.append("checks reference unknown evidence sources: " + ", ".join(unknown_refs))

    hard_failures = [item["reason"] for item in normalized_checks if item["state"] == CHECK_FAIL]
    warnings = [item["reason"] for item in normalized_checks if item["state"] == CHECK_WARN]
    hard_failures.extend(source_failures)
    warnings.extend(source_warnings)

    if hard_failures:
        deterministic_state = BLOCKED
    elif warnings:
        deterministic_state = REVIEW_REQUIRED
    else:
        deterministic_state = PASS

    material = {
        "contract_version": CONTRACT_VERSION,
        "domain": domain_name,
        "subject": subject,
        "policy_version": policy_version,
        "calculation_version": calculation_version,
        "checks": normalized_checks,
        "sources": normalized_sources,
        "evidence": evidence or {},
    }
    packet_hash = content_hash(material)
    coverage_pct = (
        round(good_required_sources / required_sources * 100, 2)
        if required_sources else 0.0
    )

    return {
        **material,
        "generated_at": generated_at or utc_now(),
        "packet_hash": packet_hash,
        "deterministic_state": deterministic_state,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "coverage": {
            "required_sources": required_sources,
            "good_required_sources": good_required_sources,
            "required_source_coverage_pct": coverage_pct,
        },
        "downstream": {
            "research_complete": deterministic_state == PASS,
            "specialist_review_required": deterministic_state == REVIEW_REQUIRED,
            "blocked": deterministic_state == BLOCKED,
            "proposal_or_recommendation_eligible": deterministic_state == PASS,
        },
        "model_oversight": {
            "allowed": deterministic_state in {PASS, REVIEW_REQUIRED},
            "may_override_deterministic_state": False,
            "may_create_or_repair_evidence": False,
            "may_create_or_repair_mechanics": False,
            "paid_lane_automatic": False,
        },
        "authority": {
            "advisory_research_only": True,
            "proposal_state_write": False,
            "recommendation_activation": False,
            "broker_or_order_action": False,
            "approval_or_2fa_action": False,
            "models_may_override": False,
        },
    }


def aggregate(
    *,
    domain: str,
    subject: dict,
    children: Iterable[dict],
    policy_version: str | None = None,
    calculation_version: str | None = None,
) -> dict:
    """Build a parent packet from already-evaluated specialized child packets."""
    child_list = [child for child in children if isinstance(child, dict)]
    checks = []
    sources = []
    for index, child in enumerate(child_list):
        child_domain = child.get("domain") or f"child-{index}"
        child_hash = child.get("packet_hash")
        child_state = child.get("deterministic_state") or BLOCKED
        check_state = (
            CHECK_PASS if child_state == PASS
            else CHECK_WARN if child_state == REVIEW_REQUIRED
            else CHECK_FAIL
        )
        source_id = f"{child_domain}:{index}"
        sources.append(source_ref(
            source_id=source_id,
            provider="internal deterministic due-diligence packet",
            as_of=child.get("generated_at"),
            calculation_version=child.get("calculation_version"),
            quality="ok" if child_state == PASS else child_state.lower(),
            required=True,
            payload_hash=child_hash,
        ))
        checks.append(check(
            f"child_{index}_{child_domain}",
            check_state,
            f"{child_domain} child due diligence is {child_state}",
            evidence_refs=[source_id],
            details={"packet_hash": child_hash},
        ))
    if not child_list:
        checks.append(check("children_present", CHECK_FAIL,
                            "no specialized child due-diligence packets supplied"))
    return evaluate(
        domain=domain,
        subject=subject,
        checks=checks,
        sources=sources,
        evidence={"children": [{
            "domain": child.get("domain"),
            "subject": child.get("subject"),
            "state": child.get("deterministic_state"),
            "packet_hash": child.get("packet_hash"),
        } for child in child_list]},
        policy_version=policy_version,
        calculation_version=calculation_version,
    )
