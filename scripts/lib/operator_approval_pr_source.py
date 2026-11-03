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
from scripts.lib.operator_approval_authority import load_context as load_authority

MAX_PRS = 100
MAX_FILES = 3000
REFRESH_S = 120.0
# Read-only reflection of the explicit refusals in trusted pr_merge_delegation.Host.collect.
# The generic legacy `held` label does not undo ratified delegated engineering.
EXPLICIT_OPERATOR_HOLD_LABELS = frozenset({"hold", "do-not-merge", "operator-hold", "broker", "broker_active_trader",
                                           "active-trader", "active_trader", "broker-active-trader"})


def _read(gh, path):
    data, warning = gh.get(path)
    if warning or data is None:
        raise core.Refused("GITHUB_PR_DETAIL_UNAVAILABLE", 503)
    return data


def changed_files(pr: dict, git: Callable, gh) -> list[str]:
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    try:
        names = git("diff", "--name-only", "--no-renames", f"{base}...{head}", "--").splitlines()
    except (subprocess.SubprocessError, OSError, core.Refused):
        names = []
        for page in range(1, MAX_FILES // 100 + 1):
            rows = _read(gh, f"repos/{gh.repo}/pulls/{int(pr['number'])}/files?per_page=100&page={page}")
            if (not isinstance(rows, list) or len(rows) > 100
                    or any(not isinstance(r, dict) or not isinstance(r.get("filename"), str)
                           or (r.get("status") == "renamed" and not isinstance(r.get("previous_filename"), str))
                           for r in rows)):
                raise core.Refused("GITHUB_PR_FILES_INVALID", 503)
            for record in rows:
                names.append(record["filename"])
                if record.get("previous_filename"):
                    names.append(record["previous_filename"])
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


def project(pr: dict, *, git: Callable, gh, as_of: str, annotations: Callable | None = None,
            authority=None) -> dict | None:
    """Exact-head projection; inputs may be synthetic. Closed/merged PRs never remain pending."""
    if pr.get("state") != "open" or pr.get("merged_at") or (pr.get("base") or {}).get("ref") != "main":
        return None
    head, base = (pr.get("head") or {}).get("sha", ""), (pr.get("base") or {}).get("sha", "")
    if not core.SHA.fullmatch(head) or not core.SHA.fullmatch(base):
        raise core.Refused("EXACT_PR_HEAD_REQUIRED", 503)
    files = changed_files(pr, git, gh)
    raw_labels = pr.get("labels")
    if (not isinstance(raw_labels, list)
            or any(not isinstance(row, str) and (not isinstance(row, dict) or not isinstance(row.get("name"), str))
                   for row in raw_labels)):
        raise core.Refused("PR_LABELS_UNAVAILABLE", 503)
    labels = {(row["name"] if isinstance(row, dict) else row).lower() for row in raw_labels}
    held = merge_hold_paths.held_classes(files)
    is_policy = "AGENTS.md" in files
    scope = authority.classify(files, head_sha=head) if authority is not None else None
    protected = bool(scope and scope.get("mode") == "delegated" and scope.get("complete")
                     and scope.get("operator_required"))
    explicit_hold = labels & EXPLICIT_OPERATOR_HOLD_LABELS
    scope_unknown = bool(scope and not scope.get("complete"))
    if not is_policy and not held and not protected and not explicit_hold and not scope_unknown and not (labels & merge_hold_paths.hold_labels()):
        return None
    # A label alone is not exact-head approval or evidence that a PR completed.
    number = int(pr["number"])
    same_active_version = False
    if is_policy:
        text, old = policy_text(head, git, gh), policy_text(base, git, gh)
        if text == old:
            return None
        match = re.search(r"^Policy-Version:\s*(\d+\.\d+\.\d+)\s*$", text, re.M)
        active_version = getattr(authority, "policy_version", None)
        if (match and isinstance(active_version, str) and re.fullmatch(r"\d+\.\d+\.\d+", active_version)
                and getattr(authority, "gap", None) is None
                and tuple(map(int, match[1].split("."))) < tuple(map(int, active_version.split(".")))):
            row = core.item(ident=f"policy:{number}", kind="POLICY", title=pr.get("title") or f"Policy PR #{number}",
                            proposed_by=(pr.get("user") or {}).get("login"), created_at=pr.get("created_at"),
                            doc=core.document(f"Policy {match[1]} is superseded by active {active_version}.",
                                              source_sha=head, version=match[1]), source="github_pr_snapshot", pr=number)
            row.update(source_sha=head, source_as_of=as_of, actionable=False,
                       resolution="superseded_by_active_policy", active_policy_sha=authority.policy_sha)
            return row
        same_active_version = bool(match and active_version == match[1] and getattr(authority, "gap", None) is None)
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
        if scope and explicit_hold:
            scope = {**scope, "operator_required": True, "next_actor": "operator", "reason": "explicit_hold_requires_resolution"}
        if scope and scope.get("complete") and scope.get("operator_required") is False:
            if labels & merge_hold_paths.hold_labels() and not scope.get("held_classes", sorted(held)):
                scope = {**scope, "complete": False, "gap": "HELD_LABEL_CLASS_UNRESOLVED"}
            else:
                return None  # Ratified delegated engineering belongs to its coordinator, not this queue.
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
    if authority is not None:
        if is_policy:
            if same_active_version:
                row.update(actionable=False, next_actor="coordinator",
                           next_action="Coordinator: reconcile this proposal with the already active policy version.",
                           source_gap="POLICY_VERSION_ALREADY_ACTIVE")
                row.pop("policy_approval_command", None)
                return row
            # An exact current token may already be recorded on GitHub before the PR merges.
            # Merge-intent digest approvals never substitute for this policy evidence.
            reviewed_head = None
            # ACTIVE metadata may be a bounded activation of an already reviewed head.
            # A mismatch asks the coordinator to verify continuation; it never asks for a new token by inference.
            if re.search(r"^Status:\s*ACTIVE\s*$", text, re.M) and doc["version"] == "30.0.0":
                try:
                    manifest = json.loads(git("show", f"{head}:config/agent_standing_authority.json"))
                    reviewed_head = (manifest.get("ratification") or {}).get("reviewed_head")
                except (subprocess.SubprocessError, OSError, core.Refused, ValueError, AttributeError):
                    pass
            approval = authority.policy_approval(pr=number, head_sha=head, version=doc["version"],
                                                  reviewed_head_sha=reviewed_head)
            row["approval"] = approval
            if approval.get("state") == "approved":
                row.update(resolution="policy_ratification_approved", actionable=False)
                row.pop("policy_approval_command", None)
            elif approval.get("state") != "pending":
                row.update(actionable=False, next_actor="coordinator", next_action="Coordinator: verify ratification evidence for this head.",
                           source_gap=approval.get("gap") or "POLICY_APPROVAL_EVIDENCE_UNAVAILABLE")
                row.pop("policy_approval_command", None)
        else:
            row["approval_scope"] = scope
            if not scope.get("complete"):
                row.update(actionable=False, next_actor="coordinator", next_action="Coordinator: verify the current approval authority.",
                           source_gap=scope.get("gap") or "APPROVAL_AUTHORITY_SCOPE_UNPROVEN")
    return row


class Snapshot:
    """Single-flight source, last good kept, with no request-thread GitHub calls."""
    def __init__(self, *, board, git, gh_factory=lifecycle.GitHubReader, annotations=None, clock=time.monotonic):
        self.board, self.git, self.gh_factory, self.annotations, self.clock = board, git, gh_factory, annotations, clock
        self.rows = None
        self.resolved = []
        self._failed_refresh = False
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
                stale = self._failed_refresh or not fresh or head != row.get("source_sha") or bool(row.get("source_gap"))
                if stale:
                    action = row.get("next_action") if row.get("source_gap") else "Coordinator: refresh the current PR evidence before acting."
                    row.update(actionable=False, stale=True, next_actor="coordinator", next_action=action)
                    row.pop("policy_approval_command", None)
                    gap = gap or "PR approval evidence does not match the current head"
                rows.append(row)
            return {"rows": rows, "resolved": list(self.resolved), "gap": gap, "as_of": self.as_of}

    def _refresh(self, prs):
        rows, gaps, resolved = [], [], []
        now = core.utc_now()
        as_of = lifecycle._iso(now)
        try:
            gh = self.gh_factory()
            authority = load_authority(git=self.git, gh=gh, now=now)
            if getattr(authority, "gap", None):
                gaps.append(f"Approval authority: {authority.gap}")
            for pr in prs[:MAX_PRS]:
                try:
                    row = project(pr, git=self.git, gh=gh, as_of=as_of, annotations=self.annotations, authority=authority)
                    if row:
                        if row.get("resolution"):
                            resolved.append(row)
                        elif row.get("source_gap"):
                            gaps.append(f"PR #{pr.get('number', '?')}: {row['source_gap']}")
                            rows.append(row)
                        else:
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
                present = {row.get("pr") for row in rows}
                rows.extend({**r, "source_gap": "PR_APPROVAL_DETAILS_UNAVAILABLE"}
                            for r in self.rows or [] if r.get("pr") in failed and r.get("pr") not in present)
                self.rows, self.resolved, self.as_of = rows, resolved, as_of
                self._failed_refresh = False
                self.warning = "; ".join(gaps[:6]) or None
        except Exception as exc:  # background source must leave the last good queue readable
            with self._lock:
                self._failed_refresh = True
                self.warning = f"PR approval refresh failed ({type(exc).__name__}); last good kept"
        finally:
            with self._lock:
                self._running = False
