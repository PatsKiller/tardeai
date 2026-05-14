#!/usr/bin/env python3
"""check_deep_overnight_health.py — Deep overnight LLM health checker.

Checks model residency, lock status, queue health, and safety gates.
Returns PASS/WARN/FAIL for each check. Exits nonzero on any FAIL.

Usage:
    .venv/bin/python scripts/check_deep_overnight_health.py --summary
    .venv/bin/python scripts/check_deep_overnight_health.py --json > /tmp/health.json

Does NOT touch broker, holdings, execution, or trading behavior.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJ = Path(__file__).resolve().parent.parent

LOCK_FILE = Path("/tmp/tradeai_deep_llm_window.lock")
OLLAMA_BASE = "http://localhost:11434"
HOLDINGS_PATH = PROJ / "data" / "portfolios" / "state" / "holdings.json"

# ── Alert event types ─────────────────────────────────────────────────
ALERT_LOCK_STUCK = "DEEP_LLM_LOCK_STUCK"
ALERT_QWEN_FAIL = "QWEN_RESTORE_FAILED"
ALERT_NOMIC_FAIL = "NOMIC_RESTORE_FAILED"
ALERT_RISK_MISSING = "RISK_SYNTHESIS_MISSING"
ALERT_P0_PENDING = "DEEP_QUEUE_P0_PENDING"


# ── Helpers ───────────────────────────────────────────────────────────

def _read_env() -> dict[str, str]:
    env_path = PROJ / ".env"
    env_vars: dict[str, str] = {}
    if not env_path.exists():
        return env_vars
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return env_vars


def get_db_connection():
    import psycopg2
    env_vars = _read_env()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def _ollama_get(path: str, timeout: float = 5.0) -> dict | None:
    """GET request to ollama API. Returns parsed JSON or None on failure."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}{path}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _try_alert(event_type: str, title: str, body: str):
    """Try to dispatch an alert via alert_dispatcher. Swallow import errors."""
    try:
        sys.path.insert(0, str(PROJ / "scripts"))
        from alert_dispatcher import dispatch_alert
        dispatch_alert(
            alert_type=event_type,
            title=title,
            body=body,
            tier="ALERT",
            source="check_deep_overnight_health",
            dedupe_scope="global",
        )
    except ImportError:
        log.debug("alert_dispatcher not importable — skipping alert for %s", event_type)
    except Exception as exc:
        log.debug("alert dispatch failed for %s: %s", event_type, exc)


# ── Check functions ───────────────────────────────────────────────────
# Each returns {"status": "PASS"|"WARN"|"FAIL", "detail": str, ...}

def check_deep_lock_stuck(verbose: bool = False) -> dict[str, Any]:
    """FAIL if lock file exists and owning PID is dead."""
    if not LOCK_FILE.exists():
        return {"status": "PASS", "detail": "No lock file present"}
    try:
        content = LOCK_FILE.read_text().strip()
        pid = int(content.split()[0]) if content else 0
    except (ValueError, IndexError):
        return {"status": "WARN", "detail": f"Lock file exists but unreadable: {content!r}"}

    if pid and _pid_alive(pid):
        return {"status": "PASS", "detail": f"Lock held by PID {pid} (alive)"}

    detail = f"Stale lock — PID {pid} is not running"
    _try_alert(ALERT_LOCK_STUCK, "Deep LLM lock stuck", detail)
    return {"status": "FAIL", "detail": detail}


def check_gemma_still_resident(verbose: bool = False) -> dict[str, Any]:
    """WARN if gemma3-overnight is still loaded in ollama."""
    data = _ollama_get("/api/ps")
    if data is None:
        return {"status": "WARN", "detail": "Could not reach ollama /api/ps"}
    models = [m.get("name", "") for m in data.get("models", [])]
    for m in models:
        if "gemma" in m.lower() and "overnight" in m.lower():
            return {"status": "WARN", "detail": f"gemma3-overnight still resident: {m}"}
    return {"status": "PASS", "detail": "gemma3-overnight not resident"}


