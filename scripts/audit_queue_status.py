#!/usr/bin/env python3
"""audit_queue_status.py — keep AUDIT_FIX_QUEUE.json's status field true from GitHub.

Implements AuditFixQueueStatusRules@v1 (authored cc-deepseek-3, adopted by cc-deepseek-7, 2026-11-04):

  * rule 1  fix_in_review at PR open: an open PR naming a row moves it out of queued/assigned
  * rule 3  on merge -> delivered, with the merge commit
  * rule 4  on PR closed without merge -> parked
  * rule 5  closed_no_longer_reproduces and other closed states are the author's to set; never inferred here
  * rule 6  the dispatcher only sends queued/assigned — so this tool must never leave a delivered row in either

The row is matched by `FQ-0NN` anywhere in the PR body, or by the branch name (`wt/fq022-…` → FQ-022). A row whose
status is HELD_*, delivered, parked or closed_* is never touched: those are decisions, not observations.

Dry run by default. `--apply` writes the queue after making a timestamped backup beside it, and only if something
changed. Nothing here reads the network except `gh pr list`; it never writes to GitHub.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

#: The queue lives in the coordination tree beside the releases, never inside the repo. Resolved from HOME so no
#: user's home directory is written into the source; AUDIT_FIX_QUEUE_PATH overrides it.
DEFAULT_QUEUE = Path(
    os.environ.get("AUDIT_FIX_QUEUE_PATH")
    or Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "coordination" / "coordinator"
    / "AUDIT_FIX_QUEUE.json"
)

SCHEMA = "AuditFixQueueStatusSync@v1"
#: The dark-contract declaration: this CLI is run on demand (and may be put on a timer by the coordinator). It reads
#: GitHub and writes only the coordination queue, and only when asked with --apply.
SCHEDULED_ENTRYPOINT = (
    "NONE — unscheduled by design; operator/coordinator-run CLI. Scheduling is operator-only (AGENTS.md §17). "
    "Reads `gh pr list`; writes AUDIT_FIX_QUEUE.json only with --apply, after a backup."
)
AUTHOR = "audit_queue_status.py"

#: Rows in these states are observations and may move. Everything else is a decision and is left alone.
TRANSIENT = ("queued", "assigned", "fix_in_review")

_ROW_IN_BODY = re.compile(r"FQ-(\d{3})\b", re.IGNORECASE)
_ROW_IN_BRANCH = re.compile(r"(?:^|[/_-])fq-?(\d{3})(?=$|[/_-])", re.IGNORECASE)

PR_FIELDS = "number,state,headRefName,headRefOid,body,mergedAt,mergeCommit"


def gh_pr_list(runner: Callable[[list[str]], str] | None = None, *, limit: int = 500) -> list[dict[str, Any]]:
    """Every PR we might need to look at, one call. ``runner`` is injectable for tests."""
    argv = ["gh", "pr", "list", "--state", "all", "--limit", str(limit), "--json", PR_FIELDS]
    if runner is None:
        # A fixed argv with no shell: the only variable is the limit, an int we format ourselves.
        out = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603, S607
        if out.returncode != 0:
            raise RuntimeError(f"gh pr list failed ({out.returncode}): {out.stderr[:300]}")
        text = out.stdout
    else:
        text = runner(argv)
    data = json.loads(text or "[]")
    return data if isinstance(data, list) else []


#: Rule 3 of the queue brief has authors name the rows they are NOT closing, so a bare mention is not a claim.
_NEGATED = re.compile(r"\b(not|NOT)\b[^\n]{0,40}\b(clos\w+|address\w+|includ\w+|touch\w+|fix\w+)", re.IGNORECASE)

#: A first-class declaration: the verb that says this PR does the work, on the same line as the row. A row named in
#: prose ("this supersedes the old FQ-045 approach") is a MENTION and may not move a row that already has a PR — the
#: 2026-11-05 review (#2640 F1) found a passing mention parking a row whose real PR was open.
_DECLARES = re.compile(
    r"\b(?:clos(?:e|es|ed|ing)|fix(?:es|ed|ing)?|resolv(?:e|es|ed|ing)|implement(?:s|ed|ing)?|address(?:es|ed|ing)?"
    r"|deliver(?:s|ed|ing)?|does|owns?)\b[^\n]{0,80}?\bFQ-(\d{3})\b",
    re.IGNORECASE,
)


def _body_lines(pr: dict[str, Any]) -> list[str]:
    return [line for line in str(pr.get("body") or "").splitlines() if not _NEGATED.search(line)]


def rows_named_by(pr: dict[str, Any]) -> set[str]:
    """Which queue rows a PR names at all. A row named only in a "not closing FQ-0NN" line is not named."""
    out: set[str] = set()
    for line in _body_lines(pr):
        for m in _ROW_IN_BODY.finditer(line):
            out.add(f"FQ-{m.group(1)}")
    for m in _ROW_IN_BRANCH.finditer(str(pr.get("headRefName") or "")):
        out.add(f"FQ-{m.group(1)}")
    return out


def rows_claimed_by(pr: dict[str, Any]) -> set[str]:
    """Which rows a PR CLAIMS — by branch name or by a first-class "closes/fixes FQ-0NN" line.

    A weaker match than :func:`rows_named_by`: it is the set allowed to retake a row that already has a PR.
    """
    out: set[str] = set()
    for line in _body_lines(pr):
        for m in _DECLARES.finditer(line):
            out.add(f"FQ-{m.group(1)}")
    for m in _ROW_IN_BRANCH.finditer(str(pr.get("headRefName") or "")):
        out.add(f"FQ-{m.group(1)}")
    return out


def _entry(now: str, old: str, new: str, why: str) -> dict[str, str]:
    return {"at": now, "by": AUTHOR, "from": old, "to": new, "why": why}


def plan(item: dict[str, Any], pr: dict[str, Any] | None, now: str) -> dict[str, Any] | None:
    """The change this row needs, or None. Pure: no I/O, no clock read."""
    status = str(item.get("status") or "").strip()
    if status not in TRANSIENT:
        return None
    if pr is None:
        return None
    state = str(pr.get("state") or "").upper()
    prn = pr.get("number")
    # QS1 (cx-openai BLOCK at f10e73cb4): a row whose PR has ALREADY merged must go to delivered from ANY transient state.
    # This tool is the only thing that writes these statuses, and it runs on demand — so the first observation of a PR can
    # be after it merged (the intermediate open/in-review observation was never taken). Handling MERGED only inside
    # `fix_in_review` left such a row permanently dispatchable, which is the failure the tool exists to prevent.
    if state == "MERGED":
        sha = (pr.get("mergeCommit") or {}).get("oid")
        return {"status": "delivered", "pr": prn, "head": sha or pr.get("headRefOid"),
                "history": _entry(now, status, "delivered", f"PR #{prn} merged")}
    # QS2 (cx-openai BLOCK at 9a6cc70d2): the same missed-observation defect for a PR closed WITHOUT merging. Rule 4
    # parks an abandoned row; a first observation after the abandonment must honour it from any transient state, exactly
    # as the merge catch-up above honours rule 3. Leaving CLOSED inside `fix_in_review` left a queued or assigned row
    # dispatchable for ever — the dispatcher would send work whose PR was already abandoned.
    if state == "CLOSED":
        return {"status": "parked", "pr": prn,
                "history": _entry(now, status, "parked", f"PR #{prn} closed without merging")}
    if status in ("queued", "assigned") and state == "OPEN":
        return {"status": "fix_in_review", "pr": prn, "head": pr.get("headRefOid"),
                "history": _entry(now, status, "fix_in_review", f"PR #{prn} is open")}
    if status == "fix_in_review":
        head = pr.get("headRefOid")
        if head and (head != item.get("head") or not item.get("pr")):
            return {"head": head, "pr": prn,
                    "history": _entry(now, status, status, f"PR #{prn} head {head[:9]}")}
    return None


def choose_pr(item: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Which of a row's candidate PRs decides its status.

    Order of evidence, strongest first:
      1. a PR that CLAIMS the row (branch name or a first-class "closes FQ-0NN" line) beats one that mentions it;
      2. an OPEN PR beats a merged/closed one — a newer closed PR must not park a row whose work is still open;
      3. the row's existing PR keeps the association when both are equally strong;
      4. the higher PR number (the newest) breaks the remaining tie.
    A MENTION-only PR never retakes a row that already has a PR: the tool may only move an association when the PR that
    owns it says so (#2640 F1).
    """
    if not candidates:
        return None
    row = str(item.get("id"))
    claimed = [p for p in candidates if row in rows_claimed_by(p)]
    pool = claimed or candidates
    owned = item.get("pr")

    def rank(pr: dict[str, Any]) -> tuple[int, int, int]:
        number = int(pr.get("number") or 0)
        return (1 if str(pr.get("state") or "").upper() == "OPEN" else 0,
                1 if owned is not None and number == int(owned) else 0,
                number)

    chosen = max(pool, key=rank)
    if owned is not None and int(chosen.get("number") or 0) != int(owned) and row not in rows_claimed_by(chosen):
        return None
    # QS3 (cx-openai-2/cx-openai-5 at 0c2614145): a mere mention is not evidence. When NO candidate claims the row, only
    # the row's own existing association may decide its status — otherwise an unrelated PR that says "FQ-021 came up in
    # passing" would deliver, park or re-assign a row it has nothing to do with.
    if not claimed:
        if owned is not None and int(chosen.get("number") or 0) == int(owned):
            return chosen
        return None
    return chosen


