#!/usr/bin/env python3
"""P1: route-policy replay — re-run route_social_candidate over recent social scalp rows.

Shows how many recent social candidates would be tradeable micro-cap momentum scalps vs
large-float manual-review scouts vs watch-only social surges vs rejected, and compares the
OLD score-only injection (score >= 25) against the NEW route-aware injection. Demonstrates
large-float scouts are RETAINED for operator review and social-only names cannot become GO.
Read-only — NO broker writes.

    python3 scripts/replay_social_route_policy.py --days 30 --json
    python3 scripts/replay_social_route_policy.py --days 30 --markdown > docs/diligence/current/SOCIAL_ROUTE_POLICY_REPLAY.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OLD_SCORE_THRESHOLD = 25


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        from db_adapter import get_connection
        from social_route_policy import route_social_candidate
        from continuous_runner import classify_social_injection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "warnings": [f"unavailable: {e}"], "note": "Read-only replay. No broker writes."}

    warnings = []
    try:
        cur.execute(f"""
            SELECT symbol, score, rvol, price, gap_pct, float_mm AS float_m, decision,
                   catalyst_verified, catalyst_source, sources
            FROM scalp_scan_results
            WHERE scanned_at > NOW() - INTERVAL '{int(days)} days'
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "status": "WARN", "generated_at": started,
                "warnings": [f"query failed: {str(e).splitlines()[0][:120]}"],
                "note": "Read-only replay. No broker writes."}

    routes = Counter()
    actionabilities = Counter()
    old_injected = 0       # OLD: score >= 25 (regardless of route/catalyst)
    new_tradeable = 0      # NEW: route-aware tradeable momentum_scalp
    new_scout = 0          # NEW: large-float manual-review scout (retained, not tradeable)
    new_watch = 0          # NEW: watch-only / not injected
    go_leak = 0            # social-only that would have been GO (must be 0)

    for r in rows:
        cand = {"symbol": r["symbol"], "mention_count": 0, "sources": r.get("sources") or [],
                "strategy_tags": []}
        finviz = {"price": r.get("price"), "rvol": r.get("rvol"),
                  "float_m": r.get("float_m"), "gap_pct": r.get("gap_pct")}
        ce = {"catalyst_verified": r.get("catalyst_verified"),
              "catalyst_source": r.get("catalyst_source")}
        route = route_social_candidate(cand, finviz, ce, trace_id=None)
        routes[route["route"]] += 1
        actionabilities[route["actionability"]] += 1

        if (r.get("score") or 0) >= OLD_SCORE_THRESHOLD:
            old_injected += 1

        inj = classify_social_injection({
            "decision": r.get("decision"), "route": route["route"],
            "route_actionability": route["actionability"], "route_strategy_id": route["strategy_id"],
            "catalyst_verified": r.get("catalyst_verified"), "rvol": r.get("rvol"),
            "float_m": r.get("float_m"), "price": r.get("price")})
        if inj.get("tradeable"):
            new_tradeable += 1
        elif inj.get("manual_review_required"):
            new_scout += 1
        else:
            new_watch += 1

        if not r.get("catalyst_verified") and route["actionability"] == "GO":
            go_leak += 1

    return {
        "ok": True,
        "status": "PASS" if not warnings else "WARN",
        "generated_at": started,
        "window_days": days,
        "rows_replayed": len(rows),
        "route_distribution": dict(routes),
        "actionability_distribution": dict(actionabilities),
        "injection_comparison": {
            "old_score_only_injected": old_injected,
            "new_tradeable_momentum_scalp": new_tradeable,
            "new_large_float_scout_retained": new_scout,
            "new_watch_only_not_injected": new_watch,
        },
        "social_only_go_leaks": go_leak,
        "large_float_scouts_retained": new_scout,
        "warnings": warnings,
        "note": "Read-only replay. No broker writes. Large-float scouts are retained for operator "
                "review (not discarded); social-only candidates can never be GO/actionable.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Social Route Policy Replay", "",
         f"**Status: {r['status']}** | window: {r.get('window_days')}d  ",
         f"_Generated: {r['generated_at']}_  ",
         "_Source: `python3 scripts/replay_social_route_policy.py --days N --json`_  ", ""]
    if not r.get("ok"):
        return "\n".join(L + ["> WARN: " + "; ".join(r.get("warnings", ["no data"]))])
    ic = r["injection_comparison"]
    L += [f"Replayed **{r['rows_replayed']}** social scan rows.", "",
          "## Route distribution", "", "| Route | Count |", "|-------|-------|"]
    for k, v in r["route_distribution"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## OLD score-only vs NEW route-aware injection", "",
          f"- OLD (score ≥ {25}) injected: **{ic['old_score_only_injected']}**",
          f"- NEW tradeable micro-cap momentum_scalp: **{ic['new_tradeable_momentum_scalp']}**",
          f"- NEW large-float scout (retained, manual review): **{ic['new_large_float_scout_retained']}**",
          f"- NEW watch-only (not injected): **{ic['new_watch_only_not_injected']}**", "",
          f"- **Social-only GO leaks: {r['social_only_go_leaks']}** (must be 0)",
          f"- **Large-float scouts retained for operator: {r['large_float_scouts_retained']}**", "",
          "> " + r["note"]]
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
        print(f"Route replay: {r.get('status')} rows={r.get('rows_replayed')} "
              f"go_leaks={r.get('social_only_go_leaks')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
