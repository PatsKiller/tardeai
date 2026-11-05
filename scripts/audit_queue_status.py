#!/usr/bin/env python3
"""audit_queue_status.py — keep AUDIT_FIX_QUEUE.json's status field true from GitHub.

Implements AuditFixQueueStatusRules@v1 (authored cc-deepseek-3, adopted by cc-deepseek-7, 2026-11-04):

  * rule 1  fix_in_review at PR open: an open PR naming a row moves it out of queued/assigned
  * rule 3  on merge -> delivered, with the merge commit
  * rule 4  on PR closed without merge -> parked
  * rule 5  closed_no_longer_reproduces and other closed states are the author's to set; never inferred here
  * rule 6  the dispatcher only sends queued/assigned — so this tool must never leave a delivered row in either

A row is NAMED by `FQ-0NN` anywhere in the PR body, or by the branch name (`wt/fq022-…` → FQ-022). Naming only makes
the PR a candidate; a row is CLAIMED by the branch name or by a first-class declaration ("closes/fixes FQ-0NN") in a
clause that does not negate it. One declaration governs every row after its verb in the clause ("Closes FQ-021 and
FQ-022." claims both). Negation is scoped to the row it governs, not the line, so one line may claim one row
and disclaim another. A row's recorded `pr` remains evidence even when that PR's current wording no longer names it.
A passing mention decides nothing (#2640 QS3). A row whose status is HELD_*, delivered, parked or
closed_* is never touched: those are decisions, not observations.

Dry run by default. `--apply` writes the queue under an exclusive lock, after a timestamped backup beside it, and only
if something changed; a concurrent writer that moved the file meanwhile makes it refuse rather than overwrite. Nothing
here reads the network except the read-only `gh` PR census (`gh pr list`, paged through `gh api` when the window is
full); it never writes to GitHub.
"""

from __future__ import annotations

import argparse
import fcntl
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
    "Reads the read-only `gh` PR census (`gh pr list`, paged through `gh api` when its window is full); writes "
    "AUDIT_FIX_QUEUE.json only with --apply, under a lock and after a backup."
)
AUTHOR = "audit_queue_status.py"

#: Rows in these states are observations and may move. Everything else is a decision and is left alone.
TRANSIENT = ("queued", "assigned", "fix_in_review")

_ROW_IN_BODY = re.compile(r"FQ-(\d{3})\b", re.IGNORECASE)
_ROW_IN_BRANCH = re.compile(r"(?:^|[/_-])fq-?(\d{3})(?=$|[/_-])", re.IGNORECASE)

PR_FIELDS = "number,state,headRefName,headRefOid,body,mergedAt,mergeCommit"

#: REST page size for the completeness fallback, and the hard stop. A fetch that would need more pages than this
#: refuses rather than presenting a truncated list as the whole PR universe (#2640 B2).
REST_PAGE_SIZE = 100
MAX_REST_PAGES = 100


class FetchIncomplete(RuntimeError):
    """The PR census could not be established completely. Unknown must never render as "0 change(s)"."""


def _run_gh(argv: list[str], runner: Callable[[list[str]], str] | None) -> str:
    if runner is not None:
        return runner(argv)
    # A fixed argv with no shell: the only variables are ints we format ourselves.
    out = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603, S607
    if out.returncode != 0:
        raise FetchIncomplete(f"{' '.join(argv[:4])} failed ({out.returncode}): {out.stderr[:300]}")
    return out.stdout


def _json_list(text: str) -> list[Any]:
    """A gh payload must be a JSON list. Invalid JSON or any other shape is UNKNOWN, never "no PRs" (#2640 N2)."""
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError as exc:
        raise FetchIncomplete(f"gh returned invalid JSON: {exc}") from None
    if not isinstance(data, list):
        raise FetchIncomplete(f"gh returned a {type(data).__name__}, expected a JSON list")
    return data


