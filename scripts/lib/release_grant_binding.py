"""Fail-closed binding of a release-write grant to the release it authorizes.

Incident (2026-09-25 08:12–09:16 ET): two PR-specific Telegram requests for
the #1229 go-live were never approved (b02cec0b SUPERSEDED, 0f7ca85f PENDING),
yet #1229 and #1230 were prepared and promoted while a 30-use / 12-hour
release-write grant issued from a local shell for the
"trade-ai-maturity-overnight-20260912" campaign was active. Nothing in the
deploy path checked that the grant's text named that PR, SHA or campaign; the
tier matched, so the action went ahead. Action-class matching let a different
campaign's grant stand in for a specific request that was still pending.

This module decides, deterministically and fail-closed, whether an available
grant covers a specific release action. It does not issue grants, does not
talk to Telegram and holds no credential: it reads the grant rows the guard
already keeps (``~/.cursor/approvals/grants.json``) and the request rows
(``~/.cursor/approvals/remote_requests.json``) and returns a verdict.

Binding rule (all must hold):
  * tier == release-write, not expired, uses > 0
  * the grant's reason names THIS action's binding: the PR number ("#1229"),
    the target SHA (≥ 9 hex chars prefix) or the campaign id the action is run
    under — a generic campaign grant that names none of them is NOT a match
  * if a PENDING request exists for this exact PR/SHA, only a grant that
    settled THAT request (remote_request_id) or names the PR/SHA may satisfy
    it; an unrelated grant cannot "answer" a pending specific request
  * the action (prepare | promote | rollback) must be within the grant's
    allowed actions when the reason lists any

Operator bypass: none inside this module. The deploy script may run in
``TRADEAI_RELEASE_GRANT_BINDING=warn`` mode during the transition, which
prints the refusal and continues; the default is ``enforce``.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "ReleaseGrantBinding@v1"
TIER = "release-write"
ACTIONS = ("prepare", "promote", "rollback", "verify")
GRANTS_PATH = Path(os.environ.get("TRADEAI_GUARD_GRANTS_PATH", str(Path.home() / ".cursor/approvals/grants.json")))
REQUESTS_PATH = Path(os.environ.get("TRADEAI_GUARD_REQUESTS_PATH", str(Path.home() / ".cursor/approvals/remote_requests.json")))

_PR_RE = re.compile(r"(?:PR\s*)?#(\d{3,6})\b", re.IGNORECASE)
_SHA_RE = re.compile(r"\b([0-9a-f]{9,40})\b")
_ACTION_RE = re.compile(r"\b(prepare|promote|rollback|roll back|verify)\b", re.IGNORECASE)


@dataclass
class ReleaseAction:
    action: str                      # prepare | promote | rollback | verify
    target_sha: str                  # full or ≥9-char prefix of the merged SHA
    pr_number: Optional[int] = None
    campaign: Optional[str] = None   # campaign id this action is run under, if any
    environment: str = "production"
    operator: Optional[str] = None
    now: Optional[float] = None      # epoch seconds (injectable for tests)


@dataclass
class Verdict:
    allowed: bool
    reason: str
    grant_id: Optional[str] = None
    matched_by: list[str] = field(default_factory=list)
    pending_request_ids: list[str] = field(default_factory=list)
    refused_grants: list[dict[str, Any]] = field(default_factory=list)
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "allowed": self.allowed, "reason": self.reason, "grant_id": self.grant_id,
                "matched_by": list(self.matched_by), "pending_request_ids": list(self.pending_request_ids),
                "refused_grants": list(self.refused_grants)}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_grants(path: Path = GRANTS_PATH) -> list[dict[str, Any]]:
    """Grant rows as the guard stores them: a dict tier -> row, or a list of rows."""
    raw = _load_json(path)
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for tier, row in raw.items():
            if isinstance(row, dict):
                rows.append({**row, "tier": row.get("tier") or tier})
            elif isinstance(row, list):
                rows.extend({**r, "tier": r.get("tier") or tier} for r in row if isinstance(r, dict))
    elif isinstance(raw, list):
        rows = [r for r in raw if isinstance(r, dict)]
    return rows


def load_requests(path: Path = REQUESTS_PATH) -> list[dict[str, Any]]:
    raw = _load_json(path)
    if isinstance(raw, dict):
        vals = raw.get("requests") if isinstance(raw.get("requests"), (list, dict)) else raw
        if isinstance(vals, dict):
            return [{**v, "request_id": v.get("request_id") or k} for k, v in vals.items() if isinstance(v, dict)]
        if isinstance(vals, list):
            return [r for r in vals if isinstance(r, dict)]
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


def _names_action(reason: str, act: ReleaseAction) -> list[str]:
    """Which of the action's binding facts the grant text names."""
    text = reason or ""
    hit: list[str] = []
    if act.pr_number is not None and any(int(n) == int(act.pr_number) for n in _PR_RE.findall(text)):
        hit.append(f"pr:#{act.pr_number}")
    sha = (act.target_sha or "").lower()
    if sha and len(sha) >= 9:
        for cand in _SHA_RE.findall(text.lower()):
            if sha.startswith(cand[:9]) or cand.startswith(sha[:9]):
                hit.append(f"sha:{cand[:12]}")
                break
    if act.campaign and act.campaign.lower() in text.lower():
        hit.append(f"campaign:{act.campaign}")
    return hit


