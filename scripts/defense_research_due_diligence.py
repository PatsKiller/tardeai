#!/usr/bin/env python3
"""Shared due-diligence adapter for all Defense recommendation groups.

Rotate-in cards use the stricter sector/account/risk adapter in
``research_due_diligence_adapters``. This module covers protection, trim, hedge,
pair and other advisory recommendation families so no Defense card remains
silently unassessed. The adapter never changes card mechanics or activates a
recommendation.
"""
from __future__ import annotations

from typing import Any

import research_due_diligence as rdd

ADAPTER_VERSION = "defense-all-groups-due-diligence-v1"


def _accounts(card: dict) -> list[str]:
    values = card.get("accounts") or []
    if isinstance(values, str):
        values = [values]
    out = {str(value) for value in values if value}
    for key in ("account", "account_key", "account_id"):
        if card.get(key):
            out.add(str(card[key]))
    out.update(str(key) for key in (card.get("account_sizing") or {}))
    out.update(str(key) for key in (card.get("allocation_policy") or {}))
    return sorted(out)


def _instruments(card: dict) -> list[dict]:
    values = []
    for item in card.get("instruments") or []:
        if isinstance(item, dict):
            values.append(item)
        elif item:
            values.append({"symbol": str(item)})
    for key in ("symbol", "underlying", "etf"):
        if card.get(key):
            values.append({"symbol": str(card[key]), "source_field": key})
    ticket = card.get("ticket") or {}
    for item in ticket.get("options") or []:
        if isinstance(item, dict):
            values.append(item)
        elif item:
            values.append({"line": str(item)})
    seen = set()
    out = []
    for item in values:
        key = str(item.get("symbol") or item.get("occ_symbol") or item.get("line") or item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _rationale(card: dict) -> Any:
    return (
        card.get("trim_rationale")
        or card.get("entry_logic")
        or card.get("rationale")
        or card.get("reason")
        or card.get("style_rationale")
        or card.get("factors")
    )


def _mechanics(card: dict) -> dict:
    return {
        "levels": card.get("levels"),
        "ticket": card.get("ticket"),
        "size_band": card.get("size_band"),
        "account_sizing": card.get("account_sizing"),
        "invalidation": card.get("invalidation"),
        "on_trigger": card.get("on_trigger"),
        "sell_ticket": card.get("sell_ticket"),
        "buy_legs": card.get("buy_legs"),
        "dollars_by_account": card.get("dollars_by_account"),
    }


def defense_card_due_diligence(card: dict, snapshot: dict) -> dict:
    """Evaluate one non-rotate-in Defense card without inventing domain facts."""
    group = str(card.get("group") or "unknown").lower()
    as_of = card.get("as_of") or snapshot.get("generated_at")
    quality_gate = card.get("quality_gate") or {}
    calc_version = (
        quality_gate.get("version")
        or card.get("calculation_version")
        or snapshot.get("calculation_version")
        or "defense-recommendations-unversioned"
    )
    accounts = _accounts(card)
    instruments = _instruments(card)
    rationale = _rationale(card)
    mechanics = _mechanics(card)
    has_mechanics = any(value not in (None, "", [], {}) for value in mechanics.values())
    pair_complete = bool(card.get("sell_ticket") and card.get("buy_legs"))

    sources = [
        rdd.source_ref(
            source_id="defense_card",
            provider="Defense recommendation producer",
            as_of=as_of,
            calculation_version=calc_version,
            quality="ok" if card else "missing",
            required=True,
            payload=card,
        ),
        rdd.source_ref(
            source_id="account_scope",
            provider="Defense account routing and sizing context",
            as_of=as_of,
            calculation_version=calc_version,
            quality="ok" if accounts else "missing",
            required=True,
            payload={
                "accounts": accounts,
                "account_sizing": card.get("account_sizing"),
                "dollars_by_account": card.get("dollars_by_account"),
            },
        ),
        rdd.source_ref(
            source_id="instrument_scope",
            provider="Defense instrument or leg registry",
            as_of=as_of,
            calculation_version=calc_version,
            quality="ok" if instruments else "missing",
            required=True,
            payload=instruments,
        ),
        rdd.source_ref(
            source_id="mechanics",
            provider="deterministic Defense recommendation mechanics",
            as_of=as_of,
            calculation_version=calc_version,
            quality="ok" if has_mechanics else "missing",
            required=True,
            payload=mechanics,
        ),
        rdd.source_ref(
            source_id="quality_gate",
            provider="Defense specialized quality gate",
            as_of=as_of,
            calculation_version=quality_gate.get("version") or calc_version,
            quality="ok" if quality_gate else "unconfirmed",
            required=False,
            payload=quality_gate,
        ),
    ]

    checks = [
        rdd.check(
            "shadow_mode",
            rdd.CHECK_PASS if card.get("mode") == "SHADOW" else rdd.CHECK_FAIL,
            "Defense recommendation remains SHADOW/advisory"
            if card.get("mode") == "SHADOW"
            else "Defense recommendation mode is not SHADOW",
            evidence_refs=["defense_card"],
        ),
        rdd.check(
            "card_identity",
            rdd.CHECK_PASS if card.get("id") and card.get("title") and group != "unknown"
            else rdd.CHECK_FAIL,
            "card id, title and recommendation group are explicit"
            if card.get("id") and card.get("title") and group != "unknown"
            else "card id, title or recommendation group is missing",
            evidence_refs=["defense_card"],
        ),
        rdd.check(
            "account_scope",
            rdd.CHECK_PASS if accounts else rdd.CHECK_FAIL,
            "account scope is explicit" if accounts else "account scope is missing",
            evidence_refs=["account_scope"],
            details={"accounts": accounts},
        ),
        rdd.check(
            "instrument_scope",
            rdd.CHECK_PASS if instruments else rdd.CHECK_FAIL,
            "instrument or leg scope is explicit"
            if instruments else "instrument or leg scope is missing",
            evidence_refs=["instrument_scope"],
        ),
        rdd.check(
            "research_rationale",
            rdd.CHECK_PASS if rationale else rdd.CHECK_FAIL,
            "recommendation rationale or deterministic factors are explicit"
            if rationale else "recommendation rationale and factors are missing",
            evidence_refs=["defense_card"],
        ),
        rdd.check(
            "action_mechanics",
            rdd.CHECK_PASS if has_mechanics else rdd.CHECK_FAIL,
            "recommendation carries explicit size, level, trigger, invalidation or leg mechanics"
            if has_mechanics else "recommendation mechanics are missing",
            evidence_refs=["mechanics"],
        ),
        rdd.check(
            "pair_legs",
            rdd.CHECK_PASS if group != "pair" or pair_complete else rdd.CHECK_FAIL,
            "pair recommendation has both sell and buy legs"
            if group == "pair" and pair_complete
            else "pair recommendation is missing one or more legs"
            if group == "pair" else "not a pair recommendation",
            evidence_refs=["mechanics", "instrument_scope"],
        ),
        rdd.check(
            "quality_disclosure",
            rdd.CHECK_PASS if quality_gate else rdd.CHECK_WARN,
            "specialized quality gate result is attached"
            if quality_gate else "specialized quality gate is not attached; specialist review required",
            evidence_refs=["quality_gate"],
        ),
    ]

    result = rdd.evaluate(
        domain="defense",
        subject={
            "card_id": card.get("id"),
            "group": group,
            "title": card.get("title"),
        },
        checks=checks,
        sources=sources,
        evidence={
            "accounts": accounts,
            "instruments": instruments,
            "rationale": rationale,
            "mechanics": mechanics,
            "quality_gate": quality_gate,
        },
        policy_version="research-due-diligence-policy-v1",
        calculation_version=ADAPTER_VERSION,
    )
    result["downstream"].update({
        "defense_research_complete": result["deterministic_state"] == rdd.PASS,
        "recommendation_card_eligible": result["deterministic_state"] == rdd.PASS,
        "recommendation_activation": False,
    })
    return result
