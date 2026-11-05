"""W7 page projection. Shared facts come only from lib.cio_truth.resolve.

This adapter is a reader, not a writer or job. The optional resolver and inputs
make fixture and copied-tree verification hermetic. Missing W1 is an explicit
gap; it never activates a legacy reader or recomputes a portfolio total.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from scripts.lib.w7_lookthrough import number, project


def validate_payload(payload: dict) -> dict:
    """Validate the read projection's display contract, including nullable facts.

    This deliberately accepts unavailable sections with a gap, rather than
    demanding invented numbers to satisfy a success-only schema.
    """
    sections = ("portfolio", "positions", "stops", "regime", "approvals", "cio_status", "capital", "do_now", "lookthrough", "conflicts", "concentration_policy")
    if not isinstance(payload, dict) or any(not isinstance(payload.get(k), dict) for k in sections):
        raise ValueError("W7 page sections must be objects")
    def nullable_number(value):
        if value is not None and (isinstance(value, str) or number(value) is None):
            raise ValueError("W7 measurements must be finite numbers or null")
    for key in ("total_usd", "cash_usd", "day_pl_usd", "position_count"):
        nullable_number(payload["portfolio"].get(key))
    for row in payload["positions"].get("rows") or []:
        if not isinstance(row, dict) or not row.get("symbol") or not row.get("account_label"):
            raise ValueError("W7 positions require symbol and account display name")
        if row.get("stop_state") not in (None, "active", "pending_activation", "filled", "none", "unknown"):
            raise ValueError("W7 stop state is not recognized")
        for key in ("price", "shares", "stop_price", "distance_to_stop_pct", "loss_at_stop_usd"):
            nullable_number(row.get(key))
    views = [payload["lookthrough"], *(payload["lookthrough"].get("by_account") or {}).values()]
    for view in views:
        for key in ("portfolio_total_usd", "looked_through_usd", "fund_covered_usd", "fund_value_usd", "fund_coverage_pct"):
            nullable_number(view.get(key))
        for key in ("industries", "sectors", "top_underlying", "gaps", "funds_without_holdings"):
            if not isinstance(view.get(key), list):
                raise ValueError("W7 look-through collections must be lists")
        for row in view["top_underlying"]:
            if not row.get("symbol") or not isinstance(row.get("sources"), list):
                raise ValueError("W7 underlyings require symbol and source contributions")
            nullable_number(row.get("value_usd"))
    if not isinstance(payload["conflicts"].get("findings"), list):
        raise ValueError("W7 conflict findings must be an engine list")
    policy = payload["concentration_policy"]
    if not isinstance(policy.get("classes"), list):
        raise ValueError("W7 concentration classes must be a canonical list")
    for row in policy["classes"]:
        if not isinstance(row, dict):
            raise ValueError("W7 concentration class must be an object")
        nullable_number(row.get("limit_pct"))
        nullable_number(row.get("near_limit_pct"))
    for key in ("lookthrough_company_limit_pct", "lookthrough_sector_limit_pct", "near_limit_fraction"):
        nullable_number(policy.get(key))
    return payload


def _json(path: Path, *, max_bytes: int = 1_000_000) -> dict:
    try:
        if path.stat().st_size > max_bytes:
            return {}
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def unavailable(reason: str) -> dict:
    section = lambda: {"gap": reason, "source": "CIO", "as_of": None, "stale": True}
    return {name: section() for name in ("portfolio", "positions", "stops", "regime", "approvals",
                                        "cio_status", "capital", "do_now", "companies", "sectors")}


def page_payload(root: Path | str, *, now: datetime | None = None,
                 resolver: Callable | None = None, inputs: dict | None = None, db_query: Callable | None = None,
                 concentration_resolver: Callable | None = None, concentration_inputs: dict | None = None,
                 lookthrough_inputs: dict | None = None) -> dict:
    """GET-only adapter. All state reads are cached artifacts, never providers.

    root contains data/. Config comes from the code checkout when a copied state
    tree contains no config/. Production callers pass their resolved state root.
    """
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    if resolver is None:
        try:
            from scripts.lib.cio_truth import resolve
            resolver = resolve
        except ImportError:
            resolver = None
    if resolver is None:
        truth = unavailable("The CIO shared record is not available yet")
    else:
        try:
            truth = resolver(root=root, now=now, inputs=inputs, db_query=db_query)
        except Exception as exc:
            truth = unavailable("The CIO shared record could not be read (" + type(exc).__name__ + ")")
    if "concentration_policy" not in truth:
        if concentration_resolver is None:
            try:
                from scripts.lib.ips_policy import apply_concentration
                concentration_resolver = apply_concentration
            except ImportError:
                concentration_resolver = None
        if concentration_resolver is not None:
            try:
                composed = concentration_resolver(truth, **(concentration_inputs or {}))
                if not isinstance(composed, dict):
                    raise ValueError("Canonical concentration projection is not an object")
                truth = composed
            except Exception as exc:
                truth = {**truth, "concentration_policy": {"classes": [], "as_of": None,
                         "source": "CIO concentration policy", "gap": {"reason":
                         "Canonical concentration policy could not be read (" + type(exc).__name__ + ")"}}}
    payload = validate_payload(project_pages(truth, **(lookthrough_inputs if lookthrough_inputs is not None else load_lookthrough_inputs(root))))
    from scripts.lib.home_board14 import apply_home_board
    return apply_home_board(payload, root=root, now=now, db_query=db_query)


def load_lookthrough_inputs(root: Path) -> dict:
    state = root / "data/portfolios/state"
    config = root / "config"
    if not config.is_dir():
        config = Path(__file__).resolve().parents[2] / "config"
    # These are constants belonging to the existing writer, not a second theme catalog.
    from scripts.portfolio_lookthrough_themes import _KNOWN_ETFS, _STATIC_THEMES
    from scripts.holding_proxies import HOLDING_PROXY_MAP
    members = {k: set(v) for k, v in _STATIC_THEMES.items()}
    constituents = _json(state / "index_constituents.json")
    for key, name in (("NASDAQ100", "Nasdaq 100"), ("SP500", "S&P 500")):
        if isinstance(constituents.get(key), list):
            members[name] = set(constituents[key])
    proxies = {k: v[0] for k, v in HOLDING_PROXY_MAP.items()}
    mapping = _json(config / "snaptrade_401k_fund_map.json").get("codes") or {}
    for code, row in mapping.items():
        source = row.get("lookthrough_source")
        if source in proxies:
            proxies[code] = proxies[source]
    universe = _json(config / "etf_fund_universe.json")
    funds = set(_KNOWN_ETFS) | set(proxies)
    funds.update(x["symbol"] for x in universe.get("instruments", []) if x.get("symbol"))
    return {"fund_cache": _json(state / "fund_holdings_cache.json"), "fund_symbols": funds,
            "proxies": proxies, "theme_members": members, "theme_targets": universe.get("sleeve_targets") or {},
            "snapshot": _json(state / "lookthrough_themes.json")}


def project_pages(truth: dict, **lookthrough_inputs) -> dict:
    # Forward W1's values, including None, provenance, stop state and conflicts.
    result = {name: truth.get(name) or unavailable("CIO field unavailable")[name]
              for name in ("portfolio", "positions", "stops", "regime", "approvals", "cio_status", "capital", "do_now", "sectors")}
    from scripts.lib.home_board14 import cap_do_now
    result["do_now"] = cap_do_now(result["do_now"])
    # Engine findings are a registered read projection. Legacy record diagnostics
    # are never reclassified into a page warning here.
    result["conflicts"] = truth.get("conflicts") or {
        "findings": [], "source": "conflict engine read projection", "as_of": None, "stale": True,
        "gap": {"reason": "Conflict engine accepted source not yet integrated"}}
    # W1 owns class detection and the one IPS rulebook. This display section
    # intentionally supplies no numeric defaults while its source is pending.
    result["concentration_policy"] = truth.get("concentration_policy") or {
        "classes": [], "source": "CIO concentration policy", "as_of": None,
        "gap": {"reason": "Class-specific concentration policy has not been published"}}
    portfolio = result["portfolio"]
    companies = [{"security_guid": guid, **c} for guid, c in ((truth.get("companies") or {}).get("by_guid") or {}).items()]
    # Account IDs and labels are W1's normalized aliases; only the derived view uses a local alias key.
    accounts = [{**a, "account": a.get("account_id"), "label": a.get("account_label"),
                 "state": a.get("status")} for a in portfolio.get("accounts") or []]
    basis = {**portfolio, "accounts": accounts}
    defaults = {"fund_cache": {}, "fund_symbols": set(), "proxies": {}, "theme_members": {},
                "theme_targets": {}, "snapshot": {}}
    defaults.update(lookthrough_inputs)
    holdings = [{**h, "account": h.get("account_id", h.get("account"))} for h in portfolio.get("holdings") or []]
    # Reuse the existing instrument-family classification, including mutual funds
    # and collective fund codes; never call the fund-weights provider from a GET.
    from scripts.holding_family import is_unstoppable_fund
    defaults["fund_symbols"] = set(defaults["fund_symbols"]) | {
        h.get("symbol") for h in holdings if is_unstoppable_fund(h.get("symbol"))}
    result["lookthrough"] = project(portfolio=basis, holdings=holdings, companies=companies, **defaults)
    result["lookthrough"]["accounts"] = [{"id": a["account"], "label": a["label"]} for a in accounts]
    result["lookthrough"]["by_account"] = {
        a["account"]: project(portfolio=basis, holdings=holdings, companies=companies, account=a["account"], **defaults)
        for a in accounts if a.get("account")}
    # The browser needs scalar facts and display rows, not duplicate full broker
    # observations, transfer histories, or the holdings export used above.
    result["portfolio"] = {k: v for k, v in result["portfolio"].items() if k not in ("holdings", "stored_totals")}
    display_keys = {"symbol", "account_id", "account_label", "shares", "quantity", "price", "current_price", "market_value",
                    "stop_price", "stop_source", "stop_state", "stop_captured_at", "stop_evidence", "broker_protected",
                    "distance_to_stop_pct", "loss_at_stop_usd", "risk_usd",
                    # #2141 stop categories: Risk/Defense need these to show resting stops and hide dust rows.
                    "counted", "stop_category", "resting_stop_distance_pct", "loss_at_resting_stop_usd",
                    "planned_stop_distance_pct"}
    result["positions"] = {**result["positions"], "rows": [
        {k: v for k, v in row.items() if k in display_keys} for row in result["positions"].get("rows") or []]}
    return result
