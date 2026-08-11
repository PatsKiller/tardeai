#!/usr/bin/env python3
"""Run / report Advisory Desk Phase 5 shadow sessions.

Usage:
  .venv/bin/python scripts/advisory_shadow_session.py --once
  .venv/bin/python scripts/advisory_shadow_session.py --once --live   # ADVISORY_DESK_V1 Flash/Pro
  .venv/bin/python scripts/advisory_shadow_session.py --status
  .venv/bin/python scripts/advisory_shadow_session.py --specialists-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Run one shadow session")
    ap.add_argument("--live", action="store_true", help="Enable ADVISORY_DESK_V1 paid Flash/Pro")
    ap.add_argument("--status", action="store_true", help="Print scoreboard")
    ap.add_argument("--specialists-only", action="store_true", help="Guardian/Ledger/Steph only")
    ap.add_argument("--max-rows", type=int, default=10)
    ap.add_argument("--budget", type=float, default=0.05)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.status or (not args.once and not args.specialists_only):
        from lib.advisory.shadow_session import scoreboard_status, rebuild_scoreboard
        board = rebuild_scoreboard() if args.once is False and args.status else scoreboard_status()
        if not args.status and not args.once and not args.specialists_only:
            board = rebuild_scoreboard()
        print(json.dumps(board, indent=2, default=str) if args.json else _fmt_board(board))
        if not args.once and not args.specialists_only:
            return 0

    if args.specialists_only:
        from lib.advisory.specialist_shadow import run_all_specialists
        r = run_all_specialists(session_id="manual")
        print(json.dumps({
            "ok": r.get("ok"),
            "contradictions": r.get("contradictions"),
            "guardian": (r.get("guardian") or {}).get("artifact_id"),
            "ledger": (r.get("ledger") or {}).get("artifact_id"),
            "steph": (r.get("steph") or {}).get("artifact_id"),
            "deepseek_on_tax_lane": r.get("deepseek_on_tax_lane"),
        }, indent=2))
        return 0 if r.get("ok") else 1

    if args.once:
        from lib.advisory.shadow_session import run_shadow_session
        rec = run_shadow_session(
            live_llm=args.live,
            max_rows=args.max_rows,
            budget_usd=args.budget,
            run_specialists=True,
        )
        if args.json:
            # drop large hash list for readability unless wanted
            slim = {k: v for k, v in rec.items() if k != "row_hashes"}
            print(json.dumps(slim, indent=2, default=str))
        else:
            g = rec.get("gates") or {}
            sb = rec.get("scoreboard") or {}
            print(
                f"session {rec.get('session_id')} pass={g.get('session_pass')} "
                f"live={g.get('live_llm')} spend=${g.get('spend_usd')} "
                f"changed={((rec.get('metrics') or {}).get('changed_rows'))} "
                f"progress={sb.get('sessions_passed')}/{sb.get('target')} "
                f"specialists_ok={((rec.get('specialists') or {}).get('ok'))}"
            )
        return 0 if (rec.get("gates") or {}).get("session_pass") else 1

    return 0


def _fmt_board(b: dict) -> str:
    u = b.get("useful_rate") or {}
    return (
        f"Phase 5/7 scoreboard\n"
        f"  sessions: {b.get('sessions_passed')}/{b.get('sessions_completed')} passed "
        f"(P5 target {b.get('target')}, remaining {b.get('remaining_sessions')})\n"
        f"  consecutive_passes: {b.get('consecutive_passes')} "
        f"(P7 need {b.get('promotion_target')}, remaining {b.get('remaining_promotion_sessions')})\n"
        f"  median_changed_rows: {b.get('median_changed_rows')}\n"
        f"  mean_spend_usd: {b.get('mean_spend_usd')}\n"
        f"  useful_rate: {u.get('useful_rate')} (n={u.get('n')}, meets_60%={u.get('meets_60pct')})\n"
        f"  indefensible_WRONG_FACT: {u.get('indefensible_wrong_fact')}\n"
        f"  specialist_artifacts: {b.get('specialist_artifacts_on_disk')}\n"
        f"  phase5_ready: {b.get('phase5_ready')}  phase7_streak_met: {b.get('phase7_streak_met')}\n"
        f"  promotion_status: {b.get('promotion_status')}  morning_path_default: {b.get('morning_path_default')}\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
