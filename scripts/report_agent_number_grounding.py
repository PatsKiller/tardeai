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


def _confidence_shaped_token(tok: str) -> bool:
    """Bare 0–1 decimals (risk/score/prob) are not inventable market facts.

    Stored ``number_grounding`` rows written before the 2026-09-19 confidence
    exemption still list 0.85 / 0.95 as unsupported. The live checker no longer
    does; the SLO report must apply the same policy when aggregating stored
    tokens, or soft-share stays permanently FAIL on historical rows.
    """
    s = str(tok or "").strip()
    if not s or s.startswith("$") or "%" in s:
        return False
    if "." not in s:
        return False
    try:
        v = float(s.replace(",", ""))
    except ValueError:
        return False
    return 0.0 <= v <= 1.0


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
        # Keep verdict tallies under a prefix so soft_unsupported verdict rows
        # do not collide with the soft_flag metric key (pre-fix double-count).
        per[a][f"v:{verdict}"] += 1
        if rep.get("demoted"):
            per[a]["demoted"] += 1
        # Soft-share keys on the current checker vocabulary:
        # soft_unsupported (honesty, no demotion). Current checker never emits
        # grounded with a non-empty unsupported list — that dual-state is a
        # pre-soft_unsupported schema. Counting those residuals as soft made
        # soft_share permanently FAIL (~0.22) on stale rows while live policy
        # already labels the same case soft_unsupported. Track the stale
        # dual-state separately; do not inflate soft_flag with it.
        remaining = [
            str(tok)
            for tok in (rep.get("unsupported") or [])
            if not _confidence_shaped_token(str(tok))
        ]
        if verdict == "soft_unsupported" and remaining:
            per[a]["soft_flag"] += 1
            for tok in remaining:
                tokens[a][tok] += 1
        elif verdict == "grounded" and remaining:
            per[a]["stale_grounded_residual"] += 1
        elif remaining:
            for tok in remaining:
                tokens[a][tok] += 1
    agents = {}
    for a, c in sorted(per.items()):
        n = c["results"]
        soft = c["soft_flag"]
        ungrounded = c["v:ungrounded"]
        agents[a] = {
            "results": n,
            "ungrounded": ungrounded,
            "ungrounded_share": round(ungrounded / n, 3) if n else 0.0,
            "soft_unsupported": soft,
            "soft_unsupported_share": round(soft / n, 3) if n else 0.0,
            "stale_grounded_residual": int(c["stale_grounded_residual"]),
            "grounded": c["v:grounded"],
            "no_numbers": c["v:no_numbers"],
            "not_checked": c["v:not_checked"],
            "demoted": c["demoted"],
            "top_unsupported": tokens[a].most_common(10),
        }
    total = sum(v["results"] for v in agents.values())
    flagged = sum(v["ungrounded"] for v in agents.values())
    soft_all = sum(v["soft_unsupported"] for v in agents.values())
    stale_all = sum(v["stale_grounded_residual"] for v in agents.values())
    return {
        "schema": "AgentNumberGroundingReport@v1",
        "results": total,
        "ungrounded": flagged,
        "ungrounded_share": round(flagged / total, 3) if total else 0.0,
        "soft_unsupported": soft_all,
        "soft_unsupported_share": round(soft_all / total, 3) if total else 0.0,
        "stale_grounded_residual": stale_all,
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


def evaluate_slo(report: dict[str, Any], slo_path: Path | None = None) -> dict[str, Any]:
    """Compare a report to config/agent_number_grounding_slo.json. Pure."""
    path = slo_path or (PROJ / "config" / "agent_number_grounding_slo.json")
    slo = json.loads(path.read_text(encoding="utf-8"))
    floors = slo.get("floors") or {}
    min_n = int(floors.get("min_results_for_slo", 20))
    n = int(report.get("results") or 0)
    out: dict[str, Any] = {
        "schema": "AgentNumberGroundingSLOEval@v1",
        "slo_path": str(path),
        "slo_status": slo.get("status"),
        "results": n,
        "min_results_for_slo": min_n,
    }
    if n < min_n:
        out["verdict"] = "UNKNOWN"
        out["reason"] = "insufficient_results"
        out["ok"] = True  # do not invent red/green
        return out
    max_u = float(floors.get("max_ungrounded_share", 0.05))
    max_s = float(floors.get("max_soft_unsupported_share", 0.15))
    u = float(report.get("ungrounded_share") or 0.0)
    s = float(report.get("soft_unsupported_share") or 0.0)
    breaches = []
    if u > max_u:
        breaches.append(f"ungrounded_share {u:.4f} > {max_u}")
    if s > max_s:
        breaches.append(f"soft_unsupported_share {s:.4f} > {max_s}")
    out["ungrounded_share"] = u
    out["soft_unsupported_share"] = s
    out["breaches"] = breaches
    out["verdict"] = "PASS" if not breaches else "FAIL"
    out["ok"] = not breaches
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--check-slo",
        action="store_true",
        help="exit 1 when SLO floors are breached (UNKNOWN if too few rows)",
    )
    ap.add_argument(
        "--slo-config",
        type=Path,
        default=None,
        help="override path to agent_number_grounding_slo.json",
    )
    args = ap.parse_args()
    report = summarize(fetch(args.days))
    report["days"] = args.days
    slo_eval = None
    if args.check_slo:
        slo_eval = evaluate_slo(report, args.slo_config)
        report["slo"] = slo_eval
    if args.json:
        print(json.dumps(report, indent=2))
    else:
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
        if slo_eval is not None:
            detail = slo_eval.get("reason") or ", ".join(slo_eval.get("breaches") or ["ok"])
            print(f"SLO: {slo_eval['verdict']} ({detail})")
    if args.check_slo and slo_eval is not None and not slo_eval.get("ok", True):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
