"""Current policy and held PR approvals, derived asynchronously from the existing PR board.

No network on a queue GET. A bounded background refresh reuses WorkBoard's PR
listing, reads changed-file names and AGENTS.md only, and retains the last good
projection on failure. GitHub fallback reads are pinned to the observed head.
No merge, grant, label, ratification or other mutation is performed here.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Callable

from scripts.lib import agent_claim_lifecycle as lifecycle
from scripts.lib import merge_hold_paths
from scripts.lib import operator_approvals as core

MAX_PRS = 100
MAX_FILES = 3000
REFRESH_S = 120.0


def _read(gh, path):
    data, warning = gh.get(path)
    if warning or data is None:
        raise core.Refused("GITHUB_PR_DETAIL_UNAVAILABLE", 503)
    return data


def changed_files(pr: dict, git: Callable, gh) -> list[str]:
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    try:
        names = git("diff", "--name-only", f"{base}...{head}", "--").splitlines()
    except (subprocess.SubprocessError, OSError, core.Refused):
        names = []
        for page in range(1, MAX_FILES // 100 + 1):
            rows = _read(gh, f"repos/{gh.repo}/pulls/{int(pr['number'])}/files?per_page=100&page={page}")
            if not isinstance(rows, list):
                raise core.Refused("GITHUB_PR_FILES_INVALID", 503)
            names.extend(r["filename"] for r in rows if isinstance(r, dict) and isinstance(r.get("filename"), str))
            if len(rows) < 100:
                # The files route follows a branch; bind its result back to the observed head.
                verify_open_head(pr, gh)
                return names
        raise core.Refused("GITHUB_PR_FILES_BUDGET_EXCEEDED", 503)
    if len(names) > MAX_FILES:
        raise core.Refused("GITHUB_PR_FILES_BUDGET_EXCEEDED", 503)
    return names


def policy_text(sha: str, git: Callable, gh) -> str:
    try:
        return git("show", f"{sha}:AGENTS.md")
    except (subprocess.SubprocessError, OSError, core.Refused):
        doc = _read(gh, f"repos/{gh.repo}/contents/AGENTS.md?ref={sha}")
        if not isinstance(doc, dict) or doc.get("encoding") != "base64" or int(doc.get("size") or 0) > core.MAX_DOCUMENT:
            raise core.Refused("POLICY_COMMIT_CONTENT_UNAVAILABLE", 503)
        try:
            text = base64.b64decode(doc["content"], validate=False).decode("utf-8")
        except (KeyError, ValueError, UnicodeError) as exc:
            raise core.Refused("POLICY_COMMIT_CONTENT_INVALID", 503) from exc
        if len(text) > core.MAX_DOCUMENT:
            raise core.Refused("POLICY_COMMIT_CONTENT_UNAVAILABLE", 503)
        return text


def verify_open_head(pr: dict, gh) -> None:
    observed = _read(gh, f"repos/{gh.repo}/pulls/{int(pr['number'])}")
    if (not isinstance(observed, dict) or observed.get("state") != "open" or observed.get("merged_at")
            or (observed.get("head") or {}).get("sha") != pr["head"]["sha"]):
        raise core.Refused("PR_HEAD_CHANGED", 409)


def project(pr: dict, *, git: Callable, gh, as_of: str, annotations: Callable | None = None) -> dict | None:
    """Exact-head projection; inputs may be synthetic. Closed/merged PRs never remain pending."""
    if pr.get("state") != "open" or pr.get("merged_at") or (pr.get("base") or {}).get("ref") != "main":
        return None
    head, base = (pr.get("head") or {}).get("sha", ""), (pr.get("base") or {}).get("sha", "")
    if not core.SHA.fullmatch(head) or not core.SHA.fullmatch(base):
        raise core.Refused("EXACT_PR_HEAD_REQUIRED", 503)
    files = changed_files(pr, git, gh)
    labels = {r.get("name") if isinstance(r, dict) else r for r in pr.get("labels") or []}
    held = merge_hold_paths.held_classes(files)
    is_policy = "AGENTS.md" in files
    if not is_policy and not held and not (labels & merge_hold_paths.hold_labels()):
        return None
    # A label alone is not exact-head approval or evidence that a PR completed.
    number = int(pr["number"])
    if is_policy:
        text, old = policy_text(head, git, gh), policy_text(base, git, gh)
        if text == old:
            return None
        match = re.search(r"^Policy-Version:\s*(\d+\.\d+\.\d+)\s*$", text, re.M)
        doc = core.document(text, base_text=old, source_sha=head, version=match[1] if match else "",
                            source_verified=True)
        notes = annotations(pr, doc) if annotations else None
        if notes:
            doc = core.document(text, base_text=old, source_sha=head, version=doc["version"],
                                source_verified=True, annotations=notes)
        row = core.item(ident=f"policy:{number}", kind="POLICY", title=pr.get("title") or f"Policy PR #{number}",
                        proposed_by=(pr.get("user") or {}).get("login"), created_at=pr.get("created_at"),
                        doc=doc, source="github_pr_snapshot", pr=number)
        action = "Read this exact policy version and record its approval line."
    else:
        public = {"pr": number, "head_sha": head, "hold_classes": sorted(held),
                  "hold_labels": sorted(labels & merge_hold_paths.hold_labels()),
                  "draft": bool(pr.get("draft")), "next_action": "Independent exact-head reviews and green checks are required before operator merge."}
        row = core.item(ident=f"held-pr:{number}", kind="RELEASE", title=pr.get("title") or f"Held PR #{number}",
                        proposed_by=(pr.get("user") or {}).get("login"), created_at=pr.get("created_at"),
                        doc=core.document(json.dumps(public, indent=2), source_sha=head),
                        source="github_pr_snapshot", pr=number, governed_href=f"/releases?pr={number}")
        row["decision_mode"] = "GOVERNED_PATH"
        action = "Review this held pull request in Releases; merge after its required reviews and checks pass."
    row.update(source_sha=head, source_as_of=as_of, actionable=True, stale=False, updated_at=pr.get("updated_at"),
               pr_url=f"https://github.com/{gh.repo}/pull/{number}", next_actor="operator", next_action=action,
               source_refs=[f"github_pr:{number}:{head}"])
    return row


class Snapshot:
    """Single-flight source, last good kept, with no request-thread GitHub calls."""
    def __init__(self, *, board, git, gh_factory=lifecycle.GitHubReader, annotations=None, clock=time.monotonic):
        self.board, self.git, self.gh_factory, self.annotations, self.clock = board, git, gh_factory, annotations, clock
        self.rows = None
        self.warning = "PR approval details: first refresh pending"
        self.as_of = None
        self._at = None
        self._running = False
        self._lock = threading.Lock()

    def view(self, *, background=True):
        self.board._kick_prs(background=background)
        with self.board._lock:
            prs = None if self.board.prs is None else list(self.board.prs)
            warning = self.board.prs_warning
            observed_at = self.board._prs_at
            upstream = prs
        with self._lock:
            due = self._at is None or self.clock() - self._at >= REFRESH_S
            # A cold view must not set its clock until the upstream snapshot arrives.
            if prs is not None and due and not self._running:
                self._running = True
                self._at = self.clock()
                if background:
                    threading.Thread(target=self._refresh, args=(prs,), daemon=True, name="operator-approval-prs").start()
                else:
                    # Run outside this lock so the synchronous fixture follows the same path.
                    pass
            else:
                prs = None
        if prs is not None and not background:
            self._refresh(prs)
        with self._lock:
            gap = self.warning or warning
            if observed_at is None or self.clock() - observed_at > REFRESH_S * 2:
                gap = gap or "Open PR snapshot is stale"
            current = {pr.get("number"): pr for pr in upstream or []}
            fresh = upstream is not None and not warning and observed_at is not None and self.clock() - observed_at <= REFRESH_S * 2
            rows = []
            for known in self.rows or []:
                # A fresh successful census can resolve removed PRs immediately. An outage
                # preserves history but cannot leave a stale approval line copyable.
                if fresh and known.get("pr") not in current:
                    continue
                row = dict(known)
                head = (current.get(row.get("pr"), {}).get("head") or {}).get("sha")
                stale = bool(gap) or not fresh or head != row.get("source_sha")
                if stale:
                    row.update(actionable=False, stale=True, next_action="Refresh the current PR evidence before acting.")
                    row.pop("policy_approval_command", None)
                    gap = gap or "PR approval evidence does not match the current head"
                rows.append(row)
            return {"rows": rows, "gap": gap, "as_of": self.as_of}

    def _refresh(self, prs):
        rows, gaps = [], []
        as_of = lifecycle._iso(core.utc_now())
        try:
            gh = self.gh_factory()
            for pr in prs[:MAX_PRS]:
                try:
                    row = project(pr, git=self.git, gh=gh, as_of=as_of, annotations=self.annotations)
                    if row:
                        rows.append(row)
                except (core.Refused, subprocess.SubprocessError, OSError, ValueError, TypeError, KeyError) as exc:
                    reason = exc.code if isinstance(exc, core.Refused) else type(exc).__name__
                    gaps.append(f"PR #{pr.get('number', '?')}: {reason}")
            if len(prs) >= MAX_PRS:
                gaps.append("Open PR census may be truncated at 100")
            with self._lock:
                # Per-PR failures keep their known item, explicitly incomplete; a confirmed
                # closed or removed PR is absent from the successful listing and drops out.
                failed = {int(p.split('#', 1)[1].split(':', 1)[0]) for p in gaps if p.startswith("PR #") and p.split('#', 1)[1].split(':', 1)[0].isdigit()}
                rows.extend(r for r in self.rows or [] if r.get("pr") in failed)
                self.rows, self.as_of = rows, as_of
                self.warning = "; ".join(gaps[:6]) or None
        except Exception as exc:  # background source must leave the last good queue readable
            with self._lock:
                self.warning = f"PR approval refresh failed ({type(exc).__name__}); last good kept"
        finally:
            with self._lock:
                self._running = False
