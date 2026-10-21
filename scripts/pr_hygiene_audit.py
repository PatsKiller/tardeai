#!/usr/bin/env python3
"""pr_hygiene_audit.py — audit every open PR and local unpushed work, read-only (operator process plan 2026-10-21).

Why: on 2026-10-21 a 59-PR backlog built up unnoticed, needed an ad-hoc triage, and caused a duplicate fix (#1906
re-did #1836). The operator wants PR hygiene audited on every iteration and alerted back.

Per open PR (GitHub through ``gh``: ``gh pr list --json`` first, the REST API through ``gh api`` with the same gh
auth as the fallback):
  age, last update, draft, hold markers (DO-NOT-MERGE / PROPOSED in title or body, or a do-not-merge label);
  commits behind main and mergeability (``git merge-tree --write-tree --name-only origin/main <head>``; without a
  local clone: the compare API and GitHub's own ``mergeable``);
  required checks (branch protection contexts) passed or not, and on which head sha.
Findings (pure detectors, ``detect_*``; tests/test_pr_hygiene_audit_20261021.py):
  CONFLICT    P2  the head does not merge cleanly into main
  SUPERSEDED  P2  head already contained in main (confidence high), or every file the PR touches changed on main
                  since the PR's last update (heuristic: confidence low, medium when it also conflicts)
  DUPLICATE   P2  two open PRs edit the same function or overlapping hunks of the same non-ledger file
  STACKED     P3  a PR whose base is not main and whose base PR merged, whose base branch is gone, or whose base
                  moved past the PR's fork point
  STALE_HOLD  P3  held (DO-NOT-MERGE / PROPOSED) and untouched for more than 3 days
  UNPUSHED    P3  local branches (main repo and .claude/worktrees/*) with commits on no remote branch — branch,
                  commit count and last subject only, never contents. Not part of the alert fingerprint.

    python3 scripts/pr_hygiene_audit.py --report       # print only (also --dry-run): writes nothing, queues nothing
    python3 scripts/pr_hygiene_audit.py --report --json
    python3 scripts/pr_hygiene_audit.py                # real run: receipt + alert-on-change + weekly digest

A real run writes exactly: the LaneRunReceipt@v2 receipt ``<state root>/data/runtime/pr-hygiene-audit_last.json``
(read by GET /api/v2/needs-action, source ``pr_hygiene``), its alert state
``<state root>/data/runtime/pr_hygiene_audit_alert_state.json``, and — only when the finding set gained a finding,
or once per ISO week for the digest — ONE host comms intent (agents/pr_hygiene_findings or
agents/pr_hygiene_weekly_digest, producer pr_hygiene_audit, config/host_comms_intent_routes.json; DIGEST -> P2)
queued straight into the coordination ledger's comms_intents table (the #1899 hermes-scorer pattern: never a sender,
never lib/host_comms_intents, whose closure reaches broker modules). Plus the tree/blob objects ``git merge-tree
--write-tree`` writes to the local object store (unreferenced; gc collects them).

It never merges, closes, comments, labels, pushes, deletes or edits a PR or a branch: every gh call goes through
:func:`_assert_read_only_gh` (``pr list|view`` and GET-only ``gh api``) and every git call through
:func:`_assert_read_only_git`. ``--fetch`` (off by default) runs one plain ``git fetch origin`` (no prune).
Exit 0 = the audit completed (findings are output, not failures); 1 = GitHub could not be read (fatal
dependency_unavailable; the failed receipt keeps the previous ok_at); 2 = usage.

MBI_BEHAVIOR = 0. No broker, no database, no send. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

LANE_ID = "pr-hygiene-audit"
SCHEMA = "PrHygieneAudit@v1"
MAIN_BRANCH = "main"
STALE_HOLD_DAYS = 3.0
UNPUSHED_PRINT_MAX = 15
GH_TIMEOUT_S = 60
GIT_TIMEOUT_S = 60
#: Shared append-only ledgers every PR touches; an overlap there is a merge chore, never a duplicate fix.
LEDGER_FILES = frozenset({
    "docs/INDEX.md",
    "scripts/run_cio_hardening_ci.py",
    "docs/implementation/n8n-maturity/cron-inventory/README.md",
    "DOCS_AND_AGENTS_UPDATE_BACKLOG.md",
    "docs/DOCS_AND_AGENTS_UPDATE_BACKLOG.md",
})
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".go", ".rs")
#: Used only when branch protection cannot be read (needs admin scope); the receipt names the source.
FALLBACK_REQUIRED_CHECKS = ("cio-hardening", "agent-governance", "release-readiness")
CHECK_PASS = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
CHECK_FAIL = frozenset({"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR", "STALE"})
HOLD_RE = re.compile(r"DO[-_ ]?NOT[-_ ]?MERGE", re.I)
PROPOSED_RE = re.compile(r"\bPROPOSED\b")  # upper-case marker only; prose "proposed" is not a hold
SEVERITY = {"CONFLICT": "P2", "SUPERSEDED": "P2", "DUPLICATE": "P2", "STACKED": "P3", "STALE_HOLD": "P3",
            "UNPUSHED": "P3"}
#: Finding kinds whose set drives the change alert. UNPUSHED is local agent scratch work: reported, never alerted.
ALERT_KINDS = frozenset({"CONFLICT", "SUPERSEDED", "DUPLICATE", "STACKED", "STALE_HOLD"})

PR_FIELDS = ("number,title,body,isDraft,createdAt,updatedAt,headRefName,headRefOid,baseRefName,mergeable,url,"
             "isCrossRepository,labels,author,statusCheckRollup")

# ── alerting (host comms intent, never a send) ─────────────────────────────────────────────────────────────────
ALERT_PRODUCER = "pr_hygiene_audit"
ALERT_DOMAIN = "agents"
ALERT_KIND = "pr_hygiene_findings"
DIGEST_KIND = "pr_hygiene_weekly_digest"
ALERT_STATE_NAME = "pr_hygiene_audit_alert_state.json"


class AuditError(Exception):
    """GitHub (or the local clone, when required) could not be read."""


class ReadOnlyViolation(AssertionError):
    """A gh/git argv that could mutate a PR, a branch or a remote was refused before it ran."""


# ── read-only command runners ──────────────────────────────────────────────────────────────────────────────────

_GH_MUTATING_FLAGS = frozenset({"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"})
_GIT_READ_SUBCOMMANDS = frozenset({"rev-parse", "rev-list", "merge-base", "merge-tree", "log", "for-each-ref",
                                   "worktree", "cat-file", "remote", "show-ref"})


def _assert_read_only_gh(args: Sequence[str]) -> None:
    args = list(args)
    if not args:
        raise ReadOnlyViolation("empty gh argv")
    if args[0] == "pr":
        if len(args) < 2 or args[1] not in ("list", "view"):
            raise ReadOnlyViolation(f"gh pr {args[1:2]} refused (only list/view)")
    elif args[0] == "api":
        if any(a in _GH_MUTATING_FLAGS or a.startswith(("--method=", "-X", "--field=", "--raw-field=")) for a in args[1:]):
            raise ReadOnlyViolation("gh api refused: only GET without fields")
        if any(a == "graphql" for a in args[1:]):
            raise ReadOnlyViolation("gh api graphql refused (a query body could carry a mutation)")
    elif args[:2] == ["repo", "view"]:
        pass
    else:
        raise ReadOnlyViolation(f"gh {args[0]} refused")


def _assert_read_only_git(args: Sequence[str], *, allow_fetch: bool = False) -> None:
    args = list(args)
    if not args:
        raise ReadOnlyViolation("empty git argv")
    sub = args[0]
    if sub == "fetch":
        if not allow_fetch or any(a in ("--prune", "-p", "--prune-tags", "--force", "-f") for a in args[1:]):
            raise ReadOnlyViolation("git fetch refused (needs --fetch; never prune or force)")
        return
    if sub not in _GIT_READ_SUBCOMMANDS:
        raise ReadOnlyViolation(f"git {sub} refused")
    if sub == "worktree" and args[1:2] != ["list"]:
        raise ReadOnlyViolation("git worktree: only list")
    if sub == "remote" and args[1:2] not in (["get-url"], ["-v"]):
        raise ReadOnlyViolation("git remote: only get-url / -v")


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _default_run(argv: Sequence[str], *, cwd: Optional[str] = None, timeout: int = 60) -> "subprocess.CompletedProcess[str]":
    env = dict(os.environ)
    env.setdefault("GH_PROMPT_DISABLED", "1")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    return subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def _decode_json_stream(text: str) -> Any:
    """``gh api --paginate`` prints one JSON document per page; arrays are concatenated."""
    text = (text or "").strip()
    if not text:
        return None
    dec = json.JSONDecoder()
    docs, i = [], 0
    while i < len(text):
        doc, j = dec.raw_decode(text, i)
        docs.append(doc)
        i = j
        while i < len(text) and text[i].isspace():
            i += 1
    if len(docs) == 1:
        return docs[0]
    if all(isinstance(d, list) for d in docs):
        return [x for d in docs for x in d]
    return docs


class Gh:
    """``gh`` with read-only enforcement. ``run`` is injectable (tests feed canned JSON)."""

    def __init__(self, slug: str, run: Optional[Callable[[Sequence[str]], Any]] = None):
        self.slug = slug
        self._run = run or (lambda argv: _default_run(["gh", *argv], timeout=GH_TIMEOUT_S))
        self.calls: list[list[str]] = []

    def json(self, *args: str) -> Any:
        _assert_read_only_gh(args)
        self.calls.append(list(args))
        try:
            r = self._run(list(args))
        except (OSError, subprocess.SubprocessError) as exc:
            raise AuditError(f"gh unavailable: {type(exc).__name__}") from exc
        if r.returncode != 0:
            raise AuditError(f"gh {args[0]} exit {r.returncode}: {(r.stderr or '').strip()[:160]}")
        try:
            return _decode_json_stream(r.stdout)
        except ValueError as exc:
            raise AuditError(f"gh {args[0]} returned non-JSON") from exc

    def api(self, path: str, *, paginate: bool = False) -> Any:
        return self.json("api", *(["--paginate"] if paginate else []), path)


class Git:
    """``git -C <repo>`` with read-only enforcement. ``run`` is injectable; ``None`` repo = no local clone."""

    def __init__(self, repo: Optional[Path], run: Optional[Callable[..., Any]] = None, *, allow_fetch: bool = False):
        self.repo = Path(repo) if repo else None
        self.allow_fetch = allow_fetch
        self._run = run or (lambda argv: _default_run(["git", "-C", str(self.repo), *argv], timeout=GIT_TIMEOUT_S))

    @property
    def available(self) -> bool:
        return self.repo is not None

    def raw(self, *args: str) -> "subprocess.CompletedProcess[str]":
        _assert_read_only_git(args, allow_fetch=self.allow_fetch)
        if self.repo is None:
            raise AuditError("no local clone")
        return self._run(list(args))

    def out(self, *args: str) -> Optional[str]:
        r = self.raw(*args)
        return r.stdout if r.returncode == 0 else None

    def has_commit(self, ref: str) -> bool:
        return self.out("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None


# ── parsing + pure helpers ─────────────────────────────────────────────────────────────────────────────────────


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _days(now: datetime, ts: Any) -> Optional[float]:
    d = _parse_ts(ts)
    return None if d is None else round((now - d).total_seconds() / 86400.0, 2)


def hold_markers(title: str, body: str, labels: Iterable[str] = ()) -> list[str]:
    """DO-NOT-MERGE / PROPOSED in the title or body, or a do-not-merge label."""
    out = []
    text = f"{title or ''}\n{body or ''}"
    if HOLD_RE.search(text) or any(HOLD_RE.search(str(lb or "")) for lb in labels):
        out.append("DO-NOT-MERGE")
    if PROPOSED_RE.search(text):
        out.append("PROPOSED")
    return out


def normalize_pr_graphql(p: Mapping[str, Any]) -> dict[str, Any]:
    checks = []
    for c in p.get("statusCheckRollup") or []:
        if not isinstance(c, Mapping):
            continue
        name = c.get("name") or c.get("context")
        state = (c.get("conclusion") or c.get("state") or "").upper()
        if (c.get("status") or "").upper() not in ("", "COMPLETED") and not c.get("conclusion"):
            state = "PENDING"
        checks.append({"name": name, "state": state or "PENDING"})
    return {
        "number": int(p["number"]), "title": p.get("title") or "", "body": p.get("body") or "",
        "draft": bool(p.get("isDraft")), "created_at": p.get("createdAt"), "updated_at": p.get("updatedAt"),
        "head": p.get("headRefName") or "", "head_sha": p.get("headRefOid") or "", "base": p.get("baseRefName") or "",
        "url": p.get("url") or "", "cross_repo": bool(p.get("isCrossRepository")),
        "labels": [lb.get("name") for lb in p.get("labels") or [] if isinstance(lb, Mapping)],
        "author": (p.get("author") or {}).get("login") if isinstance(p.get("author"), Mapping) else None,
        "gh_mergeable": p.get("mergeable"), "checks": checks, "checks_source": "graphql_rollup",
    }


def normalize_pr_rest(p: Mapping[str, Any]) -> dict[str, Any]:
    head, base = p.get("head") or {}, p.get("base") or {}
    head_repo = (head.get("repo") or {}).get("full_name")
    base_repo = (base.get("repo") or {}).get("full_name")
    return {
        "number": int(p["number"]), "title": p.get("title") or "", "body": p.get("body") or "",
        "draft": bool(p.get("draft")), "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
        "head": head.get("ref") or "", "head_sha": head.get("sha") or "", "base": base.get("ref") or "",
        "url": p.get("html_url") or "", "cross_repo": bool(head_repo and base_repo and head_repo != base_repo),
        "labels": [lb.get("name") for lb in p.get("labels") or [] if isinstance(lb, Mapping)],
        "author": (p.get("user") or {}).get("login"), "gh_mergeable": None, "checks": None, "checks_source": None,
    }


def required_checks_status(checks: Optional[list[dict]], required: Sequence[str]) -> dict[str, Any]:
    """PASS when every required context concluded in CHECK_PASS on the head; FAIL when any failed; else PENDING."""
    if checks is None:
        return {"status": "UNKNOWN", "missing": list(required), "failed": []}
    by: dict[str, list[str]] = {}
    for c in checks:
        by.setdefault(str(c.get("name")), []).append(str(c.get("state") or "").upper())
    failed, missing, pending = [], [], []
    for name in required:
        states = by.get(name)
        if not states:
            missing.append(name)
        elif any(s in CHECK_FAIL for s in states):
            failed.append(name)
        elif not all(s in CHECK_PASS for s in states):
            pending.append(name)
    status = "FAIL" if failed else ("PENDING" if missing or pending else "PASS")
    return {"status": status, "missing": missing, "failed": failed, "pending": pending}


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_FUNC_CTX_RE = re.compile(r"\b(def|class|function|func|fn)\b|=>|^\s*(export\s+)?(async\s+)?[\w$]+\s*\(")


def parse_patch_hunks(patch: str) -> list[dict[str, Any]]:
    """Unified-diff hunks -> [{func, span: (lo, hi) in OLD line numbers, deletes: bool, body: sha1 of the +/- lines}].
    A span covers every deleted old line and every insertion point (the old line an added line goes before)."""
    hunks: list[dict[str, Any]] = []
    cur = None
    old = 0
    for line in (patch or "").splitlines():
        m = _HUNK_RE.match(line)
        if m:
            cur = {"func": (m.group(5) or "").strip(), "touched": [], "deletes": False, "lines": []}
            hunks.append(cur)
            old = int(m.group(1))
            if m.group(2) == "0":  # pure insertion after line `old`
                old += 1
            continue
        if cur is None or line.startswith("\\"):
            continue
        if line.startswith("-"):
            cur["touched"].append(old)
            cur["deletes"] = True
            cur["lines"].append(line)
            old += 1
        elif line.startswith("+"):
            cur["touched"].append(old)
            cur["lines"].append(line)
        else:
            old += 1
    out = []
    for h in hunks:
        if h["touched"]:
            body = hashlib.sha1("\n".join(h["lines"]).encode("utf-8")).hexdigest()[:12]
            out.append({"func": h["func"], "span": (min(h["touched"]), max(h["touched"])), "deletes": h["deletes"],
                        "body": body})
    return out


def _is_func_ctx(ctx: str) -> bool:
    return bool(ctx) and bool(_FUNC_CTX_RE.search(ctx))


def _file_overlap(path: str, a: list[dict], b: list[dict]) -> Optional[dict[str, Any]]:
    """Same function (code files, a def-like hunk context) or intersecting hunk spans. A hunk whose +/- lines are
    identical in both PRs is a SHARED change (a stack, a rebased copy, a common base commit), never evidence of two
    independent fixes, so it is set aside before comparing."""
    shared = {h["body"] for h in a} & {h["body"] for h in b}
    a = [h for h in a if h["body"] not in shared]
    b = [h for h in b if h["body"] not in shared]
    code = path.endswith(CODE_SUFFIXES)
    funcs = sorted({h["func"] for h in a if code and _is_func_ctx(h["func"])}
                   & {h["func"] for h in b if code and _is_func_ctx(h["func"])})
    spans = []
    for ha in a:
        for hb in b:
            lo, hi = max(ha["span"][0], hb["span"][0]), min(ha["span"][1], hb["span"][1])
            if lo <= hi:
                spans.append({"lines": [lo, hi], "both_modify": ha["deletes"] and hb["deletes"]})
    if not funcs and not spans:
        return None
    return {"file": path, "functions": [f[:120] for f in funcs][:5], "overlapping_lines": spans[:5],
            "shared_hunks": len(shared)}


# ── detectors (pure) ───────────────────────────────────────────────────────────────────────────────────────────


def detect_duplicates(pr_files: Mapping[int, Mapping[str, list[dict]]]) -> list[dict[str, Any]]:
    """Pairs of open PRs editing the same functions or overlapping hunks in the same non-ledger files."""
    out = []
    nums = sorted(pr_files)
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            shared = sorted((set(pr_files[a]) & set(pr_files[b])) - LEDGER_FILES)
            overlaps = [o for f in shared if (o := _file_overlap(f, pr_files[a][f], pr_files[b][f]))]
            if not overlaps:
                continue
            strong = len(overlaps) >= 2 or any(s["both_modify"] for o in overlaps for s in o["overlapping_lines"])
            out.append({"prs": [a, b], "files": overlaps, "shared_files": len(shared),
                        "confidence": "high" if strong else "medium"})
    return out


def detect_superseded(*, contained_in_main: Optional[bool], files: Sequence[str], main_changed: Optional[set],
                      conflict: Optional[bool]) -> Optional[dict[str, Any]]:
    """Head already in main (high), or every non-ledger file it touches changed on main since its last update
    (heuristic: low; medium when the PR also conflicts)."""
    if contained_in_main:
        return {"reason": "head_contained_in_main", "confidence": "high"}
    own = [f for f in files if f not in LEDGER_FILES]
    if not own or main_changed is None:
        return None
    if all(f in main_changed for f in own):
        return {"reason": "all_files_changed_on_main_since_last_update", "files": len(own),
                "confidence": "medium" if conflict else "low"}
    return None


def detect_stale_hold(pr: Mapping[str, Any], now: datetime, days: float = STALE_HOLD_DAYS) -> Optional[dict]:
    if not pr.get("holds"):
        return None
    idle = _days(now, pr.get("updated_at"))
    if idle is not None and idle > days:
        return {"holds": pr["holds"], "idle_days": idle}
    return None


STACKED_ON_RE = re.compile(r"stacked on (?:PR\s*)?#(\d+)", re.I)


def declared_parent(pr: Mapping[str, Any]) -> Optional[int]:
    """A main-based PR that says "stacked on #N" in its title or body carries #N's commits (a content stack)."""
    m = STACKED_ON_RE.search(f"{pr.get('title') or ''}\n{pr.get('body') or ''}")
    return int(m.group(1)) if m and int(m.group(1)) != pr.get("number") else None