def _rest_pr(raw: Any) -> dict[str, Any]:
    """A REST pull reduced to the compact shape `gh pr list --json` gives us."""
    if not isinstance(raw, dict):
        raise FetchIncomplete(f"REST pulls returned a non-object row: {type(raw).__name__}")
    head = raw.get("head") if isinstance(raw.get("head"), dict) else {}
    merge_sha = raw.get("merge_commit_sha")
    return {
        "number": raw.get("number"),
        # REST calls a merged PR "closed"; the rules distinguish MERGED from CLOSED-without-merge.
        "state": "MERGED" if raw.get("merged_at") else str(raw.get("state") or "").upper(),
        "headRefName": head.get("ref"),
        "headRefOid": head.get("sha"),
        "body": raw.get("body"),
        "mergedAt": raw.get("merged_at"),
        "mergeCommit": {"oid": merge_sha} if merge_sha else None,
    }


def _all_prs_rest(runner: Callable[[list[str]], str] | None) -> list[dict[str, Any]]:
    """Page the REST pulls endpoint to completion. A full final page at the cap is an error, not a universe."""
    rows: list[dict[str, Any]] = []
    for page in range(1, MAX_REST_PAGES + 1):
        argv = ["gh", "api", f"repos/{{owner}}/{{repo}}/pulls?state=all&per_page={REST_PAGE_SIZE}&page={page}"]
        batch = _json_list(_run_gh(argv, runner))
        rows.extend(_rest_pr(raw) for raw in batch)
        if len(batch) < REST_PAGE_SIZE:
            return rows
    raise FetchIncomplete(
        f"PR census exceeded {MAX_REST_PAGES} REST pages ({MAX_REST_PAGES * REST_PAGE_SIZE} PRs); refusing to "
        "treat a truncated set as the whole universe"
    )


def gh_pr_list(runner: Callable[[list[str]], str] | None = None, *, limit: int = 500) -> list[dict[str, Any]]:
    """Every PR we might need to look at. ``runner`` is injectable for tests.

    `gh pr list` is one window; a full window means gh cannot say whether older PRs exist, so it is NOT the whole
    universe (#2640 B2). That case pages the REST endpoint to completion instead of reporting a silently truncated
    census; if even that hits its cap, the census is refused.
    """
    argv = ["gh", "pr", "list", "--state", "all", "--limit", str(limit), "--json", PR_FIELDS]
    data = _json_list(_run_gh(argv, runner))
    if len(data) >= limit:
        # Keep the window's rows (they are the freshest) and add every REST row the paged census found beyond it.
        complete = _all_prs_rest(runner)
        seen = {p.get("number") for p in data}
        return data + [p for p in complete if p.get("number") not in seen]
    return data


#: Rule 3 of the queue brief has authors name the rows they are NOT closing — often on the same line as a row they
#: DO close. Negation is therefore scoped to the row it governs, never to the whole line (#2640 B1):
#: "Closes FQ-022; not closing FQ-033." claims FQ-022 and disclaims FQ-033.
_CLAUSE_SPLIT = re.compile(r"[\n;]+|(?<=[.!?])\s+")
_NEGATION = re.compile(r"\b(?:not|never|no longer|cannot|isn't|aren't|won't|doesn't|don't)\b", re.IGNORECASE)
#: The verbs that make a naming a first-class declaration rather than a passing mention. A declaration governs EVERY
#: row after it in the same clause, until the next verb takes over: "Closes FQ-021 and FQ-022." declares both (#2640
#: CX1). A row named in prose ("this supersedes the old FQ-045 approach") has no declaration verb before it, so it is
#: a MENTION and may not move a row that already has a PR — the 2026-11-05 review (#2640 F1) found a passing mention
#: parking a row whose real PR was open.
#: A negation between a declaration verb and a row disclaims only that row: "Closes FQ-021, not FQ-022."
_NOT_BEFORE_ROW = re.compile(r"\b(?:not|except|excluding)\b", re.IGNORECASE)
_DECLARES_VERB = re.compile(
    r"\b(?:clos(?:e|es|ed|ing)|fix(?:es|ed|ing)?|resolv(?:e|es|ed|ing)|implement(?:s|ed|ing)?|address(?:es|ed|ing)?"
    r"|deliver(?:s|ed|ing)?|does|owns?)\b",
    re.IGNORECASE,
)
#: Every action verb a negation may govern. Kept a superset of `_DECLARES_VERB` so "not touching FQ-033" is read too.
_ACTION = re.compile(
    r"\b(?:clos(?:e|es|ed|ing)|fix(?:es|ed|ing)?|resolv(?:e|es|ed|ing)|implement(?:s|ed|ing)?"
    r"|address(?:es|ed|ing)?|deliver(?:s|ed|ing)?|touch(?:es|ed|ing)?|includ(?:e|es|ed|ing)?|does|owns?)\b",
    re.IGNORECASE,
)
#: How far before a verb a negation still governs it ("does not <40 chars> close").
_NEGATION_WINDOW = 40


