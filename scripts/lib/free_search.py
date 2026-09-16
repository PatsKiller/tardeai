#!/usr/bin/env python3
"""free_search.py — governed free web search (SearXNG), under the same ledger discipline as paid search.

WHY
---
Measured 2026-09-16 against the live budget ledger: **129 denial receipts, every
one ``reason=CALLER_DAILY_CAP``, every one ``spilled_to: null``.**

``CALLER_DAILY_CAP`` is deliberately NOT in the registry's ``web_search.spill_on``
(operator decision 2026-09-13): a per-caller cap is fairness *between callers*,
not a provider quota, so a caller over its own slice is refused rather than
spilled. That decision is correct and this module does not re-litigate it.

But the refused questions were not too expensive to ask. They were never asked
anywhere:

  * Brave's month was **85% unspent** (228 of 1,500) at the time of measurement;
  * a self-hosted SearXNG with a **10,000/day** allowance sat idle — 207 spills
    reached it in September and **zero** questions were ever put to it first.

So ~44-70 questions a day died at a gate that was protecting a budget nobody was
exhausting, while free capacity went unused. This module is the "asked somewhere"
path for exactly those questions.

WHAT THIS IS NOT
----------------
It is **not** a spill adapter. ``brave_router``'s spill seam is injected and
asserted by ``tests/test_brave_router_spill.py``, which requires exactly one
transport call *plus a denial receipt*; a free hit produces no denial, and a
free hit that caches produces no receipt at all. A prototype that borrowed that
seam broke 9 of those tests, correctly. This is a separate, independently
budgeted provider call that a caller makes **after** the router has already
refused it — the router's contract is untouched.

GOVERNANCE — identical in kind to the paid path
-----------------------------------------------
  * **One ledger unit per HTTP request, taken BEFORE the request.** A check that
    is separate from the spend lets two processes both observe an under-limit
    counter and both call.
  * **A request that never happened is refunded.** The provider is free to us;
    the counter must still describe reality.
  * **news→general is a SECOND request and costs a SECOND unit.** The paid path
    has a known defect — one logical search issuing web+news bills the provider
    twice against a single reserved unit, so recorded usage is roughly half of
    actual. This module does not reproduce it.
  * **Fail closed.** An unreadable ledger denies; it never fails open.

Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops, or writes broker state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional
from pathlib import Path

SCHEMA = "FreeSearchResponse@v1"
PROVIDER = "searxng"

#: Callers opt in per lane. Off → this module makes no network call at all.
FALLBACK_FLAG = "RESEARCH_FREE_FALLBACK"

#: The only router refusal this module answers. A caller over its own slice has
#: a budget objection, not a "there is no answer" objection — the question is
#: still worth asking somewhere free. Every other refusal (DAILY_EXHAUSTED,
#: MONTHLY_EXHAUSTED, HTTP_429) already spills through the registry chain.
FALLBACK_ON = ("CALLER_DAILY_CAP",)

Transport = Callable[..., list[dict[str, Any]]]


@dataclass
class FreeSearchResponse:
    """Duck-compatible with ``brave_router.RouterResponse`` on the fields callers read.

    Deliberately a separate type rather than a ``RouterResponse``: that dataclass
    stamps the router's own ``schema``/``interface_version`` defaults, and a free
    provider call is not a router call. Sharing the *attribute names* keeps the
    consuming code identical; sharing the *schema string* would put a false
    provenance claim into every research object built from a free answer.
    """

    schema: str = SCHEMA
    ok: bool = False
    reason: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    provider: str = PROVIDER
    cache_hit: bool = False
    #: Always None — this path reserves nothing. Present so callers that thread
    #: ``resp.reservation_id`` into provenance work unchanged.
    reservation_id: Optional[str] = None
    receipt: Optional[dict[str, Any]] = None
    #: How many ledger units this call actually consumed (1, or 2 with a retry).
    units: int = 0


def fallback_enabled(env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FALLBACK_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


def applies_to(reason: str) -> bool:
    """True when ``reason`` is a refusal this module is allowed to answer."""
    return any(r in str(reason or "") for r in FALLBACK_ON)


def _categories(kind: str) -> str:
    return "news" if str(kind or "").strip().lower() == "news" else "general"


def _default_transport(query: str, *, categories: str, limit: int,
                       timeout: float) -> list[dict[str, Any]]:
    """The shared client only. Five bespoke SearXNG clients already bypass the
    ledger, which is why free usage is unobservable today; this adds no sixth."""
    try:
        from scripts.lib.searxng_client import searx_search
    except ImportError:  # pragma: no cover - dual-import shape, see AGENTS
        from lib.searxng_client import searx_search  # type: ignore
    return searx_search(query, categories=categories, limit=limit, timeout=timeout)


def _budget():
    try:
        from scripts.lib import search_budget
    except ImportError:  # pragma: no cover
        from lib import search_budget  # type: ignore
    return search_budget


def _failed(hits: list[dict[str, Any]]) -> str:
    """``searx_search`` never raises; it reports transport failure as one error row."""
    if len(hits) == 1 and isinstance(hits[0], dict) and hits[0].get("error"):
        return str(hits[0]["error"])
    return ""


def _normalise(hits: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Map the SearXNG hit shape onto the keys paid-search consumers already read.

    Brave spells the body ``description``; SearXNG spells it ``snippet``. A
    consumer that reads ``description`` (governed_research_producer builds the
    research object's body from it) would otherwise silently produce empty
    bodies for every free answer — present, well-formed, and content-free.
    """
    out: list[dict[str, Any]] = []
    for h in hits:
        if not isinstance(h, dict):
            continue
        url = str(h.get("url") or "").strip()
        if not url:
            continue
        body = h.get("snippet") or h.get("content") or h.get("description") or ""
        out.append({
            "title": str(h.get("title") or "")[:400],
            "url": url,
            "description": str(body)[:4000],
            "snippet": str(body)[:4000],
            "domain": str(h.get("domain") or ""),
            "engine": PROVIDER,
        })
        if len(out) >= limit:
            break
    return out


