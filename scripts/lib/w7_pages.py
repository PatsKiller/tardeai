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

from scripts.lib.w7_lookthrough import project


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
    return project_pages(truth, **(lookthrough_inputs if lookthrough_inputs is not None else load_lookthrough_inputs(root)))


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
    result["do_now"] = {**result["do_now"], "items": (result["do_now"].get("items") or [])[:7]}
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
    result["lookthrough"] = project(portfolio=basis, holdings=holdings, companies=companies, **defaults)
    result["lookthrough"]["accounts"] = [{"id": a["account"], "label": a["label"]} for a in accounts]
    result["lookthrough"]["by_account"] = {
        a["account"]: project(portfolio=basis, holdings=holdings, companies=companies, account=a["account"], **defaults)
        for a in accounts if a.get("account")}
    return result