def _clauses(body: str) -> list[str]:
    """Sentences/clauses, so a negation binds inside its own clause instead of dropping a whole line."""
    return [c for c in _CLAUSE_SPLIT.split(body) if c.strip()]


def _negated_verbs(clause: str, verbs: list[re.Match[str]]) -> list[bool]:
    """Per verb: does a negation govern it? A negation binds the FIRST verb after it, not every verb within reach,
    so "Not closing FQ-033 but closes FQ-022" negates only "closing"."""
    out: list[bool] = []
    negations = list(_NEGATION.finditer(clause))
    for vm in verbs:
        negated = False
        for nm in negations:
            if nm.start() >= vm.start():
                break  # negations after the verb do not govern it
            if vm.start() - nm.end() > _NEGATION_WINDOW:
                continue  # too far away to be the same phrase
            if any(nm.end() <= other.start() < vm.start() for other in verbs):
                continue  # another verb in between already took this negation
            negated = True
            break
        out.append(negated)
    return out


def _negated_rows(clause: str) -> set[str]:
    """Rows in this clause whose governing verb is negated.

    The verb nearest before the row governs it ("Closes FQ-022 and is not touching FQ-033": Closes governs
    FQ-022, touching governs FQ-033). A row with no verb before it is negated only when the nearest verb after it
    is ("FQ-033 is not being closed").
    """
    out: set[str] = set()
    verbs = list(_ACTION.finditer(clause))
    negated = _negated_verbs(clause, verbs)
    for m in _ROW_IN_BODY.finditer(clause):
        before = [i for i, v in enumerate(verbs) if v.start() < m.start()]
        governing = before[-1] if before else next(
            (i for i, v in enumerate(verbs) if v.start() >= m.start()), None)
        if governing is not None and negated[governing]:
            out.add(f"FQ-{m.group(1)}")
    return out


def _disclaimed_rows(pr: dict[str, Any]) -> set[str]:
    '''Rows this PR explicitly says it is NOT closing, at row level: "Closes FQ-021, not FQ-022."'''
    out: set[str] = set()
    for clause in _clauses(str(pr.get("body") or "")):
        for m in _ROW_IN_BODY.finditer(clause):
            if _NOT_BEFORE_ROW.search(clause[_row_or_verb_start(clause, m.start()):m.start()]):
                out.add(f"FQ-{m.group(1)}")
    return out


def _row_or_verb_start(clause: str, row_start: int) -> int:
    """Start of the segment governing this row: after the last declaration verb before it."""
    verbs = [v for v in _ACTION.finditer(clause) if v.start() < row_start]
    return verbs[-1].end() if verbs else 0


def rows_named_by(pr: dict[str, Any]) -> set[str]:
    """Which queue rows a PR names at all. A row named only in "not closing FQ-0NN" is not named."""
    out: set[str] = set()
    for clause in _clauses(str(pr.get("body") or "")):
        negated = _negated_rows(clause)
        for m in _ROW_IN_BODY.finditer(clause):
            row = f"FQ-{m.group(1)}"
            if row not in negated:
                out.add(row)
    for m in _ROW_IN_BRANCH.finditer(str(pr.get("headRefName") or "")):
        out.add(f"FQ-{m.group(1)}")
    return out


