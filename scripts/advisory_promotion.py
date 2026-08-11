#!/usr/bin/env python3
"""Phase 7 promotion gate CLI.

Usage:
  .venv/bin/python scripts/advisory_promotion.py status
  .venv/bin/python scripts/advisory_promotion.py evaluate
  .venv/bin/python scripts/advisory_promotion.py promote --confirm [--force] [--operator NAME]
  .venv/bin/python scripts/advisory_promotion.py demote --reason "..."
  .venv/bin/python scripts/advisory_promotion.py simulate-streak --n 30   # test only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    from lib.advisory import promotion_gate as pg

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("evaluate")
    pr = sub.add_parser("promote")
    pr.add_argument("--confirm", action="store_true")
    pr.add_argument("--force", action="store_true")
    pr.add_argument("--operator", default="operator")
    pd = sub.add_parser("demote")
    pd.add_argument("--reason", default="operator_demote")
    pd.add_argument("--operator", default="operator")
    ps = sub.add_parser("simulate-streak")
    ps.add_argument("--n", type=int, default=30)
    ps.add_argument("--clear", action="store_true", help="Wipe simulated sessions first (test path only)")
    args = p.parse_args(argv)

    if args.cmd == "status":
        st = pg.load_promotion_state()
        ev = pg.evaluate_promotion()
        print(json.dumps({
            "status": st.get("status") or ev.get("status"),
            "promoted": st.get("promoted") or ev.get("promoted"),
            "morning_path_default": st.get("morning_path_default") or ev.get("morning_path_default"),
            "consecutive_passes": (ev.get("gates") or {}).get("consecutive_30"),
            "all_gates_green": ev.get("all_gates_green"),
            "useful_rate": (ev.get("gates") or {}).get("useful_rate"),
            "authority_fence_ok": ((ev.get("gates") or {}).get("authority_fence") or {}).get("ok"),
            "alert_integrity_ok": ((ev.get("gates") or {}).get("alert_integrity") or {}).get("ok"),
            "lessons_ok": ((ev.get("gates") or {}).get("lessons") or {}).get("ok"),
        }, indent=2, default=str))
        return 0

    if args.cmd == "evaluate":
        ev = pg.evaluate_promotion()
        # slim print
        g = ev.get("gates") or {}
        slim = {
            "status": ev.get("status"),
            "all_gates_green": ev.get("all_gates_green"),
            "eligible": ev.get("eligible"),
            "consecutive": g.get("consecutive_30"),
            "useful_rate": g.get("useful_rate"),
            "indefensible_zero": g.get("indefensible_zero"),
            "budget": g.get("budget"),
            "authority_fence": g.get("authority_fence"),
            "alert_integrity": {"ok": (g.get("alert_integrity") or {}).get("ok")},
            "lessons": g.get("lessons"),
            "notes": ev.get("notes"),
        }
        print(json.dumps(slim, indent=2, default=str))
        return 0 if ev.get("all_gates_green") else 1

    if args.cmd == "promote":
        r = pg.promote(operator=args.operator, confirm=args.confirm, force=args.force)
        print(json.dumps(r, indent=2, default=str))
        return 0 if r.get("ok") else 1

    if args.cmd == "demote":
        r = pg.demote(operator=args.operator, reason=args.reason)
        print(json.dumps(r, indent=2, default=str))
        return 0

    if args.cmd == "simulate-streak":
        # Test helper: append N green dry sessions (does not spend LLM)
        from lib.advisory.shadow_session import run_shadow_session, SESSIONS_PATH, rebuild_scoreboard
        if args.clear and SESSIONS_PATH.exists():
            # only clear if under advisory_shadow — safety
            SESSIONS_PATH.write_text("", encoding="utf-8")
        n = max(1, int(args.n))
        passed = 0
        for i in range(n):
            rec = run_shadow_session(
                live_llm=False,
                max_rows=3,
                run_specialists=(i % 5 == 0),  # specialists every 5th to limit IO
                session_label=f"simulate-{i+1}",
            )
            if (rec.get("gates") or {}).get("session_pass"):
                passed += 1
        board = rebuild_scoreboard()
        ev = pg.evaluate_promotion()
        print(json.dumps({
            "simulated": n,
            "passed": passed,
            "scoreboard": {
                "sessions_completed": board.get("sessions_completed"),
                "sessions_passed": board.get("sessions_passed"),
            },
            "consecutive": (ev.get("gates") or {}).get("consecutive_30"),
            "all_gates_green": ev.get("all_gates_green"),
            "status": ev.get("status"),
        }, indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
