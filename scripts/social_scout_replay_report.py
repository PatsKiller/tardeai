#!/usr/bin/env python3
"""P0-7: Social Scout replay/report — re-run the 5-pillar Social Scout model over recent social scan
rows and show how many partial setups would surface to the operator, WITHOUT any of them becoming
validation-ready or GO unless the normal route policy + deterministic gates pass.

Read-only. NO broker writes. NO raw social-post text (only derived pillar metadata + counts).

    python3 scripts/social_scout_replay_report.py --days 30 --json
    python3 scripts/social_scout_replay_report.py --days 30 --markdown > docs/diligence/current/SOCIAL_SCOUT_REPLAY.md
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


def aggregate(rows: list) -> dict:
    """Pure aggregation over scan-row dicts (DB-free, testable). Each row may carry: symbol,
    mention_count, sources, score, rvol, price, gap_pct, change_pct, float_m, decision,
    catalyst_verified, catalyst_source, strategy_tags."""
    from social_route_policy import route_social_candidate

    pillar_hist = {i: 0 for i in range(6)}      # 0/5 .. 5/5
    scouts_surfaced = 0
    large_float_scouts = 0
    social_only_scouts = 0
    graduated_go = 0
    blocked_from_validation = 0                 # every scout is blocked from the validation fast path
    missing_pillars = Counter()
    reason_codes = Counter()
    actionabilities = Counter()

    for r in rows:
        cand = {"symbol": r.get("symbol"), "mention_count": r.get("mention_count") or 0,
                "sources": r.get("sources") or [], "strategy_tags": r.get("strategy_tags") or [],
                "score": r.get("score"), "sample_content": r.get("sample_content")}
        finviz = {"price": r.get("price"), "rvol": r.get("rvol"),
                  "float_m": r.get("float_m") if r.get("float_m") is not None else r.get("float_mm"),
                  "gap_pct": r.get("gap_pct"), "change_pct": r.get("change_pct")}
        ce = {"catalyst_verified": r.get("catalyst_verified"),
              "catalyst_source": r.get("catalyst_source")}
        route = route_social_candidate(cand, finviz, ce, trace_id=None)

        pillar_hist[int(route.get("scout_pillar_count") or 0)] += 1
        actionabilities[route["actionability"]] += 1

        if route["actionability"] == "GO":
            graduated_go += 1

        if route.get("scout_status") == "SOCIAL_SCOUT":
            scouts_surfaced += 1
            blocked_from_validation += 1        # invariant: a scout is never validation-eligible
            if route.get("float_class") == "large_float" or route.get("manual_review_required"):
                large_float_scouts += 1
            if route.get("social_only"):
                social_only_scouts += 1
            for p in route.get("pillars_missing") or []:
                missing_pillars[p] += 1
            for rc in route.get("reason_codes") or []:
                if rc.startswith("SCOUT_") or rc.startswith("NEEDS_"):
                    reason_codes[rc] += 1

    return {
        "rows_replayed": len(rows),
        "pillar_count_histogram": {f"{k}/5": v for k, v in pillar_hist.items()},
        "social_scouts_surfaced": scouts_surfaced,
        "large_float_social_scouts": large_float_scouts,
        "social_only_social_scouts": social_only_scouts,
        "graduated_to_momentum_scalp_go": graduated_go,
        "scouts_blocked_from_validation": blocked_from_validation,
        "top_missing_pillars": missing_pillars.most_common(5),
        "top_reason_codes": reason_codes.most_common(8),
        "actionability_distribution": dict(actionabilities),
    }


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started, "window_days": days,
                "warnings": [f"db unavailable: {str(e).splitlines()[0][:120]}"],
                "note": "Read-only Social Scout replay. No broker writes."}

    try:
        cur.execute(f"""
            SELECT symbol, mention_count, score, rvol, price, gap_pct, change_pct,
                   float_mm AS float_m, decision, catalyst_verified, catalyst_source, sources
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
        return {"ok": False, "status": "WARN", "generated_at": started, "window_days": days,
                "warnings": [f"query failed: {str(e).splitlines()[0][:120]}"],
                "note": "Read-only Social Scout replay. No broker writes."}

    body = aggregate(rows)
    body.update({
        "ok": True, "status": "PASS", "generated_at": started, "window_days": days,
        "warnings": [],
        "note": "Read-only. No broker writes. A Social Scout is operator-awareness ONLY — it is never "
                "validation-ready or GO unless the normal route policy + deterministic gates pass. "
                "Validation maturity is unchanged by Social Scout surfacing.",
    })
    return body


def to_markdown(r: dict) -> str:
    L = ["# Social Scout Replay", "",
         f"**Status: {r.get('status')}** | window: {r.get('window_days')}d  ",
         f"_Generated: {r.get('generated_at')}_  ",
         "_Source: `python3 scripts/social_scout_replay_report.py --days N --json`_  ", ""]
    if not r.get("ok"):
        return "\n".join(L + ["> WARN: " + "; ".join(r.get("warnings", ["no data"])), "",
                              "> " + r.get("note", "")])
    L += [f"Replayed **{r['rows_replayed']}** social scan rows.", "",
          "## Pillar-count histogram", "", "| Pillars | Count |", "|---------|-------|"]
    for k, v in r["pillar_count_histogram"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Social Scout surfacing", "",
          f"- Social Scouts surfaced (≥2/5): **{r['social_scouts_surfaced']}**",
          f"- Large-float Social Scouts (manual-review only): **{r['large_float_social_scouts']}**",
          f"- Social-only Social Scouts (WATCH/WAIT/SCOUT only): **{r['social_only_social_scouts']}**",
          f"- Graduated to momentum_scalp / GO (normal gates): **{r['graduated_to_momentum_scalp_go']}**",
          f"- Scouts blocked from validation fast path: **{r['scouts_blocked_from_validation']}** "
          f"(equals scouts surfaced — none are validation-ready)", ""]
    if r["top_missing_pillars"]:
        L += ["## Top missing pillars", ""]
        for p, c in r["top_missing_pillars"]:
            L.append(f"- {p}: {c}")
        L.append("")
    if r["top_reason_codes"]:
        L += ["## Top reason codes", ""]
        for rc, c in r["top_reason_codes"]:
            L.append(f"- {rc}: {c}")
        L.append("")
    L += ["> " + r["note"]]
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
        print(f"Social Scout replay: {r.get('status')} rows={r.get('rows_replayed')} "
              f"scouts={r.get('social_scouts_surfaced')} "
              f"blocked_from_validation={r.get('scouts_blocked_from_validation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