def rows_claimed_by(pr: dict[str, Any]) -> set[str]:
    """Which rows a PR CLAIMS — by branch name or by a non-negated first-class "closes/fixes FQ-0NN" declaration.

    A declaration governs every row in its clause after the verb, until the next verb takes over: "Closes FQ-021 and
    FQ-022." claims both (#2640 CX1), while each row's own governing verb still decides negation ("Closes FQ-021 and
    is not touching FQ-033" claims only FQ-021). A row with no verb before it in its clause is a mention, not a claim.

    A weaker match than :func:`rows_named_by`: it is the set allowed to retake a row that already has a PR.
    """
    out: set[str] = set()
    for clause in _clauses(str(pr.get("body") or "")):
        verbs = list(_ACTION.finditer(clause))
        negated = _negated_verbs(clause, verbs)
        for m in _ROW_IN_BODY.finditer(clause):
            governing = [i for i, v in enumerate(verbs) if v.start() < m.start()]
            if not governing:
                continue  # no verb before the row: this is a mention, not a declaration
            i = governing[-1]
            if negated[i] or not _DECLARES_VERB.fullmatch(verbs[i].group(0)):
                continue
            # Row-local negation (cx-openai triage on f0ae3822f): a list can disclaim one of its own rows —
            # "Closes FQ-021, not FQ-022." The verb is not negated, so the marker between the verb and THIS row
            # is what decides: a negation there means the declaration does not govern this row.
            if _NOT_BEFORE_ROW.search(clause[verbs[i].end():m.start()]):
                continue
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


def _as_pr_number(value: Any) -> int | None:
    """A PR number from a census row or a queue item, or None when it is absent or unreadable."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def choose_pr(item: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Which of a row's candidate PRs decides its status.

    Order of evidence, strongest first:
      1. a PR that CLAIMS the row (branch name or a first-class "closes FQ-0NN" line) beats one that mentions it;
      2. an OPEN PR beats a merged/closed one — a newer closed PR must not park a row whose work is still open;
      3. the row's existing PR keeps the association when both are equally strong;
      4. the higher PR number (the newest) breaks the remaining tie.
    A MENTION-only PR decides nothing (#2640 QS3): when no candidate claims the row, only the row's own existing
    association may decide its status — a passing mention neither retakes an association nor moves an unowned row.
    """
    if not candidates:
        return None
    row = str(item.get("id"))
    claimed = [p for p in candidates if row in rows_claimed_by(p)]
    owned = _as_pr_number(item.get("pr"))

    # QS3 / CX3 (#2640, codex-cloud): a mere mention is not evidence. When NO candidate claims the row, only the
    # row's own recorded PR is allowed to rank. Leaving mention-only rows in the pool let an unrelated OPEN mention
    # outrank the recorded PR and then be rejected, returning None instead of falling back to the association.
    if claimed:
        pool = claimed
    elif owned is not None:
        pool = [p for p in candidates if _as_pr_number(p.get("number")) == owned]
        # ...but a recorded PR whose own text DISCLAIMS the row is a statement, not silence: it may not close or
        # park a row it says it is not closing (cx-openai triage on f0ae3822f).
        pool = [p for p in pool if row not in _disclaimed_rows(p)]
    else:
        return None
    if not pool:
        return None

    def rank(pr: dict[str, Any]) -> tuple[int, int, int]:
        number = _as_pr_number(pr.get("number")) or 0
        return (1 if str(pr.get("state") or "").upper() == "OPEN" else 0,
                1 if number == owned else 0,
                number)

    return max(pool, key=rank)


