#!/usr/bin/env python3
"""Adapt one governed Watch decision packet to the shared research standard.

The existing Watch validator and quality-admission engine remain sovereign. This
adapter does not recompute or replace them; it proves that their result is bound
to current market, technical, fundamental and event evidence with explicit
provenance before downstream proposal or Defense research may consume it.
"""
from __future__ import annotations

from typing import Any

import research_due_diligence as rdd
import watch_packet_quality

ADAPTER_VERSION = "watch-research-due-diligence-v1"


def _source(
    source_id: str,
    *,
    provider: str,
    as_of: Any,
    calculation_version: str,
    quality: str,
    payload: Any = None,
    payload_hash: str | None = None,
    required: bool = True,
    stale: bool = False,
) -> dict:
    return rdd.source_ref(
        source_id=source_id,
        provider=provider,
        as_of=as_of,
        calculation_version=calculation_version,
        quality=quality,
        payload=payload,
        payload_hash=payload_hash,
        required=required,
        stale=stale,
    )


def watch_due_diligence(packet: dict | None) -> dict:
    packet = packet or {}
    selected = watch_packet_quality.select_governing_validation(packet)
    validation = selected.get("validation") or {}
    quality = validation.get("quality_admission") or {}
    snapshot = packet.get("current_input_snapshot") or packet.get("input_snapshot") or {}
    market = snapshot.get("market") or {}
    fundamentals = snapshot.get("fundamentals") or {}
    events = snapshot.get("events") or packet.get("event_state") or {}
    technical = packet.get("technical_state") or {}
    freshness = packet.get("freshness") or {}
    freshness_state = str(freshness.get("overall_state") or "UNKNOWN").upper()
    technical_freshness = str(technical.get("overall_freshness") or "UNKNOWN").upper()
    conflicts = watch_packet_quality.presentation_conflicts(packet)

    sources = [
        _source(
            "governing_validation",
            provider="Watch deterministic ticket validator",
            as_of=packet.get("evaluated_at") or packet.get("generated_at")
            or freshness.get("last_strategy_build_at"),
            calculation_version=validation.get("validator_version")
            or "watch-ticket-validator-unversioned",
            quality="ok" if validation else "missing",
            payload=validation,
            payload_hash=validation.get("ticket_hash"),
        ),
        _source(
            "market",
            provider="canonical Watch market input snapshot",
            as_of=market.get("price_as_of") or packet.get("facts_as_of"),
            calculation_version=packet.get("action_policy_version")
            or "watch-market-snapshot-v1",
            quality="ok" if market else "missing",
            payload=market,
            stale=freshness_state in {"STALE", "FAILED"},
        ),
        _source(
            "technicals",
            provider="canonical multi-timeframe technical intelligence",
            as_of=technical.get("computed_at") or market.get("technical_as_of")
            or packet.get("evaluated_at"),
            calculation_version=technical.get("schema_version")
            or "technical-intelligence-unversioned",
            quality=technical_freshness.lower(),
            payload=technical,
            payload_hash=technical.get("source_hash"),
            stale=technical_freshness in {"STALE", "FAILED"},
        ),
        _source(
            "fundamentals",
            provider=fundamentals.get("provider") or "governed fundamentals snapshot",
            as_of=fundamentals.get("fetched_at") or packet.get("fundamentals_as_of")
            or packet.get("evaluated_at"),
            calculation_version="watch-fundamentals-snapshot-v1",
            quality="ok" if fundamentals.get("content_hash") else "missing",
            payload=fundamentals,
            payload_hash=fundamentals.get("content_hash"),
        ),
        _source(
            "events",
            provider="normalized Watch event snapshot",
            as_of=events.get("as_of") or events.get("latest_catalyst_at")
            or packet.get("evaluated_at"),
            calculation_version="normalized-event-contract",
            quality="ok" if events else "missing",
            payload=events,
            payload_hash=events.get("event_content_hash"),
        ),
    ]

    deterministic_state = selected.get("deterministic") or "NOT_RUN"
    quality_state = str(quality.get("state") or "UNASSESSED").upper()
    checks = [
        rdd.check(
            "deterministic_ticket_validation",
            rdd.CHECK_PASS if deterministic_state == "PASS"
            else rdd.CHECK_WARN if deterministic_state == "REVIEW_REQUIRED"
            else rdd.CHECK_FAIL,
            f"governing Watch ticket validation is {deterministic_state}",
            evidence_refs=["governing_validation"],
            details={"source": selected.get("source")},
        ),
        rdd.check(
            "quality_admission",
            rdd.CHECK_PASS if quality_state == "ADMITTED"
            and quality.get("new_entry_allowed") is not False
            else rdd.CHECK_FAIL,
            "Watch instrument is explicitly ADMITTED for a new entry"
            if quality_state == "ADMITTED" and quality.get("new_entry_allowed") is not False
            else f"Watch quality admission is {quality_state}",
            evidence_refs=["governing_validation", "fundamentals"],
        ),
        rdd.check(
            "packet_freshness",
            rdd.CHECK_PASS if freshness_state in {"CURRENT", "DUE_SOON"}
            else rdd.CHECK_FAIL,
            f"Watch packet freshness is {freshness_state}",
            evidence_refs=["market", "technicals", "fundamentals", "events"],
        ),
        rdd.check(
            "technical_freshness",
            rdd.CHECK_PASS if technical_freshness in {"CURRENT", "PARTIAL"}
            else rdd.CHECK_FAIL,
            f"technical evidence freshness is {technical_freshness}",
            evidence_refs=["technicals"],
        ),
        rdd.check(
            "presentation_consistency",
            rdd.CHECK_PASS if not conflicts else rdd.CHECK_FAIL,
            "persisted Watch presentation has one coherent operator decision"
            if not conflicts else "; ".join(conflicts),
            evidence_refs=["governing_validation"],
        ),
    ]

    result = rdd.evaluate(
        domain="watch",
        subject={
            "symbol": str(packet.get("symbol") or "").upper(),
            "packet_version": packet.get("packet_version"),
        },
        checks=checks,
        sources=sources,
        evidence={
            "validation_source": selected.get("source"),
            "deterministic": deterministic_state,
            "quality_admission": quality,
            "freshness": freshness,
            "technical_freshness": technical_freshness,
            "presentation_conflicts": conflicts,
        },
        policy_version=quality.get("policy_version")
        or packet.get("action_policy_version")
        or "watch-quality-admission-v1",
        calculation_version=ADAPTER_VERSION,
    )
    result["downstream"].update({
        "watch_research_complete": result["deterministic_state"] == rdd.PASS,
        "proposal_research_may_consume": result["deterministic_state"] == rdd.PASS,
    })
    return result
