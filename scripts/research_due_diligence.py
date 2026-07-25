#!/usr/bin/env python3
"""Deterministic due-diligence envelope for specialized research.

Watch, Defense, sector rotation, industry rotation and proposal assembly use
specialized calculations, but every actionable conclusion must prove the same
maturity properties: methodology, provenance, freshness, coverage, named
checks, explicit insufficiency, and bounded independent oversight.

A verified result is eligible only for operator proposal review. This module
has no external-action authority and cannot activate any downstream workflow.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "config" / "research_due_diligence_policy.json").read_text())
POLICY_VERSION = str(POLICY["version"])
VALID_DOMAINS = set(POLICY["domains"])

VERIFIED = "VERIFIED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
REJECTED = "REJECTED"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _source_failures(sources: list[dict]) -> list[str]:
    failures: list[str] = []
    if not sources:
        return ["no source records supplied"]
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            failures.append(f"source[{index}] is not structured")
            continue
        for field, required in POLICY["source_requirements"].items():
            if required and not _present(source.get(field)):
                failures.append(f"source[{index}] missing {field}")
        quality = str(source.get("quality") or "").lower()
        if quality in {"missing", "error", "stale", "query_error", "unavailable"}:
            failures.append(f"source[{index}] quality={quality}")
    return failures


def evaluate(
    *,
    domain: str,
    subject: str,
    methodology_version: str,
    as_of: str,
    sources: list[dict],
    deterministic_checks: list[dict],
    coverage: dict | None = None,
    warnings: list[str] | None = None,
    contradictions: list[str] | None = None,
    freshness: dict | None = None,
    oversight: dict | None = None,
) -> dict:
    """Build one immutable, model-free due-diligence packet."""
    domain_u = str(domain or "").upper()
    missing: list[str] = []
    hard: list[str] = []
    cautions = [str(x) for x in (warnings or []) if str(x).strip()]
    conflicts = [str(x) for x in (contradictions or []) if str(x).strip()]

    if domain_u not in VALID_DOMAINS:
        hard.append(f"unsupported domain {domain_u or '<empty>'}")
    for name, value in (
        ("subject", subject), ("methodology_version", methodology_version), ("as_of", as_of)
    ):
        if not _present(value):
            missing.append(f"{name} missing")
    missing.extend(_source_failures(sources or []))

    normalized: list[dict] = []
    if not deterministic_checks:
        missing.append("no deterministic checks supplied")
    for index, check in enumerate(deterministic_checks or []):
        if not isinstance(check, dict) or not _present(check.get("name")):
            missing.append(f"deterministic_check[{index}] missing name")
            continue
        severity = "warning" if str(check.get("severity") or "hard").lower() == "warning" else "hard"
        record = {
            "name": str(check["name"]),
            "passed": check.get("passed") is True,
            "severity": severity,
            "reason": str(check.get("reason") or check["name"]),
            "evidence_ref": check.get("evidence_ref"),
        }
        normalized.append(record)
        if not record["passed"]:
            (cautions if severity == "warning" else hard).append(record["reason"])

    fresh = freshness or {}
    if fresh.get("stale") is True:
        hard.append(str(fresh.get("reason") or "research evidence is stale"))
    elif fresh.get("state") and str(fresh["state"]).upper() not in {
        "CURRENT", "CLOSE_CONFIRMED", "SAME_RUN", "PARTIAL"
    }:
        cautions.append(f"freshness state {fresh['state']}")

    cov = coverage or {}
    if cov.get("required") is not None and cov.get("observed") is not None:
        try:
            if float(cov["observed"]) < float(cov["required"]):
                hard.append(f"coverage {cov['observed']} below required {cov['required']}")
        except (TypeError, ValueError):
            missing.append("coverage values are not numeric")

    if missing:
        state = INSUFFICIENT_EVIDENCE
    elif hard:
        state = REJECTED
    elif conflicts or cautions:
        state = REVIEW_REQUIRED
    else:
        state = VERIFIED

    packet = {
        "contract": POLICY_VERSION,
        "domain": domain_u,
        "subject": str(subject),
        "methodology_version": str(methodology_version),
        "as_of": str(as_of),
        "state": state,
        "release_allowed": state == VERIFIED,
        "release_scope": "operator_proposal_review_only",
        "sources": sources or [],
        "deterministic_checks": normalized,
        "coverage": cov,
        "freshness": fresh,
        "missing_evidence": missing,
        "hard_failures": hard,
        "warnings": cautions,
        "contradictions": conflicts,
        "oversight": {
            "deterministic_complete": state != INSUFFICIENT_EVIDENCE,
            "models_allowed": state in {VERIFIED, REVIEW_REQUIRED},
            "models_may_override": False,
            "premium_operator_only": True,
            "reviews": oversight or {},
        },
        "authority": {
            "operator_review_eligible": state == VERIFIED,
            "external_action_allowed": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    packet["evidence_hash"] = _stable_hash({
        key: packet[key]
        for key in (
            "contract", "domain", "subject", "methodology_version", "as_of",
            "sources", "deterministic_checks", "coverage", "freshness",
            "missing_evidence", "hard_failures", "warnings", "contradictions",
        )
    })
    return packet


def proposal_gate(subject: str, specialized_packets: list[dict]) -> dict:
    """Require every supplied specialized research dependency to be VERIFIED."""
    packets = [p for p in (specialized_packets or []) if isinstance(p, dict)]
    checks = [
        {
            "name": f"{str(p.get('domain') or 'unknown').lower()}_research_verified",
            "passed": p.get("state") == VERIFIED and p.get("release_allowed") is True,
            "severity": "hard",
            "reason": f"{str(p.get('domain') or 'UNKNOWN').upper()} research state={p.get('state') or 'MISSING'}",
            "evidence_ref": p.get("evidence_hash"),
        }
        for p in packets
    ]
    now = datetime.now(timezone.utc).isoformat()
    return evaluate(
        domain="PROPOSAL",
        subject=subject,
        methodology_version=POLICY_VERSION,
        as_of=now,
        sources=[{
            "provider": "specialized_research_packets",
            "as_of": now,
            "quality": "ok" if packets else "missing",
            "provenance_ref": _stable_hash([p.get("evidence_hash") for p in packets]),
        }],
        deterministic_checks=checks,
        coverage={"required": len(checks), "observed": sum(1 for c in checks if c["passed"])},
    )
