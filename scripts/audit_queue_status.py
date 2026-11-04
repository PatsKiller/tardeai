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

DEFAULT_QUEUE = Path(
    "/home/johnclaw/trade-ai-releases/persistent-state/data/coordination/coordinator/AUDIT_FIX_QUEUE.json"
)

SCHEMA = "AuditFixQueueStatusSync@v1"
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
        out = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError(f"gh pr list failed ({out.returncode}): {out.stderr[:300]}")
        text = out.stdout
    else:
        text = runner(argv)
    data = json.loads(text or "[]")
    return data if isinstance(data, list) else []


#: Rule 3 of the queue brief has authors name the rows they are NOT closing, so a bare mention is not a claim.
_NEGATED = re.compile(r"\b(not|NOT)\b[^\n]{0,40}\b(clos\w+|address\w+|includ\w+|touch\w+|fix\w+)", re.IGNORECASE)


def rows_named_by(pr: dict[str, Any]) -> set[str]:
    """Which queue rows a PR claims to be about. A row named only in a "not closing FQ-0NN" line is not claimed."""
    out: set[str] = set()
    for line in str(pr.get("body") or "").splitlines():
        if _NEGATED.search(line):
            continue
        for m in _ROW_IN_BODY.finditer(line):
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
    if status in ("queued", "assigned") and state == "OPEN":
        prn = pr.get("number")
        return {"status": "fix_in_review", "pr": prn, "head": pr.get("headRefOid"),
                "history": _entry(now, status, "fix_in_review", f"PR #{prn} is open")}
    if status == "fix_in_review":
        prn = pr.get("number")
        if state == "MERGED":
            sha = (pr.get("mergeCommit") or {}).get("oid")
            return {"status": "delivered", "pr": prn, "head": sha or pr.get("headRefOid"),
                    "history": _entry(now, status, "delivered", f"PR #{prn} merged")}
        if state == "CLOSED":
            return {"status": "parked", "pr": prn,
                    "history": _entry(now, status, "parked", f"PR #{prn} closed without merging")}
        head = pr.get("headRefOid")
        if head and (head != item.get("head") or not item.get("pr")):
            return {"head": head, "pr": prn,
                    "history": _entry(now, status, status, f"PR #{prn} head {head[:9]}")}
    return None


def sync(queue: dict[str, Any], prs: Iterable[dict[str, Any]], *, now: str | None = None) -> dict[str, Any]:
    """Apply the rules to a queue document in memory. Returns a report; mutates a copy, never the input."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_row: dict[str, list[dict[str, Any]]] = {}
    for pr in prs:
        for row in rows_named_by(pr):
            by_row.setdefault(row, []).append(pr)
    # newest PR wins when a row has more than one (a superseded PR is still evidence the row is in review).
    for row in by_row:
        by_row[row].sort(key=lambda p: int(p.get("number") or 0), reverse=True)

    doc = json.loads(json.dumps(queue))  # deep copy: the caller's object stays clean
    changes: list[dict[str, Any]] = []
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        pr = (by_row.get(str(item.get("id"))) or [None])[0]
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
    ap.add_argument("--queue", default=os.environ.get("AUDIT_FIX_QUEUE_PATH") or str(DEFAULT_QUEUE))
    ap.add_argument("--apply", action="store_true", help="write the queue (default is a dry run)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    path = Path(args.queue)
    queue = json.loads(path.read_text(encoding="utf-8"))
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
    bak = _backup(path)
    path.write_text(json.dumps(report["queue"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.json:
        print(f"wrote {path} (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