def detect_stacked(pr: Mapping[str, Any], base_state: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """base_state = {base, merged_pr, closed_pr, exists, base_moved} for a PR whose base is not main, or whose
    declared parent ("stacked on #N") is another PR."""
    if not base_state:
        return None
    reasons = []
    if base_state.get("merged_pr"):
        reasons.append(f"base PR #{base_state['merged_pr']} merged")
    if base_state.get("closed_pr"):
        reasons.append(f"base PR #{base_state['closed_pr']} closed unmerged")
    if base_state.get("exists") is False and not base_state.get("merged_pr"):
        reasons.append("base branch gone")
    if base_state.get("base_moved"):
        reasons.append("base moved since the PR was cut")
    base = base_state.get("base") or pr.get("base")
    return {"base": base, "reasons": reasons} if reasons else None


def stack_related(a: Mapping[str, Any], b: Mapping[str, Any], open_by_num: Mapping[int, Mapping[str, Any]],
                  git: Optional["Git"], main_ref: str) -> Optional[str]:
    """Why two PRs are one stack (their overlap is shared commits, not two fixes), or None.

    declared: one says "stacked on #N" and the chain reaches the other; ancestry: one head is in the other's
    history; shared_unmerged: their merge-base is not on main (they carry the same unmerged commits)."""
    def chain(pr: Mapping[str, Any]) -> set:
        seen, cur = set(), pr
        while cur is not None:
            parent = declared_parent(cur)
            if parent is None or parent in seen:
                break
            seen.add(parent)
            cur = open_by_num.get(parent)
        return seen
    if b.get("number") in chain(a) or a.get("number") in chain(b):
        return "declared"
    if git is None or not a.get("head_ref_used") or not b.get("head_ref_used"):
        return None
    ha, hb = a["head_ref_used"], b["head_ref_used"]
    for x, y in ((ha, hb), (hb, ha)):
        if git.raw("merge-base", "--is-ancestor", x, y).returncode == 0:
            return "ancestry"
    mb = (git.out("merge-base", ha, hb) or "").strip()
    if mb and git.raw("merge-base", "--is-ancestor", mb, main_ref).returncode == 1:
        return "shared_unmerged"
    return None


def split_stack_families(candidates: list[dict], open_by_num: Mapping[int, Mapping[str, Any]],
                         git: Optional["Git"], main_ref: str) -> tuple[list[dict], list[dict]]:
    """Duplicate candidates -> (independent duplicates, stack-family pairs reported as info)."""
    dups, fams = [], []
    for d in candidates:
        a, b = (open_by_num.get(n) or {"number": n} for n in d["prs"])
        why = stack_related(a, b, open_by_num, git, main_ref)
        if why:
            fams.append({"prs": d["prs"], "relation": why})
        else:
            dups.append(d)
    return dups, fams


def build_findings(prs: list[dict], duplicates: list[dict], unpushed: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(kind: str, key: str, pr: Optional[dict], title: str, detail: Any, confidence: Optional[str] = None,
            prs_: Optional[list[int]] = None, url: Optional[str] = None):
        out.append({"key": key, "kind": kind, "severity": SEVERITY[kind], "pr": pr["number"] if pr else None,
                    "prs": prs_ or ([pr["number"]] if pr else []), "title": title[:200],
                    "url": url if url is not None else (pr or {}).get("url"), "confidence": confidence,
                    "detail": detail})

    for pr in prs:
        n = pr["number"]
        if pr.get("conflict"):
            add("CONFLICT", f"CONFLICT:#{n}", pr, f"#{n} conflicts with main: {pr['title']}",
                {"files": (pr.get("conflict_files") or [])[:10], "source": pr.get("mergeability_source")})
        if pr.get("superseded"):
            s = pr["superseded"]
            add("SUPERSEDED", f"SUPERSEDED:#{n}", pr, f"#{n} looks superseded ({s['reason']}): {pr['title']}", s,
                s["confidence"])
        if pr.get("stacked"):
            add("STACKED", f"STACKED:#{n}", pr, f"#{n} stacked on {pr['base']}: {', '.join(pr['stacked']['reasons'])}",
                pr["stacked"])
        if pr.get("stale_hold"):
            add("STALE_HOLD", f"STALE_HOLD:#{n}", pr,
                f"#{n} held ({'/'.join(pr['stale_hold']['holds'])}) and idle {pr['stale_hold']['idle_days']:.1f} d",
                pr["stale_hold"])
    by_num = {p["number"]: p for p in prs}
    for d in duplicates:
        a, b = d["prs"]
        files = ", ".join(o["file"] for o in d["files"][:3])
        add("DUPLICATE", f"DUPLICATE:#{a}+#{b}", by_num.get(a), f"#{a} and #{b} edit the same code ({files})",
            d, d["confidence"], prs_=[a, b])
    for u in unpushed:
        add("UNPUSHED", f"UNPUSHED:{u['branch']}", None,
            f"local branch {u['branch']}: {u['commits']} commit(s) on no remote", u, url="")
    return out


def fingerprint(findings: Iterable[Mapping[str, Any]]) -> tuple[str, list[str]]:
    keys = sorted(f["key"] for f in findings if f["kind"] in ALERT_KINDS)
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16], keys


# ── collection ─────────────────────────────────────────────────────────────────────────────────────────────────


def list_open_prs(gh: Gh) -> tuple[list[dict], str]:
    """GraphQL-backed ``gh pr list`` first; REST ``gh api`` pulls (same auth) when it fails."""
    try:
        rows = gh.json("pr", "list", "--repo", gh.slug, "--state", "open", "--limit", "500", "--json", PR_FIELDS)
        if isinstance(rows, list):
            return [normalize_pr_graphql(r) for r in rows], "gh_pr_list"
    except AuditError:
        pass
    rows = gh.api(f"repos/{gh.slug}/pulls?state=open&per_page=100", paginate=True)
    if not isinstance(rows, list):
        raise AuditError("REST pulls returned no list")
    prs = [normalize_pr_rest(r) for r in rows]
    for pr in prs:
        try:
            runs = gh.api(f"repos/{gh.slug}/commits/{pr['head_sha']}/check-runs?per_page=100")
            pr["checks"] = [{"name": c.get("name"),
                             "state": (c.get("conclusion") or ("PENDING" if c.get("status") != "completed" else "")).upper()}
                            for c in (runs or {}).get("check_runs", [])]
            pr["checks_source"] = "rest_check_runs"
        except AuditError:
            pr["checks"] = None
    return prs, "rest_api"


def required_contexts(gh: Gh, base: str = MAIN_BRANCH) -> tuple[list[str], str]:
    try:
        ctx = gh.api(f"repos/{gh.slug}/branches/{base}/protection/required_status_checks")
        names = list((ctx or {}).get("contexts") or [])
        if names:
            return names, "branch_protection"
    except AuditError:
        pass
    return list(FALLBACK_REQUIRED_CHECKS), "fallback_constant"


def pr_files(gh: Gh, number: int) -> dict[str, list[dict]]:
    rows = gh.api(f"repos/{gh.slug}/pulls/{number}/files?per_page=100", paginate=True) or []
    out: dict[str, list[dict]] = {}
    for r in rows if isinstance(rows, list) else []:
        name = r.get("filename")
        if name:
            out[name] = parse_patch_hunks(r.get("patch") or "")
    return out


def main_changes_since(git: Git, main_ref: str, since: datetime) -> list[tuple[datetime, set]]:
    """First-parent history of main after ``since``: [(commit time, files)] (merges diffed against parent 1)."""
    text = git.out("log", "--first-parent", "-m", f"--since={since.isoformat()}", "--format=%x00%ct",
                   "--name-only", main_ref)
    if text is None:
        return []
    out = []
    for chunk in text.split("\x00"):
        lines = [x for x in chunk.splitlines() if x.strip()]
        if not lines or not lines[0].isdigit():
            continue
        out.append((datetime.fromtimestamp(int(lines[0]), timezone.utc), set(lines[1:])))
    return out


def merge_tree(git: Git, main_ref: str, head_ref: str) -> tuple[Optional[bool], list[str]]:
    """``git merge-tree --write-tree --name-only``: (conflict?, conflicted files). None when it could not run."""
    r = git.raw("merge-tree", "--write-tree", "--name-only", main_ref, head_ref)
    if r.returncode not in (0, 1):
        return None, []
    lines = (r.stdout or "").splitlines()
    files = []
    for line in lines[1:]:
        if not line.strip():
            break
        files.append(line.strip())
    return r.returncode == 1, files


def _head_ref(git: Git, pr: Mapping[str, Any]) -> Optional[str]:
    sha = pr.get("head_sha")
    if sha and git.has_commit(sha):
        return sha
    if not pr.get("cross_repo") and pr.get("head") and git.has_commit(f"origin/{pr['head']}"):
        return f"origin/{pr['head']}"
    return None


def assess_with_git(git: Git, pr: dict, main_ref: str, changes: list[tuple[datetime, set]]) -> None:
    head = _head_ref(git, pr)
    pr["head_ref_used"] = head
    if head is None:
        pr["mergeability_source"] = "github_mergeable (head not in local clone)"
        pr["conflict"] = pr.get("gh_mergeable") == "CONFLICTING" if pr.get("gh_mergeable") else None
        return
    if head != pr.get("head_sha"):
        pr["local_head_stale"] = True
    cnt = git.out("rev-list", "--count", f"{head}..{main_ref}")
    pr["behind_main"] = int(cnt.strip()) if cnt and cnt.strip().isdigit() else None
    anc = git.raw("merge-base", "--is-ancestor", head, main_ref)
    pr["contained_in_main"] = anc.returncode == 0 if anc.returncode in (0, 1) else None
    conflict, files = merge_tree(git, main_ref, head)
    pr["conflict"], pr["conflict_files"], pr["mergeability_source"] = conflict, files, "git_merge_tree"
    upd = _parse_ts(pr.get("updated_at"))
    if upd is not None:
        changed: set = set()
        for ts, fs in changes:
            if ts > upd:
                changed |= fs
        pr["main_changed"] = changed


def assess_with_api(gh: Gh, pr: dict) -> None:
    try:
        cmp = gh.api(f"repos/{gh.slug}/compare/{MAIN_BRANCH}...{pr['head_sha']}") or {}
        pr["behind_main"] = cmp.get("behind_by")
        pr["contained_in_main"] = cmp.get("status") in ("behind", "identical")
    except AuditError:
        pr["behind_main"], pr["contained_in_main"] = None, None
    pr["mergeability_source"] = "github_mergeable"
    pr["conflict"] = (pr.get("gh_mergeable") == "CONFLICTING") if pr.get("gh_mergeable") else None
    pr["main_changed"] = None


def base_state(gh: Gh, git: Git, pr: Mapping[str, Any]) -> dict[str, Any]:
    """A PR based on another branch: was that branch's PR merged, is the branch gone, did it move past the PR?"""
    base = pr["base"]
    st: dict[str, Any] = {"base": base, "merged_pr": None, "exists": None, "base_moved": None}
    try:
        rows = gh.json("pr", "list", "--repo", gh.slug, "--state", "merged", "--head", base, "--json",
                       "number,mergedAt", "--limit", "5") or []
        if rows:
            st["merged_pr"] = rows[0].get("number")
    except AuditError:
        pass
    if git.available:
        ref = f"origin/{base}"
        st["exists"] = git.has_commit(ref)
        head = pr.get("head_ref_used")
        if st["exists"] and head:
            r = git.raw("merge-base", "--is-ancestor", ref, head)
            st["base_moved"] = r.returncode == 1 if r.returncode in (0, 1) else None
    else:
        try:
            cmp = gh.api(f"repos/{gh.slug}/compare/{pr['head_sha']}...{base}") or {}
            st["exists"] = True
            st["base_moved"] = int(cmp.get("ahead_by") or 0) > 0
        except AuditError:
            st["exists"] = None
    return st


def parent_state(gh: Gh, git: Git, pr: Mapping[str, Any], parent: int, open_by_num: Mapping[int, Mapping]) -> dict:
    """A content stack ("stacked on #N"): #N merged or closed, or #N's head no longer in this PR's history."""
    st: dict[str, Any] = {"base": f"#{parent}", "merged_pr": None, "closed_pr": None, "exists": True,
                          "base_moved": None}
    par = open_by_num.get(parent)
    if par is None:
        try:
            info = gh.json("pr", "view", str(parent), "--repo", gh.slug, "--json", "state,mergedAt") or {}
        except AuditError:
            return {**st, "exists": None}
        state = str(info.get("state") or "").upper()
        if state == "MERGED":
            st["merged_pr"] = parent
        elif state == "CLOSED":
            st["closed_pr"] = parent
        return st
    head = pr.get("head_ref_used")
    if git.available and head and par.get("head_sha") and git.has_commit(par["head_sha"]):
        r = git.raw("merge-base", "--is-ancestor", par["head_sha"], head)
        st["base_moved"] = r.returncode == 1 if r.returncode in (0, 1) else None
    return st


def pr_heads(gh: Gh) -> Optional[dict[str, dict]]:
    """branch -> {number, state} of the newest PR (any state) whose head is that branch; None when unreadable."""
    try:
        rows = gh.json("pr", "list", "--repo", gh.slug, "--state", "all", "--limit", "1000", "--json",
                       "number,headRefName,state") or []
    except AuditError:
        return None
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: int(x.get("number") or 0)):
        if r.get("headRefName"):
            out[r["headRefName"]] = {"number": r.get("number"), "state": str(r.get("state") or "").upper()}
    return out


