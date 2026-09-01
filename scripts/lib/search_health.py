#!/usr/bin/env python3
"""search_health.py — per-provider search health, and pool degradation made loud.

`research_lane_health` monitors LLM lanes. Measured 2026-08-30 it had **zero
lanes covering search providers**, so the state below was invisible to it:

    SearXNG /search?q=nvidia -> 200, 10 results
      engines that SERVED results : {'bing': 10}
      unresponsive                : brave "too many requests",
                                    duckduckgo CAPTCHA, startpage CAPTCHA

Three of four engines down, every result from one engine, and the response looks
exactly like a healthy ten-result answer. **A thinner answer that is
indistinguishable from a full one is the failure this whole programme exists to
eliminate**, so `pool_health()` returns a degradation record that the research
record carries rather than discarding.

READ_ONLY_ADVISORY. Probes are HTTP GETs against a self-hosted endpoint; no
paid provider is called by this module.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = "SearchHealth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888")

# Below this many distinct engines actually returning results, the pool is
# impaired regardless of how many results came back: a ten-result answer drawn
# from one engine has one engine's blind spots.
MIN_HEALTHY_ENGINES = 2


def probe_searxng(query: str = "nvidia", *, url: Optional[str] = None,
                  timeout: int = 20) -> dict[str, Any]:
    """One live probe. Never raises."""
    base = (url or SEARXNG_URL).rstrip("/")
    target = f"{base}/search?{urllib.parse.urlencode({'q': query, 'format': 'json'})}"
    try:
        req = urllib.request.Request(target, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read())
    except Exception as e:
        return {"reachable": False, "error": f"{type(e).__name__}: {e}",
                "results": 0, "serving_engines": [], "unresponsive": []}

    results = doc.get("results") or []
    serving: dict[str, int] = {}
    for r in results:
        for eng in (r.get("engines") or ([r.get("engine")] if r.get("engine") else [])):
            if eng:
                serving[str(eng)] = serving.get(str(eng), 0) + 1
    unresponsive = []
    for u in doc.get("unresponsive_engines") or []:
        if isinstance(u, (list, tuple)):
            unresponsive.append({"engine": str(u[0]),
                                 "reason": str(u[1]) if len(u) > 1 else ""})
        else:
            unresponsive.append({"engine": str(u), "reason": ""})
    return {"reachable": True, "results": len(results),
            "serving_engines": sorted(serving), "engine_counts": serving,
            "unresponsive": unresponsive}


def pool_health(query: str = "nvidia", *, url: Optional[str] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """The degradation record a research result should carry.

    `impaired` is deliberately driven by how many engines actually SERVED
    results, not by the result count. The measured failure had ten results and
    one engine.
    """
    now = now or datetime.now(timezone.utc)
    p = probe_searxng(query, url=url)
    serving = p.get("serving_engines") or []
    down = p.get("unresponsive") or []
    impaired = (not p["reachable"]) or len(serving) < MIN_HEALTHY_ENGINES

    if not p["reachable"]:
        note = f"SearXNG unreachable: {p.get('error')}"
    elif impaired:
        note = (f"Search pool impaired: {len(serving)} engine(s) served results "
                f"({', '.join(serving) or 'none'}); "
                f"{len(down)} unavailable ("
                + "; ".join(f"{d['engine']}: {d['reason']}" for d in down) + "). "
                "Coverage is narrower than a normal result set of this size.")
    else:
        note = (f"Search pool healthy: {len(serving)} engines served results "
                f"({', '.join(serving)}).")

    return {
        "schema": SCHEMA, "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "impaired": impaired,
        "reachable": p["reachable"],
        "results": p.get("results", 0),
        "serving_engines": serving,
        "engines_serving_count": len(serving),
        "unresponsive_engines": down,
        "min_healthy_engines": MIN_HEALTHY_ENGINES,
        "degradation_note": note,
    }


def collect_search_health(*, now: Optional[datetime] = None,
                          probe: bool = True) -> dict[str, Any]:
    """One lane row for `research_lane_health`, same shape as its collectors."""
    now = now or datetime.now(timezone.utc)
    firing: list[str] = []
    pool: dict[str, Any] = {}
    if probe:
        pool = pool_health(now=now)
        if not pool["reachable"]:
            firing.append("searxng_unreachable")
        elif pool["impaired"]:
            firing.append("engine_pool_impaired")

    budgets: dict[str, Any] = {}
    try:
        from scripts.lib.search_budget import all_status
    except Exception:
        try:
            from lib.search_budget import all_status  # type: ignore
        except Exception:
            all_status = None                       # type: ignore
    if all_status is not None:
        budgets = all_status(now=now)
        for name, st in budgets.items():
            if st.get("error"):
                firing.append(f"{name}_budget_unavailable")
            elif st.get("alert") == "critical":
                firing.append(f"{name}_budget_critical")
            elif st.get("alert") == "warning":
                firing.append(f"{name}_budget_warning")

    return {
        "lane": "search-providers",
        "ok": not firing,
        "firing": firing,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "pool": pool,
        "budgets": budgets,
    }
