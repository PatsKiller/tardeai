"""Policy provenance — never let a default cash band masquerade as operator policy.

READ_ONLY_ADVISORY. Distinguishes MATERIAL_FACT / POLICY_GAP / ADVISORY_INTERPRETATION.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_cash_evidence import is_evidence_block, unstamped_evidence

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "PolicyProvenance@v1"

# Hardcoded capital-plan defaults. These are ADVISORY_INTERPRETATION, never policy.
DEFAULT_CASH_MIN_PCT = 20.0
DEFAULT_CASH_MAX_PCT = 25.0

KIND_FACT = "MATERIAL_FACT"
KIND_GAP = "POLICY_GAP"
KIND_INTERP = "ADVISORY_INTERPRETATION"

# Freshness vocabulary, shared with the financial truth gate so the operator
# does not have to learn two of them. This module publishes the STAMP, not an
# age verdict -- `effective_at` carries the date and the reader (or the gate)
# decides whether that is recent enough.
FRESH_AS_OF = "VERIFIED_AS_OF"
FRESH_UNDATED = "DATA_UNAVAILABLE"
FRESH_UNAVAILABLE = "UNAVAILABLE"


def cash_fact_freshness(value: Any, cash_as_of: dict[str, Any] | None) -> tuple[str, str | None]:
    """Freshness + effective_at for a cash fact, from the shared derivation.

    This used to be `"CURRENT" if value is not None`, with `effective_at=None`:
    the presence of a number was treated as proof of its age. On the served
    book the number was present and up to 27 days old. A cash figure is now
    dated by the OLDEST balance that contributes to it, or is openly undated.
    """
    if value is None:
        return FRESH_UNAVAILABLE, None
    ev = cash_as_of if is_evidence_block(cash_as_of) else unstamped_evidence()
    stamp = ev.get("as_of")
    if not stamp:
        return FRESH_UNDATED, None
    return FRESH_AS_OF, str(stamp)


def _field(
    *,
    field: str,
    value: Any,
    source: str,
    authority: str,
    version: str | None,
    effective_at: str | None,
    confirmed_by_operator: bool,
    freshness: str,
    kind: str,
) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "source": source,
        "authority": authority,
        "version": version,
        "effective_at": effective_at,
        "confirmed_by_operator": bool(confirmed_by_operator),
        "freshness": freshness,
        "kind": kind,
        "schema": SCHEMA,
    }


def confirmed_cash_range(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    policy = policy or {}
    fields = policy.get("fields") or {}
    raw = fields.get("cash_target_range_pct") or {}
    if isinstance(raw, dict) and raw.get("operator_confirmed") and isinstance(raw.get("value"), dict):
        value = raw["value"]
        if value.get("min") is not None and value.get("max") is not None:
            return {"min": float(value["min"]), "max": float(value["max"])}
    return None


def audit_cash_posture_policy(
    *,
    cash_total_usd: Any,
    portfolio_value_usd: Any,
    live_band: dict[str, Any] | None,
    live_status: str | None,
    policy: dict[str, Any] | None,
    capital_plan_version: str | None = None,
    cash_as_of: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain ABOVE_BAND / IN_BAND without inventing operator policy.

    `cash_as_of` is the capital plan's cash-evidence block (the one shared
    derivation). Omitting it does not make the cash look current -- the facts
    below then publish DATA_UNAVAILABLE rather than borrowing a clock.
    """
    cash_freshness, cash_effective_at = cash_fact_freshness(cash_total_usd, cash_as_of)
    confirmed = confirmed_cash_range(policy)
    cash_pct = None
    try:
        if cash_total_usd is not None and portfolio_value_usd not in (None, 0, 0.0):
            cash_pct = round(float(cash_total_usd) / float(portfolio_value_usd) * 100.0, 4)
    except (TypeError, ValueError, ZeroDivisionError):
        cash_pct = None

    facts = [
        _field(
            field="observed_cash_usd",
            value=cash_total_usd,
            source="verified_holdings_or_capital_plan (oldest contributing balance)",
            authority=AUTHORITY,
            version=capital_plan_version,
            effective_at=cash_effective_at,
            confirmed_by_operator=False,
            freshness=cash_freshness,
            kind=KIND_FACT,
        ),
        _field(
            field="cash_pct",
            value=cash_pct,
            source="observed_cash / portfolio_value",
            authority=AUTHORITY,
            version=capital_plan_version,
            # A ratio is no fresher than its numerator.
            effective_at=cash_effective_at if cash_pct is not None else None,
            confirmed_by_operator=False,
            freshness=(cash_freshness if cash_pct is not None else FRESH_UNAVAILABLE),
            kind=KIND_FACT,
        ),
    ]

    band = live_band or {}
    band_min = band.get("min_pct")
    default_used = (
        confirmed is None
        and band_min is not None
        and abs(float(band_min) - DEFAULT_CASH_MIN_PCT) < 1e-9
    )
    if confirmed:
        policy_status = "CONFIRMED"
        band_kind = KIND_INTERP
        source = "operator_profile.cash_target_range_pct"
        confirmed_flag = True
    else:
        policy_status = "POLICY_GAP"
        band_kind = KIND_GAP if confirmed is None else KIND_INTERP
        source = (
            "cio_capital_plan.CASH_BAND_DEFAULT_MIN_PCT"
            if default_used
            else "capital_plan.cash_policy_band_unconfirmed"
        )
        confirmed_flag = False

    band_row = _field(
        field="cash_target_range_pct",
        value=confirmed or {"min": band.get("min_pct"), "max": band.get("max_pct")},
        source=source,
        authority=AUTHORITY,
        version=capital_plan_version,
        effective_at=None,
        confirmed_by_operator=confirmed_flag,
        freshness="CURRENT" if confirmed_flag else "UNCONFIRMED",
        kind=KIND_GAP if not confirmed_flag else KIND_INTERP,
    )

    status_kind = KIND_INTERP
    if not confirmed_flag:
        status_kind = KIND_GAP
    status_row = _field(
        field="cash_posture_status",
        value=live_status,
        source="cio_capital_plan.cash_posture vs band",
        authority=AUTHORITY,
        version=capital_plan_version,
        # ABOVE_BAND / IN_BAND is a verdict ON the cash figure, so it inherits
        # the cash figure's age. It used to be flatly CURRENT.
        effective_at=cash_effective_at,
        confirmed_by_operator=False,
        freshness=cash_freshness,
        kind=status_kind,
    )

    masquerade = bool(live_status == "ABOVE_BAND" and not confirmed_flag)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "policy_status": policy_status,
        "cash_posture_status": live_status,
        "masquerades_as_operator_policy": masquerade,
        "may_recommend_deployment": bool(confirmed_flag and live_status == "ABOVE_BAND"),
        "material_fact": facts,
        "policy": band_row,
        "interpretation": status_row,
        "default_band_used": default_used,
        "operator_question": (
            "Cash is a material observed fact, but I cannot complete a deployment "
            "recommendation because cash_target_range_pct is not operator-confirmed."
            if (not confirmed_flag and cash_pct is not None and cash_pct >= 20.0)
            else None
        ),
        "financial_action": False,
        "memory_behavior_influence": 0,
    }


def assert_not_operator_policy(row: dict[str, Any]) -> None:
    if row.get("confirmed_by_operator") and row.get("source", "").startswith("cio_capital_plan.CASH_BAND_DEFAULT"):
        raise AssertionError("default_cash_band_masquerading_as_operator_policy")
