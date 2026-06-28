#!/usr/bin/env python3
"""P1: momentum_scalp validation-sample tracker.

Tracks progress toward the validation gate (≥30 closed paper trades, ≥50% win rate,
≥1.3 profit factor, ≥6 calendar months, human approval) using ONLY conservatively
confirmed momentum_scalp paper trades (scalp_trade_attribution). When the confirmed
count is zero it says so plainly and never claims live-readiness. Read-only; no writes.

    python3 scripts/momentum_scalp_validation_tracker.py --json
    python3 scripts/momentum_scalp_validation_tracker.py --markdown > docs/diligence/current/MOMENTUM_SCALP_VALIDATION_TRACKER.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

GATE = {"min_closed_paper_trades": 30, "min_win_rate": 0.50,
        "min_profit_factor": 1.30, "min_calendar_months": 6, "human_approval_required": True}


def build() -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        from db_adapter import get_connection
        import scalp_trade_attribution as attr_mod
        conn = get_connection()
        attr = attr_mod.attribute(conn)
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "note": f"no database / attribution unavailable: {e}",
                "confirmed_closed": None, "gate_met": False, "live_ready": False}

    if not attr.get("ok"):
        return {"ok": False, "status": "WARN", "generated_at": started,
                "note": attr.get("note", "attribution unavailable"),
                "confirmed_closed": None, "gate_met": False, "live_ready": False}

    closed = attr["confirmed_closed"]
    win_rate = attr.get("confirmed_win_rate")
    pf = attr.get("confirmed_profit_factor")

    # Calendar-month span of confirmed closed trades (from attribution chains is not enough; query span).
    months = None
    try:
        cur = conn.cursor()
        ids = attr.get("confirmed_trade_ids") or []
        if ids:
            cur.execute("SELECT MIN(entry_time), MAX(entry_time) FROM paper_trades WHERE id = ANY(%s)", (ids,))
            lo, hi = cur.fetchone()
            if lo and hi:
                months = round((hi - lo).days / 30.0, 2)
    except Exception:
        months = None

    progress = {
        "closed_paper_trades": {"have": closed, "need": GATE["min_closed_paper_trades"],
                                "met": closed >= GATE["min_closed_paper_trades"]},
        "win_rate": {"have": win_rate, "need": GATE["min_win_rate"],
                     "met": win_rate is not None and win_rate >= GATE["min_win_rate"]},
        "profit_factor": {"have": pf, "need": GATE["min_profit_factor"],
                          "met": pf is not None and pf >= GATE["min_profit_factor"]},
        "calendar_months": {"have": months, "need": GATE["min_calendar_months"],
                            "met": months is not None and months >= GATE["min_calendar_months"]},
        "human_approval": {"have": False, "need": True, "met": False},
    }
    gate_met = all(p["met"] for p in progress.values())

    if closed == 0:
        headline = "No confirmed sample yet — 0 confirmed closed momentum_scalp paper trades."
    else:
        headline = (f"{closed}/{GATE['min_closed_paper_trades']} confirmed closed paper trades "
                    f"(win {win_rate}, PF {pf}). Sample insufficient — still TESTING.")

    return {
        "ok": True,
        "status": "PASS",
        "generated_at": started,
        "operator_correction": "Counts use conservative confirmed attribution only "
                               "(scalp_trade_attribution); ambiguous/non-executed rows excluded.",
        "confirmed_closed": closed,
        "confirmed_winners": attr.get("confirmed_winners"),
        "win_rate": win_rate,
        "profit_factor": pf,
        "calendar_months_observed": months,
        "confirmed_trade_ids": attr.get("confirmed_trade_ids"),
        "ambiguous_excluded": attr.get("ambiguous_trade_ids"),
        "non_executed_excluded": attr.get("non_executed_count"),
        "progress": progress,
        "gate": GATE,
        "gate_met": gate_met,
        "live_ready": False,
        "headline": headline,
        "next_actions": [
            "Ensure the in-window momentum_scalp paper path converts (see "
            "diagnose_momentum_scalp_paper_path.py).",
            "Collect confirmed closed paper trades toward the 30-trade / 6-month gate.",
            "Do NOT promote to live; per-order operator confirmation / 2FA remains required and is "
            "out of scope.",
        ],
        "note": "Read-only. No broker writes. LLMs advisory only.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Momentum Scalp Validation Tracker", "",
         f"**Status: {r['status']}** | gate met: **{r.get('gate_met')}** | live-ready: **{r.get('live_ready')}**  ",
         f"_Generated: {r['generated_at']}_  ",
         "_Source: `python3 scripts/momentum_scalp_validation_tracker.py --json`_  ", ""]
    if not r.get("ok"):
        return "\n".join(L + ["", "> WARN: " + r.get("note", "unavailable")])
    L += [f"> {r.get('operator_correction','')}", "", f"**{r['headline']}**", "",
          f"Confirmed trade IDs: {r.get('confirmed_trade_ids')} "
          f"(excluded ambiguous {r.get('ambiguous_excluded')}, "
          f"{r.get('non_executed_excluded')} non-executed).", "",
          "| Criterion | Have | Need | Met |", "|-----------|------|------|-----|"]
    for k, p in r["progress"].items():
        L.append(f"| {k} | {p['have']} | {p['need']} | {p['met']} |")
    L += ["", "## Next actions", ""] + [f"- {a}" for a in r.get("next_actions", [])]
    L += ["", "> " + r.get("note", "")]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--out", default="data/runtime/momentum_scalp_validation_tracker_latest.json")
    args = ap.parse_args()
    r = build()
    try:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r, indent=2, default=str))
    except Exception:
        pass
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Validation tracker: gate_met={r.get('gate_met')} confirmed_closed={r.get('confirmed_closed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
