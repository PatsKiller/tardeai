"""One authority for every position count (LQ-20261107-1820, Reality Drift #10).

Overview, /holdings and /risk all read ``cio_truth.resolve()["portfolio"]``; that document, and the overview
response after the store totals are published, take their counts from ``counts_for_rows`` here. One definition:

  headline ``position_count`` = non-cash instruments (one per account+symbol, quantity above 0) whose
  market_value is AT OR ABOVE the configured floor, valued on the positions-store basis
  (``broker_market_value``) when every non-cash row has a store value, else on the live re-mark, and the
  response says which (``source``). All-held is the separate, labelled ``held_count``.

The floor is config/position_count_authority.json (``floor_source`` says config or config_unreadable).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, MutableMapping

try:
    from scripts.lib.canonical_observation import position_count_contract
    from scripts.lib.portfolio_total_contract import (
        OVER_100_SCOPE, POSITION_SCOPE, SCOPE_DEFINITIONS, current_floor, is_cash_row, position_scopes,
    )
    from scripts.lib.portfolio_value_basis import STORE_BASIS, row_store_value
except ImportError:  # pragma: no cover - the served API puts scripts/ on sys.path
    from lib.canonical_observation import position_count_contract  # type: ignore[no-redef]
    from lib.portfolio_total_contract import (  # type: ignore[no-redef]
        OVER_100_SCOPE, POSITION_SCOPE, SCOPE_DEFINITIONS, current_floor, is_cash_row, position_scopes,
    )
    from lib.portfolio_value_basis import STORE_BASIS, row_store_value  # type: ignore[no-redef]

CONTRACT_VERSION = "PositionCountAuthority@v1"
HEADLINE_SCOPE = OVER_100_SCOPE


def _prep(rows: Iterable[Mapping[str, Any]], store_basis: bool):
    """Rows on one basis. A non-cash row with no store value is excluded from a store-basis count (flagged)."""
    out, not_on_store = [], []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("is_loan"):
            continue
        r = dict(row)
        r["account"] = r.get("account_id") or r.get("account")
        if store_basis and not is_cash_row(r):
            v = row_store_value(r)
            if v is None:
                not_on_store.append(f"{r['account']}:{r.get('symbol')}")
                r["market_value"] = None
            else:
                r["market_value"] = v
        out.append(r)
    return out, not_on_store


def _over_keys(scoped_rows: list[dict[str, Any]], floor: float) -> set[tuple[str, str]]:
    value: dict[tuple[str, str], float] = {}
    qty: dict[tuple[str, str], bool] = {}
    for r in scoped_rows:
        if is_cash_row(r):
            continue
        k = (str(r.get("account") or ""), str(r.get("symbol") or "").upper())
        try:
            value[k] = value.get(k, 0.0) + float(r.get("market_value") or 0)
        except (TypeError, ValueError):
            pass
        q = next((r.get(f) for f in ("quantity", "shares") if r.get(f) is not None), None)
        try:
            qty[k] = qty.get(k, False) or q is None or float(q) > 0
        except (TypeError, ValueError):
            qty[k] = True
    return {k for k, v in value.items() if qty.get(k) and v >= floor}


def store_basis_available(rows: Iterable[Mapping[str, Any]]) -> bool:
    nc = [r for r in rows if isinstance(r, Mapping) and not is_cash_row(r) and not r.get("is_loan")]
    return bool(nc) and all(row_store_value({**r, "is_cash": False}) is not None for r in nc)


def counts_for_rows(rows: Iterable[Mapping[str, Any]], *, store_basis: bool | None = None, as_of: Any = None,
                    min_position_usd: float | None = None) -> dict[str, Any]:
    """The one count contract. ``position_count`` is the headline; ``held_count`` is all held, labelled."""
    rows = [r for r in rows if isinstance(r, Mapping)]
    if min_position_usd is None:
        floor, floor_source = current_floor()
    else:
        floor, floor_source = float(min_position_usd), "argument"
    if store_basis is None:
        store_basis = store_basis_available(rows)
    scoped, not_on_store = _prep(rows, store_basis)
    scopes = position_scopes(scoped, min_position_usd=floor)
    headline = scopes[HEADLINE_SCOPE]
    source = "positions_current" if store_basis else "live_mark_rows"
    findings: list[dict[str, Any]] = []
    if not_on_store:
        findings.append({"code": "ROW_NOT_ON_STORE_BASIS", "rows": sorted(not_on_store),
                         "detail": "non-cash rows with no store value are excluded from the store-basis count"})
    live_scopes = None
    if store_basis:
        live, _ = _prep(rows, False)
        live_scopes = position_scopes(live, min_position_usd=floor)
        if live_scopes[HEADLINE_SCOPE] != headline or live_scopes[POSITION_SCOPE] != scopes[POSITION_SCOPE]:
            moved = sorted(f"{a}:{s}" for a, s in _over_keys(live, floor) ^ _over_keys(scoped, floor))
            findings.append({
                "code": "LIVE_MARK_COUNT_DIFFERS",
                "detail": (f"the live re-mark counts {live_scopes[HEADLINE_SCOPE]} instruments at or above ${floor:,.0f} "
                           f"where the positions store counts {headline}; the store count is the headline"),
                "instruments_crossing_floor": moved})
    if floor_source.startswith("config_unreadable"):
        findings.append({"code": "FLOOR_CONFIG_UNREADABLE", "detail": floor_source})
    under, unp = scopes["holdings.held_under_100"], scopes["holdings.unpriced"]
    summary = f"{headline} position{'' if headline == 1 else 's'} at or above ${floor:,.0f}"
    if under:
        summary += f" · {under} held under ${floor:,.0f}"
    if unp:
        summary += f" · {unp} unpriced lot{'' if unp == 1 else 's'} excluded"
    contract = position_count_contract(scopes)
    contract["definitions"] = {s: SCOPE_DEFINITIONS.get(s, f"scope {s}") for s in scopes}
    contract.update(
        contract_version=CONTRACT_VERSION, primary_scope=HEADLINE_SCOPE,
        primary_definition=contract["definitions"][HEADLINE_SCOPE], position_count=headline,
        held_count=scopes[POSITION_SCOPE], held_count_definition=SCOPE_DEFINITIONS[POSITION_SCOPE],
        source=source, as_of=as_of or datetime.now(timezone.utc).isoformat(),
        as_of_basis="data" if as_of else "read_time", min_position_usd=floor, floor_source=floor_source,
        live_mark_scopes=live_scopes, findings=findings, summary=summary,
        # legacy aliases, same numbers
        definition=contract["definitions"][HEADLINE_SCOPE], all_rows=scopes["holdings.all_rows"],
        cash_rows=scopes["holdings.cash"], non_cash_rows=scopes["holdings.non_cash"],
        held_rows=scopes[POSITION_SCOPE], below_100=scopes["holdings.held_under_100"], counted=headline,
    )
    return contract


def publish_position_counts(out: MutableMapping[str, Any], portfolio: Mapping[str, Any],
                            *, min_position_usd: float | None = None) -> MutableMapping[str, Any]:
    pt = out.get("portfolio_total")
    as_of = ((pt or {}).get("as_of") if isinstance(pt, dict) else None) or portfolio.get("valuation_as_of") \
        or portfolio.get("positions_as_of") or out.get("as_of")
    store_basis = (out.get("totals_basis") or {}).get("basis") == STORE_BASIS
    c = counts_for_rows(portfolio.get("holdings") or [], store_basis=store_basis, as_of=as_of,
                        min_position_usd=min_position_usd)
    headline = c["position_count"]
    out["position_count"] = headline
    out["held_count"] = c["held_count"]
    out["position_counts"] = c
    if isinstance(pt, dict):
        pt.update(position_count=headline, held_count=c["held_count"], position_scope=HEADLINE_SCOPE,
                  position_scope_definition=c["primary_definition"], position_counts=c, position_summary=c["summary"])
    if isinstance(out.get("observation"), dict):
        obs = out["observation"].get("position_counts") or {}
        risk = (obs.get("scopes") or {}).get("risk.risk_included")
        scopes = {HEADLINE_SCOPE: headline, POSITION_SCOPE: c["held_count"]}
        if risk is not None:
            scopes["risk.risk_included"] = risk  # a different population, named, not a competing headline
        o = position_count_contract(scopes)
        o["scope_definitions"] = {s: SCOPE_DEFINITIONS.get(s, "risk_management.json positions where not "
                                  "risk_excluded (same rule as GET /api/v2/risk)") for s in scopes}
        o.update(primary_scope=HEADLINE_SCOPE, source=c["source"], as_of=c["as_of"])
        out["observation"]["position_counts"] = o
    surfaces = {"position_count": out["position_count"], "position_counts.position_count": c["position_count"],
                "portfolio_total.position_count": (pt or {}).get("position_count"),
                "observation.position_counts.scopes": ((out.get("observation") or {}).get("position_counts") or {})
                .get("scopes", {}).get(HEADLINE_SCOPE)}
    present = {k: v for k, v in surfaces.items() if v is not None}
    c["reconciliation"] = {"headline_scope": HEADLINE_SCOPE, "headline_value": headline, "surfaces": present,
                           "agree": len(set(present.values())) <= 1}
    return out
