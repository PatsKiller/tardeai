#!/usr/bin/env python3
"""Enqueue risk_agent + tax_agent jobs for current holdings symbols.

Maria already covers holdings via the watchlist processor priority path.
Risk/Tax historically only ran on watchlist symbols, so the advisory desk
evidence gap was agent_opinions = Maria-only.

This script inserts queued jobs for every non-CASH holding that lacks a
fresh (<7d) result for the target agent. Dedupes against existing
queued/pending/processing jobs.

Usage:
  .venv/bin/python scripts/enqueue_holdings_agent_opinions.py --dry-run
  .venv/bin/python scripts/enqueue_holdings_agent_opinions.py --apply
  .venv/bin/python scripts/enqueue_holdings_agent_opinions.py --apply --agents risk_agent,tax_agent
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
REPORT_PATH = PROJECT_ROOT / "data" / "runtime" / "holdings_agent_enqueue_latest.json"
DEFAULT_AGENTS = ("risk_agent", "tax_agent")
FRESH_DAYS = 7
# Skip delisted/CUSIP-like symbols without a tradable ticker shape
_TICKER_RE = __import__("re").compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _holdings_symbols() -> list[str]:
    if not HOLDINGS_PATH.exists():
        return []
    data = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    out: set[str] = set()
    for pos in data.get("holdings") or data.get("positions") or []:
        if not isinstance(pos, dict):
            continue
        s = str(pos.get("symbol") or "").strip().upper()
        if not s or s == "CASH":
            continue
        if not _TICKER_RE.match(s):
            continue
        # Skip pure numeric CUSIPs / 9-digit ids
        if s.isdigit() or (len(s) >= 8 and any(c.isdigit() for c in s) and not s.isalpha()):
            # Allow standard tickers with digits (e.g. none common); block CUSIP-like
            if sum(c.isdigit() for c in s) >= 5:
                continue
        out.add(s)
    return sorted(out)


def enqueue(*, agents: list[str], dry_run: bool = True, max_per_agent: int = 40) -> dict:
    from db_adapter import _execute

    symbols = _holdings_symbols()
    report: dict = {
        "ok": True,
        "dry_run": dry_run,
        "at": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "holdings_symbols": symbols,
        "enqueued": [],
        "skipped_fresh": [],
        "skipped_queued": [],
        "errors": [],
    }

    for agent in agents:
        queued_n = 0
        for sym in symbols:
            if queued_n >= max_per_agent:
                break
            # Already queued?
            pending = _execute(
                """SELECT 1 FROM watchlist_agent_jobs
                   WHERE symbol=%s AND requested_agent=%s
                     AND status IN ('queued','pending','processing')
                   LIMIT 1""",
                (sym, agent),
                fetch="one",
            )
            if pending:
                report["skipped_queued"].append({"symbol": sym, "agent": agent})
                continue
            # Fresh result?
            fresh = _execute(
                """SELECT 1 FROM watchlist_agent_results
                   WHERE upper(symbol)=%s AND agent=%s
                     AND completed_at > now() - make_interval(days => %s)
                   LIMIT 1""",
                (sym, agent, FRESH_DAYS),
                fetch="one",
            )
            if fresh:
                report["skipped_fresh"].append({"symbol": sym, "agent": agent})
                continue

            job = {
                "id": str(uuid.uuid4()),
                "symbol": sym,
                "agent": agent,
            }
            if dry_run:
                report["enqueued"].append({**job, "status": "would_enqueue"})
                queued_n += 1
                continue
            try:
                _execute(
                    """INSERT INTO watchlist_agent_jobs
                       (id, symbol, requested_agent, request_type, note, status,
                        priority, submitted_from, created_at)
                       VALUES (%s,%s,%s,'full_analysis',%s,'queued',2,%s,NOW())""",
                    (
                        job["id"],
                        sym,
                        agent,
                        f"holdings coverage for advisory desk ({agent})",
                        "advisory_desk_holdings_enqueue",
                    ),
                    fetch="none",
                )
                report["enqueued"].append({**job, "status": "queued"})
                queued_n += 1
            except Exception as e:
                report["errors"].append({"symbol": sym, "agent": agent, "error": str(e)[:200]})

    report["counts"] = {
        "enqueued": len(report["enqueued"]),
        "skipped_fresh": len(report["skipped_fresh"]),
        "skipped_queued": len(report["skipped_queued"]),
        "errors": len(report["errors"]),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(REPORT_PATH)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write jobs (default is dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="Explicit dry-run (default)")
    ap.add_argument(
        "--agents",
        default=",".join(DEFAULT_AGENTS),
        help="Comma-separated agents (default: risk_agent,tax_agent)",
    )
    ap.add_argument("--max-per-agent", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    dry = not args.apply
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    report = enqueue(agents=agents, dry_run=dry, max_per_agent=args.max_per_agent)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        c = report.get("counts") or {}
        print(
            f"holdings agent enqueue: enqueued={c.get('enqueued')} "
            f"fresh_skip={c.get('skipped_fresh')} queued_skip={c.get('skipped_queued')} "
            f"errors={c.get('errors')} dry_run={report.get('dry_run')}"
        )
        print(f"  report: {report.get('report_path')}")
    return 0 if report.get("ok") and not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
