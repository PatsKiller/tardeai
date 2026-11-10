"""One authority for every position count on /api/v2/overview (LQ-20261107-1820, Reality Drift #10).

Before: the response carried 5 counts from 4 code paths. ``position_count`` / ``position_counts`` came from the
live re-marked rows (cio_truth, floor ``>=``), ``observation.position_counts`` from the legacy holdings.json
(floor ``>``), and ``portfolio_total.position_counts`` from the re-marked rows while the dollars beside it had
been switched to the positions-store basis. One holding the store marks under the floor but the live re-mark
puts over it made the headline 13 while the store (system of record) said 12.

Now every count is computed once, by ``portfolio_total_contract.position_scopes``, over the SAME rows the
totals use: the positions-store basis (``broker_market_value``) when the store totals are published, else the
live re-mark, and the response says which (``source``). The floor is config. The live re-mark's own count is
published beside it, named, and a difference is stated as a finding, never headlined.
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping

try:
    from scripts.lib.canonical_observation import position_count_contract
    from scripts.lib.portfolio_total_contract import (
        MIN_POSITION_USD, OVER_100_SCOPE, POSITION_SCOPE, SCOPE_DEFINITIONS, position_scopes, position_summary,
    )
    from scripts.lib.portfolio_value_basis import STORE_BASIS, row_store_value
except ImportError:  # pragma: no cover - the served API puts scripts/ on sys.path
    from lib.canonical_observation import position_count_contract  # type: ignore[no-redef]
    from lib.portfolio_total_contract import (  # type: ignore[no-redef]
        MIN_POSITION_USD, OVER_100_SCOPE, POSITION_SCOPE, SCOPE_DEFINITIONS, position_scopes, position_summary,
    )
    from lib.portfolio_value_basis import STORE_BASIS, row_store_value  # type: ignore[no-redef]

CONTRACT_VERSION = "PositionCountAuthority@v1"


def _rows_on_basis(portfolio: Mapping[str, Any], store_basis: bool) -> list[dict[str, Any]]:
    out = []
    for row in portfolio.get("holdings") or []:
        r = dict(row)
        r["account"] = r.get("account_id") or r.get("account")
        if store_basis and not r.get("is_cash"):
            v = row_store_value(r)
            if v is not None:
                r["market_value"] = v
        out.append(r)
    return out


def _keys_over_floor(rows: list[dict[str, Any]], floor: float) -> set[tuple[str, str]]:
    value: dict[tuple[str, str], float] = {}
    for r in rows:
        if r.get("is_cash") or str(r.get("symbol") or "").upper() in ("CASH", "SPAXX", "FDRXX"):
            continue
        k = (str(r.get("account") or ""), str(r.get("symbol") or "").upper())
        try:
            value[k] = value.get(k, 0.0) + float(r.get("market_value") or 0)
        except (TypeError, ValueError):
            pass
    return {k for k, v in value.items() if v > floor}


def publish_position_counts(out: MutableMapping[str, Any], portfolio: Mapping[str, Any],
                            *, min_position_usd: float | None = None) -> MutableMapping[str, Any]:
    floor = MIN_POSITION_USD if min_position_usd is None else float(min_position_usd)
    basis = (out.get("totals_basis") or {}).get("basis")
    store_basis = basis == STORE_BASIS
    rows = _rows_on_basis(portfolio, store_basis)
    scopes = position_scopes(rows, min_position_usd=floor)
    source = "positions_current" if store_basis else "live_mark_rows"
    as_of = ((out.get("portfolio_total") or {}).get("as_of") or portfolio.get("valuation_as_of")
             or portfolio.get("positions_as_of"))

    findings: list[dict[str, Any]] = []
    live_scopes = None
    if store_basis:
        live_rows = _rows_on_basis(portfolio, False)
        live_scopes = position_scopes(live_rows, min_position_usd=floor)
        if live_scopes[OVER_100_SCOPE] != scopes[OVER_100_SCOPE] or live_scopes[POSITION_SCOPE] != scopes[POSITION_SCOPE]:
            moved = sorted(f"{a}:{s}" for a, s in
                           _keys_over_floor(live_rows, floor) ^ _keys_over_floor(rows, floor))
            findings.append({
                "code": "LIVE_MARK_COUNT_DIFFERS",
                "detail": (f"the live re-mark counts {live_scopes[OVER_100_SCOPE]} instruments over ${floor:,.0f} where "
                           f"the positions store counts {scopes[OVER_100_SCOPE]}; the store count is published, the "
                           "re-mark count is listed under live_mark_scopes"),
                "instruments_crossing_floor": moved,
            })

    contract = position_count_contract(scopes)
    contract["definitions"] = {s: SCOPE_DEFINITIONS.get(s, f"scope {s}") for s in scopes}
    contract.update(
        contract_version=CONTRACT_VERSION, primary_scope=POSITION_SCOPE,
        primary_definition=SCOPE_DEFINITIONS[POSITION_SCOPE], source=source, as_of=as_of,
        min_position_usd=floor, min_position_usd_source="config/position_count_authority.json",
        live_mark_scopes=live_scopes, findings=findings, summary=position_summary(scopes),
        # legacy aliases, same numbers, so older readers keep their keys
        definition=SCOPE_DEFINITIONS[POSITION_SCOPE], all_rows=scopes["holdings.all_rows"],
        cash_rows=scopes["holdings.cash"], non_cash_rows=scopes["holdings.non_cash"],
        held_rows=scopes[POSITION_SCOPE], below_100=scopes["holdings.held_under_100"],
        counted=scopes[OVER_100_SCOPE],
    )
    headline = scopes[POSITION_SCOPE]
    out["position_count"] = headline
    out["position_counts"] = contract

    pt = out.get("portfolio_total")
    if isinstance(pt, dict):
        pt.update(position_count=headline, position_scope=POSITION_SCOPE,
                  position_scope_definition=contract["primary_definition"], position_counts=contract,
                  position_summary=contract["summary"])

    obs = ((out.get("observation") or {}).get("position_counts")
           if isinstance(out.get("observation"), dict) else None)
    if isinstance(out.get("observation"), dict):
        risk = ((obs or {}).get("scopes") or {}).get("risk.risk_included")
        obs_scopes = {POSITION_SCOPE: headline, OVER_100_SCOPE: scopes[OVER_100_SCOPE]}
        if risk is not None:
            obs_scopes["risk.risk_included"] = risk  # a different population, named, not a competing headline
        o = position_count_contract(obs_scopes)
        o["scope_definitions"] = {s: SCOPE_DEFINITIONS.get(s, "risk_management.json positions where not "
                                  "risk_excluded (same rule as GET /api/v2/risk)") for s in obs_scopes}
        o.update(primary_scope=POSITION_SCOPE, source=source, as_of=as_of)
        out["observation"]["position_counts"] = o

    surfaces = {"position_count": out.get("position_count"),
                "position_counts.scopes": contract["scopes"][POSITION_SCOPE],
                "portfolio_total.position_count": (pt or {}).get("position_count"),
                "observation.position_counts.scopes": ((out.get("observation") or {}).get("position_counts") or {})
                .get("scopes", {}).get(POSITION_SCOPE)}
    present = {k: v for k, v in surfaces.items() if v is not None}
    contract["reconciliation"] = {"headline_scope": POSITION_SCOPE, "headline_value": headline,
                                  "surfaces": present, "agree": len(set(present.values())) <= 1}
    return out
