"""AGENTS.md version status and the two equal ratification paths (PR comment, in-app decision).

How ratification is detected (unchanged): the operator's ratification of a PROPOSED AGENTS.md version is the exact
token ``APPROVE_AGENTS_POLICY_<X_Y_Z> <pr_number> <head_sha>``. The ratify tooling
(e.g. ``docs/ops/packets/agents-21-20261023-wp16/operator21.py``) looks for a PR comment by the operator's GitHub
account whose body, stripped, equals that token, and then makes the ratifying edit.

The in-app path (Command Center /v3/policy, 2026-10-25): the operator reads every change in the exact PR head in the
document reader and taps "Approve version X". ``operator_approvals.DecisionLedger.decide`` writes the SAME
``DECIDED`` row the Approvals Center writes for a POLICY item -- actor = authenticated tailnet operator, kind POLICY,
``policy_token`` = the exact token above, bound to the document fingerprint and head commit. The server has no GitHub
write path, so the row's derived effect is ``RECORDED_AWAITING_RELAY``: the coordinator runs
``scripts/relay_policy_approvals.py --apply``, which posts the token verbatim as the PR comment (only for a ledger row
whose PR head still equals the token's commit, and only once). After the relay, every existing detector sees the same
comment it always looked for; before it, ``ratification_evidence`` (below) accepts the ledger row as equivalent.

Pure: no I/O. Ledger rows and PR comments are passed in.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, Mapping

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # scripts/ is a namespace package; the repo root must be importable
    sys.path.insert(0, str(_ROOT))

from scripts import check_agents_policy_state as cps  # noqa: E402

TOKEN_RE = re.compile(r"^APPROVE_AGENTS_POLICY_(\d+)_(\d+)_(\d+) ([1-9]\d{0,6}) ([0-9a-f]{40})$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OPERATOR_GITHUB_LOGIN = "PatsKiller"
RELAY_EFFECT = "RECORDED_AWAITING_RELAY"


def token_for(version: str, pr: int, head_sha: str) -> str | None:
    if not (isinstance(version, str) and VERSION_RE.fullmatch(version) and type(pr) is int and pr > 0
            and isinstance(head_sha, str) and SHA_RE.fullmatch(head_sha)):
        return None
    return f"APPROVE_AGENTS_POLICY_{version.replace('.', '_')} {pr} {head_sha}"


def parse_token(token: str) -> dict | None:
    m = TOKEN_RE.fullmatch((token or "").strip())
    if not m:
        return None
    return {"version": ".".join(m.group(1, 2, 3)), "pr": int(m.group(4)), "head_sha": m.group(5)}


def _row(text: str, version: str | None) -> dict | None:
    return next((r for r in cps.version_rows(text) if r["version"] == version), None)


def current_status(text: str, source_sha: str) -> dict:
    """The served AGENTS.md: header + its version-history row + the post-merge state check."""
    cb = cps.control_block(text)
    version = cb.get("Policy-Version")
    row = _row(text, version)
    errors = cps.check(text, on_main=True)
    return {"version": version, "status": cb.get("Status"), "effective_date": cb.get("Effective-Date"),
            "supersedes": cb.get("Supersedes"), "last_reviewed": cb.get("Last-Reviewed"),
            "row_status": row["status"] if row else None, "source_sha": source_sha,
            "consistent": not errors, "errors": errors[:10]}


def proposed_status(text: str) -> dict:
    """A PR head's AGENTS.md: is it a PROPOSED version that names a pending operator ratification?"""
    cb = cps.control_block(text)
    version = cb.get("Policy-Version")
    row = _row(text, version)
    approval = (row or {}).get("rest", "")
    return {"version": version, "status": cb.get("Status"), "row_status": row["status"] if row else None,
            "awaits_token": bool(row) and "PENDING" in approval and "APPROVE_" in approval,
            "classification": (row or {}).get("cls")}


def _operator_actor(actor) -> bool:
    return isinstance(actor, str) and actor.startswith("tailnet:") and len(actor) > len("tailnet:")


def in_app_ratification(rows: Iterable[Mapping], *, token: str) -> Mapping | None:
    """The operator's in-app DECIDED APPROVE row carrying exactly ``token`` (latest), else None."""
    hit = None
    for r in rows:
        if (r.get("event") == "DECIDED" and r.get("decision") == "APPROVE" and r.get("kind") == "POLICY"
                and r.get("policy_token") == token and _operator_actor(r.get("actor"))):
            hit = r
    return hit


def ratification_evidence(*, token: str, comments: Iterable[Mapping] = (), ledger_rows: Iterable[Mapping] = (),
                          operator_login: str = OPERATOR_GITHUB_LOGIN) -> dict | None:
    """Either path ratifies equally. The PR comment wins when both exist (it is what the history row quotes)."""
    if not parse_token(token):
        return None
    for c in comments or ():
        if (c.get("user") or {}).get("login") == operator_login and (c.get("body") or "").strip() == token:
            return {"path": "pr_comment", "token": token, "comment_id": c.get("id"), "at": c.get("created_at"),
                    "url": c.get("html_url")}
    row = in_app_ratification(ledger_rows or (), token=token)
    if row:
        return {"path": "in_app_decision", "token": token, "actor": row.get("actor"), "at": row.get("at"),
                "ledger_hash": row.get("hash_self"), "document_sha": row.get("document_sha"),
                "effect": RELAY_EFFECT}
    return None
