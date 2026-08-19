#!/usr/bin/env python3
"""Read-only overnight soak spend report for watchlist agent jobs.

Prints JSON on stdout. Never prints secrets or API keys.
No broker / order / stop / risk / 2FA mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

SECRET_KEYS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "deepseek_tradeai",
    "authorization",
)


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, val in obj.items():
            lk = str(key).lower()
            if any(s in lk for s in SECRET_KEYS):
                out[key] = "redacted"
            else:
                out[key] = _redact(val)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def _job_counts_from_db() -> tuple[dict[str, int] | None, str | None]:
    try:
        from db_adapter import _execute, USE_DB
    except Exception as exc:
        return None, f"db_adapter_import_failed:{type(exc).__name__}"
    if not USE_DB:
        return None, "db_unavailable"
    try:
        rows = _execute(
            "SELECT status, COUNT(*) FROM watchlist_agent_jobs GROUP BY status",
            fetch="all",
        )
    except Exception as exc:
        return None, f"query_error:{type(exc).__name__}"
    counts: dict[str, int] = {}
    for row in rows or []:
        if isinstance(row, dict):
            status = str(row.get("status") or row.get("STATUS") or "")
            cnt = row.get("count") or row.get("COUNT") or list(row.values())[1]
        else:
            status = str(row[0])
            cnt = row[1]
        counts[status] = int(cnt or 0)
    return counts, None


def _ledger_paid_today() -> tuple[float | None, str | None]:
    try:
        from lib.llm_consumption import ledger_paid_usd_today
    except Exception as exc:
        return None, f"ledger_import_failed:{type(exc).__name__}"
    try:
        return float(ledger_paid_usd_today(None)), None
    except Exception as exc:
        return None, f"ledger_error:{type(exc).__name__}"


def build_report(
    *,
    ledger_paid_usd_today: Callable[[], float] | None = None,
    job_counts_fn: Callable[[], dict[str, int]] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "authority": "READ_ONLY_ADVISORY",
        "lane": "watchlist_agent_jobs_offpeak_soak",
        "soak_cap_usd": 2.00,
        "ledger_paid_usd_today": None,
        "watchlist_agent_jobs": None,
        "errors": [],
    }
    if ledger_paid_usd_today is not None:
        try:
            report["ledger_paid_usd_today"] = float(ledger_paid_usd_today())
        except Exception as exc:
            report["errors"].append(f"ledger_error:{type(exc).__name__}")
    else:
        paid, err = _ledger_paid_today()
        report["ledger_paid_usd_today"] = paid
        if err:
            report["errors"].append(err)

    if job_counts_fn is not None:
        try:
            report["watchlist_agent_jobs"] = dict(job_counts_fn())
        except Exception as exc:
            report["errors"].append(f"job_counts_error:{type(exc).__name__}")
    else:
        counts, err = _job_counts_from_db()
        report["watchlist_agent_jobs"] = counts
        if err:
            report["errors"].append(err)
    return _redact(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only agent-jobs soak spend report")
    parser.add_argument("--json", action="store_true", help="Write JSON to stdout (required)")
    args = parser.parse_args(argv)
    if not args.json:
        parser.error("--json is required")
    payload = build_report()
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
