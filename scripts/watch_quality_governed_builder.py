#!/usr/bin/env python3
"""Canonical governed Watch packet builder.

The source-hardened projection is the immutable quality-admission input for a
bounded build. Ticket arithmetic, event, timing and technical validation still
run normally inside ``shadow_decision_service``. Only the duplicate quality
lookup is replaced, so the packet builder cannot reinterpret cache units or
silently lose a quality result when no current ticket exists.

This module is deliberately synchronous and process-local. It temporarily
patches ``watch_quality_policy.evaluate_admission`` while one packet is built,
disables every model/critic lane, restores all process state, then stamps the
projection evidence and one-decision presentation into the packet.
"""
from __future__ import annotations

import copy
import os
import re
from typing import Any

import shadow_decision_service as decision_service
import watch_packet_quality as packet_quality
import watch_quality_policy as quality_policy

CONTRACT = "watch-quality-governed-builder-v1"


def _projection_admission(row: dict, *, family: str | None = None,
                          ticket: dict | None = None) -> dict:
    hard = list(row.get("hard_failures") or [])
    warnings = list(row.get("warnings") or [])
    structure = str((ticket or {}).get("structure") or "").upper()
    for token in quality_policy.EXCLUDED_STRUCTURE_TOKENS:
        if token in structure:
            reason = f"structure {structure} is outside the governed non-scalping Watch mandate"
            if reason not in hard:
                hard.append(reason)

    management_only = bool(row.get("management_only"))
    state = (
        quality_policy.QUARANTINED if hard
        else quality_policy.RESEARCH_ONLY if warnings
        else quality_policy.ADMITTED
    )
    new_entry_allowed = state == quality_policy.ADMITTED and not management_only
    reasons: list[str] = []
    if management_only:
        reasons.append("existing holding remains visible for management only; quality issues block a new add")
    reasons.extend(hard)
    reasons.extend(warnings)

    projected = str(row.get("projected_quality") or "UNASSESSED").upper()
    if state != projected:
        # A ticket-specific excluded structure may only make the state stricter.
        severity = {"UNASSESSED": 0, "ADMITTED": 1, "RESEARCH_ONLY": 2, "QUARANTINED": 3}
        if severity.get(state, 0) < severity.get(projected, 0):
            state = projected
            new_entry_allowed = bool(row.get("new_entry_allowed")) and not management_only

    return {
        "policy_version": "watch-quality-admission-v1",
        "policy_source": "source-hardened watch-quality-projection-v2 evidence",
        "policy_load_ok": True,
        "projection_contract": "watch-quality-projection-v2",
        "projection_generated_at": row.get("projection_generated_at"),
        "state": state,
        "new_entry_allowed": new_entry_allowed,
        "management_only": management_only,
        "family": str(family or "").upper() or None,
        "instrument_class": row.get("instrument_class"),
        "thesis_state": row.get("thesis_state"),
        "reasons": reasons,
        "hard_failures": hard,
        "warnings": warnings,
        "facts_used": copy.deepcopy(row.get("facts_used") or {}),
        "provenance": copy.deepcopy(row.get("provenance") or {}),
        "authority": "deterministic admission only; models cannot override",
    }


def build_packet(symbol: str, conn, projection_row: dict, *, source_commit: str,
                 origin: str, requested_by: str) -> dict:
    """Build one packet with the exact preserved projection admission.

    The caller remains responsible for persistence. A malformed source commit,
    symbol mismatch, model output or review output is a hard error.
    """
    sym = str(symbol or "").upper()
    if not re.fullmatch(r"[A-Z0-9.\-]{1,16}", sym):
        raise RuntimeError("invalid governed Watch symbol")
    if sym != str(projection_row.get("symbol") or "").upper():
        raise RuntimeError("projection row symbol does not match requested symbol")
    if not re.fullmatch(r"[0-9a-f]{40}", str(source_commit or "")):
        raise RuntimeError("source_commit must be an exact 40-character SHA")

    original_admission = quality_policy.evaluate_admission
    old_models = os.environ.get("SHADOW_DISABLE_MODELS")
    old_critic = os.environ.get("SHADOW_DISABLE_TICKET_CRITIC")

    def projected_admission(facts: dict | None, *, technical_snapshot=None,
                            ticket=None, family=None, ownership=None) -> dict:
        return _projection_admission(projection_row, family=family, ticket=ticket)

    try:
        quality_policy.evaluate_admission = projected_admission
        os.environ["SHADOW_DISABLE_MODELS"] = "1"
        os.environ["SHADOW_DISABLE_TICKET_CRITIC"] = "1"
        packet = decision_service.evaluate(
            sym,
            conn,
            origin=origin,
            requested_by=requested_by,
            run_models=False,
        )
    finally:
        quality_policy.evaluate_admission = original_admission
        if old_models is None:
            os.environ.pop("SHADOW_DISABLE_MODELS", None)
        else:
            os.environ["SHADOW_DISABLE_MODELS"] = old_models
        if old_critic is None:
            os.environ.pop("SHADOW_DISABLE_TICKET_CRITIC", None)
        else:
            os.environ["SHADOW_DISABLE_TICKET_CRITIC"] = old_critic

    root_admission = _projection_admission(projection_row)
    packet["quality_admission"] = root_admission
    packet["quality_projection_snapshot"] = {
        "contract": "watch-quality-projection-v2",
        "generated_at": projection_row.get("projection_generated_at"),
        "symbol": sym,
        "rank": projection_row.get("rank"),
        "projected_quality": projection_row.get("projected_quality"),
        "facts_used": copy.deepcopy(projection_row.get("facts_used") or {}),
        "provenance": copy.deepcopy(projection_row.get("provenance") or {}),
    }
    packet["governance_source_commit"] = source_commit
    packet["governance_contracts"] = {
        **(packet.get("governance_contracts") or {}),
        "quality": "watch-quality-admission-v1",
        "projection": "watch-quality-projection-v2",
        "builder": CONTRACT,
        "presentation": packet_quality.PRESENTATION_CONTRACT,
    }
    packet_quality.apply_operator_presentation(packet)

    completed = (packet.get("model_review") or {}).get("lanes_completed") or []
    reviews = (packet.get("ticket_review") or {}).get("reviews") or {}
    if completed or reviews:
        raise RuntimeError("governed LOCAL_QUANT build recorded a model or critic result")
    return packet
