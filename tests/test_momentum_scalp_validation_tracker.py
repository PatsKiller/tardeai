#!/usr/bin/env python3
"""P1: validation tracker — zero sample reports 0/30 gate false; counts only confirmed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_validation_tracker import build, to_markdown, GATE  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    r = build()
    if not r.get("ok"):
        WARN.append("db")
        print(f"  [WARN] tracker — {r.get('note')}")
    else:
        check("gate not met on tiny/zero sample", r["gate_met"] is False)
        check("never live-ready", r["live_ready"] is False)
        check("confirmed_closed below 30", (r["confirmed_closed"] or 0) < GATE["min_closed_paper_trades"])
        check("excludes ambiguous + non-executed", "ambiguous_excluded" in r and "non_executed_excluded" in r)
        check("progress tracks all 5 criteria", set(r["progress"].keys()) ==
              {"closed_paper_trades", "win_rate", "profit_factor", "calendar_months", "human_approval"})
        check("human approval not auto-met", r["progress"]["human_approval"]["met"] is False)
        check("headline honest about sample", "TESTING" in r["headline"] or "No confirmed sample" in r["headline"])
        check("next actions say do not promote live",
              any("Do NOT promote to live" in a or "do not promote" in a.lower() for a in r["next_actions"]))
        check("markdown renders", "Momentum Scalp Validation Tracker" in to_markdown(r))
        # If sample is exactly zero, headline must say "No confirmed sample yet".
        if r["confirmed_closed"] == 0:
            check("zero sample says 'No confirmed sample yet'", "No confirmed sample yet" in r["headline"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