def sync(queue: dict[str, Any], prs: Iterable[dict[str, Any]], *, now: str | None = None) -> dict[str, Any]:
    """Apply the rules to a queue document in memory. Returns a report; mutates a copy, never the input."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_row: dict[str, list[dict[str, Any]]] = {}
    for pr in prs:
        for row in rows_named_by(pr):
            by_row.setdefault(row, []).append(pr)

    doc = json.loads(json.dumps(queue))  # deep copy: the caller's object stays clean
    changes: list[dict[str, Any]] = []
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        pr = choose_pr(item, by_row.get(str(item.get("id"))) or [])
        delta = plan(item, pr, now)
        if not delta:
            continue
        before = {k: item.get(k) for k in ("status", "pr", "head")}
        for k, v in delta.items():
            if k == "history":
                continue
            item[k] = v
        item.setdefault("history", []).append(delta["history"])
        changes.append({"id": item.get("id"), "from": before, "to": {k: item.get(k) for k in ("status", "pr", "head")},
                        "why": delta["history"]["why"]})
    if changes:
        doc["as_of"] = now
        doc.setdefault("status_source", "")
        doc["status_source"] = (doc["status_source"] + "; " if doc["status_source"] else "") + f"{AUTHOR} {now}"
    return {"schema": SCHEMA, "as_of": now, "changed": len(changes), "changes": changes, "queue": doc}


def _backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = path.with_suffix(path.suffix + f".bak-{AUTHOR.replace('.py', '')}-{stamp}")
    out.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync AUDIT_FIX_QUEUE.json status from open/merged/closed PRs.")
    ap.add_argument("--queue", default=str(DEFAULT_QUEUE))
    ap.add_argument("--apply", action="store_true", help="write the queue (default is a dry run)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    path = Path(args.queue)
    snapshot = path.read_text(encoding="utf-8")
    queue = json.loads(snapshot)
    report = sync(queue, gh_pr_list())

    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "queue"}, indent=2))
    else:
        print(f"{report['schema']} as_of {report['as_of']}: {report['changed']} change(s)")
        for c in report["changes"]:
            print(f"  {c['id']}: {c['from']['status']} -> {c['to']['status']}  ({c['why']})")

    if not args.apply:
        if not args.json:
            print("dry run — pass --apply to write")
        return 0
    if not report["changed"]:
        return 0
    # QS4 (cx-openai-2/cx-openai-5 at 0c2614145): this run read the whole queue, then spent seconds-to-minutes collecting
    # GitHub state, then wrote its stale snapshot back. Anything that happened to the file in between — another agent's
    # decision, an operator's HELD_* — was silently overwritten, including rows this run never looked at. Refuse instead:
    # a status writer that loses an operator decision is worse than one that asks to be re-run.
    if path.read_text(encoding="utf-8") != snapshot:
        print(
            f"REFUSED: {path} changed while GitHub state was being collected (another writer's update would be lost). "
            "Nothing was written; re-run.",
            file=sys.stderr,
        )
        return 2
    bak = _backup(path)
    path.write_text(json.dumps(report["queue"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.json:
        print(f"wrote {path} (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
