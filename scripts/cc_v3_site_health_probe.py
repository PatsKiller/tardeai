#!/usr/bin/env python3
"""Probe CC v3 page-load API endpoints for post-upgrade regressions."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
BASE = "http://127.0.0.1:7777"
DEFAULT_TIMEOUT = 20.0
# Single-threaded API — these endpoints routinely exceed 20s on cold cache.
SLOW_TIMEOUT = 65.0
SLOW_PREFIXES = (
    "/api/v2/broker-proposals",
    "/api/v2/schwab/accounts-live",
)

# GET endpoints used on initial page load / hub tabs (read-only smoke)
ENDPOINTS = [
    "/api/health",
    "/api/v2/health",
    "/api/v2/overview",
    "/api/v2/portfolio/holdings",
    "/api/v2/portfolio/llm-coverage",
    "/api/v2/portfolio/performance",
    "/api/v2/portfolio/lookthrough",
    "/api/v2/holdings/live-stops",
    "/api/v2/holdings/monitored-stops",
    "/api/v2/stops/management",
    "/api/v2/stops/audit",
    "/api/v2/stops/reentry-watch?days=365",
    "/api/v2/risk",
    "/api/v2/risk-regime/latest",
    "/api/v2/risk-regime/indicators",
    "/api/v2/risk-regime/history",
    "/api/v2/open-trades",
    "/api/v2/open-trades/intelligence",
    "/api/v2/paper-proposals",
    "/api/v2/paper-status",
    "/api/v2/pipeline-run-health",
    "/api/v2/trade-ai",
    "/api/v2/strategy-desk",
    "/api/v2/strategy-intelligence",
    "/api/v2/strategy-leaderboard",
    "/api/v2/strategy-configs",
    "/api/v2/agents/summary",
    "/api/v2/agent-pipeline",
    "/api/v2/hermes/health",
    "/api/v2/hermes/maturity-dashboard",
    "/api/v2/hermes/llm-auth-status",
    "/api/v2/llm/oauth-lanes",
    "/api/v2/llm-health",
    "/api/v2/local-llm-status",
    "/api/v2/retirement",
    "/api/v2/watchlist/summary",
    "/api/v2/watchlist/items",
    "/api/v2/watchpool",
    "/api/v2/pullback-macd/candidates",
    "/api/v2/sector-performance",
    "/api/v2/sectors/monitor",
    "/api/v2/reports/list",
    "/api/v2/reports/portal-summary",
    "/api/v2/rotation/summary",
    "/api/v2/rec-intel/summary",
    "/api/v2/rec-intel/lifecycle",
    "/api/v2/rec-intel/open-positions",
    "/api/v2/system/pipeline-health",
    "/api/v2/system/pipeline-summary",
    "/api/v2/system/schwab-status",
    "/api/v2/system/scheduled-jobs",
    "/api/v2/system/runtime-inventory",
    "/api/v2/data-source-health",
    "/api/v2/brokers/schwab/token-health",
    "/api/v2/schwab/accounts-live",
    "/api/v2/dividends",
    "/api/v2/forecast",
    "/api/v2/tax-lots",
    "/api/v2/journal/analytics",
    "/api/v2/journal",
    "/api/v2/backtesting/status",
    "/api/v2/backtesting/runs",
    "/api/v2/scalp/stop-monitor",
    "/api/v2/scalp/live",
    "/api/v2/market-intelligence",
    "/api/v2/morning-brief",
    "/api/v2/correlation",
    "/api/v2/inbox",
    "/api/v2/incubator",
    "/api/v2/recovery",
    "/api/v2/rag/status",
    "/api/v2/openclaw/status",
    "/api/v2/live-trading-gate",
    "/api/v2/broker-accounts",
    "/api/v2/broker-orders/drafts",
    "/api/v2/broker-proposals",
    "/api/v2/time-exit-proposals",
    "/api/v2/tos-watchlists",
    # POST-only — GET list is /api/v2/watch-directives
    "/api/v2/watch-directives",
    "/api/v2/finviz-enrichment?symbol=RKLB",
    "/api/v2/plan-vs-performance",
    "/api/v2/execution-quality",
    "/api/v2/health/proposals",
    "/api/v2/health/activity",
    "/api/v2/health/history",
    "/api/v2/atm/setup-advisory",
    "/api/v2/atm/gate-status",
    "/api/v2/paper-trade-readiness",
    "/api/v2/snaptrade/status",
    "/api/v2/intelligence/library",
    "/api/v2/weekly-learning",
    "/api/v2/cio-decisions",
    "/api/v2/trade-integrity-audit",
    "/api/v2/tradeai/fleet",
]


def _timeout_for(path: str) -> float:
    return SLOW_TIMEOUT if any(path.startswith(p) for p in SLOW_PREFIXES) else DEFAULT_TIMEOUT


def probe(path: str, timeout: float | None = None) -> dict:
    if timeout is None:
        timeout = _timeout_for(path)
    url = BASE + path
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(500_000).decode("utf-8", errors="replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        body = e.read(3000).decode("utf-8", errors="replace")
        return {"path": path, "status": e.code, "ok": False, "err": body[:200]}
    except Exception as e:
        return {"path": path, "status": 0, "ok": False, "err": str(e)[:200]}

    ok = code == 200
    err = None
    try:
        j = json.loads(body) if body.strip().startswith(("{", "[")) else None
        if isinstance(j, dict):
            if j.get("ok") is False or j.get("error"):
                ok = False
                err = str(j.get("error") or j.get("message") or j)[:200]
            elif "data" in j and isinstance(j["data"], dict) and j["data"].get("ok") is False:
                ok = False
                err = str(j["data"].get("error") or j["data"])[:200]
    except json.JSONDecodeError:
        pass

    if not ok and not err:
        err = body[:160]
    return {"path": path, "status": code, "ok": ok, "err": err}


def main() -> int:
    # Single-threaded server — probe sequentially to avoid wedging/killing it.
    results = []
    for p in ENDPOINTS:
        results.append(probe(p))
        import time
        time.sleep(0.15)

    results.sort(key=lambda r: (r["ok"], r["path"]))
    fail = [r for r in results if not r["ok"]]
    print(f"Probed {len(results)} endpoints — {len(results) - len(fail)} OK, {len(fail)} FAIL\n")
    for r in fail:
        print(f"FAIL [{r['status']}] {r['path']}")
        if r.get("err"):
            print(f"       {r['err']}")
    if not fail:
        print("All endpoints OK")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())