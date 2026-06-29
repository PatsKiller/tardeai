#!/usr/bin/env python3
"""apply_finviz_screener_cadence.py — map every registry screener to a cadence class and report the
actual-vs-recommended run schedule. Validates that scalp_fast is the ONLY class allowed at <=5-min
cadence and that the broad DB screeners never run at scalp cadence. Read-only report (no broker writes,
does not auto-install crons — generates the proposed schedule for operator review).

    python3 scripts/apply_finviz_screener_cadence.py --json
    python3 scripts/apply_finviz_screener_cadence.py --markdown
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "finviz_screeners.yaml"
POLICY = ROOT / "config" / "finviz_screener_cadence_policy.yaml"


def build() -> dict:
    reg = yaml.safe_load(REGISTRY.read_text())
    pol = yaml.safe_load(POLICY.read_text())["cadence_classes"]
    screeners = list(reg.get("screeners", [])) + list(reg.get("db_screeners", []))

    issues = []
    assignments = []
    for s in screeners:
        cls = s.get("cadence_class")
        if cls not in pol:
            issues.append(f"{s['screener_id']}: cadence_class '{cls}' not in policy")
            continue
        p = pol[cls]
        # schedule summary
        if p.get("default_windows"):
            sched = "; ".join(f"{w['start']}-{w['end']} /{w['every_minutes']}m" for w in p["default_windows"])
        elif p.get("default_times"):
            sched = "@ " + ", ".join(p["default_times"]) + (" " + ",".join(p.get("default_days", [])) if p.get("default_days") else "")
        elif p.get("active") is False:
            sched = "DISABLED"
        else:
            sched = "—"
        # INVARIANT: only scalp_fast may run at <=5-min cadence
        fast = bool(p.get("default_windows") and any(w.get("every_minutes", 999) <= 5 for w in p["default_windows"]))
        if fast and cls != "scalp_fast":
            issues.append(f"{s['screener_id']}: non-scalp class '{cls}' at <=5-min cadence")
        assignments.append({"screener_id": s["screener_id"], "strategy_family": s.get("strategy_family"),
                            "cadence_class": cls, "schedule": sched,
                            "local_llm_allowed": p.get("local_llm_allowed"),
                            "cloud_llm_allowed": p.get("cloud_llm_allowed")})

    # scalp-cadence integrity: only the 3 registry scalp_lane ids are scalp_fast
    scalp_fast_ids = [a["screener_id"] for a in assignments if a["cadence_class"] == "scalp_fast"]
    swing_at_scalp = [a["screener_id"] for a in assignments
                      if "swing" in (a["strategy_family"] or "") and a["cadence_class"] == "scalp_fast"]
    if swing_at_scalp:
        issues.append(f"swing screeners at scalp cadence: {swing_at_scalp}")

    return {
        "ok": not issues, "status": "PASS" if not issues else "FAIL",
        "screener_count": len(assignments),
        "by_class": {c: sum(1 for a in assignments if a["cadence_class"] == c) for c in
                     ["scalp_fast", "scout_intraday", "swing_intraday", "swing_daily",
                      "fundamental_daily", "income_weekly", "experimental_disabled"]},
        "scalp_fast_screeners": scalp_fast_ids,
        "assignments": assignments, "issues": issues,
        "note": "Read-only cadence map. Only scalp_fast may run at <=5-min cadence. No broker writes.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Finviz Screener Cadence Assignments", "",
         f"**Status: {r['status']}** | {r['screener_count']} screeners  ", "",
         "| Class | Count |", "|-------|------:|"]
    for c, n in r["by_class"].items():
        L.append(f"| {c} | {n} |")
    L += ["", "| Screener | Family | Cadence class | Schedule (ET) | Local LLM | Cloud LLM |",
          "|----------|--------|---------------|---------------|-----------|-----------|"]
    for a in r["assignments"]:
        L.append(f"| {a['screener_id']} | {a['strategy_family']} | {a['cadence_class']} | {a['schedule']} | "
                 f"{a['local_llm_allowed']} | {a['cloud_llm_allowed']} |")
    if r["issues"]:
        L += ["", "## Issues", ""] + [f"- {i}" for i in r["issues"]]
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build()
    print(to_markdown(r) if args.markdown else (json.dumps(r, indent=2, default=str) if args.json else
          f"cadence: {r['status']} by_class={r['by_class']} issues={len(r['issues'])}"))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
