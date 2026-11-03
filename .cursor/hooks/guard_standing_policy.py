"""Ratified standing authority, evaluated only from a caller's trusted main snapshot.

The pure validator does not fetch policy or authenticate local session records.
Callers supply policy and manifest from the SAME canonical remote-main commit;
feature/worktree text is never a source of authority. No expiry or extra issue
approval is invented. Revocation is a separate fixed-path fail-closed read.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import os
import pwd
import re
from typing import Any

SCHEMA = "AgentStandingAuthority@v1"
REPOSITORY = "PatsKiller/tardeai"
MINIMUM_POLICY = (30, 0, 0)
CAPABILITIES = frozenset({"feature_push", "delegated_upload", "coordinator_merge"})
COORDINATION_ROOT = (Path(pwd.getpwuid(os.getuid()).pw_dir)
                     / "trade-ai-releases/persistent-state/data/coordination/coordinator")
REVOCATION_PATH = COORDINATION_ROOT / "STANDING_AUTHORITY_REVOKED.json"
_SHA = re.compile(r"[0-9a-f]{40}")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_TOKEN = re.compile(r"(?<![A-Z0-9_])APPROVE_AGENTS_POLICY_30_0_0 ([1-9][0-9]*) ([0-9a-f]{40})(?![0-9a-f])")
_BRANCH = re.compile(r"wt/[A-Za-z0-9][A-Za-z0-9._-]{2,120}")
_FENCE = re.compile(r"(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}\1[ \t]*$|\Z)")
_HTML = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_INDENT = re.compile(r"^(?: {4,}|\t)[^\n]*$", re.MULTILINE)


def revoked_marker() -> bool:
    """Any marker presence (including broken symlinks) or read failure denies.

    The path comes from passwd-home, never HOME, a pusher environment variable
    or a caller-provided directory. Tests may patch the module constant only.
    """
    try:
        REVOCATION_PATH.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _unfenced(text: str) -> str:
    # Keep #2459's safeguards: hidden, fenced and indented examples do not grant.
    return _INDENT.sub("", _FENCE.sub("", _HTML.sub("", text)))


def _version(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _VERSION.fullmatch(value)
    return tuple(map(int, match.groups())) if match else None


def _history_row(text: str, version: str) -> list[str] | None:
    heading = re.search(r"^# Version history[ \t]*$", text, re.MULTILINE)
    if not heading:
        return None
    rows = []
    for line in _unfenced(text[heading.end():]).splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) >= 3 and cells[0] == version:
            rows.append(cells)
    return rows[0] if len(rows) == 1 else None


def authorize(policy_text: Any, manifest: Any, *, capability: Any,
              policy_sha: Any, branch: Any = None, revoked: bool = False) -> dict:
    """Validate local consistency only; actual policy-comment evidence is ALSO required.

    ``policy_sha`` identifies the trusted main snapshot, not the ratification's
    reviewed feature head. The manifest tuple must match the ACTIVE30.0.0
    history row. Matching local fields is provenance consistency, not a signature.
    """
    def deny(reason: str) -> dict:
        return {"ok": False, "reason": reason, "authority": None}

    if type(revoked) is not bool or revoked:
        return deny("standing authority revoked or revocation state invalid")
    if not isinstance(capability, str) or capability not in CAPABILITIES:
        return deny("unknown standing capability")
    if not isinstance(policy_sha, str) or not _SHA.fullmatch(policy_sha):
        return deny("trusted policy commit must be a full lowercase40-character SHA")
    if not isinstance(policy_text, str) or not policy_text.strip():
        return deny("trusted main policy unavailable")
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        return deny("standing authority manifest absent or malformed")
    if manifest.get("status") != "ACTIVE":
        return deny("standing authority manifest is not ACTIVE")
    minimum = _version(manifest.get("minimum_policy"))
    if minimum is None or minimum < MINIMUM_POLICY:
        return deny("standing authority minimum policy is below30.0.0 or malformed")
    blocks = re.findall(r"(?ms)^```[ \t]*\n(Policy-Version:[^\n]*\n.*?)^```[ \t]*$", policy_text)
    if len(blocks) != 1:
        return deny("policy control block absent or ambiguous")
    control = {}
    for line in blocks[0].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if key in control:
                return deny("duplicate policy control field")
            control[key] = value
    version = control.get("Policy-Version")
    current = _version(version)
    if current is None or current < minimum or control.get("Status") != "ACTIVE":
        return deny("main policy is not ACTIVE at the manifest minimum")
    current_row = _history_row(policy_text, version)
    if current_row is None or current_row[2] != "ACTIVE":
        return deny("current policy history row is not uniquely ACTIVE")
    operative = re.search(r"^# 0[ \t]+·[^\n]*$", policy_text, re.MULTILINE)
    history = re.search(r"^# Version history[ \t]*$", policy_text, re.MULTILINE)
    if operative is None or history is None or history.start() <= operative.end():
        return deny("operative policy boundaries unavailable")
    binding = _unfenced(policy_text[operative.end():history.start()])
    if not re.search(r"^Standing-Authority:[ \t]+AgentStandingAuthority@v1[ \t]*$", binding, re.MULTILINE):
        return deny("standing authority binding is absent from operative main policy")
    ratification = manifest.get("ratification")
    if not isinstance(ratification, dict):
        return deny("ratification record unavailable")
    token = ratification.get("approval_token")
    match = _TOKEN.fullmatch(token) if isinstance(token, str) else None
    pr, reviewed = ratification.get("pr"), ratification.get("reviewed_head")
    if (match is None or type(pr) is not int or pr <= 0 or not isinstance(reviewed, str)
            or not _SHA.fullmatch(reviewed) or int(match[1]) != pr or match[2] != reviewed):
        return deny("ratification token/PR/reviewed-head tuple is missing or inconsistent")
    ratified = _history_row(policy_text, "30.0.0")
    if ratified is None or ratified[2] != "ACTIVE":
        return deny("30.0.0 ratification history row is not uniquely ACTIVE")
    if not ratified[-1].lstrip("`").startswith("APPROVE_AGENTS_POLICY_30_0_0 "):
        return deny("ratification approval cell is not an explicit approval token")
    history_tokens = _TOKEN.findall(" | ".join(ratified))
    if history_tokens != [(str(pr), reviewed)]:
        return deny("ratification tuple does not match the30.0.0 ACTIVE history row")
    caps = manifest.get("capabilities")
    if not isinstance(caps, dict) or set(caps) != CAPABILITIES:
        return deny("standing capability records absent or malformed")
    feature, delegated, merge = (caps.get(name) for name in ("feature_push", "delegated_upload", "coordinator_merge"))
    if (not isinstance(feature, dict) or feature.get("branch_prefixes") != ["wt/"]
            or feature.get("approved_scope_required") is not True):
        return deny("feature upload must require approved scope and only wt/ branches")
    if not isinstance(delegated, dict) or delegated.get("coordinator_handoff_required") is not True:
        return deny("delegated upload must require coordinator handoff")
    if (not isinstance(merge, dict) or type(merge.get("ordinary_reviews")) is not int
            or merge["ordinary_reviews"] < 1 or type(merge.get("held_reviews")) is not int
            or merge["held_reviews"] < 2):
        return deny("coordinator merge must retain ordinary/held independent review floors")
    reserved = manifest.get("reserved_paths")
    if (not isinstance(reserved, list) or not reserved or any(not isinstance(p, str) or not p.strip()
            or p.startswith("/") or ".." in p.split("/") or "\n" in p or "\x00" in p for p in reserved)):
        return deny("reserved path manifest is absent or malformed")
    if capability in {"feature_push", "delegated_upload"}:
        if (not isinstance(branch, str) or not _BRANCH.fullmatch(branch) or ".." in branch
                or branch.endswith((".lock", "."))):
            return deny("standing upload covers only safe wt/ feature branches")
    return {"ok": True, "reason": "local main policy/manifest consistency validated; actual operator comment required",
            "authority": {"policy_sha": policy_sha, "policy_version": version, "minimum_policy": manifest["minimum_policy"],
                          "manifest_schema": SCHEMA, "repository": REPOSITORY, "capability": capability,
                          "ratification": deepcopy(ratification), "requirements": deepcopy(caps[capability]),
                          "reserved_paths": list(reserved)}}


def verify_ratification_evidence(authority: Any, actual_comments: Any, expected_operator: Any) -> dict:
    """Require the one genuine unedited operator policy-ratification comment.

    ``authority`` is authorize()["authority"], not its wrapper. Comments must
    come from the real canonical policy PR's bounded REST issue-comments read.
    This pure function checks the returned provenance; it does not fetch or sign.
    No per-branch comment, issue, grant or expiry is introduced.
    """
    def deny(reason: str) -> dict:
        return {"ok": False, "reason": reason, "authority": None}

    if (not isinstance(authority, dict) or authority.get("manifest_schema") != SCHEMA
            or authority.get("repository") != REPOSITORY):
        return deny("canonical local policy authority unavailable")
    if not isinstance(expected_operator, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", expected_operator):
        return deny("expected operator identity unavailable")
    ratification = authority.get("ratification")
    if not isinstance(ratification, dict):
        return deny("policy ratification tuple unavailable")
    token, pr, reviewed = (ratification.get(k) for k in ("approval_token", "pr", "reviewed_head"))
    match = _TOKEN.fullmatch(token) if isinstance(token, str) else None
    if (match is None or type(pr) is not int or pr <= 0 or not isinstance(reviewed, str)
            or not _SHA.fullmatch(reviewed) or str(pr) != match[1] or reviewed != match[2]):
        return deny("policy ratification tuple malformed or inconsistent")
    if not isinstance(actual_comments, list) or len(actual_comments) > 1000:
        return deny("actual policy PR comment collection unavailable or incomplete")
    for comment in actual_comments:
        if not isinstance(comment, dict):
            continue
        user, body, cid = comment.get("user"), comment.get("body"), comment.get("id")
        if (not isinstance(user, dict) or user.get("login") != expected_operator or not isinstance(body, str)
                or type(cid) is not int or cid <= 0):
            continue
        url = comment.get("html_url")
        allowed_urls = {f"https://github.com/{REPOSITORY}/{kind}/{pr}#issuecomment-{cid}"
                        for kind in ("pull", "issues")}
        if not isinstance(url, str) or url not in allowed_urls:
            continue
        created, updated = comment.get("created_at"), comment.get("updated_at")
        if not isinstance(created, str) or not created or created != updated:
            continue
        try:
            instant = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if instant.tzinfo is None or instant.utcoffset() is None:
                continue
        except ValueError:
            continue
        if not any(line.strip() == token for line in _unfenced(body).splitlines()):
            continue
        result = deepcopy(authority)
        result["ratification_evidence"] = {"comment_id": cid, "url": url, "author": expected_operator,
                                          "created_at": created}
        return {"ok": True, "reason": "actual unedited operator policy ratification verified", "authority": result}
    return deny("no actual unedited operator comment ratifies the exact policy PR/reviewed head")
