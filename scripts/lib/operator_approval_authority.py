"""Read-only approval scope from one trusted, ratified current-main snapshot.

Call load_context once during a background refresh, then classify every PR using
that immutable context. Existing installed guard and canonical merge helpers own
all authority/path rules. No apply, merge, grant, label or push entrypoint is used.
Healthy pre-30 main keeps the legacy held-PR rule without inventing a source gap.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
import os
import pwd
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPOSITORY = "PatsKiller/tardeai"
CANONICAL_REPOSITORY = Path(pwd.getpwuid(os.getuid()).pw_dir) / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"
MAX_SOURCE_BYTES = 2_000_000
MAX_COMMENT_PAGES = 10
MAX_PATHS = 6000
SHA = re.compile(r"[0-9a-f]{40}\Z")
SOURCE = "trusted_main_approval_authority"
_VERIFIED_MODULES: dict[str, types.ModuleType] = {}
_MODULE_LOCK = threading.RLock()


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


class _VerifiedSnapshotLoader(importlib.abc.SourceLoader):
    """Standard module loading from the verified snapshot, with no path/cache reread."""

    def __init__(self, path: Path, raw: bytes):
        self.path, self.raw = str(path), raw

    def get_filename(self, fullname: str) -> str:
        return self.path

    def get_data(self, path: str) -> bytes:
        if path != self.path:
            raise OSError("unverified_helper_read")
        return self.raw

    def get_code(self, fullname: str):
        # Bypass SourceLoader's filesystem/bytecode-cache lookup. The only code
        # source is the immutable owner-checked, current-main-matched snapshot.
        return self.source_to_code(self.raw, self.path)


def _module(path: Path, expected: str) -> types.ModuleType:
    # Validate every observation, including cache hits. Only code is cached;
    # load_context still reads policy/manifest/comments and revocation afresh.
    raw = _read(path)
    if raw != expected.encode("utf-8"):
        raise ValueError("trusted_helper_not_current_main")
    identity = hashlib.sha256(str(path).encode("utf-8") + b"\0" + raw).hexdigest()
    name = "approval_authority_" + path.stem + "_" + identity
    with _MODULE_LOCK:
        cached = _VERIFIED_MODULES.get(name)
        if cached is not None:
            # A generic sys.modules entry is never authority for the cache.
            sys.modules[name] = cached
            return cached
        loader = _VerifiedSnapshotLoader(path, raw)
        spec = importlib.util.spec_from_loader(name, loader, origin=str(path))
        if spec is None:
            raise ValueError("trusted_helper_spec_unavailable")
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(path)
        previous, had_previous = sys.modules.get(name), name in sys.modules
        sys.modules[name] = module
        _VERIFIED_MODULES[name] = module
        try:
            loader.exec_module(module)
        except BaseException:
            if _VERIFIED_MODULES.get(name) is module:
                _VERIFIED_MODULES.pop(name, None)
            if sys.modules.get(name) is module:
                if had_previous:
                    sys.modules[name] = previous
                else:
                    sys.modules.pop(name, None)
            raise
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


ACTIVATION_FILES = ("AGENTS.md", "config/agent_standing_authority.json", "docs/governance/AGENTS_HISTORY.md")


def _once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("activation_shape_unrecognized")
    return text.replace(old, new, 1)


def _activation_row(text: str, version: str, date: str, token: str, url: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith(f"| {version} |")]
    if len(rows) != 1:
        raise ValueError("activation_history_ambiguous")
    cells = [cell.strip() for cell in rows[0].split("|")[1:-1]]
    placeholder = f"PENDING `APPROVE_AGENTS_POLICY_{version.replace('.', '_')} <PR> <head_sha>`"
    if len(cells) != 6 or cells[1:3] != ["PENDING", "PROPOSED"] or cells[-1] != placeholder:
        raise ValueError("activation_history_shape_unrecognized")
    cells[1:3], cells[-1] = [date, "ACTIVE"], f"`{token}` (operator, {url})"
    return _once(text, rows[0], "| " + " | ".join(cells) + " |")


def _activation_banner(text: str, version: str, supersedes: str) -> str:
    banner = re.findall(rf"^\*\*{re.escape(version)} is PROPOSED \((MAJOR|MINOR|PATCH)\)\*\*", text, re.M)
    if len(banner) != 1:
        raise ValueError("activation_banner_ambiguous")
    text = _once(text, f"**{version} is PROPOSED ({banner[0]})**", f"**{version} is ACTIVE ({banner[0]})**")
    before = (
        "The operator directly authorized preparation; ratification is still required. Policy and capability manifest stay\n"
        f"PROPOSED and grant nothing until ratified and merged. **{supersedes} remains active.** Earlier banners and consolidation\n"
        "records are in docs/governance/AGENTS_HISTORY.md; old source branches remain. No broker, secret or deploy grant."
    )
    after = (
        "Ratified by the operator at the reviewed source head; this status-only edit takes effect on merge.\n"
        "Approval and consolidation records are in docs/governance/AGENTS_HISTORY.md; old source branches remain.\n"
        "No broker, secret or deploy grant."
    )
    return _once(text, before, after)


def _unique_json(raw: str):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate_manifest_key")
            out[key] = value
        return out

    return json.loads(raw, object_pairs_hook=pairs)


def verify_status_only_continuation(
    *, git: Callable, reviewed_head_sha: str, head_sha: str, version: str, pr: int, comment_proof: dict
) -> dict:
    """Compare every changed byte with the known ratifying-edit format.

    This comparator alone does not establish approval. policy_approval calls it
    only AFTER verifying the genuine exact reviewed-head public comment. It
    recognizes this repository's explicit activation format; unfamiliar formats
    stay unknown. No arbitrary Status/history line is ignored, and every other
    path must retain its reviewed tree content.
    """
    result = {
        "verified": False,
        "reviewed_head_sha": reviewed_head_sha,
        "head_sha": head_sha,
        "source": "exact_activation_transform",
        "gap": "POLICY_RATIFICATION_CONTINUATION_UNVERIFIED",
    }
    try:
        if (
            not _sha(reviewed_head_sha)
            or not _sha(head_sha)
            or type(pr) is not int
            or pr <= 0
            or not isinstance(version, str)
            or not re.fullmatch(r"\d+\.\d+\.\d+", version)
            or comment_proof.get("reviewed_head_sha") != reviewed_head_sha
        ):
            return result
        stamp = datetime.fromisoformat(comment_proof["created_at"].replace("Z", "+00:00"))
        at, date = _at(stamp), _at(stamp)[:10]
        url = comment_proof["url"]
        cid = comment_proof["comment_id"]
        if (
            type(cid) is not int
            or cid <= 0
            or url
            not in {f"https://github.com/{REPOSITORY}/{kind}/{pr}#issuecomment-{cid}" for kind in ("issues", "pull")}
        ):
            return result
        git("merge-base", "--is-ancestor", reviewed_head_sha, head_sha)
        names = git("diff", "--name-only", "--no-renames", reviewed_head_sha, head_sha, "--").splitlines()
        if len(names) != len(ACTIVATION_FILES) or set(names) != set(ACTIVATION_FILES):
            return result
        before, after = {}, {}
        for name in ACTIVATION_FILES:
            before[name] = git("show", f"{reviewed_head_sha}:{name}")
            after[name] = git("show", f"{head_sha}:{name}")
            if (
                not isinstance(before[name], str)
                or not isinstance(after[name], str)
                or len(before[name].encode()) > MAX_SOURCE_BYTES
                or len(after[name].encode()) > MAX_SOURCE_BYTES
            ):
                return result
        policy = before["AGENTS.md"]
        control = re.findall(r"(?ms)^```[ \t]*\n(Policy-Version:[^\n]*\n.*?)^```[ \t]*$", policy)
        if len(control) != 1:
            return result
        block = control[0]
        policy_version = re.search(r"^Policy-Version:[ \t]*(\d+\.\d+\.\d+)[ \t]*$", block, re.M)
        supersedes = re.search(r"^Supersedes:[ \t]*(\d+\.\d+\.\d+)[ \t]*$", block, re.M)
        if not policy_version or policy_version[1] != version or not supersedes:
            return result
        active_block = block
        for key, old, new in (("Status", "PROPOSED", "ACTIVE"), ("Effective-Date", "PENDING", date)):
            matches = list(re.finditer(rf"^({key}:[ \t]*){old}([ \t]*)$", active_block, re.M))
            if len(matches) != 1:
                return result
            match = matches[0]
            active_block = _once(active_block, match[0], match[1] + new + match[2])
        policy = _once(policy, block, active_block)
        token = f"APPROVE_AGENTS_POLICY_{version.replace('.', '_')} {pr} {reviewed_head_sha}"
        policy = _activation_row(_activation_banner(policy, version, supersedes[1]), version, date, token, url)
        if policy != after["AGENTS.md"]:
            return result
        manifest = _unique_json(before["config/agent_standing_authority.json"])
        ratification = {"approval_token": None, "pr": None, "reviewed_head": None}
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != "AgentStandingAuthority@v1"
            or manifest.get("status") != "PROPOSED"
            or manifest.get("ratification") != ratification
        ):
            return result
        if json.dumps(manifest, ensure_ascii=True, indent=2) + "\n" != before["config/agent_standing_authority.json"]:
            return result
        manifest["status"] = "ACTIVE"
        manifest["ratification"] = {"approval_token": token, "pr": pr, "reviewed_head": reviewed_head_sha}
        if json.dumps(manifest, ensure_ascii=True, indent=2) + "\n" != after["config/agent_standing_authority.json"]:
            return result
        history = before["docs/governance/AGENTS_HISTORY.md"]
        header, separator, tail = history.partition("\n## ")
        if not separator:
            return result
        observed = re.findall(r"^as_of:[ \t]*(.+)$", header, re.M)
        measured = re.findall(
            rf"^Measured at:[ \t]*{re.escape(version)} preparation from main [0-9a-f]{{7,40}}; PROPOSED, no ratification claimed$",
            header,
            re.M,
        )
        if len(observed) != 1 or len(measured) != 1:
            return result
        _at(datetime.fromisoformat(observed[0].replace("Z", "+00:00")))
        header = _once(header, observed[0], at)
        header = _once(
            header,
            measured[0],
            f"Measured at: operator ratification of reviewed source {reviewed_head_sha}; status-only edit effective on merge",
        )
        history = header + separator + tail
        history = _once(
            history,
            "merge-watching and the approved-plan registry rule. Ratification remains one later exact-head operator act.",
            f"merge-watching and the approved-plan registry rule. The operator ratified the reviewed source at {at}.",
        )
        history = _once(history, f"### {version} proposal record", f"### {version} ratification record")
        history = _activation_row(_activation_banner(history, version, supersedes[1]), version, date, token, url)
        if history != after["docs/governance/AGENTS_HISTORY.md"]:
            return result
        return {
            **result,
            "verified": True,
            "gap": None,
            "changed_paths": list(ACTIVATION_FILES),
            "approved_at": at,
            "effective_on_merge": True,
        }
    except Exception:
        return result


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
    git: Any = None
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

        A current/reviewed head mismatch is accepted only when every changed
        byte matches the bounded activation transform. Other deltas stay unknown;
        this display adjudication never infers another operator token is needed.
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
                proof = {
                    "comment_id": cid,
                    "url": row["html_url"],
                    "created_at": _at(stamp),
                    "reviewed_head_sha": reviewed,
                }
                if reviewed != head_sha:
                    continuation = verify_status_only_continuation(
                        git=self.git,
                        reviewed_head_sha=reviewed,
                        head_sha=head_sha,
                        version=version,
                        pr=pr,
                        comment_proof=proof,
                    )
                    if not continuation["verified"]:
                        return {**out, "gap": continuation["gap"], "proof": proof}
                    proof["continuation"] = continuation
                return {
                    **out,
                    "state": "approved",
                    "state_detail": "approval_recorded",
                    "merged": None,
                    "live": None,
                    "proof": proof,
                }
            return (
                {**out, "state": "pending"}
                if reviewed == head_sha
                else {**out, "gap": "POLICY_RATIFICATION_CONTINUATION_UNVERIFIED"}
            )
        except Exception:
            return {**out, "gap": "POLICY_RATIFICATION_EVIDENCE_INVALID"}


def load_context(*, git: Callable, gh, now: datetime, source_root: Path = CANONICAL_REPOSITORY) -> AuthorityContext:
    """Bounded background-only reads; all helper rules come from trusted main.

    git must be the canonical checkout's read-only git reader. The local remote
    ref and GitHub main must agree. Installed guard code and canonical helper
    code must exactly match that same SHA before they may classify a PR.
    """
    context = AuthorityContext(None, _at(now), gh=gh, git=git)
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
