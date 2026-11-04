#!/usr/bin/env python3
"""Automatic agent dispatch — the CLI (operator P0, 2026-11-04 ~13:10 ET).

Dry run is the DEFAULT and writes nothing; ``--apply`` sends, then writes its own ledger and report files. Nothing
here schedules itself: the lane is enabled by the operator, and this file never touches cron, timers or
``config/lane_registry.json``.

Usage:
  python3 scripts/agent_dispatch.py                 # dry run: the whole plan, no writes, no keystrokes
  python3 scripts/agent_dispatch.py --apply         # send to idle sessions, write ledger + MERGE_READY.md
  python3 scripts/agent_dispatch.py --limit 2       # cap how many sessions are dispatched this cycle
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import agent_dispatch as D  # noqa: E402

COORD_DEFAULT = Path(os.environ.get("TRADEAI_COORD_DIR")
                     or (Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "coordination" / "coordinator"))


# ── live providers (all injectable so tests never touch tmux, gh or the fleet) ────────────────────────────────────


def _run(cmd: Sequence[str], **kw: Any) -> Any:
    # Fixed argv, no shell: every caller passes a literal list (tmux/gh); this is the same shape the nudger uses,
    # and S603 is silenced at the one call site rather than for the file.
    return subprocess.run(list(cmd), capture_output=True, text=True, **kw)  # noqa: S603


def tmux_sessions(run: Callable[..., Any] = _run) -> list[str]:
    proc = run(["tmux", "ls", "-F", "#S"])
    if getattr(proc, "returncode", 1) != 0:
        return []
    return D.selectable_sessions((proc.stdout or "").split())


def tmux_screen(session: str, run: Callable[..., Any] = _run) -> str | None:
    proc = run(["tmux", "capture-pane", "-p", "-t", session])
    return None if getattr(proc, "returncode", 1) != 0 else (proc.stdout or "")


def load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_queue(path: Path) -> list[dict[str, Any]]:
    doc = load_json(path)
    items = doc.get("items") if isinstance(doc, dict) else doc
    return [i for i in (items or []) if isinstance(i, dict)]


def load_review_artifacts(coord: Path) -> list[dict[str, Any]]:
    """Every review artifact on disk: registered evidence plus companions filed in the coordinator inbox."""
    out: list[dict[str, Any]] = []
    for folder, pattern in ((coord / "review-evidence", "*.json"), (coord / "inbox", "*/*.json")):
        if not folder.is_dir():
            continue
        for path in folder.glob(pattern):
            doc = load_json(path)
            if isinstance(doc, dict) and doc.get("pr") and (doc.get("verdict") or doc.get("reviews")):
                out.append(doc)
    return out


def open_prs(run: Callable[..., Any] = _run, with_commits: bool = True) -> list[D.PullRequest]:
    """Open PRs from `gh`. Commit SHAs are fetched only for CLEAN candidates (they are the merge-prep evidence)."""
    proc = run(["gh", "pr", "list", "--state", "open", "--limit", "200", "--json",
                "number,headRefName,headRefOid,mergeStateStatus,isDraft,updatedAt"])
    if getattr(proc, "returncode", 1) != 0:
        return []
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return []
    out: list[D.PullRequest] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        pr = D.PullRequest(number=int(r["number"]), head_sha=str(r.get("headRefOid") or ""),
                           head_ref=str(r.get("headRefName") or ""),
                           merge_state=str(r.get("mergeStateStatus") or ""), draft=bool(r.get("isDraft")),
                           updated_at=str(r.get("updatedAt") or ""))
        if with_commits and pr.clean:
            c = run(["gh", "pr", "view", str(pr.number), "--json", "commits"])
            if getattr(c, "returncode", 1) == 0:
                try:
                    commits = json.loads(c.stdout or "{}").get("commits") or []
                    pr.commit_shas = tuple(str(x.get("oid")) for x in commits if isinstance(x, dict) and x.get("oid"))
                except ValueError:
                    pass
        out.append(pr)
    return out


def author_sessions(prs: Sequence[D.PullRequest], claims: Sequence[D.Claim]) -> dict[int, str]:
    """Who authored each PR: the session holding the active claim on its head branch. Not a guess — a lookup."""
    by_branch: dict[str, str] = {}
    for c in sorted(claims, key=lambda c: c.age_h):
        if c.status == "active" and c.branch:
            by_branch.setdefault(c.branch, c.session)
    return {pr.number: by_branch.get(pr.head_ref, "") for pr in prs}


# ── the cycle ────────────────────────────────────────────────────────────────────────────────────────────────


def run_cycle(*, apply: bool, coord: Path, queue_path: Path, claims_dir: Path, ledger_path: Path,
              limit: int | None = None, run: Callable[..., Any] = _run,
              sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    cycle_id = "cyc-" + uuid.uuid4().hex[:12]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    sessions = tmux_sessions(run)
    panes = [D.classify_pane(s, tmux_screen(s, run)) for s in sessions]
    queue = load_queue(queue_path)
    claims = D.load_claims(claims_dir)
    prs = open_prs(run)
    verdicts = D.verdicts_at_head(load_review_artifacts(coord))
    authors = author_sessions(prs, claims)

    assignments: list[D.Assignment] = []
    reviewed: set[tuple[int, str]] = set()
    review_counts: dict[int, int] = {}
    for (pr_no, head), entries in verdicts.items():
        pr = next((p for p in prs if p.number == pr_no and p.head_sha == head), None)
        if pr is None:
            continue
        reviewers = {e["reviewer"] for e in entries if e["verdict"] == "MERGE" and e["reviewer"] != authors.get(pr_no, "")}
        review_counts[pr_no] = len(reviewers)
    for pane in panes:
        if not pane.idle:
            continue
        if limit is not None and len(assignments) >= limit:
            break
        a = D.select_work(pane.session, queue=queue, claims=claims, prs=prs, verdicts=verdicts,
                          author_of=authors, coord=str(coord), reviewed_pairs=reviewed, review_counts=review_counts)
        if a:
            assignments.append(a)
            if a.kind == "review":
                reviewed.add((int(a.target), pane.session))
                review_counts[int(a.target)] = review_counts.get(int(a.target), 0) + 1

    ready = D.merge_ready(prs, verdicts, claims, authors)
    idle_minutes = [(p.session, 0.0) for p in panes if p.idle]  # a cycle has no memory; the alert uses dwell from state
    alerts = D.idle_alert(idle_minutes, generated_at=generated_at) if (not assignments and panes) else None

    plan = D.plan_lines(assignments, panes, dispatchable=False)
    result: dict[str, Any] = {"cycle_id": cycle_id, "generated_at": generated_at, "sessions": len(sessions),
                              "idle": sum(1 for p in panes if p.idle), "assignments": [a.as_dict() for a in assignments],
                              "merge_ready": ready, "plan": plan, "ledger": [], "applied": apply}

    if not apply:
        result["merge_ready_md"] = D.render_merge_ready(ready, generated_at=generated_at)
        result["idle_alert_md"] = alerts
        return result

    lines: list[str] = []
    for a in assignments:
        r = D.submit(a.session, a.instruction, run=run, sleep=sleep)
        line = D.ledger_line(session=a.session, assignment=a, result=r, cycle_id=cycle_id)
        lines.append(line)
        result["ledger"].append(json.loads(line))
    if lines:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")

    (coord / "MERGE_READY.md").write_text(D.render_merge_ready(ready, generated_at=generated_at), encoding="utf-8")
    if alerts:
        (coord / "DISPATCH_IDLE_ALERT.md").write_text(alerts, encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Automatic agent dispatch (dry run by default).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="send keystrokes and write ledger/report files")
    mode.add_argument("--dry-run", action="store_true", help="explicit dry run (the default)")
    ap.add_argument("--coord", help="coordinator directory (default $TRADEAI_COORD_DIR or the persistent-state path)")
    ap.add_argument("--queue", help="audit fix queue JSON")
    ap.add_argument("--claims", help="claims directory")
    ap.add_argument("--ledger", help="dispatch ledger JSONL")
    ap.add_argument("--limit", type=int, default=None, help="cap dispatches this cycle")
    ap.add_argument("--json", action="store_true", help="print the machine result instead of the plan")
    a = ap.parse_args(argv)

    coord = Path(a.coord or COORD_DEFAULT)
    queue_path = Path(a.queue or (coord / "AUDIT_FIX_QUEUE.json"))
    claims_dir = Path(a.claims or (coord.parent / "claims"))
    ledger_path = Path(a.ledger or (coord / "dispatch_ledger.jsonl"))

    out = run_cycle(apply=bool(a.apply), coord=coord, queue_path=queue_path, claims_dir=claims_dir,
                    ledger_path=ledger_path, limit=a.limit)
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(("APPLY" if a.apply else "DRY RUN") + f" @ {out['generated_at']}  cycle {out['cycle_id']}")
        print(f"sessions {out['sessions']} · idle {out['idle']} · assignments {len(out['assignments'])}")
        print("\n".join(out["plan"]))
        print(f"\nmerge pump: ready {len(out['merge_ready']['ready'])} · one step away {len(out['merge_ready']['one_step'])}")
        if out.get("idle_alert_md"):
            print("ESCALATION: no work to hand out while sessions are idle — DISPATCH_IDLE_ALERT.md would be written")
        if a.apply:
            print(f"ledger: {ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
