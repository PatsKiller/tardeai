#!/usr/bin/env python3
"""CC v3 hub tab → API contract smoke (Phase 3).

Maps each primary hub surface to at least one GET endpoint the tab depends on.
Run against live server: python3 tests/test_cc_v3_hub_contract.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:7777"

# hub → [(label, path, timeout_sec)]
HUB_CONTRACT: list[tuple[str, list[tuple[str, str, float]]]] = [
    ("Home", [("overview", "/api/v2/overview", 20), ("command", "/api/v2/command", 20), ("inbox", "/api/v2/inbox", 20)]),
    ("Portfolio", [("holdings", "/api/v2/portfolio/holdings", 25)]),
    ("Risk", [("risk", "/api/v2/risk", 25)]),
    ("Trading/Proposals", [("broker-proposals", "/api/v2/broker-proposals?page=1&page_size=5", 65)]),
    ("Trading/Schwab", [("accounts-live", "/api/v2/schwab/accounts-live", 65)]),
    ("Strategy", [("leaderboard", "/api/v2/strategy-leaderboard", 25)]),
    ("Agents", [("summary", "/api/v2/agents/summary", 25)]),
    ("Intelligence", [("market-intel", "/api/v2/market-intelligence", 30)]),
    ("Hermes", [("health", "/api/v2/hermes/health", 30)]),
    ("Journal", [("journal", "/api/v2/journal", 30)]),
    ("Watch/Watchlist", [("items", "/api/v2/watchlist/items", 30)]),
    ("Watch/Watchpool", [("watchpool", "/api/v2/watchpool", 30)]),
    ("Watch/Sectors", [("sectors", "/api/v2/sectors/monitor", 30)]),
    ("Watch/Pullback", [("pullback", "/api/v2/pullback-macd/candidates", 30)]),
    ("Reports", [("portal", "/api/v2/reports/portal-summary", 25)]),
    ("Rotation", [("summary", "/api/v2/rotation/summary", 40)]),
    ("Rec Intel", [("summary", "/api/v2/rec-intel/summary", 30)]),
    ("Health", [("health", "/api/v2/health", 25)]),
    ("System", [("pipeline", "/api/v2/system/pipeline-health", 30)]),
]

ROUTES = [
    "/v3/", "/v3/watch", "/v3/rotation", "/v3/trading",
]


def probe(path: str, timeout: float) -> dict:
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(300_000).decode("utf-8", errors="replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "err": e.read(200).decode()[:120]}
    except Exception as e:
        return {"ok": False, "status": 0, "err": str(e)[:120]}
    ok = code == 200
    if path.startswith("/api/") and body.strip().startswith("{"):
        try:
            j = json.loads(body)
            if isinstance(j, dict) and j.get("ok") is False:
                ok = False
        except json.JSONDecodeError:
            pass
    return {"ok": ok, "status": code}


def main() -> int:
    fails = []
    for hub, endpoints in HUB_CONTRACT:
        for label, path, timeout in endpoints:
            r = probe(path, timeout)
            if not r["ok"]:
                fails.append((hub, label, path, r))
                print(f"FAIL {hub}/{label} {path} — {r.get('err', r.get('status'))}")
            else:
                print(f"OK   {hub}/{label}")
    for route in ROUTES:
        r = probe(route, 15)
        if not r["ok"]:
            fails.append(("route", route, route, r))
            print(f"FAIL route {route}")
        else:
            print(f"OK   route {route}")
    print(f"\n{len(HUB_CONTRACT)} hubs · {sum(len(e) for _, e in HUB_CONTRACT)} API checks · {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())