def scan_unpushed(git: Git, heads: Optional[Mapping[str, Mapping[str, Any]]] = None) -> dict[str, Any]:
    """Local branches with commits on no remote branch, plus detached worktree heads under .claude/worktrees/*.
    Branch, commit count, last subject and date only — never contents.

    ``heads`` (branch -> newest PR {number, state}) separates real unpushed work (no PR, or an OPEN PR whose head
    is behind the local branch) from settled leftovers: a branch whose PR merged or closed keeps local commits on no
    remote once GitHub deleted the remote branch after a squash merge. Settled branches are counted, not listed as
    findings. Without ``heads`` (GitHub unreadable) every branch is reported."""
    if not git.available:
        return {"measured": False, "reason": "no local clone", "branches": []}
    refs = git.out("for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/heads")
    if refs is None:
        return {"measured": False, "reason": "for-each-ref failed", "branches": []}
    checked_out: dict[str, str] = {}
    detached: list[tuple[str, str]] = []
    wt = git.out("worktree", "list", "--porcelain") or ""
    path = None
    head = None
    for line in wt.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("HEAD "):
            head = line[5:]
        elif line.startswith("branch "):
            checked_out[line[7:].removeprefix("refs/heads/")] = path or ""
        elif line == "detached" and path and "/.claude/worktrees/" in path and head:
            detached.append((f"(detached) {Path(path).name}", head))
        elif not line:
            path = head = None
    out = []
    settled: dict[str, int] = {}
    items = [tuple(x.split("\t", 1)) for x in refs.splitlines() if "\t" in x] + detached
    for name, sha in items:
        cnt = git.out("rev-list", "--count", sha, "--not", "--remotes")
        n = int(cnt.strip()) if cnt and cnt.strip().isdigit() else 0
        if n <= 0:
            continue
        meta = (git.out("log", "-1", "--format=%s%x00%cI", sha) or "").rstrip("\n").split("\x00")
        wt_path = checked_out.get(name, "")
        pr = (heads or {}).get(name) or {}
        row = {"branch": name, "commits": n, "last_subject": (meta[0] if meta else "")[:160],
               "last_commit_at": meta[1] if len(meta) > 1 else None,
               "worktree": Path(wt_path).name if wt_path else None,
               "pr": pr.get("number"), "pr_state": pr.get("state")}
        if pr.get("state") in ("MERGED", "CLOSED"):
            settled[pr["state"]] = settled.get(pr["state"], 0) + 1
            continue
        out.append(row)
    out.sort(key=lambda u: str(u.get("last_commit_at") or ""), reverse=True)
    return {"measured": True, "pr_map": heads is not None, "branches": out, "settled_local": settled}


