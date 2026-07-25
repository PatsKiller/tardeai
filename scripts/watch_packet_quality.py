#!/usr/bin/env python3
"""Canonical extraction of deterministic quality/validation state from a packet.

A failed family is retained under plan_families after current mechanics are
stripped. Consumers must inspect those audit structures instead of looking only
at current_actionable_plan and incorrectly reporting UNASSESSED.
"""
from __future__ import annotations

from typing import Iterator

FAMILY_ORDER = ("swing", "long_term", "bearish", "options", "no_trade")
VALIDATION_SEVERITY = {"FAIL": 3, "REVIEW_REQUIRED": 2, "PASS": 1, "NOT_RUN": 0}
QUALITY_SEVERITY = {"QUARANTINED": 3, "RESEARCH_ONLY": 2, "ADMITTED": 1, "UNASSESSED": 0}


def iter_ticket_validations(packet: dict | None) -> Iterator[dict]:
    packet = packet or {}
    current = packet.get("current_actionable_plan")
    if isinstance(current, dict) and isinstance(current.get("ticket_validation"), dict):
        yield {
            "source": "current_actionable_plan",
            "family": current.get("family") or current.get("structure_family"),
            "ticket": current,
            "validation": current["ticket_validation"],
        }

    families = packet.get("plan_families") or {}
    for family_key in FAMILY_ORDER:
        family = families.get(family_key) or {}
        family_validation = family.get("ticket_validation")
        if isinstance(family_validation, dict):
            yield {
                "source": f"plan_families.{family_key}",
                "family": family_key.upper(),
                "ticket": family,
                "validation": family_validation,
            }
        for index, structure in enumerate(family.get("structures") or []):
            if not isinstance(structure, dict):
                continue
            validation = structure.get("ticket_validation")
            if isinstance(validation, dict):
                yield {
                    "source": f"plan_families.{family_key}.structures[{index}]",
                    "family": family_key.upper(),
                    "ticket": structure,
                    "validation": validation,
                }


def select_governing_validation(packet: dict | None) -> dict:
    candidates = list(iter_ticket_validations(packet))
    if not candidates:
        return {
            "source": None,
            "family": None,
            "ticket": {},
            "validation": {},
            "deterministic": "NOT_RUN",
            "quality": "UNASSESSED",
        }

    # Current actionable plan is governing when present. If mechanics were
    # stripped, select the most severe retained family result so a failure can
    # never disappear into an UNASSESSED label.
    current = next((item for item in candidates
                    if item["source"] == "current_actionable_plan"), None)
    if current:
        selected = current
    else:
        def severity(item):
            validation = item["validation"] or {}
            quality = validation.get("quality_admission") or {}
            return (
                VALIDATION_SEVERITY.get(str(validation.get("state") or "NOT_RUN").upper(), 0),
                QUALITY_SEVERITY.get(str(quality.get("state") or "UNASSESSED").upper(), 0),
            )
        selected = max(candidates, key=severity)

    validation = selected["validation"] or {}
    quality = validation.get("quality_admission") or {}
    return {
        **selected,
        "deterministic": str(validation.get("state") or "NOT_RUN").upper(),
        "quality": str(quality.get("state") or "UNASSESSED").upper(),
    }


def packet_gate(packet: dict | None) -> dict:
    packet = packet or {}
    selected = select_governing_validation(packet)
    validation = selected["validation"] or {}
    quality = validation.get("quality_admission") or {}
    ownership = packet.get("ownership") or {}
    return {
        "validation_source": selected.get("source"),
        "family": selected.get("family"),
        "quality": selected["quality"],
        "new_entry_allowed": quality.get("new_entry_allowed"),
        "deterministic": selected["deterministic"],
        "held": bool(ownership.get("held") or ownership.get("shares")),
        "quality_reasons": quality.get("reasons") or [],
        "hard_failures": validation.get("hard_failures") or [],
        "warnings": validation.get("warnings") or [],
        "ticket_hash": validation.get("ticket_hash"),
    }


def presentation_conflicts(packet: dict | None) -> list[str]:
    """Return deterministic semantic conflicts in persisted presentation data."""
    packet = packet or {}
    operator = packet.get("operator_presentation") or {}
    header = str(operator.get("header_state") or packet.get("decision_state") or "").upper()
    families = packet.get("plan_families") or {}
    conflicts: list[str] = []
    if header and header != "READY":
        for key, family in families.items():
            if not isinstance(family, dict):
                continue
            if str(family.get("action_state") or "").upper() == "READY":
                conflicts.append(
                    f"header {header} with non-primary {key} action_state READY; UI must scope as eligibility/evidence"
                )
    return conflicts
