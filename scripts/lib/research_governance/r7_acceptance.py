"""R7 policy + behavioral acceptance (R7A-1)."""
from __future__ import annotations

from dataclasses import replace

from .behavioral import AUTHORITY as BEHAVIORAL_AUTHORITY
from .behavioral import FRAMES, as_research_evidence as behavioral_evidence
from .behavioral import bundle
from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass, ResearchStatus
from .policy import AUTHORITY as POLICY_AUTHORITY
from .policy import POLICY_TYPE_GATE_KEYS, PolicyRule
from .policy import as_research_evidence as policy_evidence
from .policy import evaluate_policy, promotion_ctx
from .promotion_gate import run_promotion_gate
from .source_catalog import load_sources

AUTHORITY = "READ_ONLY_ADVISORY"

_CATALOG_FRAME_IDS = frozenset({
    "housel_psychology_of_money",
    "marks_most_important_thing",
    "malkiel_random_walk",
})


def _pass(d: str) -> tuple[str, str]:
    return GateState.PASS.value, d


def _fail(d: str) -> tuple[str, str]:
    return GateState.FAIL.value, d


def complete_policy_rule() -> PolicyRule:
    return PolicyRule(
        rule_id="us_irs_rmd_pub_590b",
        fact=(
            "US required minimum distribution rules are published by the IRS "
            "and must be applied from the current authoritative publication."
        ),
        source_id="irs_publication_590b",
        authoritative_source="IRS Publication 590-B",
        jurisdiction="US-federal",
        effective_date="2023-01-01",
        verified_at="2026-01-15",
        current_as_of="2026-08-01",
        next_reverify_at="2027-01-15",
        future_effective=False,
        citation_url="https://www.irs.gov/publications/p590b",
        citation_title="IRS Publication 590-B",
    )


def check_policy_behavioral() -> tuple[str, str]:
    if POLICY_AUTHORITY != AUTHORITY or BEHAVIORAL_AUTHORITY != AUTHORITY:
        return _fail("authority drifted from READ_ONLY_ADVISORY")

    rule = complete_policy_rule()
    evaluation = evaluate_policy(rule)
    if evaluation.get("status") != "OK":
        return _fail(f"complete policy not OK: {evaluation}")

    ctx = promotion_ctx(rule)
    for key in (
        "authoritative_source",
        "effective_date",
        "jurisdiction",
        "verified_at",
        "current_as_of",
        "next_reverify_at",
        "future_effective",
    ):
        if key not in ctx:
            return _fail(f"promotion_ctx missing {key}")

    gated = run_promotion_gate(ctx)
    for key in POLICY_TYPE_GATE_KEYS:
        rec = gated.get("gate_results", {}).get(key)
        if not rec or rec.get("state") != GateState.PASS.value:
            return _fail(f"complete policy type gate {key} did not pass: {rec}")

    ev = policy_evidence(rule, evaluation)
    if ev.evidence_type != EvidenceType.POLICY_OR_REGULATORY:
        return _fail("policy evidence type drifted")
    if ev.influence_class != InfluenceClass.CONTEXT_MODIFIER:
        return _fail("policy influence is not CONTEXT_MODIFIER")
    if ev.evidence_grade != EvidenceGrade.C:
        return _fail(f"OK policy must grade C, got {ev.evidence_grade}")
    if ev.role_in_decision != "risk_modifier_or_context":
        return _fail("policy role_in_decision drifted")

    missing_j = replace(rule, jurisdiction="")
    missing_eval = evaluate_policy(missing_j)
    if missing_eval.get("status") != "UNAVAILABLE":
        return _fail(f"missing jurisdiction must be UNAVAILABLE: {missing_eval}")
    missing_gate = run_promotion_gate(promotion_ctx(missing_j))
    jrec = missing_gate.get("gate_results", {}).get("jurisdiction")
    if not jrec or jrec.get("state") != GateState.FAIL.value:
        return _fail(f"missing jurisdiction type gate must FAIL: {jrec}")

    stale = replace(rule, current_as_of="2026-08-01", next_reverify_at="2026-01-01")
    stale_eval = evaluate_policy(stale)
    if stale_eval.get("status") != "UNAVAILABLE":
        return _fail(f"stale reverify must be UNAVAILABLE: {stale_eval}")
    if "overdue" not in str(stale_eval.get("reason", "")).lower():
        return _fail(f"stale reason not overdue: {stale_eval}")

    pack = bundle()
    if pack.get("authority") != AUTHORITY:
        return _fail("behavioral authority drifted")
    if pack.get("partisan_conclusion") is not None:
        return _fail("partisan_conclusion must be null")
    if pack.get("standalone_sell") or pack.get("creates_trim"):
        return _fail("behavioral must not sell or TRIM")
    if pack.get("fulltext") or not pack.get("citation_only"):
        return _fail("behavioral pack must be citation-only / no full text")
    if pack.get("influence") != InfluenceClass.CONTEXT_MODIFIER.value:
        return _fail("behavioral influence is not CONTEXT_MODIFIER")
    if float(pack.get("max_influence_pct", 99)) > 10.0:
        return _fail("behavioral max_influence_pct exceeds 10")

    catalog_ids = {s["source_id"] for s in load_sources()}
    if set(FRAMES) != _CATALOG_FRAME_IDS:
        return _fail(f"FRAMES ids drifted: {set(FRAMES)}")
    frames = pack.get("frames") or {}
    if set(frames) != _CATALOG_FRAME_IDS:
        return _fail(f"bundle frames drifted: {set(frames)}")
    for fid, fr in frames.items():
        sid = fr.get("source_id")
        if sid not in catalog_ids:
            return _fail(f"{fid} source_id {sid!r} not in load_sources()")
        if sid not in _CATALOG_FRAME_IDS:
            return _fail(f"{fid} is not a permitted catalog source")
        if not fr.get("citation_only") or fr.get("fulltext"):
            return _fail(f"{fid} is not citation-only")
        claim = (fr.get("layers") or {}).get("source_claim") or {}
        if not claim.get("citation_only") or claim.get("fulltext"):
            return _fail(f"{fid} source_claim is not citation-only")
        if claim.get("page_or_section") is not None:
            return _fail(f"{fid} must not carry page numbers")
        summary = fr.get("summary") or ""
        if "Not a book extract" not in summary:
            return _fail(f"{fid} summary missing operator disclaimer")
        if fr.get("partisan_conclusion") is not None:
            return _fail(f"{fid} partisan_conclusion not null")
        if fr.get("standalone_sell") or fr.get("creates_trim"):
            return _fail(f"{fid} must not sell or TRIM")
        bev = behavioral_evidence(fid)
        if bev.evidence_grade != EvidenceGrade.D:
            return _fail(f"{fid} must be grade D")
        if bev.research_status != ResearchStatus.SOURCE_CLAIM:
            return _fail(f"{fid} must stay SOURCE_CLAIM (no full text)")
        if bev.evidence_type != EvidenceType.BEHAVIORAL_FRAMEWORK:
            return _fail(f"{fid} evidence type drifted")

    return _pass(
        "complete policy OK + type gates; missing jurisdiction / stale reverify "
        "UNAVAILABLE; behavioral citation-only, no TRIM/sell, partisan null, catalog ids"
    )


CHECKS = {"R7A-1": check_policy_behavioral}