def search(query: str, *, caller: str = "default", kind: str = "web",
           count: int = 3, timeout: float = 12.0,
           root: Optional[Path] = None,
           transport: Optional[Transport] = None) -> FreeSearchResponse:
    """Ask the free provider, one budgeted request at a time.

    Returns a refusal rather than raising: a caller reaching here has already
    been refused once, and a second exception at the rescue path would turn a
    recoverable question into a producer break.
    """
    q = str(query or "").strip()
    if not q:
        return FreeSearchResponse(ok=False, reason="EMPTY_QUERY")

    sb = _budget()
    tx = transport or _default_transport
    limit = max(1, int(count or 1))
    units = 0
    attempts: list[str] = []

    # news→general: two categories are two requests, and each one is metered.
    wanted = [_categories(kind)]
    if wanted[0] == "news":
        wanted.append("general")

    for categories in wanted:
        verdict = sb.try_consume(PROVIDER, caller=caller, root=root)
        if not verdict.get("allowed"):
            reason = str(verdict.get("reason") or "BUDGET_REFUSED")
            return FreeSearchResponse(ok=False, reason=f"BUDGET_REFUSED:{reason}",
                                      units=units)
        units += 1
        try:
            hits = tx(q, categories=categories, limit=limit, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - a call that never happened is refunded
            sb.refund(PROVIDER, caller=caller, root=root)
            units -= 1
            attempts.append(f"{categories}:{type(exc).__name__}")
            continue

        err = _failed(list(hits or []))
        if err:
            sb.refund(PROVIDER, caller=caller, root=root)
            units -= 1
            attempts.append(f"{categories}:{err}")
            continue

        results = _normalise(list(hits or []), limit=limit)
        if results:
            return FreeSearchResponse(ok=True, reason="OK", results=results,
                                      units=units)
        attempts.append(f"{categories}:zero_results")

    reason = "PROVIDER_ERROR" if any(":" in a and not a.endswith("zero_results")
                                     for a in attempts) else "ZERO_RESULTS"
    return FreeSearchResponse(ok=False, reason=f"{reason}:{','.join(attempts)}",
                              units=units)


__all__ = [
    "SCHEMA",
    "PROVIDER",
    "FALLBACK_FLAG",
    "FALLBACK_ON",
    "FreeSearchResponse",
    "fallback_enabled",
    "applies_to",
    "search",
]
