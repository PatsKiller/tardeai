"""Metric identity and scope coverage (HQ-07 / PR-002), additive to ``BrokerEvidence@v1``.

Two gaps this closes, without recomputing a single financial number:

* **HQ-07 — one metric ID per figure.** Header, Portfolio, Risk and a CSV export each showed "today" or
  "value" under their own label, so two screens could disagree about which number they were showing even
  when they were showing the same one. ``metrics()`` publishes one row per measure the payload already
  carries: ``metric_id`` (``portfolio.account_value`` …), the scope and ``snapshot_id`` it belongs to, its
  basis, its market-day period, the value in cents, and — for the two P&L metrics — the stored
  reconciliation as a ``bridge``. A page cites ``metric_id`` + ``snapshot_id`` instead of a label.
* **PR-002 — a row census that adds up.** The 33/30/25/11 populations were counts on a page with no
  statement of what they counted. ``scope_coverage()`` lifts the count contract's named scopes
  (``all_rows`` / ``cash`` / ``non_cash`` / ``held`` / over-floor / under-floor / unpriced), the excluded
  populations with their reasons, the price-move row coverage, and the number of rows actually rendered,
  from the same payload the rows come from.

Nothing here reads: no DB, no file, no provider, no clock. Every value is the payload's, lifted verbatim;
a fact the payload does not publish is ``None`` with a named reason, never a zero and never an invention.
The P&L stays **UNVERIFIED** unless the stored record itself carries a value, a source and an ``as_of``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.broker_contract_adapters import _cents

#: The measures the writer publishes, in a fixed order so a page's row order is stable.
MEASURE_IDS: tuple[str, ...] = (
    "account_value",
    "price_move_estimate",
    "account_value_change_1d",
    "verified_daily_pnl",
)

#: The metrics that are P&L statements and therefore carry the reconciliation bridge.
_PNL_METRICS = ("account_value_change_1d", "verified_daily_pnl")


def _scope_value(payload: Mapping[str, Any], scope: Mapping[str, Any] | None) -> dict[str, Any]:
    """The caller's scope, or the route module's ``scope_of`` — imported late: the route imports this.

    ``broker_route_evidence`` imports :func:`metrics` and :func:`scope_coverage` (it attaches both to the
    payload); this module needs the route's one ``scope_of``. A module-level import here would be circular,
    so the dependency is resolved at call time and only when the caller did not supply a scope.
    """
    if scope is not None:
        return dict(scope)
    from lib.broker_route_evidence import scope_of  # local import: see docstring
    return scope_of(dict(payload))


def _deep(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _measures(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    inner = _deep(payload, "measures", "measures")
    return inner if isinstance(inner, Mapping) else {}


def _bridge(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """The stored reconciliation, lifted as the bridge for a P&L metric. Never computed here."""
    recon = payload.get("reconciliation")
    if not isinstance(recon, Mapping):
        recon = _deep(payload, "measures", "reconciliation")
    if not isinstance(recon, Mapping) or not recon:
        return None
    total = recon.get("total") if isinstance(recon.get("total"), Mapping) else {}
    residual = total.get("residual") if isinstance(total.get("residual"), Mapping) else {}
    return {
        "reconciliation_status": total.get("status"),
        "residual_cents": _cents(residual.get("value_usd")),
        "known_components_residual_cents": _cents(residual.get("known_components_residual_usd")),
        "tolerance_cents": _cents(residual.get("tolerance_usd")),
        "provisional": bool(residual.get("provisional")),
        "unknown_components": list(residual.get("unknown_components") or []),
        "within_tolerance": residual.get("within_tolerance"),
        "accounts_reconciled": total.get("accounts_reconciled"),
        "accounts_total": total.get("accounts_total"),
        "policy": residual.get("policy"),
        "contract_version": recon.get("contract_version"),
    }


def metrics(payload: Mapping[str, Any], *, snapshot_id: str, scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """One typed row per published measure. A measure the payload does not carry is listed as UNKNOWN.

    Listing all four every time is deliberate: a page that filters on ``status == "OK"`` cannot silently
    drop a measure that went missing, because the row is still there with ``status`` UNKNOWN and
    ``cause.reason`` naming what was absent.
    """
    measures = _measures(payload)
    scope_value = _scope_value(payload, scope)
    basis = _deep(payload, "measures", "basis")
    basis_applied = basis.get("applied") if isinstance(basis, Mapping) else None
    session = _deep(payload, "measures", "session")
    market_day = payload.get("measures_materialized_at") or _deep(payload, "measures", "materialized_at")
    truth = payload.get("truth") if isinstance(payload.get("truth"), Mapping) else {}
    bridge = _bridge(payload)
    rows: list[dict[str, Any]] = []
    for name in MEASURE_IDS:
        meas = measures.get(name)
        meas = meas if isinstance(meas, Mapping) else None
        coverage = meas.get("coverage") if meas and isinstance(meas.get("coverage"), Mapping) else None
        complete = None
        if coverage and coverage.get("row_count") is not None:
            unknown = coverage.get("unknown_rows") or 0
            measured = coverage.get("measured_rows")
            complete = unknown == 0 and (measured is None or measured == coverage.get("row_count"))
        value = meas.get("value") if meas else None
        source = (meas.get("source") if meas else None) or truth.get("source")
        as_of = meas.get("as_of") if meas else None
        status = (meas.get("status") if meas else None) or "UNKNOWN"
        # The verified label survives only with a stored receipt: value + source + as_of. This is the same
        # rule the adapter applies to verified_daily_pnl, restated here because this row is what a CSV cites.
        verified = (str(status).upper() == "VERIFIED" and value is not None
                    and bool(meas.get("source")) and bool(meas.get("as_of")))
        row: dict[str, Any] = {
            "metric_id": f"portfolio.{name}",
            "measure": name,
            "label": (meas.get("label") if meas else None),
            "definition": (meas.get("definition") if meas else None),
            "scope": dict(scope_value),
            "snapshot_id": snapshot_id,
            "basis": (meas.get("basis") if meas else None) or basis_applied,
            "period": {"session_id": scope_value.get("session_id"), "session": session, "market_day": market_day},
            "value_cents": _cents(value),
            "status": "UNKNOWN" if meas is None else status,
            "complete": complete,
            "as_of": as_of,
            "source": source,
            "verified": bool(verified),
            "receipt": ({"source": meas.get("source"), "as_of": meas.get("as_of")} if verified else None),
            "residual_cents": None,
            "bridge": None,
            "cause": (None if meas is not None else
                      {"reason": f"the payload publishes no {name} measure", "owner": "portfolio measures writer",
                       "next_action": "run the measures writer, then re-read"}),
        }
        if name in _PNL_METRICS and bridge is not None:
            row["bridge"] = bridge
            row["residual_cents"] = bridge["residual_cents"]
        if isinstance(coverage, Mapping) and coverage.get("unknown_rows"):
            row["coverage_gap"] = {"reason": f"{coverage['unknown_rows']} of {coverage.get('row_count')} rows "
                                             "have no measured mark", "rows": list(coverage.get("unknown") or [])}
        rows.append(row)
    return rows


def scope_coverage(payload: Mapping[str, Any], *, snapshot_id: str,
                   scope: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The row census behind the figures: what was read, what counted, what did not, and why.

    Every number is the payload's own count contract (``position_counts``, built by
    ``lib/position_count_authority.py``); this function counts only the rows the payload actually hands a
    page. ``agree`` is deliberately **not** lifted: it compares counts across different populations, so it
    is false by construction whenever two scopes differ and must never be read as a defect.
    """
    scope_value = _scope_value(payload, scope)
    counts = payload.get("position_counts") if isinstance(payload.get("position_counts"), Mapping) else None
    scopes = counts.get("scopes") if counts and isinstance(counts.get("scopes"), Mapping) else {}
    floor = counts.get("min_position_usd") if counts else None
    rows = payload.get("holdings")
    excluded: list[dict[str, Any]] = []
    under = scopes.get("holdings.held_under_100")
    if under:
        excluded.append({"reason": (f"priced under ${float(floor):,.0f}: listed, not counted"
                                    if isinstance(floor, (int, float)) else "under the count floor: listed, not counted"),
                         "count": under, "scope": "holdings.held_under_100"})
    unpriced = scopes.get("holdings.unpriced")
    if unpriced:
        excluded.append({"reason": "no market value above $0 (e.g. a lot with no quote): listed separately, never a zero",
                         "count": unpriced, "scope": "holdings.unpriced"})
    coverage = _deep(payload, "measures", "measures", "price_move_estimate", "coverage")
    src = payload.get("source_coverage")
    out = {
        "snapshot_id": snapshot_id,
        "scope": dict(scope_value),
        "count_source": counts.get("source") if counts else None,
        "count_as_of": counts.get("as_of") if counts else None,
        "count_basis": counts.get("as_of_basis") if counts else None,
        "min_position_usd": floor,
        "scopes": dict(scopes),
        "counted": counts.get("counted") if counts else None,
        "held": counts.get("held_count") if counts else None,
        "excluded": excluded,
        "rows_read": scopes.get("holdings.all_rows"),
        "cash_rows": scopes.get("holdings.cash"),
        "non_cash_rows": scopes.get("holdings.non_cash"),
        "rendered_rows": (len(rows) if isinstance(rows, list) else None),
        "priceable": ({
            "measured_rows": coverage.get("measured_rows"),
            "unknown_rows": coverage.get("unknown_rows"),
            "row_count": coverage.get("row_count"),
            "unknown": list(coverage.get("unknown") or []),
        } if isinstance(coverage, Mapping) else None),
        "source_coverage": src if isinstance(src, Mapping) else None,
        "findings": list(counts.get("findings") or []) if counts else [],
        # a census the payload does not publish is None with its reason, never a zero
        "filtered_rows": None,
        "duplicate_rows": None,
        "unpublished": {
            "filtered_rows": "the payload publishes rows and counts, not a page-filter census",
            "duplicate_rows": "the count contract de-duplicates by (account, symbol) and publishes no duplicate count",
        },
    }
    return out
