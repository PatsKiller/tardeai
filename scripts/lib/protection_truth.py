#!/usr/bin/env python3
"""protection_truth.py — how much of the book actually has a stop under it.

Two defects, both measured on live data 2026-09-03:

1. **Real protection reported as absent.** Four positions (V, SCHD, DIV, BAH,
   $72,782.66 of market value) carry BROKER-VERIFIED stops — the served rows say
   ``has_stop=true, broker_protected=true, stop_source="broker"`` — yet their
   status reads ``NO STOP`` and their market value is excluded from
   ``total_protected_mv``. The aggregate is built by ``portfolio_stops`` from the
   planned-stops file alone, so a stop that lives at the broker is invisible to
   it. The operator is told $72.8k is unprotected when it is not.

2. **A percentage whose numerator and denominator come from different
   populations.** ``pct_protected = total_protected_mv / total_mv`` divides by the
   WHOLE portfolio ($1,299,166.67) while ``total_unprotected_mv`` sums only the
   risk-included subset ($653,205.34). Protected + unprotected does not equal the
   denominator, so the published 0.39% answers a question nobody asked.

Together they understate stop coverage by roughly thirty-fold: 0.39% published
against 11.92% of the risk-included population actually covered.

This module recomputes protection from the ONE population that carries the stop
facts — the served position rows — and publishes the numerator, the denominator
and the population rule by name. A position whose stop facts are absent is
``UNKNOWN``: never inferred as protected, and never inferred as unprotected.

AUTHORITY: READ_ONLY_ADVISORY. Pure functions over rows already fetched. No
network, broker, order, scheduler or production mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA = "ProtectionTruth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "1.0.0"

# ── protection classes. Four, not two. ───────────────────────────────────────
BROKER_VERIFIED = "BROKER_VERIFIED"
"""A stop the broker confirms it is holding."""

PLANNED_ONLY = "PLANNED_ONLY"
"""A stop level we intend but the broker is not holding. Not the same thing."""

UNPROTECTED = "UNPROTECTED"
"""Positively known to have no stop of either kind."""

UNKNOWN = "UNKNOWN"
"""The stop facts are missing. Never counted as protected OR unprotected."""

CLASSES = (BROKER_VERIFIED, PLANNED_ONLY, UNPROTECTED, UNKNOWN)

#: The population the percentage is taken over. Named, so it can be argued with.
DENOMINATOR_RULE = (
    "risk_included_positions: every position the risk surface returns, excluding "
    "rows flagged risk_excluded. Cash and non-position assets are NOT in the "
    "denominator, because a stop is not a thing cash can have."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def classify_position(row: dict[str, Any]) -> tuple[str, str]:
    """Classify one position's protection. Returns (class, reason).

    Absence of evidence is ``UNKNOWN``. The one thing this must never do is pick
    a side when the row does not say.
    """
    has_stop = row.get("has_stop")
    broker = row.get("broker_protected")
    source = (row.get("stop_source") or "").strip().lower()
    stop_price = _num(row.get("stop_price"))

    known = any(k in row for k in ("has_stop", "broker_protected", "stop_source"))
    if not known:
        return UNKNOWN, "the row carries no stop facts at all"

    if broker is True or source == "broker":
        return BROKER_VERIFIED, f"broker_protected={broker!r} stop_source={source or 'unset'!r}"
    if has_stop is True or source == "planned" or (stop_price is not None and stop_price > 0):
        return PLANNED_ONLY, (
            f"a stop level is recorded (has_stop={has_stop!r} stop_source={source or 'unset'!r}) "
            "but the broker is not holding it"
        )
    if has_stop is False or source in ("none", "", "null"):
        return UNPROTECTED, f"has_stop={has_stop!r} stop_source={source or 'unset'!r}"
    return UNKNOWN, f"stop facts present but undecidable: has_stop={has_stop!r} stop_source={source!r}"


def protection_truth(
    positions: Iterable[dict[str, Any]] | None,
    *,
    legacy: dict[str, Any] | None = None,
    max_list: int = 50,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute protection over one population, with everything named.

    ``legacy`` is the risk payload's own ``pct_protected`` / ``total_protected_mv``
    / ``total_unprotected_mv``. It is compared, never trusted: where the two
    disagree the disagreement is published rather than silently resolved.
    """
    rows = list(positions or [])
    if not rows:
        return {
            "schema": SCHEMA,
            "calculation_version": CALCULATION_VERSION,
            "authority": AUTHORITY,
            "as_of": _now(),
            "status": "UNAVAILABLE",
            "reason": "the risk surface returned no positions; protection coverage is unknown, not zero",
            "position_count": 0,
            "denominator_rule": DENOMINATOR_RULE,
            "observation": observation or {},
        }

    included = [r for r in rows if not r.get("risk_excluded")]
    excluded = [r for r in rows if r.get("risk_excluded")]

    by_class: dict[str, dict[str, Any]] = {c: {"count": 0, "market_value": 0.0, "symbols": []} for c in CLASSES}
    detail = []
    undated_mv = 0.0
    for r in included:
        cls, why = classify_position(r)
        mv = _num(r.get("market_value"))
        if mv is None:
            undated_mv += 0.0
            mv_val = 0.0
            mv_known = False
        else:
            mv_val = mv
            mv_known = True
        b = by_class[cls]
        b["count"] += 1
        b["market_value"] += mv_val
        b["symbols"].append(r.get("symbol"))
        detail.append(
            {
                "symbol": r.get("symbol"),
                "account": r.get("account"),
                "market_value": mv,
                "market_value_known": mv_known,
                "protection_class": cls,
                "reason": why,
            }
        )

    for c in CLASSES:
        by_class[c]["market_value"] = round(by_class[c]["market_value"], 2)

    denom_mv = round(sum(by_class[c]["market_value"] for c in CLASSES), 2)
    # UNKNOWN is deliberately outside BOTH the covered and the uncovered figure.
    covered_mv = round(by_class[BROKER_VERIFIED]["market_value"] + by_class[PLANNED_ONLY]["market_value"], 2)
    broker_mv = by_class[BROKER_VERIFIED]["market_value"]
    unknown_mv = by_class[UNKNOWN]["market_value"]
    decidable_mv = round(denom_mv - unknown_mv, 2)

    def pct(numerator: float, denominator: float) -> float | None:
        return round(numerator / denominator * 100, 2) if denominator else None

    accounts = sorted({str(r.get("account")) for r in included if r.get("account")})
    truncated = len(detail) > max_list

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "status": "OK",
        "denominator_rule": DENOMINATOR_RULE,
        "population": {
            "positions_returned": len(rows),
            "risk_included": len(included),
            "risk_excluded": len(excluded),
            "accounts": accounts,
            "account_count": len(accounts),
            "scope": "ALL_ACCOUNTS" if len(accounts) != 1 else accounts[0],
        },
        "counts": {c: by_class[c]["count"] for c in CLASSES},
        "market_value": {c: by_class[c]["market_value"] for c in CLASSES},
        "denominator_market_value": denom_mv,
        "decidable_market_value": decidable_mv,
        "coverage": {
            "any_stop_pct_of_included": pct(covered_mv, denom_mv),
            "any_stop_pct_of_decidable": pct(covered_mv, decidable_mv),
            "broker_verified_pct_of_included": pct(broker_mv, denom_mv),
            "numerator": "market value of BROKER_VERIFIED + PLANNED_ONLY positions",
            "denominator": "market value of every risk-included position",
            "unknown_excluded_from_both": True,
            "unknown_market_value": unknown_mv,
        },
        "positions": detail[:max_list],
        "list_truncated": truncated,
        "list_shown": min(len(detail), max_list),
        "list_total": len(detail),
        "observation": observation or {},
        "rule": (
            "A position with no stop facts is UNKNOWN and is counted in neither the "
            "covered nor the uncovered figure. Protection is never inferred."
        ),
    }

    if legacy:
        legacy_prot = _num(legacy.get("total_protected_mv"))
        legacy_unprot = _num(legacy.get("total_unprotected_mv"))
        legacy_pct = _num(legacy.get("pct_protected"))
        implied_denom = (
            round(legacy_prot / (legacy_pct / 100), 2)
            if legacy_prot is not None and legacy_pct not in (None, 0)
            else None
        )
        agrees_mv = legacy_prot is not None and abs(legacy_prot - covered_mv) < 0.01
        agrees_denom = (
            implied_denom is not None
            and legacy_prot is not None
            and legacy_unprot is not None
            and abs(implied_denom - (legacy_prot + legacy_unprot)) < 0.01
        )
        missed = [d["symbol"] for d in detail if d["protection_class"] == BROKER_VERIFIED]
        result["legacy_comparison"] = {
            "legacy_total_protected_mv": legacy_prot,
            "legacy_total_unprotected_mv": legacy_unprot,
            "legacy_pct_protected": legacy_pct,
            "legacy_implied_denominator": implied_denom,
            "legacy_denominator_matches_its_own_parts": agrees_denom,
            "recomputed_covered_mv": covered_mv,
            "recomputed_pct_of_included": pct(covered_mv, denom_mv),
            "agrees_on_protected_mv": agrees_mv,
            "broker_verified_symbols_the_legacy_figure_omits": ([] if agrees_mv else missed),
            "verdict": "AGREES" if (agrees_mv and agrees_denom) else "DISAGREES",
            "why": (
                ""
                if (agrees_mv and agrees_denom)
                else (
                    "the legacy aggregate is built from the planned-stops file only, so "
                    "broker-held stops are missing from it, and its percentage divides by "
                    "the whole portfolio rather than by the population it sums"
                )
            ),
        }
    return result
