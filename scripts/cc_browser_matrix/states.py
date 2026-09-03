#!/usr/bin/env python3
"""The forced states a Command Center route must survive.

Every state here is a shape the real API can produce. The point of the matrix is
that a route must render an honest surface in each one — not that it renders at
all. A page that shows the same confident number under LOADING, STALE and
PROVIDER_UNAVAILABLE is not reading its own data.

READ_ONLY: this module builds response bodies. It performs no I/O.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "BrowserStateMatrix@v1"

LOADING = "loading"
POPULATED = "populated"
EMPTY = "legitimate_empty"
STALE = "stale"
PARTIAL = "partial"
DISCONNECTED = "disconnected"
TIMEOUT = "timeout"
RETAINED_304 = "retained_304"
MALFORMED = "malformed"
PROVIDER_UNAVAILABLE = "provider_unavailable"
UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
MARKET_CLOSED = "market_closed"
PREMARKET = "premarket"
AFTER_HOURS = "after_hours"
UNDATED = "undated"
MIXED_SCOPE = "mixed_account_scope"

#: The full matrix, in the order the brief lists them.
STATES: tuple[str, ...] = (
    LOADING,
    POPULATED,
    EMPTY,
    STALE,
    PARTIAL,
    DISCONNECTED,
    TIMEOUT,
    RETAINED_304,
    MALFORMED,
    PROVIDER_UNAVAILABLE,
    UNAUTHORIZED,
    FORBIDDEN,
    MARKET_CLOSED,
    PREMARKET,
    AFTER_HOURS,
    UNDATED,
    MIXED_SCOPE,
)

#: States expressed by transport rather than body.
TRANSPORT_STATES = frozenset({LOADING, DISCONNECTED, TIMEOUT, RETAINED_304, UNAUTHORIZED, FORBIDDEN})

#: What each state must be visible as. A surface that cannot show the distinction
#: is the defect; the matrix records the requirement next to the observation.
REQUIREMENT: dict[str, str] = {
    LOADING: "a pending read is visibly pending, never a zero and never a stale number presented as fresh",
    POPULATED: "real values with their own provenance",
    EMPTY: "an explicit 'no rows' that is distinguishable from a failed read",
    STALE: "an explicit STALE marker carrying the data clock, not the receipt clock",
    PARTIAL: "the missing part is named; the present part is not presented as complete",
    DISCONNECTED: "last-good is labelled as last-good; the surface never collapses to zeros",
    TIMEOUT: "an explicit timeout, distinguishable from an empty result",
    RETAINED_304: "transport RETAINED stays visible and the data clock does not advance",
    MALFORMED: "an explicit parse failure, never a silently empty render",
    PROVIDER_UNAVAILABLE: "the provider is named as unavailable; no fallback number is shown as primary",
    UNAUTHORIZED: "an explicit 401 state; no cached privileged data is shown",
    FORBIDDEN: "an explicit 403 state; controls disarm rather than appear armed",
    MARKET_CLOSED: "session state is named; a closed-session quote is not shown as live",
    PREMARKET: "session state is named as premarket",
    AFTER_HOURS: "session state is named as after-hours",
    UNDATED: "an observation with no date says so; it never borrows another clock",
    MIXED_SCOPE: "aggregate and per-account scopes are named separately and never conflated",
}

_BASE_OBS = {
    "data_as_of": "2026-09-03",
    "last_repriced": "2026-09-03T13:45:00-04:00",
    "pipeline_completed": "2026-09-03T13:46:00-04:00",
    "read_only": True,
}


def http_status(state: str) -> int:
    return {UNAUTHORIZED: 401, FORBIDDEN: 403, TIMEOUT: 504, PROVIDER_UNAVAILABLE: 503}.get(state, 200)


def session_label(state: str) -> str | None:
    return {
        MARKET_CLOSED: "CLOSED",
        PREMARKET: "PREMARKET",
        AFTER_HOURS: "AFTER_HOURS",
    }.get(state)


def shape(state: str, base: Any) -> Any:
    """Return the body the hermetic server should serve for ``state``.

    ``base`` is the POPULATED body. Every other state is derived from it so the
    matrix cannot accidentally compare two different datasets.
    """
    if state == POPULATED:
        return base
    if state == EMPTY:
        return _empty(base)
    if state == MALFORMED:
        return "{ this is not json"
    if state == PARTIAL:
        return _partial(base)
    if state == STALE:
        return _restamp(base, {"data_as_of": "2026-08-20", "last_repriced": "2026-08-20T16:00:00-04:00"})
    if state == UNDATED:
        return _restamp(base, {"data_as_of": None, "last_repriced": None, "pipeline_completed": None})
    if state in (MARKET_CLOSED, PREMARKET, AFTER_HOURS):
        return _restamp(base, {"session_state": session_label(state)})
    if state == MIXED_SCOPE:
        return _mixed_scope(base)
    if state == PROVIDER_UNAVAILABLE:
        return {
            "ok": False,
            "error": "provider_unavailable",
            "provider": "finviz",
            "detail": "the primary quote provider did not answer",
            "data": None,
        }
    if state == UNAUTHORIZED:
        return {"ok": False, "error": "unauthorized", "detail": "no valid operator credential"}
    if state == FORBIDDEN:
        return {"ok": False, "error": "forbidden", "detail": "operator is not permitted this surface"}
    if state == TIMEOUT:
        return {"ok": False, "error": "upstream_timeout", "detail": "the producer did not answer in time"}
    # LOADING / DISCONNECTED / RETAINED_304 are transport-shaped; the server
    # delays, drops or 304s instead of changing the body.
    return base


def _payload(base: Any) -> Any:
    if isinstance(base, dict) and isinstance(base.get("data"), (dict, list)):
        return base["data"]
    return base


def _rewrap(base: Any, payload: Any) -> Any:
    if isinstance(base, dict) and "data" in base:
        out = dict(base)
        out["data"] = payload
        return out
    return payload


def _empty(base: Any) -> Any:
    p = _payload(base)
    if isinstance(p, list):
        return _rewrap(base, [])
    if isinstance(p, dict):
        out = {
            k: ([] if isinstance(v, list) else (0 if isinstance(v, (int, float)) and not isinstance(v, bool) else v))
            for k, v in p.items()
        }
        out["empty_reason"] = "the producer ran and returned no rows"
        out["is_legitimately_empty"] = True
        return _rewrap(base, out)
    return _rewrap(base, {"empty_reason": "no rows", "is_legitimately_empty": True})


def _partial(base: Any) -> Any:
    p = _payload(base)
    if not isinstance(p, dict):
        return _rewrap(base, {"partial": True, "missing": ["payload"], "reason": "upstream returned a fragment"})
    keys = [k for k in p if not k.startswith("_")]
    drop = set(keys[len(keys) // 2 :])
    out = {k: v for k, v in p.items() if k not in drop}
    out["partial"] = True
    out["missing"] = sorted(drop)
    out["partial_reason"] = "one or more producers did not answer for this read"
    return _rewrap(base, out)


def _restamp(base: Any, stamps: dict[str, Any]) -> Any:
    p = _payload(base)
    if not isinstance(p, dict):
        return base
    out = dict(p)
    out.update(stamps)
    obs = out.get("observation")
    if isinstance(obs, dict):
        o = dict(obs)
        o.update({k: v for k, v in stamps.items() if k in _BASE_OBS or k == "session_state"})
        out["observation"] = o
    return _rewrap(base, out)


def _mixed_scope(base: Any) -> Any:
    p = _payload(base)
    if not isinstance(p, dict):
        return base
    out = dict(p)
    out["portfolio_aggregate"] = {
        "contract_version": "PortfolioAggregate@v1",
        "portfolio_scope": "ALL_ACCOUNTS",
        "included_account_count": 3,
        "oldest_observation_time": "2026-08-20T16:00:00-04:00",
        "oldest_observation_account": "alpaca_paper",
        "newest_observation_time": "2026-09-03T13:45:00-04:00",
        "freshness_state": "STALE",
        "freshness_reason": "oldest observation: alpaca_paper 2026-08-20 (349h)",
        "read_only": True,
    }
    out["position_counts"] = {
        "overview.non_cash_over_100": 14,
        "holdings.all_rows": 29,
        "holdings.non_cash": 25,
        "risk.risk_included": 15,
        "agree": False,
        "rule": "four named populations; none of them is 'the' position count",
    }
    return _rewrap(base, out)
