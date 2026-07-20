#!/usr/bin/env python3
"""finviz_http.py — the ONLY sanctioned way to make a Finviz HTTP request.

Every Finviz call must pass through the global cross-process throttle
(scripts/finviz_throttle.py). That throttle exists because of the 2026-06-22
429 storm, which collapsed the screener universe to ~40-70 symbols, zeroed the
GO tier and produced no strategy signals for a full day. The storm was
self-inflicted: one bulk consumer ignored everyone else's cooldown.

On 2026-07-20 an audit found 12 live callers still bypassing it — enrichment,
technicals, catalysts, market context, the social scalp scanner, four
health/credential probes, an api_v2 chart proxy and the backtest analyzer.
Individually low-volume, collectively the same exposure.

This module centralizes the contract so it cannot drift again:

  * acquire() a global slot before every request
  * on HTTP 429, publish a cooldown so EVERY process backs off, not just this one
  * honour Retry-After when the server supplies it
  * probes can pass a short throttle_timeout and skip rather than block

Usage:
    from finviz_http import finviz_get
    resp = finviz_get(url, headers={...}, timeout=30)

Callers keep their own parsing and error handling; this only owns rate limiting.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Health/credential probes must not block a monitoring run for minutes.
PROBE_THROTTLE_TIMEOUT = float(os.getenv("FINVIZ_PROBE_THROTTLE_TIMEOUT", "30"))


class FinvizRateLimited(RuntimeError):
    """HTTP 429. A global cooldown has been published for every process."""


def finviz_get(url: str, *, headers: Optional[dict] = None, timeout: int = 30,
               throttle_timeout: float = 300, raise_on_429: bool = True,
               **kwargs):
    """Throttled GET against any finviz host.

    raise_on_429=True  -> FinvizRateLimited after publishing the cooldown
    raise_on_429=False -> the 429 response is returned; cooldown still published
                          (for callers that treat rate limiting as a soft skip)
    """
    import requests
    import finviz_throttle

    finviz_throttle.acquire(timeout=throttle_timeout)
    resp = requests.get(url, headers=headers or {}, timeout=timeout, **kwargs)
    if resp.status_code == 429:
        # Publish globally so sibling processes back off too — the single most
        # important behaviour in this module.
        finviz_throttle.cooldown(resp.headers.get("Retry-After"))
        if raise_on_429:
            raise FinvizRateLimited(f"Finviz 429 for {url[:80]} — global cooldown set")
    return resp


def finviz_probe(url: str, *, headers: Optional[dict] = None, timeout: int = 15):
    """Short-wait variant for health checks, credential and preflight probes.

    Still fully throttled, but gives up waiting quickly so a monitoring run
    reports rather than hangs.
    """
    return finviz_get(url, headers=headers, timeout=timeout,
                      throttle_timeout=PROBE_THROTTLE_TIMEOUT,
                      raise_on_429=False)