def check_qwen_not_resident(verbose: bool = False) -> dict[str, Any]:
    """FAIL if qwen3:14b is NOT resident."""
    data = _ollama_get("/api/ps")
    if data is None:
        return {"status": "FAIL", "detail": "Could not reach ollama /api/ps"}
    models = [m.get("name", "") for m in data.get("models", [])]
    for m in models:
        if "qwen3" in m.lower() and "14b" in m.lower():
            return {"status": "PASS", "detail": f"qwen3:14b resident: {m}"}
    detail = "qwen3:14b is NOT resident in ollama"
    _try_alert(ALERT_QWEN_FAIL, "qwen3:14b not resident", detail)
    return {"status": "FAIL", "detail": detail}


def check_nomic_not_resident(verbose: bool = False) -> dict[str, Any]:
    """FAIL if nomic-embed-text is NOT resident."""
    data = _ollama_get("/api/ps")
    if data is None:
        return {"status": "FAIL", "detail": "Could not reach ollama /api/ps"}
    models = [m.get("name", "") for m in data.get("models", [])]
    for m in models:
        if "nomic" in m.lower():
            return {"status": "PASS", "detail": f"nomic-embed-text resident: {m}"}
    detail = "nomic-embed-text is NOT resident in ollama"
    _try_alert(ALERT_NOMIC_FAIL, "nomic-embed-text not resident", detail)
    return {"status": "FAIL", "detail": detail}


def check_risk_synthesis_missing(verbose: bool = False) -> dict[str, Any]:
    """WARN if no risk_synthesis_results row in last 48 hours."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM risk_synthesis_results WHERE generated_at > NOW() - INTERVAL '48 hours'"
        )
        count = cur.fetchone()[0]
        conn.close()
        if count > 0:
            return {"status": "PASS", "detail": f"{count} risk synthesis rows in last 48h"}
        detail = "No risk_synthesis_results in last 48 hours"
        _try_alert(ALERT_RISK_MISSING, "Risk synthesis missing", detail)
        return {"status": "WARN", "detail": detail}
    except Exception as exc:
        return {"status": "WARN", "detail": f"DB query failed: {exc}"}


def check_p0_jobs_pending(verbose: bool = False) -> dict[str, Any]:
    """WARN if any P0 priority jobs are pending in deep_overnight_llm_queue."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM deep_overnight_llm_queue WHERE priority_tier = 'P0' AND status = 'pending'"
        )
        count = cur.fetchone()[0]
        conn.close()
        if count == 0:
            return {"status": "PASS", "detail": "No P0 jobs pending"}
        detail = f"{count} P0 jobs still pending"
        _try_alert(ALERT_P0_PENDING, "Deep queue P0 pending", detail)
        return {"status": "WARN", "detail": detail}
    except Exception as exc:
        return {"status": "WARN", "detail": f"DB query failed: {exc}"}


def check_failed_jobs_high(verbose: bool = False) -> dict[str, Any]:
    """WARN if >5 failed jobs in 24h, FAIL if >15."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM deep_overnight_llm_queue "
            "WHERE status = 'failed' AND updated_at > NOW() - INTERVAL '24 hours'"
        )
        count = cur.fetchone()[0]
        conn.close()
        if count > 15:
            return {"status": "FAIL", "detail": f"{count} failed jobs in last 24h (>15)"}
        if count > 5:
            return {"status": "WARN", "detail": f"{count} failed jobs in last 24h (>5)"}
        return {"status": "PASS", "detail": f"{count} failed jobs in last 24h"}
    except Exception as exc:
        return {"status": "WARN", "detail": f"DB query failed: {exc}"}


def check_deep_run_status(verbose: bool = False) -> dict[str, Any]:
    """FAIL if last deep run was >36h ago."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(updated_at) FROM deep_overnight_llm_queue "
            "WHERE status IN ('completed', 'failed')"
        )
        row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return {"status": "FAIL", "detail": "No completed/failed jobs found in queue"}
        last_ts = row[0]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last_ts
        hours = age.total_seconds() / 3600
        if hours > 36:
            return {"status": "FAIL", "detail": f"Last deep run was {hours:.1f}h ago (>36h)"}
        return {"status": "PASS", "detail": f"Last deep run {hours:.1f}h ago"}
    except Exception as exc:
        return {"status": "WARN", "detail": f"DB query failed: {exc}"}