def sync(queue: dict[str, Any], prs: Iterable[dict[str, Any]], *, now: str | None = None) -> dict[str, Any]:
    """Apply the rules to a queue document in memory. Returns a report; mutates a copy, never the input."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_row: dict[str, list[dict[str, Any]]] = {}
    by_number: dict[int, dict[str, Any]] = {}
    for pr in prs:
        number = _as_pr_number(pr.get("number"))
        if number is not None:
            by_number.setdefault(number, pr)
        for row in rows_named_by(pr):
            by_row.setdefault(row, []).append(pr)

    doc = json.loads(json.dumps(queue))  # deep copy: the caller's object stays clean
    changes: list[dict[str, Any]] = []
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        candidates = list(by_row.get(str(item.get("id"))) or [])
        # CX2 (#2640, codex-cloud): a row's recorded association is evidence in its own right. The census is built
        # from current body/branch wording, so a PR whose text no longer names the row was dropped from its own row's
        # candidates — leaving a merged PR's row queued (dispatchable) or a closed PR's row never parked. Index the
        # census by number and add the recorded PR independently of the wording.
        recorded = _as_pr_number(item.get("pr"))
        if recorded is not None and recorded not in {_as_pr_number(p.get("number")) for p in candidates}:
            recorded_pr = by_number.get(recorded)
            # ...unless that PR's own text DISCLAIMS the row ("Closes FQ-021, not FQ-022."). A body that stopped
            # naming the row is silence; a body that names it under a negation is a statement, and the recorded
            # association cannot close or park a row the PR says it is not closing (cx-openai triage, f0ae3822f).
            if recorded_pr is not None and str(item.get("id")) not in _disclaimed_rows(recorded_pr):
                candidates.append(recorded_pr)
        pr = choose_pr(item, candidates)
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


def _commit(path: Path, snapshot: str, rendered: str) -> Path | None:
    """Replace the queue only if it still holds ``snapshot``; the whole boundary runs under an exclusive lock.

    QS4 (#2640; cx-openai-2/cx-openai-5 P1 and cc-deepseek-5 N1): this run read the queue, spent seconds-to-minutes
    collecting GitHub state, then wrote its stale snapshot back. Anything that happened to the file in between —
    another agent's decision, an operator's HELD_* — was silently overwritten. A byte comparison before the write is
    not enough: a peer can write after it. So the whole compare/backup/replace is serialized under ``<queue>.lock``
    (cooperative writers take the same lock), the byte check is repeated after the backup I/O, and the replacement is
    an atomic temp-file rename. Any movement of the file returns None (refuse) and writes nothing.

    Returns the backup path on success, or None when the queue moved and this run must not write.
    """
    lock_path = path.with_name(path.name + ".lock")
    tmp_path = path.with_name(path.name + ".tmp")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            current = path.read_text(encoding="utf-8")
            if current != snapshot:
                return None
            bak = _backup(path)  # hookable in tests; reads the file as it is right now
            if path.read_text(encoding="utf-8") != current:
                return None  # a peer wrote during the backup I/O: its bytes win
            with tmp_path.open("w", encoding="utf-8") as fh:
                fh.write(rendered)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
            return bak
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _emit(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps({k: v for k, v in report.items() if k != "queue"}, indent=2))
        return
    print(f"{report['schema']} as_of {report['as_of']}: {report['changed']} change(s)")
    for c in report["changes"]:
        print(f"  {c['id']}: {c['from']['status']} -> {c['to']['status']}  ({c['why']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync AUDIT_FIX_QUEUE.json status from open/merged/closed PRs.")
    ap.add_argument("--queue", default=str(DEFAULT_QUEUE))
    ap.add_argument("--apply", action="store_true", help="write the queue (default is a dry run)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    path = Path(args.queue)
    snapshot = path.read_text(encoding="utf-8")
    queue = json.loads(snapshot)
    try:
        report = sync(queue, gh_pr_list())
    except FetchIncomplete as exc:
        # An incomplete census is unknown, not "0 change(s)" (#2640 B2/N2). Refuse to present a stale window as truth.
        print(f"REFUSED: could not read the whole PR census: {exc}. Nothing was written.", file=sys.stderr)
        return 2

    if not args.apply:
        _emit(report, args.json)
        if not args.json:
            print("dry run — pass --apply to write")
        return 0
    if report["changed"]:
        rendered = json.dumps(report["queue"], indent=1, ensure_ascii=False) + "\n"
        bak = _commit(path, snapshot, rendered)
        if bak is None:
            print(
                f"REFUSED: {path} changed while GitHub state was being collected (another writer's update would be "
                "lost). Nothing was written; re-run.",
                file=sys.stderr,
            )
            return 2
    else:
        bak = None  # nothing to write
    # N4 (#2640): emit only after the write boundary has decided. With --json --apply, a refused run must not hand a
    # stdout-only consumer a report for a write that did not happen.
    _emit(report, args.json)
    if not args.json and bak is not None:
        print(f"wrote {path} (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