def _allows_action(reason: str, action: str) -> bool:
    listed = {m.lower().replace("roll back", "rollback") for m in _ACTION_RE.findall(reason or "")}
    if not listed:
        return True             # reason lists no actions: no action restriction
    return action.lower() in listed


def pending_requests_for(act: ReleaseAction, requests: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in requests:
        if str(r.get("tier") or "") != TIER:
            continue
        if str(r.get("status") or "").upper() != "PENDING":
            continue
        text = f"{r.get('reason') or ''} {r.get('summary') or ''} {r.get('for') or ''}"
        if _names_action(text, ReleaseAction(action=act.action, target_sha=act.target_sha, pr_number=act.pr_number)):
            out.append(dict(r))
    return out


def decide(act: ReleaseAction, *, grants: Iterable[Mapping[str, Any]],
           requests: Iterable[Mapping[str, Any]] = ()) -> Verdict:
    """The verdict for one release action. Fail closed: no matching grant → refused."""
    now = act.now if act.now is not None else time.time()
    if act.action not in ACTIONS:
        return Verdict(False, f"unknown release action {act.action!r}")
    if not act.target_sha or len(act.target_sha) < 9:
        return Verdict(False, "target SHA must be given (≥ 9 hex chars) to bind a release grant")
    pend = pending_requests_for(act, list(requests))
    pend_ids = [str(p.get("request_id") or p.get("id") or "") for p in pend]
    refused: list[dict[str, Any]] = []
    for g in grants:
        gid = str(g.get("grant_id") or g.get("id") or "")
        if str(g.get("tier") or "") != TIER:
            continue
        exp = g.get("expires") or g.get("expires_at")
        try:
            expired = exp is not None and float(exp) <= now
        except (TypeError, ValueError):
            expired = True
        if expired:
            refused.append({"grant_id": gid, "why": "expired"})
            continue
        try:
            uses = int(g.get("uses") if g.get("uses") is not None else 0)
        except (TypeError, ValueError):
            uses = 0
        if uses <= 0:
            refused.append({"grant_id": gid, "why": "no_uses_left"})
            continue
        reason = str(g.get("reason") or g.get("for") or "")
        if not _allows_action(reason, act.action):
            refused.append({"grant_id": gid, "why": f"action {act.action} not in grant's listed actions"})
            continue
        named = _names_action(reason, act)
        settled_pending = bool(pend) and str(g.get("remote_request_id") or "") in pend_ids
        if not named and not settled_pending:
            refused.append({"grant_id": gid, "why": "grant names neither this PR, this SHA nor this campaign",
                            "reason": reason[:160]})
            continue
        if pend and not settled_pending and not any(m.startswith(("pr:", "sha:")) for m in named):
            # A specific request for THIS release is pending; a campaign-only
            # match cannot answer it.
            refused.append({"grant_id": gid, "why": "specific request pending; campaign-only grant cannot satisfy it",
                            "pending": pend_ids})
            continue
        return Verdict(True, "grant names this release" if named else "grant settled the pending request for this release",
                       grant_id=gid, matched_by=named or ["settled_pending_request"], pending_request_ids=pend_ids,
                       refused_grants=refused)
    why = "no release-write grant names this PR/SHA/campaign"
    if pend:
        why = f"specific request(s) still PENDING for this release: {', '.join(pend_ids)}; no grant settled them"
    return Verdict(False, why, pending_request_ids=pend_ids, refused_grants=refused)


def decide_from_disk(act: ReleaseAction, *, grants_path: Path = GRANTS_PATH,
                     requests_path: Path = REQUESTS_PATH) -> Verdict:
    return decide(act, grants=load_grants(grants_path), requests=load_requests(requests_path))


__all__ = ["SCHEMA", "TIER", "ACTIONS", "ReleaseAction", "Verdict", "decide", "decide_from_disk",
           "load_grants", "load_requests", "pending_requests_for"]
