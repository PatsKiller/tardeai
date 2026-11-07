"""Data Broker HTTP surface (catalog + Watch Intelligence).

Index / catalog (advertise all projections):
  GET /api/v3/data-broker
  GET /api/v3/data-broker/catalog

Watch Intelligence (composes existing broker domains):
  GET /api/v3/data-broker/watch-intelligence
  GET /api/v3/data-broker/watch-intelligence/{symbol}
  GET /api/v3/data-broker/watch-filters
  GET /api/v3/data-broker/watch-lists
  GET /api/v3/data-broker/watch-curation   (My Watchlist + System Suggests, operator 2026-10-23)
  GET /api/v3/data-broker/watch-universe   (Full universe on Watch: curator rank + position facts + filters)
  GET /api/v3/data-broker/watch-reviews/{symbol}
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def get_catalog() -> dict[str, Any]:
    """Advertise the full Data Broker surface (existing + Watch Intelligence)."""
    from lib.data_broker.catalog import broker_catalog

    return broker_catalog()


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import list_watch_intelligence

    out = list_watch_intelligence(query or {})
    # Advertise composition so clients know this is the broker package, not a side API
    out.setdefault(
        "data_broker",
        {
            "package": "scripts/lib/data_broker",
            "projection": "watch_intelligence",
            "contract_version": out.get("data_contract_version") or out.get("contract_version"),
            "catalog": "/api/v3/data-broker",
            "composes": [
                "watch_canonical_quote",
                "symbol_profile",
                "analyst_rollup",
                "yahoo_analyst_targets",
                "catalyst_events",
                "decision_packets",
                "review_artifacts",
                "operator_starred_symbols",
                "holdings",
                "screener_find_pins",
            ],
            "provider_calls": 0,
            "read_only": True,
        },
    )
    return out


def get_detail(symbol: str) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import detail_watch_intelligence

    out = detail_watch_intelligence(symbol)
    out.setdefault(
        "data_broker",
        {
            "package": "scripts/lib/data_broker",
            "projection": "watch_intelligence",
            "contract_version": out.get("data_contract_version") or out.get("contract_version"),
            "catalog": "/api/v3/data-broker",
            "provider_calls": 0,
            "read_only": True,
        },
    )
    return out


def get_prospects(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-prospects — the Watch page's prospect lanes (interim adapter until the
    cio_prospect projection is live; lib/data_broker/watch_prospects.py)."""
    from lib.data_broker.watch_prospects import list_watch_prospects
    from lib.site_payload_reads import prospects_page

    # The adapter composes the canonical view before applying user filters.
    source_controls = {key: (query or {})[key] for key in ("fresh",) if key in (query or {})}
    out = prospects_page(list_watch_prospects(source_controls), query or {})
    if out.get("status") == "unavailable" and out.get("payload_gap"):
        raise ValueError("Prospect payload unavailable: " + out["payload_gap"]["reason"])
    return out


#: Key path for the stale-while-revalidate cache (scripts/lib/stale_serve.py, the LQ-20261107-201 pattern).
CURATION_SWR_PATH = "/api/v3/data-broker/watch-curation"


def _read_curation(query: dict) -> dict[str, Any]:
    from lib.site_payload_reads import read_curation

    out = read_curation(query)
    if out.get("status") == "unavailable" and out.get("payload_gap"):
        raise ValueError("Curation payload unavailable: " + out["payload_gap"]["reason"])
    return out


def get_curation(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-curation — My Watchlist (every operator name, starred first, never capped) and
    System Suggests (top N of the Full universe ranking, rotating with reasons); lib/data_broker/watch_curation.py.

    Served stale-while-revalidate like the desk reads (LQ-20261107-201, scripts/lib/stale_serve.py): the composition
    behind this body takes 8-11 s warm (and 24 s under the page sweep's load), past the browser's 30 s abort on
    /v3/watch — measured 2026-11-07T19:43Z, "watch-curation aborted at 30 s", 'Loading your watchlist…' at 25 s.
    A last good body is served at once, stamped `_swr` {as_of, age_s, stale, refreshing, source}, and ONE background
    refresh recomputes it. Nothing is cached for a read that fails: an unavailable payload still raises, so the
    caller's 500 and the gap reason reach the page as before. The key is (identity, path, query), so one identity
    never receives another's watchlist.
    """
    query = query or {}
    flag = query.get("review_status")
    if flag in ("1", 1, ["1"]):
        from lib.data_broker.watch_review_status import review_status

        return review_status(query)
    swr_mod, identity, set_principal = _swr_context()
    if swr_mod is None:
        return _read_curation(query)
    # An identity-less request (the local listener, the host's page walk) gets its own bucket, not nobody's:
    # it receives the body it would have computed for itself, never an authenticated identity's body.
    key_principal = identity or "anonymous"

    def compute() -> tuple[int, dict[str, Any]]:
        return 200, _read_curation(query)

    def refresh() -> tuple[int, dict[str, Any]]:
        if set_principal is not None:
            set_principal(identity)  # the principal is thread-local; the refresh runs on its own thread
        return compute()

    status, body = swr_mod.default().get(swr_mod.request_key(CURATION_SWR_PATH, query, key_principal),
                                         compute, refresh)
    if status != 200:  # compute() only returns 200; anything else is a defect worth surfacing, not a body
        raise ValueError(f"curation served status {status}")
    return body


def _swr_context():
    """(stale_serve module, principal, set_request_principal) — or a falsy module when SWR must not apply."""
    try:
        from lib import stale_serve as swr_mod
        from lib.cc_auth import current_principal, set_request_principal
    except ImportError:
        try:
            from scripts.lib import stale_serve as swr_mod
            from scripts.lib.cc_auth import current_principal, set_request_principal
        except ImportError:
            return None, "", None
    try:
        if not swr_mod.enabled():
            return None, "", None
        return swr_mod, current_principal() or "", set_request_principal
    except Exception:  # noqa: BLE001 -- an unknown identity means "never share a body", not an error page
        return None, "", None


def get_symbol_search(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-symbol-search?q= — ticker / company typeahead for the Add-symbol box."""
    from lib.data_broker.watch_curation import list_symbol_search

    return list_symbol_search(query or {})


def get_universe(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-universe — the curator's ranked list with held / formerly held / never held,
    the last round trip and re-entry advice per row, and the position filters (lib/data_broker/watch_universe.py)."""
    from lib.data_broker.watch_universe import list_watch_universe

    return list_watch_universe(query or {})


def get_filters() -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_filters

    out = watch_filters()
    out.setdefault("data_broker", {"projection": "watch_filters", "catalog": "/api/v3/data-broker"})
    return out


def get_lists() -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_lists

    out = watch_lists()
    out.setdefault("data_broker", {"projection": "watch_lists", "catalog": "/api/v3/data-broker"})
    return out


def get_reviews(symbol: str) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_reviews

    out = watch_reviews(symbol)
    out.setdefault("data_broker", {"projection": "watch_reviews", "catalog": "/api/v3/data-broker"})
    return out
