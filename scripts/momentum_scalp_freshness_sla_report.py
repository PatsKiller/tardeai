#!/usr/bin/env python3
"""P1: momentum_scalp freshness SLA + conversion-miss report.

Separates stale-quote approval failures from TTL expiries, reports stage latency (median/p95),
and estimates how many proposals would have been eligible if ATM had run within 1 / 3 / 5
minutes of proposal creation. Read-only — NO broker writes. Missing tables degrade to WARN.

    python3 scripts/momentum_scalp_freshness_sla_report.py --days 30 --json
    python3 scripts/momentum_scalp_freshness_sla_report.py --days 30 --markdown > docs/diligence/current/MOMENTUM_SCALP_FRESHNESS_SLA.md
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
QUOTE_FRESH_MAX_MIN = 15.0


def _pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
    return round(vals[k], 2)


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    warnings = []
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "warnings": [f"no database: {e}"], "note": "Read-only SLA report. No broker writes."}

    since = f"NOW() - INTERVAL '{int(days)} days'"

    # Latency: proposal created_at → first ATM decision (decided_at).
    latencies = []
    try:
        cur.execute(f"""
            SELECT EXTRACT(EPOCH FROM (MIN(a.decided_at) - p.created_at))/60.0 AS latency_min
            FROM paper_trade_proposals p
            JOIN atm_decision_log a ON a.proposal_id = p.id
            WHERE p.strategy_id='momentum_scalp' AND p.created_at > {since}
            GROUP BY p.id, p.created_at
        """)
        latencies = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        warnings.append(f"latency: {str(e).splitlines()[0][:100]}")

    # Stale-quote failures vs TTL expiries (from failure-reason text / expiry reason).
    stale_quote_fails, ttl_expiries, quote_ages = 0, 0, []
    try:
        cur.execute(f"""SELECT atm_last_failure_reason, atm_expiry_reason
                        FROM paper_trade_proposals
                        WHERE strategy_id='momentum_scalp' AND created_at > {since}""")
        for fr, er in cur.fetchall():
            fr = fr or ""
            if "quote" in fr.lower() and ("old" in fr.lower() or "stale" in fr.lower()):
                stale_quote_fails += 1
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*min", fr)
                if m:
                    quote_ages.append(float(m.group(1)))
            if er in ("intraday_ttl_expired",) or "ttl" in (er or "").lower():
                ttl_expiries += 1
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        warnings.append(f"failure_reasons: {str(e).splitlines()[0][:100]}")

    # Fast-path eligibility: how many proposals would have SUBMITTED to paper if the deterministic
    # FAST-PATH (not the approval queue) ran within N minutes of proposal creation, keeping the quote
    # inside the freshness window. A proposal whose first-evaluation latency exceeded N minutes was
    # missed by slow timing; running the fast-path within N min would have kept it fresh.
    cadence = {}
    for n in (1, 3, 5):
        missed = sum(1 for l in latencies if l > n)
        eligible_if_fast = sum(1 for l in latencies if l <= n)
        cadence[f"within_{n}_min"] = {"would_submit_if_fast_path_ran": eligible_if_fast,
                                      "missed_by_slow_timing": missed}

    status = "PASS" if not warnings else "WARN"
    return {
        "ok": True,
        "status": status,
        "generated_at": started,
        "window_days": days,
        "latency_created_to_first_atm_min": {
            "n": len(latencies),
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "p95": _pct(latencies, 95),
            "max": round(max(latencies), 2) if latencies else None,
        },
        "failure_breakdown": {
            "stale_quote_failures": stale_quote_fails,
            "ttl_expiries": ttl_expiries,
            "quote_age_at_failure_min": {
                "n": len(quote_ages),
                "median": round(statistics.median(quote_ages), 1) if quote_ages else None,
                "p95": _pct(quote_ages, 95),
            },
            "freshness_window_min": QUOTE_FRESH_MAX_MIN,
        },
        "fast_path_timing_eligibility": cadence,
        "paper_approval_required": False,
        "warnings": warnings,
        "note": "Read-only SLA report. No broker writes. Stale-quote failures are an OPERATIONAL "
                "timing gap — the freshness gate is correct and must NOT be weakened. The fix is "
                "running the deterministic paper fast-path promptly (no human paper approval), not "
                "approving faster. Live trading is unchanged (operator confirmation + 2FA).",
    }


def to_markdown(r: dict) -> str:
    L = ["# Momentum Scalp Freshness SLA", "",
         f"**Status: {r['status']}** | window: {r.get('window_days')}d  ",
         f"_Generated: {r['generated_at']}_  ",
         "_Source: `python3 scripts/momentum_scalp_freshness_sla_report.py --days N --json`_  ", ""]
    if not r.get("ok"):
        return "\n".join(L + ["> WARN: " + "; ".join(r.get("warnings", ["no data"]))])
    lat = r["latency_created_to_first_atm_min"]
    fb = r["failure_breakdown"]
    L += [f"## Latency created → first ATM ({lat['n']} proposals)", "",
          f"- median **{lat['median']} min** · p95 **{lat['p95']} min** · max {lat['max']} min", "",
          "## Failure breakdown", "",
          f"- **Stale-quote failures: {fb['stale_quote_failures']}** "
          f"(median quote age at failure: {fb['quote_age_at_failure_min']['median']} min, "
          f"freshness window {fb['freshness_window_min']} min)",
          f"- **TTL expiries: {fb['ttl_expiries']}**", "",
          "## Fast-path timing eligibility (deterministic paper fast-path, NO approval)", "",
          "| If fast-path ran within | Would submit to paper | Missed by slow timing |",
          "|------|------|------|"]
    for k, v in r["fast_path_timing_eligibility"].items():
        L.append(f"| {k.replace('_',' ')} | {v['would_submit_if_fast_path_ran']} | {v['missed_by_slow_timing']} |")
    if r.get("warnings"):
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build(args.days)
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Freshness SLA: {r.get('status')} stale_quote={r.get('failure_breakdown',{}).get('stale_quote_failures')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