def resolve_repo(explicit: Optional[str]) -> Optional[Path]:
    """--repo, else TRADEAI_PR_HYGIENE_REPO, else the clone this script lives in (if it is one). A worktree resolves
    to its main repo (the common dir's parent) so branches of every worktree are seen."""
    cand = explicit or os.environ.get("TRADEAI_PR_HYGIENE_REPO") or str(_SCRIPTS.parent)
    p = Path(cand)
    if not (p / ".git").exists():
        return None
    try:
        r = _default_run(["git", "-C", str(p), "rev-parse", "--path-format=absolute", "--git-common-dir"], timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            common = Path(r.stdout.strip())
            if common.name == ".git":
                return common.parent
    except (OSError, subprocess.SubprocessError):
        pass
    return p


def resolve_slug(explicit: Optional[str], git: Git) -> Optional[str]:
    if explicit:
        return explicit
    if os.environ.get("TRADEAI_PR_HYGIENE_SLUG"):
        return os.environ["TRADEAI_PR_HYGIENE_SLUG"]
    if git.available:
        url = (git.out("remote", "get-url", "origin") or "").strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    return None


# ── the audit ──────────────────────────────────────────────────────────────────────────────────────────────────


def audit(gh: Gh, git: Git, *, now: Optional[datetime] = None, scan_local: bool = True) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if git.available and git.allow_fetch:
        git.raw("fetch", "--quiet", "origin")
    prs, source = list_open_prs(gh)
    required, req_source = required_contexts(gh)
    main_ref = f"origin/{MAIN_BRANCH}"
    use_git = git.available and git.has_commit(main_ref)
    oldest = min((d for d in (_parse_ts(p.get("updated_at")) for p in prs) if d), default=now)
    changes = main_changes_since(git, main_ref, oldest) if use_git and prs else []
    files_by_pr: dict[int, dict[str, list[dict]]] = {}
    errors: dict[str, int] = {}
    open_by_num = {p["number"]: p for p in prs}
    for pr in prs:
        pr["age_days"] = _days(now, pr.get("created_at"))
        pr["idle_days"] = _days(now, pr.get("updated_at"))
        pr["holds"] = hold_markers(pr["title"], pr["body"], pr.get("labels") or [])
        pr["required_checks"] = {**required_checks_status(pr.get("checks"), required), "head": pr.get("head_sha")}
        try:
            files_by_pr[pr["number"]] = pr_files(gh, pr["number"])
        except AuditError:
            errors["pr_files_unreadable"] = errors.get("pr_files_unreadable", 0) + 1
            files_by_pr[pr["number"]] = {}
        if use_git:
            assess_with_git(git, pr, main_ref, changes)
        else:
            assess_with_api(gh, pr)
        pr["superseded"] = detect_superseded(contained_in_main=pr.get("contained_in_main"),
                                             files=list(files_by_pr[pr["number"]]), main_changed=pr.get("main_changed"),
                                             conflict=pr.get("conflict"))
        pr["stale_hold"] = detect_stale_hold(pr, now)
        parent = declared_parent(pr) if pr["base"] == MAIN_BRANCH else None
        pr["stacked_on"] = pr["base"] if pr["base"] != MAIN_BRANCH else (f"#{parent}" if parent else None)
        if pr["base"] != MAIN_BRANCH:
            pr["stacked"] = detect_stacked(pr, base_state(gh, git, pr))
        elif parent:
            pr["stacked"] = detect_stacked(pr, parent_state(gh, git, pr, parent, open_by_num))
        else:
            pr["stacked"] = None
    candidates = detect_duplicates({n: f for n, f in files_by_pr.items() if f})
    duplicates, families = split_stack_families(candidates, open_by_num, git if use_git else None, main_ref)
    local = (scan_unpushed(git, pr_heads(gh)) if scan_local
             else {"measured": False, "reason": "--no-local", "branches": []})
    findings = build_findings(prs, duplicates, local.get("branches") or [])
    fp, keys = fingerprint(findings)
    counts = {k: sum(1 for f in findings if f["kind"] == k) for k in SEVERITY}
    return {
        "schema": SCHEMA, "as_of": now.isoformat(), "repo": gh.slug, "source": source,
        "mergeability": "git_merge_tree" if use_git else "github_mergeable",
        "required_checks": {"contexts": required, "source": req_source},
        "open_prs": len(prs), "drafts": sum(1 for p in prs if p["draft"]), "held": sum(1 for p in prs if p["holds"]),
        "required_checks_failing": sum(1 for p in prs if p["required_checks"]["status"] == "FAIL"),
        "counts": counts, "fingerprint": fp, "alert_keys": keys, "errors": errors,
        "findings": findings, "prs": [_compact(p) for p in prs], "local_unpushed": local,
        "stack_families": families,
    }


def _compact(p: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("number", "title", "url", "draft", "head", "head_sha", "base", "age_days", "idle_days", "holds",
            "behind_main", "conflict", "mergeability_source", "contained_in_main", "required_checks")
    out = {k: p.get(k) for k in keys}
    out["title"] = str(out["title"])[:160]
    return out


# ── outputs ────────────────────────────────────────────────────────────────────────────────────────────────────


def summary_line(report: Mapping[str, Any]) -> str:
    c = report["counts"]
    local = report.get("local_unpushed") or {}
    return (f"open_prs={report['open_prs']} drafts={report['drafts']} held={report['held']} "
            f"conflict={c['CONFLICT']} superseded={c['SUPERSEDED']} duplicate={c['DUPLICATE']} "
            f"stacked={c['STACKED']} stale_hold={c['STALE_HOLD']} "
            f"required_checks_failing={report['required_checks_failing']} "
            f"unpushed_branches={c['UNPUSHED'] if local.get('measured') else 'NOT_MEASURED'}")


def print_report(report: Mapping[str, Any]) -> None:
    print(f"[pr-hygiene] {report['repo']} as_of {report['as_of']} source={report['source']} "
          f"mergeability={report['mergeability']} required={report['required_checks']['source']}")
    print("[pr-hygiene] " + summary_line(report))
    shown_unpushed = 0
    for f in sorted(report["findings"], key=lambda x: (x["severity"], x["kind"], x["key"])):
        if f["kind"] == "UNPUSHED":
            shown_unpushed += 1
            if shown_unpushed > UNPUSHED_PRINT_MAX:
                continue
        conf = f" ({f['confidence']})" if f.get("confidence") else ""
        print(f"  {f['severity']} {f['kind']:<10} {f['title']}{conf}  {f.get('url') or ''}")
    if shown_unpushed > UNPUSHED_PRINT_MAX:
        print(f"  P3 UNPUSHED   … {shown_unpushed - UNPUSHED_PRINT_MAX} more (--json lists all)")
    settled = (report.get("local_unpushed") or {}).get("settled_local") or {}
    if settled:
        print("[pr-hygiene] settled local branches (PR merged/closed, remote branch gone; not findings): "
              + ", ".join(f"{k.lower()} {v}" for k, v in sorted(settled.items())))


def _ledger_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Same resolution as scripts/n8n_coordination_gateway.default_ledger_path (not imported: its closure reaches
    broker modules; the test pins the two equal)."""
    source = os.environ if environ is None else environ
    explicit = source.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = source.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


class _LedgerConn:
    """The two attributes CommsIntentStore uses (``_conn``, ``lock``) on a plain sqlite connection to an EXISTING
    ledger (the hermes_watchlist_scorer / disk_usage_monitor pattern)."""

    read_only = False

    def __init__(self, path: Path):
        import sqlite3
        import threading
        self.lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()


def queue_host_intent(*, kind: str, subject: str, summary: str, execution_id: str,
                      ledger_path: Optional[Path] = None, now: Optional[float] = None) -> dict:
    """Queue ONE host comms intent (never a send). Raises ValueError(<reason>)."""
    import sqlite3
    import time
    from lib.n8n_fabric_store import (SUBJECT_MAX, SUMMARY_MAX, CommsIntentStore, FabricStoreError,
                                      load_host_intent_routes, load_intent_routes, merged_intent_routes)
    try:
        hosts = load_host_intent_routes()
        routes = merged_intent_routes(load_intent_routes(), hosts)
    except FabricStoreError as exc:
        raise ValueError(getattr(exc, "reason", "intent_routes_unreadable")) from exc
    route = hosts["routes"].get((ALERT_DOMAIN, kind))
    if route is None:
        raise ValueError("intent_unrouted")
    if route.get("producer") != ALERT_PRODUCER:
        raise ValueError("producer_refused")
    path = Path(ledger_path) if ledger_path is not None else _ledger_path()
    if not path.exists():
        raise ValueError("ledger_absent")

    def clean(text: str, limit: int) -> str:
        flat = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text or "")).split())
        return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"

    request = {"domain": ALERT_DOMAIN, "kind": kind, "subject": clean(subject, SUBJECT_MAX),
               "summary": clean(summary, SUMMARY_MAX), "workflow_id": f"host.{ALERT_PRODUCER}",
               "execution_id": str(execution_id)[:40], "node": LANE_ID}
    try:
        ledger = _LedgerConn(path)
    except (sqlite3.Error, OSError) as exc:
        raise ValueError("intent_store_unavailable") from exc
    try:
        store = CommsIntentStore(ledger, routes=routes)
        return dict(store.accept(request, caller_id=f"host:{ALERT_PRODUCER}",
                                 now=time.time() if now is None else now))
    except FabricStoreError as exc:
        raise ValueError(getattr(exc, "reason", "intent_store_unavailable")) from exc
    except sqlite3.Error as exc:
        raise ValueError("intent_store_unavailable") from exc
    finally:
        ledger.close()


def _execution_id() -> str:
    raw = os.environ.get("TRADEAI_RUN_ID") or f"manual-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    return (re.sub(r"[^A-Za-z0-9_-]", "-", raw)[-40:].strip("-_")) or "host"


def _read_state(path: Path) -> dict:
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=1), encoding="utf-8")
    tmp.replace(path)


def plan_alerts(report: Mapping[str, Any], state: Mapping[str, Any], now: datetime) -> list[dict[str, str]]:
    """Pure: which intents a real run queues. A change alert only when the alertable finding set GAINED a key (a
    shrinking set updates the state silently); a weekly digest once per ISO week."""
    out = []
    prev = set(state.get("alert_keys") or [])
    new = [k for k in report["alert_keys"] if k not in prev]
    if new and report.get("fingerprint") != state.get("fingerprint"):
        c = report["counts"]
        out.append({"kind": ALERT_KIND, "subject": f"PR hygiene: {len(new)} new finding(s), {report['open_prs']} open PRs",
                    "summary": (f"New: {', '.join(new[:8])}{' …' if len(new) > 8 else ''}. Totals: "
                                f"conflict {c['CONFLICT']}, superseded {c['SUPERSEDED']}, duplicate {c['DUPLICATE']}, "
                                f"stacked {c['STACKED']}, stale hold {c['STALE_HOLD']}. See Needs action (PR hygiene).")})
    week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    if state.get("digest_week") != week:
        out.append({"kind": DIGEST_KIND, "subject": f"PR hygiene weekly digest {week}",
                    "summary": f"{summary_line(report)}. Receipt data/runtime/{LANE_ID}_last.json.", "week": week})
    return out


def emit_alerts(report: Mapping[str, Any], *, state_path: Path, queue: Optional[Callable[..., dict]] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """Queue the planned intents; the state advances only for an intent that was queued (or store-folded), so a
    refused one is retried next run. Never raises: an alert failure must not mask the audit."""
    now = now or datetime.now(timezone.utc)
    queue = queue or queue_host_intent
    state = _read_state(state_path)
    result: dict[str, Any] = {"queued": [], "refused": {}}
    for plan in plan_alerts(report, state, now):
        try:
            receipt = queue(kind=plan["kind"], subject=plan["subject"], summary=plan["summary"],
                            execution_id=_execution_id())
        except Exception as exc:  # noqa: BLE001 — the reason is recorded
            result["refused"][plan["kind"]] = str(exc)[:80] or type(exc).__name__
            continue
        result["queued"].append({"kind": plan["kind"], "intent_id": (receipt or {}).get("intent_id")})
        if plan["kind"] == DIGEST_KIND:
            state["digest_week"] = plan["week"]
    if ALERT_KIND not in result["refused"]:
        state["fingerprint"], state["alert_keys"] = report["fingerprint"], report["alert_keys"]
    state["updated_at"] = now.isoformat()
    try:
        _write_state(state_path, state)
    except OSError as exc:
        result["state_error"] = type(exc).__name__
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="print only; write nothing, queue nothing")
    ap.add_argument("--report", action="store_true", help="same as --dry-run")
    ap.add_argument("--json", action="store_true", help="print the full report JSON")
    ap.add_argument("--repo", help="local clone (default: TRADEAI_PR_HYGIENE_REPO, else this script's clone)")
    ap.add_argument("--slug", help="owner/name (default: TRADEAI_PR_HYGIENE_SLUG, else origin's URL)")
    ap.add_argument("--fetch", action="store_true", help="run one plain `git fetch origin` first (no prune)")
    ap.add_argument("--no-local", action="store_true", help="skip the local unpushed-branch scan")
    a = ap.parse_args(argv)
    dry = a.dry_run or a.report

    repo = resolve_repo(a.repo)
    git = Git(repo, allow_fetch=a.fetch)
    slug = resolve_slug(a.slug, git)
    if not slug:
        print("[pr-hygiene] no GitHub slug (pass --slug or run inside a clone)", file=sys.stderr)
        return 2
    gh = Gh(slug)
    from lib.lane_last_receipt import dry_run_report, now_iso, receipt_path, write_lane_receipt
    started = now_iso()
    try:
        report = audit(gh, git, scan_local=not a.no_local)
    except AuditError as exc:
        print(f"[pr-hygiene] GitHub unreadable: {exc}", file=sys.stderr)
        if not dry:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="pr_hygiene_audit.py",
                               error=f"AuditError: {exc}",
                               output={"produced_count": 0, "attempted_count": 0,
                                       "skipped_reasons": {"dependency_unavailable": 1}})
        return 1
    if a.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print_report(report)
    if dry:
        try:
            state = _read_state(receipt_path(LANE_ID).parent / ALERT_STATE_NAME)
        except Exception:  # noqa: BLE001 — a dry run reports; it never fails on path resolution
            state = {}
        would = [p["kind"] for p in plan_alerts(report, state, datetime.now(timezone.utc))]
        dry_run_report(LANE_ID, {"summary": summary_line(report), "fingerprint": report["fingerprint"],
                                 "would_queue": would},
                       would_write=[f"data/runtime/{LANE_ID}_last.json", f"data/runtime/{ALERT_STATE_NAME}",
                                    "coordination ledger comms_intents (only on a gained finding / weekly digest)"])
        return 0
    path = receipt_path(LANE_ID)
    alerts = emit_alerts(report, state_path=path.parent / ALERT_STATE_NAME)
    summary = {k: report[k] for k in ("schema", "as_of", "repo", "source", "mergeability", "required_checks",
                                      "open_prs", "drafts", "held", "required_checks_failing", "counts",
                                      "fingerprint", "findings", "prs", "local_unpushed")}
    summary["alerts"] = alerts
    write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started, script="pr_hygiene_audit.py",
                       summary=summary,
                       output={"produced_count": report["open_prs"], "attempted_count": report["open_prs"],
                               "skipped_reasons": report["errors"],
                               "empty_reason": "no_new_input" if report["open_prs"] == 0 else None})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
