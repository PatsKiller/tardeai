"""Analyst vote distribution from ``analyst_data_history.payload`` (2026-10-18).

The only provider that filled this payload (Finnhub recommendation) died
2026-07-28 and was retired 2026-09-13 (87906632a); every row since holds ``{}``.
An empty payload or all-zero votes is NOT "0 analysts say buy" -- it is
"unavailable". Readers use :func:`vote_distribution` and render the status
instead of an empty or zero distribution. No other source is fetched here
(CC data-broker single-source rule): no recommendation-trend source exists in
the data broker today.
"""
from __future__ import annotations

import json
from typing import Any

VOTE_KEYS = ("strong_buy", "buy", "hold", "sell", "strong_sell")
STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"
REASON_PROVIDER_RETIRED = "analyst_vote_provider_retired_20260913"
REASON_NO_VOTES = "no_votes_in_payload"
REASON_NO_ROW = "no_analyst_data_row"


def vote_distribution(payload: Any) -> dict:
    """Return {"distribution": dict|None, "status": str, "reason": str|None, "provider": str|None}."""
    if payload is None:
        return {"distribution": None, "status": STATUS_UNAVAILABLE, "reason": REASON_NO_ROW, "provider": None}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    if not isinstance(payload, dict) or not payload:
        return {"distribution": None, "status": STATUS_UNAVAILABLE,
                "reason": REASON_PROVIDER_RETIRED, "provider": None}
    votes: dict[str, int] = {}
    for k in VOTE_KEYS:
        v = payload.get(k)
        if v is None:
            continue
        try:
            votes[k] = int(v)
        except (TypeError, ValueError):
            continue
    if not votes or sum(max(v, 0) for v in votes.values()) <= 0:
        return {"distribution": None, "status": STATUS_UNAVAILABLE,
                "reason": REASON_NO_VOTES, "provider": payload.get("provider")}
    return {"distribution": {k: votes.get(k, 0) for k in VOTE_KEYS}, "status": STATUS_AVAILABLE,
            "reason": None, "provider": payload.get("provider")}
