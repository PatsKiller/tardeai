#!/usr/bin/env python3
"""OscillatorRegistry@v1 — the one canonical name for every oscillator.

Reads ``config/oscillator_registry.json``. Anything that wants to say "which
oscillator produced this reading" goes through here, so a sector RS transition,
a style spread, an industry quadrant, and a symbol confluence flip can each be
named and scoped without every producer inventing its own vocabulary.

Before this module, no registry existed. Twenty-plus oscillator-family
indicators across four scopes each carried their own state vocabulary, and
nothing downstream could tell the operator (or the CIO, or the Advisory Desk)
WHICH oscillator a number came from.

Design constraints (AGENTS.md §13.4, §13.7):
  * one canonical source of truth per concept — this file, not a per-producer
    constant
  * every registered oscillator names its producer file and store, so a DARK
    oscillator is visible here rather than discovered later
  * fail closed: an unregistered id, or a state outside that oscillator's
    declared set, raises rather than emitting an affiliation nobody can trust
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA = "OscillatorRegistry@v1"

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _ROOT / "config" / "oscillator_registry.json"

VALID_SCOPES = ("market", "style", "sector", "industry", "symbol")


class OscillatorRegistryError(ValueError):
    """The registry refused to emit an affiliation for this input."""


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise OscillatorRegistryError(
            f"oscillator registry schema is {raw.get('schema')!r}, expected {SCHEMA!r}"
        )
    return raw


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict[str, Any]]:
    return {o["oscillator_id"]: o for o in _load().get("oscillators", [])}


def registry_path() -> Path:
    return _REGISTRY_PATH


def oscillator_ids() -> tuple[str, ...]:
    """All registered oscillator ids, in declaration order."""
    return tuple(o["oscillator_id"] for o in _load().get("oscillators", []))


def get(oscillator_id: str) -> dict[str, Any]:
    """The registry entry for one oscillator. Raises on an unregistered id."""
    osc = _by_id().get(oscillator_id)
    if osc is None:
        raise OscillatorRegistryError(
            f"unregistered oscillator_id {oscillator_id!r}; registered: "
            f"{sorted(_by_id())}"
        )
    return osc


def all_entries() -> list[dict[str, Any]]:
    return [dict(o) for o in _load().get("oscillators", [])]


def _validate_state(osc: dict[str, Any], state: str | None) -> None:
    states = osc.get("states") or []
    if not states:
        # Oscillators with no named states (e.g. a raw breadth percent) accept
        # any state label the producer supplies; the registry simply records it.
        return
    if state is None:
        return
    if state not in states:
        raise OscillatorRegistryError(
            f"state {state!r} is not declared for {osc['oscillator_id']!r}; "
            f"declared: {states}"
        )


def affiliation_for(
    oscillator_id: str,
    *,
    reading_name: str | None = None,
    reading: Any = None,
    state: str | None = None,
    prior_state: str | None = None,
    as_of: str | datetime | None = None,
    confirm_days: int | None = None,
) -> dict[str, Any]:
    """Build the affiliation tag for one reading.

    ``reading`` is carried as a number where possible so downstream consumers
    (notably the Advisory Desk evidence-fidelity check) can verify that any
    prose quoting it is not a fabricated figure. A reading that is not numeric
    is still carried, but is not claimed to be a measured number.
    """
    osc = get(oscillator_id)
    _validate_state(osc, state)
    _validate_state(osc, prior_state)

    scope = osc.get("scope", "symbol")
    if scope not in VALID_SCOPES:
        raise OscillatorRegistryError(
            f"oscillator {oscillator_id!r} declares scope {scope!r}; "
            f"valid: {VALID_SCOPES}"
        )

    if as_of is None:
        as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    elif isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        as_of = as_of.isoformat()

    tag: dict[str, Any] = {
        "oscillator_id": oscillator_id,
        "display_name": osc["display_name"],
        "scope": scope,
        "reading_name": reading_name or osc.get("reading_name"),
        "state": state,
        "producer": osc["producer"],
        "as_of": as_of,
    }
    if prior_state is not None:
        tag["prior_state"] = prior_state
    if confirm_days is not None:
        tag["confirm_days"] = confirm_days
    # Reading is carried separately so it can be numeric-or-null without
    # forcing every consumer to guess its type.
    tag["reading"] = reading
    tag["reading_is_numeric"] = (
        isinstance(reading, (int, float)) and not isinstance(reading, bool)
    )
    return tag


def evidence_item_for(
    oscillator_id: str,
    *,
    subject: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """An Advisory-Desk-shaped evidence item carrying the affiliation.

    The ``title`` names the oscillator and its subject, so an ADD/TRIM/EXIT
    verdict can cite "Sector Rotation RS20 LAGGING" by name. ``value`` carries
    the numeric reading so the evidence-fidelity check accepts prose that
    quotes it rather than flagging it as fabricated.
    """
    tag = affiliation_for(oscillator_id, **kwargs)
    scope = tag["scope"]
    item_type = f"oscillator_{scope}"
    title = f"{tag['display_name']} {tag.get('reading_name') or ''}".strip()
    item: dict[str, Any] = {
        "type": item_type,
        "oscillator_id": oscillator_id,
        "title": f"{title} · {subject}",
        "state": tag.get("state"),
        "scope": scope,
        "as_of": tag["as_of"],
    }
    if tag.get("reading_is_numeric"):
        item["value"] = tag["reading"]
        r = tag["reading"]
        # Natural sign: negative readings keep their minus, positives are plain.
        item["value_label"] = f"{r:.1f}" if isinstance(r, float) else str(r)
    if tag.get("prior_state") is not None:
        item["prior_state"] = tag["prior_state"]
    return item


def try_affiliation_for(
    oscillator_id: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Fail-soft affiliation for producer emit points.

    Affiliation is additive labelling. A producer computing momentum must not
    lose its core output because the registry cannot be reached (missing file
    in a release, transient parse error). This returns None rather than
    raising, so a producer can stamp "no affiliation" and keep running.

    The strict `affiliation_for` stays for consumers and tests, where an
    unregistered id or invalid state is a genuine defect that must fail.
    """
    try:
        return affiliation_for(oscillator_id, **kwargs)
    except Exception:
        return None


def message_prefix_for(oscillator_id: str) -> str:
    """The short operator-facing label used to prefix an alert line."""
    return get(oscillator_id)["display_name"].upper()
