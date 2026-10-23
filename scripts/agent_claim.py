#!/usr/bin/env python3
"""agent_claim.py — the multi-vendor agent claim board CLI (operator-approved 2026-10-22).

Before an agent (Claude, Codex, Cursor — equal peers, no master) edits files, it claims them; before it
commits, ``check`` tells it whether another live session holds them. Store and semantics:
``scripts/lib/agent_claim_board.py`` and ``docs/ops/AGENT_CLAIM_BOARD.md``.

  claim      --task T --paths P [P ...] [--branch B] [--pr N] [--note X]
             refuse (exit 1) if any live claim of another session overlaps a path/glob; prints the holder,
             branch and since. A stale claim (no heartbeat for 2 h) is taken over and recorded.
  heartbeat  CLAIM_ID [--pr N] [--note X]          refresh; refused once taken over
  release    CLAIM_ID [--status done|abandoned] [--note X]
  list       [--json] [--all]                      live + stale by default; --all adds done/abandoned
  check      --paths P [P ...] [--no-gh] [--warn-only] [--exclude-branch B]
             exit 0 clear, 1 conflict (live claim of another session, or an open draft PR changing the
             path); --warn-only prints the same and exits 0 (the pre-commit hook mode)
  compact    --dry-run | --apply [--lane-receipt]  archive done/stale > 7 days to claims_history.jsonl, then
             remove the claim files (the archive is the durable copy)

Identity: --vendor/--session/--agent, else AGENT_CLAIM_VENDOR / AGENT_CLAIM_SESSION / AGENT_CLAIM_AGENT, else a
best-effort environment hint. Claims dir: --claims-dir, else TRADEAI_AGENT_CLAIMS_DIR, else
~/trade-ai-releases/persistent-state/data/coordination/claims/.

Exit codes: 0 ok · 1 conflict / refused claim · 2 usage or ownership error.
AUTHORITY: READ_ONLY_ADVISORY — coordination files only; no broker, DB, Telegram, scheduler or remote write
(``gh pr list`` is a read).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import agent_claim_board as B  # noqa: E402

LANE_ID = "agent-claim-compact"
SCRIPT = "scripts/agent_claim.py"


def _board(a: argparse.Namespace) -> B.ClaimBoard:
    return B.ClaimBoard(a.claims_dir, stale_after_hours=a.stale_hours, compact_after_days=a.compact_days)


def _session(a: argparse.Namespace) -> str | None:
    return a.session or B.detect_session()


def _print_conflicts(rows: list[dict], *, stream=None, prefix: str = "CONFLICT") -> None:
    stream = stream or sys.stderr
    for r in rows:
        held = ", ".join(sorted({o["held"] for o in r.get("overlaps") or []}))
        mine = ", ".join(sorted({o["path"] for o in r.get("overlaps") or []}))
        if r.get("source") == "draft_pr":
            print(
                f"{prefix}: {mine} — open draft PR #{r.get('pr')} on branch {r.get('branch')} changes {held}"
                + (f" ({r['url']})" if r.get("url") else ""),
                file=stream,
            )
        else:
            print(
                f"{prefix}: {mine} — held by {r.get('vendor')}/{r.get('agent') or '-'} session {r.get('session')}"
                f" on branch {r.get('branch') or '?'} since {r.get('started_at')} (last heartbeat"
                f" {r.get('heartbeat_at')}; claim {r.get('claim_id')}; task: {r.get('task')})",
                file=stream,
            )


def cmd_claim(a: argparse.Namespace) -> int:
    board = _board(a)
    session = _session(a)
    if not session:
        print("error: --session (or AGENT_CLAIM_SESSION) is required to claim", file=sys.stderr)
        return 2
    branch = a.branch or B.current_branch()
    try:
        doc = board.claim(
            vendor=a.vendor or B.detect_vendor(),
            session=session,
            agent=a.agent or None,
            task=a.task,
            paths=a.paths,
            branch=branch,
            pr=a.pr,
            note=a.note,
        )
    except B.ClaimConflict as exc:
        _print_conflicts(exc.conflicts)
        print(
            "refused: the paths above are claimed by another live session. Coordinate, or wait for release.",
            file=sys.stderr,
        )
        return 1
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        print(doc["claim_id"])
        for t in doc.get("takeover_of") or []:
            print(
                f"TAKEOVER: stale claim {t['claim_id']} ({t.get('vendor')}/{t.get('session')}, last heartbeat"
                f" {t.get('heartbeat_at')}) recorded in takeover_of",
                file=sys.stderr,
            )
    return 0


def cmd_heartbeat(a: argparse.Namespace) -> int:
    try:
        doc = _board(a).heartbeat(a.claim_id, session=_session(a), pr=a.pr, note=a.note, branch=a.branch)
    except B.ClaimConflict as exc:
        _print_conflicts(exc.conflicts)
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2, sort_keys=True) if a.json else f"{doc['claim_id']} heartbeat {doc['heartbeat_at']}")
    return 0


def cmd_release(a: argparse.Namespace) -> int:
    session = _session(a)
    try:
        doc = _board(a).release(
            a.claim_id, session=session, status=a.status, note=a.note, pr=a.pr, force=a.force, released_by=session
        )
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(doc, indent=2, sort_keys=True) if a.json else f"{doc['claim_id']} {doc['status']} {doc['ended_at']}"
    )
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    view = _board(a).board(include_finished=a.all)
    if a.json:
        print(json.dumps(view, indent=2, sort_keys=True))
        return 0
    rows = view["claims"]
    if view["unreadable"]:
        print(f"WARN: unreadable claim files: {', '.join(view['unreadable'])}", file=sys.stderr)
    if not rows:
        print(
            f"no claims ({'dir ' + view['claims_dir'] + ' absent' if not view['dir_present'] else view['claims_dir']})"
        )
        return 0
    heads = ["STATE", "VENDOR", "AGENT/SESSION", "BRANCH", "PR", "SINCE", "HB AGE", "TASK", "PATHS", "CLAIM"]
    table = []
    for r in rows:
        hb = r["heartbeat_age_minutes"]
        table.append(
            [
                r["state"],
                r["vendor"] or "-",
                (r["agent"] or r["session"] or "-")[:28],
                (r["branch"] or "-")[:40],
                str(r["pr"] or "-"),
                (r["started_at"] or "-")[:16],
                "-" if hb is None else f"{hb:.0f}m",
                (r["task"] or "")[:40],
                ",".join(r["paths"])[:60],
                r["claim_id"],
            ]
        )
    widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(heads)]
    print("  ".join(h.ljust(w) for h, w in zip(heads, widths)))
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    board = _board(a)
    session = _session(a)
    branch = a.exclude_branch if a.exclude_branch is not None else B.current_branch()
    try:
        rows = board.conflicts(a.paths, session=session, branch=branch)
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 0 if a.warn_only else 2
    warning = None
    if not a.no_gh:
        pr_rows, warning = B.draft_pr_conflicts(a.paths, exclude_branch=branch, timeout_s=a.gh_timeout)
        rows += pr_rows
    if warning:
        print(f"WARN: {warning}", file=sys.stderr)
    out = {
        "schema": B.CHECK_SCHEMA,
        "at": B.iso(board.now()),
        "paths": list(a.paths),
        "exclude_session": session,
        "exclude_branch": branch,
        "draft_prs_consulted": (not a.no_gh) and warning is None,
        "warning": warning,
        "conflict": bool(rows),
        "conflicts": rows,
    }
    if a.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    if rows:
        _print_conflicts(rows, prefix="WARN" if a.warn_only else "CONFLICT")
        if a.warn_only:
            print(
                "agent-claim (warn-only until AGENTS.md 19.1.0): commit continues; coordinate with the holder.",
                file=sys.stderr,
            )
            return 0
        return 1
    if not a.json and not a.quiet:
        print("clear: no live claim of another session and no open draft PR overlaps these paths")
    return 0


def cmd_compact(a: argparse.Namespace) -> int:
    started = datetime.now(timezone.utc)
    board = _board(a)
    try:
        res = board.compact(apply=a.apply)
    except OSError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        if a.apply and a.lane_receipt:
            _receipt(ok=False, started=started, summary={}, error=type(exc).__name__, history=board.history)
        return 2
    print(json.dumps(res, indent=2, sort_keys=True))
    if a.apply and a.lane_receipt:  # never from a dry run
        _receipt(
            ok=True,
            started=started,
            history=board.history,
            summary={k: res[k] for k in ("eligible", "archived", "removed")} | {"skipped": len(res["skipped"])},
        )
    return 0


def _receipt(*, ok: bool, started: datetime, summary: dict, history: Path, error: str | None = None) -> None:
    from scripts.lib import lane_last_receipt as R

    R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 2,
        started_at=started,
        script=SCRIPT,
        summary=summary,
        error=error,
        output={
            "produced_count": int(summary.get("archived") or 0),
            "attempted_count": int(summary.get("eligible") or 0),
            "skipped_reasons": {},
            "empty_reason": None if summary.get("eligible") else "nothing_eligible",
            "output_evidence": [{"kind": "file", "ref": str(history)}],
        },
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_claim.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--claims-dir", default=None, help="default: TRADEAI_AGENT_CLAIMS_DIR or persistent-state")
    p.add_argument("--stale-hours", type=float, default=None, help=f"default {B.DEFAULT_STALE_HOURS:g}")
    p.add_argument("--compact-days", type=float, default=B.DEFAULT_COMPACT_DAYS)
    p.add_argument("--vendor", default=None, help="claude | codex | cursor | any label (all equal)")
    p.add_argument("--session", default=None)
    p.add_argument("--agent", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("claim")
    c.add_argument("--task", required=True)
    c.add_argument("--paths", nargs="+", required=True)
    c.add_argument("--branch", default=None)
    c.add_argument("--pr", default=None)
    c.add_argument("--note", default=None)
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_claim)

    h = sub.add_parser("heartbeat")
    h.add_argument("claim_id")
    h.add_argument("--pr", default=None)
    h.add_argument("--note", default=None)
    h.add_argument("--branch", default=None)
    h.add_argument("--json", action="store_true")
    h.set_defaults(fn=cmd_heartbeat)

    r = sub.add_parser("release")
    r.add_argument("claim_id")
    r.add_argument("--status", choices=["done", "abandoned"], default="done")
    r.add_argument("--note", default=None)
    r.add_argument("--pr", default=None)
    r.add_argument("--force", action="store_true", help="release another session's claim; recorded as released_by")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_release)

    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--all", action="store_true", help="include done/abandoned")
    ls.set_defaults(fn=cmd_list)

    k = sub.add_parser("check")
    k.add_argument("--paths", nargs="+", required=True)
    k.add_argument("--exclude-branch", default=None, help="own branch (default: current git branch)")
    k.add_argument("--no-gh", action="store_true", help="skip the open-draft-PR fallback")
    k.add_argument("--gh-timeout", type=float, default=15.0)
    k.add_argument("--warn-only", action="store_true", help="report conflicts, exit 0 (pre-commit mode)")
    k.add_argument("--json", action="store_true")
    k.add_argument("--quiet", action="store_true")
    k.set_defaults(fn=cmd_check)

    m = sub.add_parser("compact")
    g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    m.add_argument("--lane-receipt", action="store_true", help=f"write the {LANE_ID} LaneRunReceipt (timer runs)")
    m.set_defaults(fn=cmd_compact)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
