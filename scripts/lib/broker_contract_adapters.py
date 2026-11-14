"""Adapters: lift an existing page payload into :mod:`lib.broker_contract` (SPRINT 8H-2 b2).

The rule: **an adapter lifts and labels; it never recomputes an authoritative metric.** The payload
already carries its measures (``scripts/lib/portfolio_measures.py``), its coverage, its stored
reconciliation and its ``truth`` block. This module puts those under one ``snapshot_id`` and the
seven distinct clocks so Portfolio, Risk, Home and any export can cite the same value at the same
version. It adds no read: no DB, no file, no clock of its own (``now`` is injected).

Evidence status (e.g. ``MEASURED`` / ``PARTIAL`` / ``UNKNOWN``) is carried through as the verdict;
the counted / listed-not-counted split is the payload's, never re-derived here (the $100 rule and
the unpriced-always-counts rule are policy in the producer, not presentation).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from lib import broker_contract as bc

#: Domains a page serves through this contract. Every one must carry a registry row with a stale
#: window before a page may show a freshness verdict for it (lead ruling 2026-11-14T14:27:49Z).
SERVED_DOMAINS: tuple[str, ...] = (
    "portfolio_summary",
    "positions_store",
    "incidents",
    "protection",
    "gates",
    "lane_health",
)

_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"


def stale_window(domain: str, *, registry_path: Path | None = None) -> float | None:
    """The declared ``stale_after_hours`` for ``domain``, or None when no row declares one.

    Callers pass the result into an adapter's ``stale_after_hours``; the adapter itself has no config
    dependency, so a test can drive it with an explicit window. None means "no contract": the
    envelope renders UNKNOWN/NO_FRESHNESS_CONTRACT rather than a fresh-looking default.
    """
    try:
        auth = json.loads((registry_path or _REGISTRY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for row in auth.get("domains") or []:
        if isinstance(row, Mapping) and row.get("domain") == domain:
            window = row.get("stale_after_hours")
            return float(window) if isinstance(window, (int, float)) else None
    return None


def _deep_get(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _cents(dollars: Any) -> int | None:
    """Dollars → integer cents for display arithmetic. The stored exact-cent bridge stays authoritative.

    ``Decimal(str(d))`` is exact for the printed value; ``float(d) * 100`` inherits binary rounding
    (1234.565 → 123456.49999…). The producers publish 2 dp so the difference is theoretical — this
    costs nothing and removes the question (cc-deepseek-8 review, observation 1.1).
    """
    if dollars is None:
        return None
    try:
        return int((Decimal(str(dollars)) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _measure_block(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return _deep_get(payload, "measures", "measures", name) or {}


def _verdict_for(status: str | None) -> str:
    s = str(status or "").upper()
    if s in ("MEASURED", "OK", "KNOWN"):
        return "OK"
    if s == "PARTIAL":
        return "PARTIAL"
    if s == "STALE":
        return "STALE"
    if s in ("FAILED", "ERROR"):
        return "FAILED"
    return "UNKNOWN"


def _pnl_block(payload: dict[str, Any], *, price_move_cents: int | None, account_change_cents: int | None) -> dict[str, Any]:
    """P&L as two typed measures + a verification that needs a stored, signed reconciliation.

    The producer (``scripts/lib/portfolio_measures.py``) republishes its stored
    ``doc["verified_reconciliation"]`` as ``{status: VERIFIED, value, as_of, source}``; there is no
    separate receipt-id field, so the stored record IS the evidence and its identity is
    ``source@as_of``. A VERIFIED status with no value/source/as_of is not a receipt.
    """
    verified = _measure_block(payload, "verified_daily_pnl")
    value = verified.get("value")
    if value is None:
        value = payload.get("verified_daily_pnl")
    sign_off = None
    if (str(verified.get("status") or payload.get("verified_daily_pnl_status") or "").upper() == "VERIFIED"
            and value is not None and verified.get("source") and verified.get("as_of")):
        sign_off = {
            "reconciliation_id": f"stored:{verified['source']}@{verified['as_of']}",
            "signed_at": verified["as_of"],
            "by": verified["source"],
        }
    out = bc.pnl(price_move_cents=price_move_cents, account_change_cents=account_change_cents, sign_off=sign_off)
    out["stored_status"] = verified.get("status") or payload.get("verified_daily_pnl_status")
    out["stored_value_cents"] = _cents(value)
    out["stored_as_of"] = verified.get("as_of")
    out["stored_source"] = verified.get("source")
    return out


def portfolio_evidence(
    payload: dict[str, Any],
    *,
    versions: dict[str, Any],
    scope: dict[str, Any] | None,
    stale_after_hours: float | None,
    now: datetime | None = None,
    built_at: Any = None,
    checked_at: Any = None,
    served_at: Any = None,
) -> dict[str, Any]:
    """Wrap a holdings/performance payload in the shared envelope (HQ-07, PR-002, PR-007, HQ-31).

    ``stale_after_hours`` has no default on purpose: the registry does not yet declare these domains,
    and an adapter must not invent a freshness window. Pass the window explicitly until the registry
    row exists; with None the envelope is UNKNOWN / ``NO_FRESHNESS_CONTRACT``.
    """
    truth = payload.get("truth") or {}
    source_as_of = truth.get("as_of") or payload.get("positions_as_of")
    account_value = _measure_block(payload, "account_value")
    price_move = _measure_block(payload, "price_move_estimate")
    change_1d = _measure_block(payload, "account_value_change_1d")

    # A truthy non-mapping is worse than an absent block: `if not payload.get("measures")` let a string
    # through, every block below then read as {}, and the verdict fell back to ANOTHER measure's status —
    # an OK envelope with a null account value. The shape is checked, not merely the presence (b3).
    measures_raw = payload.get("measures")
    measures_block = _deep_get(payload, "measures", "measures")
    if not isinstance(measures_raw, Mapping) or not isinstance(measures_block, Mapping) or not measures_block:
        return bc.build_evidence(
            "portfolio_summary",
            verdict="UNKNOWN",
            versions=versions,
            scope=scope,
            source_as_of=source_as_of,
            built_at=built_at,
            checked_at=checked_at,
            served_at=served_at,
            stale_after_hours=stale_after_hours,
            session_id=(scope or {}).get("session_id"),
            value=None,
            cause=bc._cause(
                "MEASURES_ABSENT" if not measures_raw else "MEASURES_UNREADABLE",
                detail=("the payload carries no measures block; no authoritative value can be cited"
                        if not measures_raw else
                        f"the payload's measures member is {type(measures_raw).__name__}, not a block with a "
                        "`measures` object; no authoritative value can be cited"),
                owner="portfolio measures writer",
                next_action="run the measures writer, then re-read",
            ),
            now=now,
        )

    # coverage lives on the price-move measure (measured_rows / unknown_rows / row_count) — the row
    # population every page figure is computed over.
    coverage = price_move.get("coverage") or {}
    counted = coverage.get("measured_rows")
    total = coverage.get("row_count")
    exclusions: list[dict[str, Any]] = []
    if coverage.get("unknown_rows"):
        exclusions.append({"reason": "rows without a measured mark", "count": coverage.get("unknown_rows"),
                           "rows": list(coverage.get("unknown") or [])[:10]})
    # source_coverage is a dict of NAMED sources ({observed, source, reason, rows}), not a pair of
    # counts: each source that was not observed is a named exclusion, never a silent gap.
    src_cov = payload.get("source_coverage") or _deep_get(payload, "measures", "source_coverage") or {}
    if isinstance(src_cov, Mapping):
        for name, src in src_cov.items():
            if isinstance(src, Mapping) and src.get("observed") is False:
                exclusions.append({"reason": f"{name}: {src.get('reason') or 'not observed'}",
                                   "count": src.get("rows"), "source": name})

    price_cents = _cents(price_move.get("value"))
    change_cents = _cents(change_1d.get("value"))
    materialized_at = payload.get("measures_materialized_at") or _deep_get(payload, "measures", "materialized_at")

    value = {
        "account_value": {
            "measure": account_value.get("measure"),
            "cents": _cents(account_value.get("value")),
            "status": account_value.get("status"),
            "as_of": account_value.get("as_of"),
        },
        "price_move": {
            "measure": price_move.get("measure"),
            "cents": price_cents,
            "status": price_move.get("status"),
        },
        "account_change_1d": {
            "measure": change_1d.get("measure") or "account_value_change_1d",
            "cents": change_cents,
            "status": change_1d.get("status") or payload.get("account_value_change_1d_status"),
        },
        "verified_pnl": _pnl_block(payload, price_move_cents=price_cents, account_change_cents=change_cents),
        # the stored bridge is evidence: lifted verbatim, never recomputed in a read
        "reconciliation": payload.get("reconciliation") or _deep_get(payload, "measures", "reconciliation"),
        "source_coverage": src_cov or None,
        "measures_materialized_at": materialized_at,
    }

    # The verdict describes THIS envelope's value. It was taken from the today-change status when the
    # account-value measure carried none — one measure's clock justifying another measure's OK, which is
    # how an envelope with a null account value could render OK. No account-value status ⇒ UNKNOWN (b3).
    status = account_value.get("status")
    return bc.build_evidence(
        "portfolio_summary",
        verdict=_verdict_for(status),
        versions=versions,
        scope=scope,
        source_as_of=source_as_of,
        built_at=built_at or materialized_at,
        checked_at=checked_at,
        served_at=served_at,
        stale_after_hours=stale_after_hours,
        session_id=(scope or {}).get("session_id"),
        completeness={"counted": counted, "total": total, "exclusions": exclusions},
        value=value,
        cause=None if status is not None else bc._cause(
            "MEASURE_MISSING",
            detail="the measures block carries no account_value measure; the envelope's value has no status",
            owner="portfolio measures writer",
            next_action="run the measures writer, then re-read",
        ),
        now=now,
    )


def positions_evidence(
    payload: dict[str, Any],
    *,
    versions: dict[str, Any],
    scope: dict[str, Any] | None,
    stale_after_hours: float | None,
    now: datetime | None = None,
    served_at: Any = None,
) -> dict[str, Any]:
    """Wrap a positions payload: counts and cash/value anchors as published, never reclassified."""
    truth = payload.get("truth") or {}
    source_as_of = truth.get("as_of") or payload.get("positions_as_of")
    account_value = _measure_block(payload, "account_value")
    rows = payload.get("holdings")
    counts = payload.get("position_counts") if isinstance(payload.get("position_counts"), Mapping) else None
    # The count contract itself carries the headline; a payload that only publishes the contract is
    # still readable, so the headline is lifted from where it is published (never re-derived).
    count = payload.get("position_count")
    if count is None and counts:
        count = counts.get("position_count")
    value = {
        "position_count": count,
        "position_counts": counts,
        "total_value_cents": _cents(payload.get("total_value")),
        "total_cash_cents": _cents(payload.get("total_cash")),
        "account_value_status": account_value.get("status"),
    }
    # The counts ARE this envelope's value: an OK over no counts, or over a `holdings` member that is
    # not a list of rows, is the "unknown rendered as known" failure. Both are named (b3).
    verdict, cause = _verdict_for(account_value.get("status")), None
    if rows is not None and not isinstance(rows, list):
        verdict = "UNKNOWN"
        cause = bc._cause("POSITIONS_UNREADABLE",
                          detail=f"the payload's holdings member is {type(rows).__name__}, not a list of rows",
                          owner="positions store reader", next_action="re-read the positions store")
    elif count is None and counts is None:
        verdict = "UNKNOWN"
        cause = bc._cause("NO_VALUE",
                          detail="the payload publishes neither position_count nor position_counts",
                          owner="positions store reader", next_action="re-read the positions store")
    # The count contract's own scopes (scripts/lib/position_count_authority.py): the headline counts
    # rows at or above the floor, `held_count` counts every held position, `below_100` is the named
    # difference. Lifted, never summed or reclassified here — ``unpriced`` always counts, so it is not
    # an exclusion (operator ruling on the verdict floor).
    held = counts.get("held_count") if counts else None
    below = counts.get("below_100") if counts else None
    floor = counts.get("min_position_usd") if counts else None
    exclusions: list[dict[str, Any]] = []
    if below:
        exclusions.append({"reason": (f"held under ${float(floor):,.0f}: listed, not counted"
                                      if isinstance(floor, (int, float))
                                      else "held under the count floor: listed, not counted"),
                           "count": below})
    return bc.build_evidence(
        "positions_store",
        verdict=verdict,
        versions=versions,
        scope=scope,
        source_as_of=source_as_of,
        served_at=served_at,
        stale_after_hours=stale_after_hours,
        session_id=(scope or {}).get("session_id"),
        completeness={
            "counted": count,
            "total": held,
            "exclusions": exclusions,
        },
        value=value,
        cause=cause,
        now=now,
    )
