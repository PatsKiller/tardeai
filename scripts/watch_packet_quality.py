#!/usr/bin/env python3
"""Canonical deterministic quality and operator-presentation helpers.

A failed family is retained under plan_families after current mechanics are
stripped. Consumers must inspect those audit structures instead of looking only
at current_actionable_plan and incorrectly reporting UNASSESSED.

The operator-presentation contract preserves every family's raw mechanics while
ensuring the desk exposes one sovereign decision. A secondary family whose raw
action_state is READY is displayed as eligibility/evidence unless it is the
selected primary family and the sovereign header is also READY.
"""
from __future__ import annotations

from typing import Iterator

FAMILY_ORDER = ("swing", "long_term", "bearish", "options", "no_trade")
VALIDATION_SEVERITY = {"FAIL": 3, "REVIEW_REQUIRED": 2, "PASS": 1, "NOT_RUN": 0}
QUALITY_SEVERITY = {"QUARANTINED": 3, "RESEARCH_ONLY": 2, "ADMITTED": 1, "UNASSESSED": 0}
PRESENTATION_CONTRACT = "watch-quality-governance-v1"


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
    packet = packet or {}
    candidates = list(iter_ticket_validations(packet))
    if not candidates:
        root_quality = packet.get("quality_admission") or {}
        return {
            "source": "quality_admission" if isinstance(root_quality, dict) and root_quality else None,
            "family": None,
            "ticket": {},
            "validation": {},
            "quality_admission": root_quality if isinstance(root_quality, dict) else {},
            "deterministic": "NOT_RUN",
            "quality": str((root_quality or {}).get("state") or "UNASSESSED").upper(),
        }

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
    quality = validation.get("quality_admission") or packet.get("quality_admission") or {}
    return {
        **selected,
        "quality_admission": quality,
        "deterministic": str(validation.get("state") or "NOT_RUN").upper(),
        "quality": str(quality.get("state") or "UNASSESSED").upper(),
    }


def packet_gate(packet: dict | None) -> dict:
    packet = packet or {}
    selected = select_governing_validation(packet)
    validation = selected["validation"] or {}
    quality = selected.get("quality_admission") or validation.get("quality_admission") or {}
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


def _primary_family(packet: dict) -> str | None:
    current = packet.get("current_actionable_plan") or {}
    operator = packet.get("operator_presentation") or {}
    value = (
        current.get("family")
        or current.get("structure_family")
        or operator.get("primary_family")
        or packet.get("primary_family")
    )
    return str(value).upper() if value else None


def _header_state(packet: dict) -> str:
    operator = packet.get("operator_presentation") or {}
    value = (
        operator.get("header_state")
        or packet.get("decision_state")
        or packet.get("action_state")
        or packet.get("operator_state")
        or "WAIT"
    )
    return str(value).upper()


def apply_operator_presentation(packet: dict | None) -> dict:
    """Persist one sovereign decision without rewriting raw family mechanics."""
    packet = packet if isinstance(packet, dict) else {}
    primary = _primary_family(packet)
    header = _header_state(packet)
    labels: dict[str, str] = {}
    raw_states: dict[str, str] = {}

    for key, family in (packet.get("plan_families") or {}).items():
        if not isinstance(family, dict):
            continue
        family_name = str(key).upper()
        raw = str(family.get("action_state") or family.get("state") or "UNAVAILABLE").upper()
        raw_states[family_name] = raw
        if raw == "READY":
            if family_name == primary and header == "READY":
                display = "READY"
            elif family_name == "LONG_TERM":
                display = "OWNERSHIP ELIGIBLE"
            else:
                display = "MECHANICS VALID"
        else:
            display = raw.replace("_", " ")
        labels[family_name] = display

    existing = packet.get("operator_presentation") or {}
    packet["operator_presentation"] = {
        **existing,
        "contract": PRESENTATION_CONTRACT,
        "header_state": header,
        "primary_family": primary,
        "family_display_states": labels,
        "family_raw_states": raw_states,
        "one_sovereign_decision": True,
    }
    return packet


def presentation_conflicts(packet: dict | None) -> list[str]:
    """Return semantic conflicts in the persisted operator presentation."""
    packet = packet or {}
    operator = packet.get("operator_presentation") or {}
    header = _header_state(packet)
    primary = _primary_family(packet)
    conflicts: list[str] = []

    display_states = operator.get("family_display_states")
    if operator.get("contract") == PRESENTATION_CONTRACT and isinstance(display_states, dict):
        if header != "READY":
            for family, display in display_states.items():
                if str(display).upper() == "READY":
                    conflicts.append(
                        f"header {header} with {family} display READY under {PRESENTATION_CONTRACT}"
                    )
        if header == "READY" and primary and str(display_states.get(primary) or "").upper() != "READY":
            conflicts.append(f"header READY but primary {primary} is not displayed READY")
        return conflicts

    families = packet.get("plan_families") or {}
    if header and header != "READY":
        for key, family in families.items():
            if not isinstance(family, dict):
                continue
            if str(family.get("action_state") or "").upper() == "READY":
                conflicts.append(
                    f"header {header} with non-primary {key} action_state READY; UI must scope as eligibility/evidence"
                )
    return conflicts
