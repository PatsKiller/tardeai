#!/usr/bin/env python3
"""cio_full_cycle_dryrun.py — Phase 9/10 full-system integration dry-run CLI.

Runs one autonomous advisory cycle end-to-end (wake → snapshot → specialists →
synthesis → capital plan → report v2 → office home → disposition → outcome
learning) and prints the complete evidence spine + store integrity + learning.

Modes:
  --sandbox (default)  self-contained run in a fresh temp directory.
  --store-dir PATH     run against a specific store directory.
  --live               run against the canonical data/cio/*.jsonl stores.

Every mode is READ_ONLY_ADVISORY: it never touches a broker, order, stop, 2FA,
or provider, and produces no execution authority. The --live mode appends
advisory events to the canonical event stores exactly as the production cron
would, but using deterministic dry-run fixtures for inputs.

Examples:
  python3 scripts/cio_full_cycle_dryrun.py
  python3 scripts/cio_full_cycle_dryrun.py --disposition ACCEPTED --rating 4
  python3 scripts/cio_full_cycle_dryrun.py --disposition REJECTED --outcome-status NEGATIVE \\
      --wrong "Overweighted energy" --symbol XOM
  python3 scripts/cio_full_cycle_dryrun.py --json
  python3 scripts/cio_full_cycle_dryrun.py --live
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_full_cycle import run_full_cycle  # noqa: E402

CANONICAL_STORE_DIR = ROOT / "data" / "cio"


def _fmt_usd(v: object) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def render_text(res: dict) -> str:
    lines: list[str] = []
    spine = res.get("spine") or {}
    integrity = res.get("integrity") or {}
    office_home = res.get("office_home") or {}
    capital_plan = res.get("capital_plan") or {}
    report_v2 = res.get("report_v2") or {}

    lines.append("=" * 72)
    lines.append("TRADE AI — Phase 9 full-system integration dry-run")
    lines.append("=" * 72)
    lines.append(f"authority      : {res.get('authority', '—')}")
    lines.append(f"ok             : {res.get('ok')}")
    lines.append(f"run_id         : {spine.get('run_id', '—')}")
    lines.append(f"wake_job_id    : {spine.get('wake_job_id', '—')}")
    lines.append(f"pass1 / pass2  : {res.get('pass1_status', '—')} / {res.get('pass2_status', '—')}")
    lines.append(f"store_dir      : {res.get('store_dir', '—')}")
    lines.append("")

    lines.append("─ Evidence spine ─" + "─" * 53)
    lines.append(f"  snapshot_id     : {spine.get('snapshot_id', '—')}")
    lines.append(f"  handoffs        : {len(spine.get('handoff_ids') or [])} routed")
    lines.append(f"  decision_id     : {spine.get('decision_id') or '—'}")
    lines.append(f"  decision        : {spine.get('decision_position') or '—'}")
    lines.append(f"  action_ids      : {len(spine.get('action_ids') or [])}")
    lines.append(f"  notification_ids: {len(spine.get('notification_ids') or [])}")
    disp = spine.get("disposition") or {}
    lines.append(
        f"  disposition     : {disp.get('operator_disposition') or '—'}"
        + (f" (rating {disp.get('rating')})" if disp.get("rating") else "")
    )
    lines.append("")

    lines.append("─ Integrity checks ─" + "─" * 50)
    for c in integrity.get("checks") or []:
        mark = "PASS" if c["ok"] else "FAIL"
        lines.append(f"  [{mark}] {c['name']:<34} {c['detail']}")
    for n in integrity.get("notes") or []:
        mark = "note" if n["ok"] else "info"
        lines.append(f"  [{mark}] {n['name']:<34} {n['detail']}")
    lines.append(
        f"  result: {integrity.get('passed_count', 0)}/{integrity.get('total_count', 0)} passed"
    )
    lines.append("")

    lines.append("─ Downstream composition (Phases 6/7/8) ─" + "─" * 29)
    lines.append(f"  office_home sections : {', '.join(sorted(office_home.keys()))}")
    lines.append(f"  capital_plan cash    : {_fmt_usd(capital_plan.get('cash_total_usd'))}")
    lines.append(f"  report_v2 rendered   : {bool(report_v2.get('html'))}")
    coverage = report_v2.get("coverage") or {}
    lines.append(f"  report coverage      : {coverage.get('source_traceability_pct', '—')}")
    lines.append("")

    learning = res.get("learning") or {}
    lines.append("─ Outcome learning (Phase 10) ─" + "─" * 41)
    lines.append(f"  signal          : {learning.get('signal') or '—'}")
    lines.append(f"  candidates      : {learning.get('candidate_count', 0)}")
    for c in (learning.get("candidates") or []):
        p = c.get("payload") or {}
        lines.append(f"    · {p.get('lesson_title', '—')}  [{p.get('proposed_effect', '—')}]")
    lines.append(f"  writebacks      : {learning.get('writeback_count', 0)}")
    for wb in (learning.get("writebacks") or []):
        lines.append(
            f"    · {wb.get('factor')} {wb.get('symbol', '—')} "
            f"{wb.get('realized_outcome') or wb.get('options_edge') or wb.get('score') or '—'} "
            f"({wb.get('evidence_class', '—')})"
        )
    cal = learning.get("calibration") or {}
    cal_gates = cal.get("gates") or {}
    if cal_gates:
        for f, g in cal_gates.items():
            lines.append(
                f"    · {f}: base={g.get('base_weight')} eff={g.get('effective_weight')} "
                f"n={g.get('n')}/{g.get('n_min')} trusted={g.get('trusted')} ({g.get('evidence_class')})"
            )
    else:
        lines.append("    · (no reverse samples — all factors damped to zero)")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 9 full-system integration dry-run")
    parser.add_argument("--sandbox", action="store_true", help="run in a fresh temp dir (default)")
    parser.add_argument("--live", action="store_true", help="run against canonical data/cio stores")
    parser.add_argument("--store-dir", type=str, default=None, help="run against a specific store dir")
    parser.add_argument("--disposition", type=str, default="ACKNOWLEDGED",
                        help="operator disposition (ACKNOWLEDGED/ACCEPTED/DEFERRED/REJECTED/DONE)")
    parser.add_argument("--rating", type=int, default=None, help="operator rating (1-5)")
    parser.add_argument("--note", type=str, default="", help="operator note")
    parser.add_argument("--outcome-status", type=str, default="UNKNOWN",
                        help="measured outcome status (POSITIVE/NEGATIVE/MIXED/UNKNOWN/NOT_MEASURABLE)")
    parser.add_argument("--right", type=str, default="", help="what went right (drives retrieval learning)")
    parser.add_argument("--wrong", type=str, default="", help="what went wrong (drives calibration learning)")
    parser.add_argument("--unknowns", type=str, default="", help="open questions (drives research checklist)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="symbol to fold a reverse writeback onto (default: first holding)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    if args.live and args.store_dir:
        print("--live and --store-dir are mutually exclusive", file=sys.stderr)
        return 2

    store_dir: Path | None
    if args.live:
        store_dir = CANONICAL_STORE_DIR
        print(f"[live] targeting canonical stores: {store_dir}", file=sys.stderr)
    elif args.store_dir:
        store_dir = Path(args.store_dir)
    elif args.sandbox or True:
        store_dir = Path(tempfile.mkdtemp(prefix="cio_full_cycle_"))

    res = run_full_cycle(
        store_dir=store_dir,
        disposition=args.disposition,
        rating=args.rating,
        note=args.note,
        outcome_status=args.outcome_status,
        what_was_right=args.right,
        what_was_wrong=args.wrong,
        unknowns=args.unknowns,
        outcome_symbol=args.symbol,
        now=datetime.now(timezone.utc),
    )

    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(render_text(res))

    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
