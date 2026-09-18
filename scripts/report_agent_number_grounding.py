#!/usr/bin/env python3
"""report_agent_number_grounding.py — how often do agent answers state numbers they were not given?

Read-only. Every agent-job result written since 2026-09-13 carries a
`number_grounding` report in watchlist_agent_results.full_result (rule G0,
lib/agent_number_grounding.py). The check ENFORCES by default: an ungrounded
answer is demoted to RESEARCH_MORE below the 40 % confidence gate. A dry run over
300 stored results put the demotion rate at no more than 3/300. This report is
the live measurement; AGENT_NUMBER_GROUNDING_MODE=record flags without changing
anything if the live rate is ever not sane.

USAGE
    python scripts/report_agent_number_grounding.py              # last 7 days
    python scripts/report_agent_number_grounding.py --days 14 --json

Reading the output: a flagged share in low single digits per agent, with the
top unsupported tokens being genuinely absent figures, is the check working. A
high share dominated by one token pattern is a checker gap: switch to record
and fix the checker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJ = Path(__file__).resolve().parent.parent


def summarize(rows: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """rows: (agent, full_result as dict or JSON text). Pure."""
    per: dict[str, Counter] = defaultdict(Counter)
    tokens: dict[str, Counter] = defaultdict(Counter)
    for agent, full in rows:
        if isinstance(full, str):
            try:
                full = json.loads(full)
            except ValueError:
                continue
        rep = (full or {}).get("number_grounding") if isinstance(full, dict) else None
        if not isinstance(rep, dict):
            continue
        a = str(agent or "unknown")
        per[a]["results"] += 1
        verdict = str(rep.get("verdict") or "unknown")
        per[a][verdict] += 1
        if rep.get("demoted"):
            per[a]["demoted"] += 1
        # Honesty: historical rows used verdict=grounded while still listing
        # unsupported tokens. Count those as soft_unsupported for the report.
        unsupported = list(rep.get("unsupported") or [])
        if verdict == "soft_unsupported" or (verdict == "grounded" and unsupported):
            per[a]["soft_unsupported"] += 1
        for tok in unsupported:
            tokens[a][str(tok)] += 1
    agents = {}
    for a, c in sorted(per.items()):
        n = c["results"]
        soft = c["soft_unsupported"]
        agents[a] = {
            "results": n,
            "ungrounded": c["ungrounded"],
            "ungrounded_share": round(c["ungrounded"] / n, 3) if n else 0.0,
            "soft_unsupported": soft,
            "soft_unsupported_share": round(soft / n, 3) if n else 0.0,
            "grounded": c["grounded"],
            "no_numbers": c["no_numbers"],
            "not_checked": c["not_checked"],
            "demoted": c["demoted"],
            "top_unsupported": tokens[a].most_common(10),
        }
    total = sum(v["results"] for v in agents.values())
    flagged = sum(v["ungrounded"] for v in agents.values())
    soft_all = sum(v["soft_unsupported"] for v in agents.values())
    return {
        "schema": "AgentNumberGroundingReport@v1",
        "results": total,
        "ungrounded": flagged,
        "ungrounded_share": round(flagged / total, 3) if total else 0.0,
        "soft_unsupported": soft_all,
        "soft_unsupported_share": round(soft_all / total, 3) if total else 0.0,
        "agents": agents,
        "authority": "READ_ONLY_ADVISORY",
    }


def _db_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if os.environ.get(k)}
    if "DB_PASSWORD" not in env and (PROJ / ".env").exists():
        for line in (PROJ / ".env").read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
                    env.setdefault(k.strip(), v.strip())
    return env


def fetch(days: int) -> list[tuple[str, str]]:
    import psycopg2  # noqa: PLC0415

    env = _db_env()
    conn = psycopg2.connect(
        host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
        user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""), connect_timeout=5,
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT agent, full_result::text FROM watchlist_agent_results "
                "WHERE created_at > NOW() - (%s * INTERVAL '1 day') "
                "AND full_result::text LIKE %s",
                [int(days), "%number_grounding%"],
            )
            return [(r[0], r[1]) for r in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = summarize(fetch(args.days))
    report["days"] = args.days
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"Agent number grounding, last {args.days} days: "
          f"{report['ungrounded']}/{report['results']} ungrounded/demotion-bar "
          f"({report['ungrounded_share']:.0%}); "
          f"{report.get('soft_unsupported', 0)} soft_unsupported "
          f"({report.get('soft_unsupported_share', 0):.0%})")
    for a, v in report["agents"].items():
        top = ", ".join(f"{t} x{n}" for t, n in v["top_unsupported"][:5]) or "none"
        print(f"  {a:<12} {v['ungrounded']:>4}/{v['results']:<4} ungrounded ({v['ungrounded_share']:.0%}), "
              f"soft {v.get('soft_unsupported', 0)}, demoted {v['demoted']}; top unsupported: {top}")
    if not report["results"]:
        print("  No checked results yet: the check writes its report as agent jobs complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
