#!/usr/bin/env python3
"""Post-deployment smoke test — verify 6 critical endpoints respond within budget.

Usage:
    python scripts/post_deploy_smoke_test.py             # full: warm + test
    python scripts/post_deploy_smoke_test.py --alert     # also sends Telegram if any fail
    python scripts/post_deploy_smoke_test.py --no-warm   # skip DB warmup (already warm)
    python scripts/post_deploy_smoke_test.py --skip-slow # skip watchlist + watch intel (fast check only)

Exit code 0 = all passed, 1 = failures found.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HEALTH_DIR = PROJECT_ROOT / "data" / "health"
HEALTH_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.getenv("SMOKE_TEST_BASE_URL", "http://localhost:7777")

# ---------------------------------------------------------------------------
# Endpoint budget: (path, max_seconds_cold, max_seconds_warm, min_bytes)
# Cold = first hit after server restart (DB cache empty).
# Warm = second+ hit after DB is cached.
# ---------------------------------------------------------------------------
ENDPOINTS = [
    ("/api/v2/overview",                      2.0,   2.0,   5000),
    ("/api/v2/defense/recommendations",        2.0,   2.0,   5000),
    ("/api/v2/reentry/decision-desk",          3.0,   3.0,  10000),
    ("/api/v2/stops/reentry-watch",            2.0,   2.0,   1000),
    # Wave C: expand coverage from 6 to 10 endpoints
    ("/api/v2/defense/posture",                2.0,   2.0,   1000),
    ("/api/v2/rotation/summary",               2.5,   2.0,   1000),
    ("/api/v2/holdings/share-drift",           2.5,   2.0,   1000),
    ("/api/v2/health",                         5.0,   2.0,    500),
    # watchlist/items LATERAL-joins 5.9K active items against 4.5M-row
    # market_quotes (729MB). Cold start is DB-bound (~11s); once cached ~4s.
    ("/api/v2/watchlist/items",               12.0,   5.0,   5000),
    # watch-intelligence projection hits every held symbol through
    # the decision_packets JSONB column (78MB). Cold ~7s, warm ~2-4s.
    ("/api/v3/data-broker/watch-intelligence", 12.0,   8.0,  10000),
]

# ---------------------------------------------------------------------------
# Memory check
# ---------------------------------------------------------------------------
def check_server_memory() -> dict:
    """Read server RSS from /proc. Returns dict with status + details."""
    result = {"component": "server_memory", "status": "OK", "rss_mb": 0, "pid": None}
    try:
        import subprocess
        raw = subprocess.check_output(
            ["systemctl", "--user", "show", "portfolio-server",
             "-p", "MainPID", "-p", "MemoryCurrent"],
            timeout=5, text=True
        )
        pid = mem = None
        for line in raw.strip().split("\n"):
            if line.startswith("MainPID="):
                pid = line.split("=", 1)[1]
            if line.startswith("MemoryCurrent="):
                mem = int(line.split("=", 1)[1]) // (1024 * 1024)
        result["pid"] = pid
        result["rss_mb"] = mem or 0
        if mem and mem > 1500:
            result["status"] = "WARN"
            result["note"] = f"RSS {mem}MB exceeds 1.5GB soft limit"
        if mem and mem > 2000:
            result["status"] = "CRITICAL"
            result["note"] = f"RSS {mem}MB exceeds 2GB hard limit — OOM imminent"
    except Exception as e:
        result["status"] = "ERROR"
        result["note"] = str(e)[:200]
    return result


# ---------------------------------------------------------------------------
# Endpoint checks
# ---------------------------------------------------------------------------
def _fetch(path: str, timeout_s: float) -> tuple[int, float, int, str]:
    """Fetch one endpoint. Returns (http_code, elapsed_s, size_bytes, note)."""
    t0 = time.time()
    try:
        req = Request(f"{BASE_URL}{path}")
        req.add_header("User-Agent", "smoke-test/1.0")
        resp = urlopen(req, timeout=int(timeout_s + 5))
        body = resp.read()
        elapsed = time.time() - t0
        code = resp.status
        size = len(body)
        note = ""
        # Quick JSON parse check
        try:
            json.loads(body)
        except json.JSONDecodeError:
            note = "Response is not valid JSON"
        return (code, round(elapsed, 3), size, note)
    except URLError as e:
        return (None, round(time.time() - t0, 3), 0, f"Connection error: {e.reason}"[:200])
    except Exception as e:
        return (None, round(time.time() - t0, 3), 0, str(e)[:200])


def warm_db() -> dict:
    """Hit heavy endpoints once to populate DB page cache. Returns timing summary."""
    heavy = [
        ("/api/v2/overview", 15),
        ("/api/v2/defense/recommendations", 15),
        ("/api/v2/watchlist/items", 60),
        ("/api/v3/data-broker/watch-intelligence", 60),
        ("/api/v2/reentry/decision-desk", 15),
    ]
    results = {}
    t_total = time.time()
    for path, timeout_s in heavy:
        code, elapsed, size, note = _fetch(path, timeout_s)
        results[path] = {"elapsed": elapsed, "http": code, "size": size}
    results["_total_warmup_s"] = round(time.time() - t_total, 1)
    return results


def check_endpoints(skip_slow: bool = False) -> list[dict]:
    """Test each endpoint. Returns list of result dicts."""
    results = []
    for path, max_cold, max_warm, min_bytes in ENDPOINTS:
        if skip_slow and path in (
            "/api/v2/watchlist/items",
            "/api/v3/data-broker/watch-intelligence",
        ):
            continue
        result = {
            "endpoint": path,
            "status": "OK",
            "http_code": None,
            "elapsed_s": 0.0,
            "size_bytes": 0,
            "note": "",
        }
        # First hit (cold budget)
        code, elapsed, size, note = _fetch(path, max(max_cold, max_warm) + 5)
        if note:
            result["status"] = "FAIL"
            result["note"] = note
        elif code != 200:
            result["status"] = "FAIL"
            result["note"] = f"HTTP {code}"
        else:
            # Use warm budget for second+ hits; cold budget for first
            budget = max_cold if elapsed > max_warm * 1.5 else max_warm
            if elapsed > budget:
                result["status"] = "SLOW"
                result["note"] = f"{elapsed:.1f}s > {budget:.0f}s budget"
            elif size < min_bytes:
                result["status"] = "WARN"
                result["note"] = f"Small response ({size}B < {min_bytes}B)"
        result["elapsed_s"] = elapsed
        result["http_code"] = code
        result["size_bytes"] = size
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Telegram alert (reuses health agent path if possible)
# ---------------------------------------------------------------------------
def _send_telegram(header: str, failures: list[dict]) -> bool:
    """Send a concise failure alert via Telegram."""
    try:
        scripts = str(PROJECT_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from system_health_agent import _send_alert
        lines = [header, ""]
        for f in failures:
            ep = f.get("endpoint", "?")
            lines.append(f"  {f['status']:8s} {ep}: {f.get('note','')}")
        _send_alert("\n".join(lines))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(*, send_alert: bool = False, warm: bool = True, skip_slow: bool = False) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    memory = check_server_memory()
    warmup = None
    if warm:
        warmup = warm_db()

    endpoints = check_endpoints(skip_slow=skip_slow)

    failures = [e for e in endpoints if e["status"] not in ("OK", "SLOW")]
    warnings = [e for e in endpoints if e["status"] == "SLOW"]
    memory_bad = memory["status"] != "OK"

    report = {
        "smoke_test": True,
        "timestamp": now,
        "all_pass": len(failures) == 0 and not memory_bad,
        "memory": memory,
        "warmup": warmup,
        "endpoints": endpoints,
        "failures": len(failures),
        "warnings": len(warnings),
        "memory_alert": memory_bad,
    }

    # Write report
    report_path = HEALTH_DIR / "smoke_test_latest.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))

    if send_alert and (failures or memory_bad):
        _send_telegram(
            "🚨 Post-deploy smoke test FAILED",
            ([memory] if memory_bad else []) + failures,
        )

    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Post-deploy smoke test")
    p.add_argument("--alert", action="store_true", help="Send Telegram alert on failure")
    p.add_argument("--no-warm", action="store_true", help="Skip DB cache warmup (already warm)")
    p.add_argument("--skip-slow", action="store_true", help="Skip heavy endpoints (watchlist + watch intel)")
    p.add_argument("--quiet", action="store_true", help="Suppress stdout")
    args = p.parse_args()

    result = run(send_alert=args.alert, warm=not args.no_warm, skip_slow=args.skip_slow)
    if not args.quiet:
        print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["all_pass"] else 1)
