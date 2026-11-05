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
    """The default adapter. Fixed argv, no shell; S603 is silenced here, at the one call site.

    F1 (cx-openai-3): this used to pass ``capture_output``/``text`` positionally-by-keyword *and* accept them from the
    caller, so every caller that supplied them — which is every tmux call in ``submit`` — raised
    ``TypeError: subprocess.run() got multiple values for keyword argument 'capture_output'`` at the first
    ``load-buffer``. The lane would have crashed on its first real dispatch. Defaults are now set with
    ``setdefault`` so a caller may pass either, and every call is time-bounded.
    """
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", D.RUN_TIMEOUT_S)
    return subprocess.run(list(cmd), **kw)  # noqa: S603


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


def prior_review_dispatches(ledger_path: Path) -> tuple[dict[tuple[int, str], set[str]], dict[tuple[int, str], int]]:
    """What earlier cycles already handed out, read from the dispatcher's own ledger.

    Without this, a PR that stays CLEAN for three cycles collects two new reviewers per cycle — six sessions on one
    PR before the first verdict lands. The ledger is the only state this lane keeps (rails: it writes nothing else).

    F4 round 2 (cx-openai-3): keyed by (pr number, HEAD SHA), not by PR number. A dispatch against an older head must
    not spend the budget at the new head, and must not bar that reviewer from reviewing the new revision. Records
    written before heads were recorded (no ``target_head``) are attributed to the empty head, which matches nothing
    and therefore neither spends the cap nor blocks a reviewer.
    Returns ({(pr, head): {reviewer sessions}}, {(pr, head): dispatched-reviewer count}).
    """
    sessions: dict[tuple[int, str], set[str]] = {}
    counts: dict[tuple[int, str], int] = {}
    try:
        lines = Path(ledger_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return sessions, counts
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("kind") != "review" or not rec.get("busy_after_30s"):
            continue
        try:
            key = (int(rec.get("target")), str(rec.get("target_head") or ""))
        except (TypeError, ValueError):
            continue
        sessions.setdefault(key, set()).add(str(rec.get("session") or ""))
        counts[key] = len(sessions[key])
    return sessions, counts


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
                "number,headRefName,headRefOid,mergeStateStatus,isDraft,updatedAt,files"])
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
                           updated_at=str(r.get("updatedAt") or ""),
                           files=tuple(str(f.get("path")) for f in (r.get("files") or [])
                                       if isinstance(f, dict) and f.get("path")))
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
    """Who authored each PR: the session whose claim names its head branch — in ANY status.

    F5 (cx-openai-3): limiting this to active claims meant a session that had *finished* and released its claim looked
    like "no author", and the dispatcher would happily send it its own PR to review. A done or stale claim still
    records authorship, so every status counts; the newest claim on the branch wins. When nothing resolves the author
    stays empty and ``select_work`` refuses to assign a reviewer (fail closed).
    """
    by_branch: dict[str, str] = {}
    for c in sorted(claims, key=lambda c: c.age_h):  # newest heartbeat first
        if c.branch and c.session:
            by_branch.setdefault(c.branch, c.session)
    return {pr.number: by_branch.get(pr.head_ref, "") for pr in prs}


# ── the cycle ────────────────────────────────────────────────────────────────────────────────────────────────


IDLE_STATE_NAME = "dispatch_idle_state.json"


def idle_minutes_from_state(panes: Sequence[D.PaneState], path: Path, now_iso: str) -> list[tuple[str, float]]:
    """(session, idle minutes) from a persisted idle streak — so the 15-minute escalation can actually fire.

    claude-lead's review of this head: the alert was built from a literal ``0.0``, against a 15-minute threshold, so
    ``DISPATCH_IDLE_ALERT.md`` could never be written no matter how long the fleet sat idle. A cycle has no memory of its
    own, so the streak is kept in a small state file keyed by session: first seen idle inside the current streak, dropped
    the moment the pane is not idle. An unreadable state file is an empty one (a missing streak is not a wrong streak).
    """
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    out: list[tuple[str, float]] = []
    updated: dict[str, str] = {}
    for pane in panes:
        if not pane.idle:
            continue  # not idle now: its streak is over, so it does not survive into the next write
        since = state.get(pane.session)
        try:
            started = datetime.fromisoformat(str(since).replace("Z", "+00:00")) if since else None
        except ValueError:
            started = None
        if started is None or started > now:
            started = now
        updated[pane.session] = started.isoformat(timespec="seconds").replace("+00:00", "Z")
        out.append((pane.session, (now - started).total_seconds() / 60.0))
    idle_minutes_from_state.last = updated  # type: ignore[attr-defined]
    return out