def check_provider_health(verbose: bool = False) -> dict[str, Any]:
    """FAIL if ollama is unreachable."""
    data = _ollama_get("/api/tags")
    if data is None:
        return {"status": "FAIL", "detail": "ollama unreachable at localhost:11434"}
    model_count = len(data.get("models", []))
    return {"status": "PASS", "detail": f"ollama alive — {model_count} models available"}


def check_safety_gates(verbose: bool = False) -> dict[str, Any]:
    """PASS if ALPACA_MODE=paper and LLM_DISABLE_LIVE_EXECUTION=true in .env."""
    env_vars = _read_env()
    alpaca_mode = env_vars.get("ALPACA_MODE", "").lower()
    llm_disable = env_vars.get("LLM_DISABLE_LIVE_EXECUTION", "").lower()
    issues = []
    if alpaca_mode != "paper":
        issues.append(f"ALPACA_MODE={alpaca_mode!r} (expected 'paper')")
    if llm_disable != "true":
        issues.append(f"LLM_DISABLE_LIVE_EXECUTION={llm_disable!r} (expected 'true')")
    if issues:
        return {"status": "FAIL", "detail": "; ".join(issues)}
    return {"status": "PASS", "detail": "ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true"}


def check_holdings_guard(verbose: bool = False) -> dict[str, Any]:
    """PASS if holdings.json total_value > 1000000."""
    try:
        data = json.loads(HOLDINGS_PATH.read_text())
        totals = data.get("portfolio_totals", {})
        total = totals.get("total_value", 0) if totals else data.get("total_value", 0)
        if total > 1_000_000:
            return {"status": "PASS", "detail": f"Portfolio total_value=${total:,.2f}"}
        return {"status": "WARN", "detail": f"Portfolio total_value=${total:,.2f} (<=1M)"}
    except FileNotFoundError:
        return {"status": "WARN", "detail": f"holdings.json not found at {HOLDINGS_PATH}"}
    except Exception as exc:
        return {"status": "WARN", "detail": f"Error reading holdings.json: {exc}"}


# ── Registry ──────────────────────────────────────────────────────────

CHECKS = [
    ("deep_lock_stuck", check_deep_lock_stuck),
    ("gemma_still_resident", check_gemma_still_resident),
    ("qwen_not_resident", check_qwen_not_resident),
    ("nomic_not_resident", check_nomic_not_resident),
    ("risk_synthesis_missing", check_risk_synthesis_missing),
    ("p0_jobs_pending", check_p0_jobs_pending),
    ("failed_jobs_high", check_failed_jobs_high),
    ("deep_run_status", check_deep_run_status),
    ("provider_health", check_provider_health),
    ("safety_gates", check_safety_gates),
    ("holdings_guard", check_holdings_guard),
]


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deep overnight LLM health checker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summary", action="store_true", default=True, help="Human-readable output (default)")
    mode.add_argument("--json", action="store_true", dest="json_mode", help="JSON output to stdout")
    parser.add_argument("--verbose", action="store_true", help="Extra detail")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    results: dict[str, dict[str, Any]] = {}
    has_fail = False

    for name, fn in CHECKS:
        try:
            result = fn(verbose=args.verbose)
        except Exception as exc:
            result = {"status": "WARN", "detail": f"Check raised exception: {exc}"}
        results[name] = result
        if result["status"] == "FAIL":
            has_fail = True

    if args.json_mode:
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall": "FAIL" if has_fail else "PASS",
            "checks": results,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # Summary mode
        print(f"\n{'='*60}")
        print(f"  Deep Overnight LLM Health Check  —  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*60}\n")

        status_icons = {"PASS": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
        for name, result in results.items():
            icon = status_icons.get(result["status"], "[????]")
            line = f"  {icon}  {name}"
            if args.verbose or result["status"] != "PASS":
                line += f"  —  {result['detail']}"
            print(line)

        overall = "FAIL" if has_fail else "ALL PASS"
        print(f"\n  Overall: {overall}")
        print(f"{'='*60}\n")

    sys.exit(1 if has_fail else 0)


if __name__ == "__main__":
    main()
