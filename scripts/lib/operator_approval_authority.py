"""Read-only approval scope from one trusted, ratified current-main snapshot.

Call load_context once during a background refresh, then classify every PR using
that immutable context. Existing installed guard and canonical merge helpers own
all authority/path rules. No apply, merge, grant, label or push entrypoint is used.
Healthy pre-30 main keeps the legacy held-PR rule without inventing a source gap.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import stat
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPOSITORY = "PatsKiller/tardeai"
CANONICAL_REPOSITORY = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
MAX_SOURCE_BYTES = 2_000_000
MAX_COMMENT_PAGES = 10
MAX_PATHS = 6000
SHA = re.compile(r"[0-9a-f]{40}\Z")
SOURCE = "trusted_main_approval_authority"


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _at(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("aware_clock_required")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read(path: Path) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o022
        or info.st_size > MAX_SOURCE_BYTES
    ):
        raise ValueError("trusted_helper_file_unsafe")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("trusted_helper_budget_exceeded")
    return raw


def _installed_hooks() -> Path:
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    raw = _read(home / ".cursor/hooks.json")
    config = json.loads(raw)
    paths = {
        Path(row["command"]).parent
        for row in config["hooks"]["beforeShellExecution"]
        if isinstance(row, dict)
        and isinstance(row.get("command"), str)
        and Path(row["command"]).is_absolute()
        and row["command"].endswith("/guard-shell.sh")
    }
    if len(paths) != 1:
        raise ValueError("installed_guard_binding_unavailable")
    return paths.pop()


def _module(path: Path, expected: str) -> types.ModuleType:
    raw = _read(path)
    if raw != expected.encode("utf-8"):
        raise ValueError("trusted_helper_not_current_main")
    module = types.ModuleType("approval_authority_" + path.stem)
    module.__file__ = str(path)
    # Execute only bytes already matched to the same canonical current-main blob;
    # no import of feature-worktree code and no bytecode/cache write is needed.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _github(gh, path: str):
    data, warning = gh.get(path)
    if warning or data is None:
        raise ValueError("authority_github_source_unavailable")
    return data


def _comments(gh, pr: int) -> list[dict]:
    rows = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        batch = _github(gh, f"repos/{REPOSITORY}/issues/{pr}/comments?per_page=100&page={page}")
        if not isinstance(batch, list) or len(batch) > 100 or any(not isinstance(r, dict) for r in batch):
            raise ValueError("ratification_comments_invalid")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError("ratification_comments_truncated")


def _paths(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) > MAX_PATHS:
        raise ValueError("changed_paths_incomplete")
    if any(
        not isinstance(p, str) or not p or p.startswith("/") or ".." in p.split("/") or "\x00" in p or "\n" in p
        for p in values
    ):
        raise ValueError("changed_paths_invalid")
    return list(values)


@dataclass
class AuthorityContext:
    policy_sha: str | None
    as_of: str
    policy_version: str | None = None
    mode: str = "unavailable"
    gap: str | None = None
    authority: dict = field(default_factory=dict)
    guard: Any = None
    merge: Any = None
    hold_helper: Any = None
    hold_config: dict = field(default_factory=dict)
    gh: Any = None
    _comment_cache: dict = field(default_factory=dict, repr=False)

    def comments(self, pr: int) -> list[dict]:
        """One bounded immutable read per policy PR in this background context."""
        if type(pr) is not int or pr <= 0 or self.gh is None:
            raise ValueError("policy_comment_source_unavailable")
        if pr not in self._comment_cache:
            self._comment_cache[pr] = _comments(self.gh, pr)
        return self._comment_cache[pr]

    def classify(
        self, files, *, previous_paths=(), head_sha: str, paths_complete: bool = True, source_as_of: str | None = None
    ) -> dict:
        """Scope only, not permission to merge or proof of checks/reviews.

        previous_paths contains every renamed/deleted source path; callers must
        set paths_complete=False if any changed-file page or rename is missing.
        """
        result = {
            "operator_required": True,
            "next_actor": "operator",
            "complete": self.gap is None,
            "gap": self.gap,
            "source": SOURCE,
            "as_of": self.as_of,
            "head_sha": head_sha if _sha(head_sha) else None,
            "policy_sha": self.policy_sha,
            "mode": self.mode,
            "reason": "legacy_held_operator_rule",
            "ratification": None,
            "held_classes": [],
        }
        try:
            paths = sorted(set(_paths(files) + _paths(previous_paths)))
            if not _sha(head_sha) or paths_complete is not True or not paths:
                raise ValueError("changed_paths_or_head_incomplete")
            if self.mode != "delegated" or self.gap:
                return result
            helper = self.merge
            requirements = self.authority.get("requirements")
            reserved = self.authority.get("reserved_paths")
            if (
                not isinstance(requirements, dict)
                or not isinstance(reserved, list)
                or not isinstance(requirements.get("excluded_globs"), list)
            ):
                raise ValueError("authority_scope_incomplete")
            patterns = (
                *helper.RESERVED,
                *helper.OPERATOR_ONLY,
                *helper.DECISION_PATHS,
                *reserved,
                *requirements["excluded_globs"],
            )
            if any(helper.hits(path, patterns) for path in paths):
                result["reason"] = "operator_reserved_or_live_decision"
                return result
            collect = getattr(helper, "collect_held_classes", None)
            if callable(collect):
                classes, _metadata = collect(paths, self.hold_config, self.hold_helper)
                if not isinstance(classes, list) or any(not isinstance(value, str) for value in classes):
                    raise ValueError("trusted_helper_class_result_invalid")
            else:
                # Earlier ratified v30 helpers expose the same pure decision through
                # held_classes + DELEGATED_HELD_CLASSES in Host.collect.
                classes = self.hold_helper.held_classes(paths, self.hold_config)
                delegated = getattr(helper, "DELEGATED_HELD_CLASSES", None)
                if not isinstance(classes, dict) or not isinstance(delegated, (set, frozenset)):
                    raise ValueError("trusted_helper_scope_contract_unavailable")
                result["held_classes"] = sorted(classes)
                if not set(classes).issubset(delegated):
                    result["reason"] = "held_class_operator_owned"
                    return result
            result["held_classes"] = sorted(classes)
            result.update(
                operator_required=False,
                next_actor="coordinator",
                reason="ratified_delegated_engineering",
                ratification=self.authority.get("ratification"),
            )
            return result
        except Exception:
            # Raw helper errors may contain local paths or metadata. Return only
            # a stable public gap and keep the more restrictive prior rule.
            result.update(complete=False, gap="APPROVAL_AUTHORITY_SCOPE_UNPROVEN", reason="scope_unproven")
            return result

    def policy_approval(
        self,
        *,
        pr: int,
        head_sha: str,
        version: str,
        comments: list | None = None,
        reviewed_head_sha: str | None = None,
    ) -> dict:
        """DISPLAY adjudication only, including proposed policies under legacy main.

        A genuine, public, unedited User comment whose entire body is the exact
        expected approval line can resolve this queue item. It does not activate
        main or the standing manifest. Existing installed authority validation is
        still mandatory before engineering scope can be delegated.

        A current/reviewed head mismatch needs a verified continuation helper.
        None exists here: return unknown, never infer another token is needed.
        """
        reviewed = reviewed_head_sha or head_sha
        out = {
            "state": "unknown",
            "head_sha": head_sha,
            "reviewed_head_sha": reviewed,
            "source": "canonical_policy_pr_comments",
            "as_of": self.as_of,
            "gap": None,
        }
        if (
            type(pr) is not int
            or pr <= 0
            or not _sha(head_sha)
            or not _sha(reviewed)
            or not isinstance(version, str)
            or not re.fullmatch(r"\d+\.\d+\.\d+", version)
        ):
            return {**out, "gap": "POLICY_RATIFICATION_IDENTITY_INVALID"}
        if reviewed != head_sha:
            return {**out, "gap": "POLICY_RATIFICATION_CONTINUATION_UNVERIFIED"}
        token = f"APPROVE_AGENTS_POLICY_{version.replace('.', '_')} {pr} {reviewed}"
        try:
            records = self.comments(pr) if comments is None else comments
            if (
                not isinstance(records, list)
                or len(records) > MAX_COMMENT_PAGES * 100
                or any(not isinstance(row, dict) for row in records)
            ):
                raise ValueError("invalid_comments")
            for row in records:
                user = row.get("user")
                if not isinstance(user, dict) or user.get("login") != REPOSITORY.split("/")[0]:
                    continue
                body = row.get("body")
                if not isinstance(body, str) or body.strip() != token:
                    continue
                cid, created, updated = row.get("id"), row.get("created_at"), row.get("updated_at")
                urls = {
                    f"https://github.com/{REPOSITORY}/{kind}/{pr}#issuecomment-{cid}" for kind in ("issues", "pull")
                }
                if (
                    user.get("type") != "User"
                    or type(cid) is not int
                    or cid <= 0
                    or row.get("html_url") not in urls
                    or not isinstance(created, str)
                    or created != updated
                ):
                    raise ValueError("ambiguous_matching_comment")
                stamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError("ambiguous_matching_timestamp")
                return {
                    **out,
                    "state": "approved",
                    "proof": {
                        "comment_id": cid,
                        "url": row["html_url"],
                        "created_at": _at(stamp),
                        "reviewed_head_sha": reviewed,
                    },
                }
            return {**out, "state": "pending"}
        except Exception:
            return {**out, "gap": "POLICY_RATIFICATION_EVIDENCE_INVALID"}


def load_context(*, git: Callable, gh, now: datetime, source_root: Path = CANONICAL_REPOSITORY) -> AuthorityContext:
    """Bounded background-only reads; all helper rules come from trusted main.

    git must be the canonical checkout's read-only git reader. The local remote
    ref and GitHub main must agree. Installed guard code and canonical helper
    code must exactly match that same SHA before they may classify a PR.
    """
    context = AuthorityContext(None, _at(now), gh=gh)
    try:
        sha = git("rev-parse", "refs/remotes/origin/main").strip()
        remote = _github(gh, f"repos/{REPOSITORY}/commits/main")
        if not _sha(sha) or not isinstance(remote, dict) or remote.get("sha") != sha:
            raise ValueError("trusted_main_snapshot_disagrees")
        context.policy_sha = sha
        policy = git("show", f"{sha}:AGENTS.md")
        version = re.search(r"^Policy-Version:\s*(\d+)\.(\d+)\.(\d+)\s*$", policy, re.M)
        status = re.search(r"^Status:\s*(\w+)\s*$", policy, re.M)
        if not version or not status or status[1] != "ACTIVE":
            raise ValueError("trusted_main_policy_inactive_or_invalid")
        context.policy_version = ".".join(version.groups())
        if tuple(map(int, version.groups())) < (30, 0, 0):
            context.mode = "legacy"
            return context
        manifest = json.loads(git("show", f"{sha}:config/agent_standing_authority.json"))
        hook_rel = ".cursor/hooks/guard_standing_policy.py"
        guard = _module(_installed_hooks() / "guard_standing_policy.py", git("show", f"{sha}:{hook_rel}"))
        context.guard = guard
        local = guard.authorize(
            policy, manifest, capability="coordinator_merge", policy_sha=sha, revoked=guard.revoked_marker()
        )
        if local.get("ok") is not True:
            raise ValueError("standing_authority_local_proof_invalid")
        pr = local["authority"]["ratification"]["pr"]
        if type(pr) is not int or pr <= 0:
            raise ValueError("ratification_pr_invalid")
        verified = guard.verify_ratification_evidence(
            local["authority"], context.comments(pr), REPOSITORY.split("/")[0]
        )
        authority = verified.get("authority")
        if (
            verified.get("ok") is not True
            or not isinstance(authority, dict)
            or authority.get("policy_sha") != sha
            or authority.get("capability") != "coordinator_merge"
            or authority.get("manifest_schema") != guard.SCHEMA
            or authority.get("repository") != REPOSITORY
            or authority.get("ratification") != local["authority"].get("ratification")
            or not isinstance(authority.get("ratification_evidence"), dict)
        ):
            raise ValueError("standing_authority_comment_proof_invalid")
        merge_rel, hold_rel = "scripts/lib/pr_merge_delegation.py", "scripts/lib/merge_hold_paths.py"
        merge = _module(Path(source_root) / merge_rel, git("show", f"{sha}:{merge_rel}"))
        hold = _module(Path(source_root) / hold_rel, git("show", f"{sha}:{hold_rel}"))
        config = json.loads(git("show", f"{sha}:config/merge_hold_paths.json"))
        context.mode, context.authority = "delegated", verified["authority"]
        context.merge, context.hold_helper, context.hold_config = merge, hold, config
        return context
    except Exception:
        context.gap = "APPROVAL_AUTHORITY_SOURCE_UNAVAILABLE"
        return context