idle_minutes_from_state.last = {}  # type: ignore[attr-defined]


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
    taken: dict[tuple[str, str], int] = {}
    prior_sessions, prior_counts = prior_review_dispatches(ledger_path)
    review_counts: dict[tuple[int, str], int] = {}
    for (pr_no, head), entries in verdicts.items():
        pr = next((p for p in prs if p.number == pr_no and p.head_sha == head), None)
        if pr is None:
            continue
        # F4: BLOCK is a verdict too — a PR with two blocks already at this head does not get a third reviewer.
        reviewers = {e["reviewer"] for e in entries
                     if e["verdict"] in ("MERGE", "BLOCK") and e["reviewer"] and e["reviewer"] != authors.get(pr_no, "")}
        # verdicts already filed + reviewers an earlier cycle already sent to THIS head both spend the cap
        review_counts[(pr_no, head)] = len(reviewers | prior_sessions.get((pr_no, head), set()))
    for pane in panes:
        if not pane.idle:
            continue
        if limit is not None and len(assignments) >= limit:
            break
        a = D.select_work(pane.session, queue=queue, claims=claims, prs=prs, verdicts=verdicts,
                          author_of=authors, coord=str(coord), reviewed_pairs=reviewed, review_counts=review_counts,
                          taken=taken, prior_review_sessions=prior_sessions)
        if a:
            assignments.append(a)
            taken[(a.kind, a.target)] = taken.get((a.kind, a.target), 0) + 1
            if a.kind == "review":
                reviewed.add((int(a.target), pane.session))
                head = next((p.head_sha for p in prs if str(p.number) == a.target), "")
                review_counts[(int(a.target), head)] = review_counts.get((int(a.target), head), 0) + 1

    ready = D.merge_ready(prs, verdicts, claims, authors)
    idle_minutes = idle_minutes_from_state(panes, coord / "dispatch_idle_state.json", generated_at)
    alerts = D.idle_alert(idle_minutes, generated_at=generated_at) if (not assignments and panes) else None

    plan = D.plan_lines(assignments, panes, dispatchable=False)
    result: dict[str, Any] = {"cycle_id": cycle_id, "generated_at": generated_at, "sessions": len(sessions),
                              "idle": sum(1 for p in panes if p.idle), "assignments": [a.as_dict() for a in assignments],
                              "merge_ready": ready, "plan": plan, "ledger": [], "applied": apply}

    if not apply:
        result["merge_ready_md"] = D.render_merge_ready(ready, generated_at=generated_at)
        result["idle_alert_md"] = alerts
        return result

    # F2 round 2 (cx-openai-3): every output identity is decided BEFORE the first keystroke. A refusal must cost
    # zero sends; validating after the loop meant a misconfigured --ledger still submitted to the whole fleet first.
    ledger_target = D.safe_output_path(ledger_path, coord=coord, protected=[queue_path, claims_dir])
    merge_ready_target = D.safe_output_path(coord / "MERGE_READY.md", coord=coord, protected=[queue_path, claims_dir])
    alert_target = D.safe_output_path(coord / "DISPATCH_IDLE_ALERT.md", coord=coord, protected=[queue_path, claims_dir])

    # R6 (codex at fffe2c9cb): a receipt is written as soon as it exists. Buffering every line until the last
    # submission returned meant one failing session discarded the already-delivered receipts, which is the opposite of
    # what an audit trail is for. An exception from a transport is recorded as a failed dispatch, never propagated.
    lines: list[str] = []
    ledger_target.parent.mkdir(parents=True, exist_ok=True)
    with D.open_output(ledger_target, append=True) as ledger_fh:
        for a in assignments:
            try:
                r = D.submit(a.session, a.instruction, run=run, sleep=sleep)
            except Exception as exc:  # noqa: BLE001 — a lane that dies mid-cycle loses the receipt of what it sent
                r = D.SubmitResult(False, False, 0, f"dispatch raised {type(exc).__name__}: {exc}")
            head = ""
            if a.kind in ("review", "merge_prep"):
                head = next((p.head_sha for p in prs if str(p.number) == a.target), "")
            line = D.ledger_line(session=a.session, assignment=a, result=r, cycle_id=cycle_id, target_head=head)
            lines.append(line)
            result["ledger"].append(json.loads(line))
            ledger_fh.write(line + "\n")
            ledger_fh.flush()

    idle_state_target = D.safe_output_path(coord / IDLE_STATE_NAME, coord=coord, protected=[queue_path, claims_dir])
    with D.open_output(idle_state_target) as fh:
        fh.write(json.dumps(getattr(idle_minutes_from_state, "last", {}), indent=1, sort_keys=True) + "\n")
    with D.open_output(merge_ready_target) as fh:
        fh.write(D.render_merge_ready(ready, generated_at=generated_at))
    if alerts:
        with D.open_output(alert_target) as fh:
            fh.write(alerts)
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
