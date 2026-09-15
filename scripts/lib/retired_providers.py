"""Providers that are RETIRED: no code path may call them.

The list is read from config/data_source_authority.json, the single declaration
of which provider supplies which domain. It is not duplicated here.

WHY
---
On 2026-09-13 the catalyst-news chain had six slots and the first four were
dead: Finnhub had returned HTTP 401 since 07-27, NewsAPI never ran, Polygon and
FMP had gone paid-only. Four scheduled callers tried them first on every run and
fell through. The quote waterfall listed polygon as a real-time provider it could
not reach. None of that was visible, because "retired" existed nowhere a program
could read it.

A chain that consults this module refuses a retired slot up front and says so in
its receipt, instead of failing and falling through in silence.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

AUTHORITY_PATH = Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"


@lru_cache(maxsize=1)
def _authority() -> dict:
    return json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))


def retired_providers() -> frozenset[str]:
    """Provider keys whose status is 'retired' in the authority registry."""
    return frozenset(k for k, v in _authority().get("providers", {}).items() if v.get("status") == "retired")


def is_retired(provider: str) -> bool:
    return str(provider or "").strip().lower() in retired_providers()


def retired_reason(provider: str) -> str:
    p = _authority().get("providers", {}).get(str(provider or "").strip().lower(), {})
    return str(p.get("_why") or "retired in config/data_source_authority.json")


def live_chain(chain: list[tuple[str, object]]) -> tuple[list[tuple[str, object]], list[str]]:
    """Split a (name, fn) chain into the slots that may run and the ones refused."""
    keep, refused = [], []
    for name, fn in chain:
        (refused if is_retired(name) else keep).append((name, fn) if not is_retired(name) else name)
    return keep, refused


def retired_on(provider: str) -> str | None:
    """ISO date the provider was retired, from its approval block, or None."""
    p = _authority().get("providers", {}).get(str(provider or "").strip().lower(), {})
    return (p.get("approval") or {}).get("retired_on")


def called_since_retirement(provider: str, *activity) -> bool:
    """True when any success/failure timestamp falls AFTER the retirement day.

    A retired provider's health row keeps its last failure forever (finnhub: HTTP 401,
    last written 2026-09-13 16:03, the minute of retirement), and the health agent read
    that as "operator must rotate FINNHUB_API_KEY". Activity after the retirement day
    is different: some caller is still reaching a provider nothing may call.
    """
    day = retired_on(provider)
    if not day:
        return True
    from datetime import date, datetime
    cutoff = date.fromisoformat(str(day)[:10])
    for ts in activity:
        if ts is None:
            continue
        d = ts.date() if isinstance(ts, datetime) else date.fromisoformat(str(ts)[:10])
        if d > cutoff:
            return True
    return False

