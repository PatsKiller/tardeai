"""hands_off_policy — the one gate for AGENTS.md 20.4.0 "hands-off delivery" mechanics.

Operator, 2026-10-25 (verbatim): "fully done, fully automatic, no input by me, for the train systems unless there's
an issue." AGENTS.md 20.4.0 (PROPOSED in a separate PR) writes the rule; this module is the ONE place code asks
whether that rule is in force, plus the shared definitions the mechanics use (coordinator claim, operator-approval
reference, adversarial-review receipt).

Gate (why a policy read and not a config flag). Every 20.4.0 mechanic -- push budget 5 and the coordinator push
override (pre-push hook), solo shared-infra trains (release train), the registry-derived relay live list -- is ON
only while ``policy_state(...)["active"]`` is True. ``active`` needs all of: the AGENTS.md control block's
Policy-Version >= 20.4.0, its Status ACTIVE, the current version's history row ACTIVE, and a ``| 20.4.0 |`` history
row that begins with ACTIVE (the ``or_later`` reading ``agent_claim_board.claim_policy_state`` already uses for the
20.0.0 pre-commit gate). Read at call time, no cache, NO environment override: the operator's ratification (the
ratifying merge of AGENTS.md to main) is the only switch, and nothing else -- no flag an agent could flip -- arms it.
A config flag defaulting off would need a second, separate edit after ratification (a second operator step, or an
agent flipping a governance flag on its own); the policy read needs neither. Unreadable or unparseable is NOT active
(fail closed: every mechanic keeps its pre-20.4.0 behavior).

Which AGENTS.md. A caller that can be run from a branch (the pre-push hook) reads ``origin/main:AGENTS.md`` through
git (``policy_state_from_git``), so a branch that edits its own AGENTS.md header cannot arm anything. Host
processes that run from the exact-main release tree (release train, deploy render, API) read the tree's file.

Pure: stdlib only; git and the claim board are read only through the functions below (both injectable in tests).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

POLICY_VERSION = (20, 4, 0)
POLICY_VERSION_TEXT = "20.4.0"
POLICY_TOKEN = "APPROVE_AGENTS_POLICY_20_4_0"
SCHEMA_STATE = "HandsOffPolicyState@v1"

#: A coordinator claim is a claim on this virtual path. Claims are exclusive per path on the board, so at most one
#: live session holds it at a time (docs/ops/AGENT_CLAIM_BOARD.md §3 overlap rule).
COORDINATOR_CLAIM_PATH = "coordination/COORDINATOR"
COORDINATOR_ENV = "TRADEAI_COORDINATOR_SESSION"

#: ``Operator-approval: <ref>`` -- a PR body line or a claim plan/worklog line naming the operator's approval
#: (a verbatim quote reference, decision id, PR comment URL, or tracker item). Empty or placeholder refs refuse.
APPROVAL_RE = re.compile(
    r"^[ \t>*-]*(?:\[[ xX]\][ \t]*)?Operator-approval:[ \t]*(?P<ref>\S[^\n]*?)[ \t]*$", re.MULTILINE
)
#: ``Real-layout proof: <ref>`` -- PR body line naming the temp-PROJECT_ROOT real-layout proof.
REAL_LAYOUT_RE = re.compile(
    r"^[ \t>*-]*(?:\[[ xX]\][ \t]*)?Real-layout proof:[ \t]*(?P<ref>\S[^\n]*?)[ \t]*$", re.MULTILINE
)
#: The coordinator's review receipt, one PR comment line (all fields required, any order after MERGE):
#:   Adversarial-review: MERGE reviewer=<ref> head=<sha 7-40> coordinator=<session>
RECEIPT_RE = re.compile(
    r"^[ \t>*-]*(?:\[[ xX]\][ \t]*)?Adversarial-review:[ \t]*MERGE\b(?P<rest>[^\n]*)$", re.MULTILINE
)
_FIELD_RE = re.compile(r"\b(reviewer|head|coordinator)=(\S+)")
_PLACEHOLDER = re.compile(r"^(?:<[^>]*>|tbd|todo|none|n/?a|pending|-+|\.+)$", re.IGNORECASE)

_ROW_RE = r"^\|\s*{v}\s*\|[^|]*\|\s*([^|]*)\|"


def _semver(v: Optional[str]) -> Optional[tuple[int, int, int]]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _control_block(text: str) -> dict[str, str]:
    m = re.search(r"```\n(Policy-Version:.*?)```", text, re.DOTALL)
    out: dict[str, str] = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _row_status(text: str, version: str) -> Optional[str]:
    m = re.search(_ROW_RE.format(v=re.escape(version)), text, re.M)
    return m.group(1).strip() if m else None


def policy_state_from_text(text: Optional[str], *, source: str = "text") -> dict[str, Any]:
    """Is 20.4.0 (or later) ACTIVE in this AGENTS.md text? ``active`` is the only field callers branch on."""
    base: dict[str, Any] = {
        "schema": SCHEMA_STATE,
        "required": POLICY_VERSION_TEXT,
        "source": source,
        "version": None,
        "header_status": None,
        "active": False,
    }
    if not isinstance(text, str) or not text.strip():
        return {**base, "state": "UNREADABLE", "detail": f"{source}: no AGENTS.md text"}
    cb = _control_block(text)
    version, status = cb.get("Policy-Version"), cb.get("Status", "")
    base.update(version=version, header_status=status or None)
    sv = _semver(version)
    if sv is None:
        return {**base, "state": "UNREADABLE", "detail": "no Policy-Version in the control block"}
    if sv < POLICY_VERSION:
        return {**base, "state": "NOT_ACTIVE", "detail": f"AGENTS.md {version} is below {POLICY_VERSION_TEXT}"}
    if not status.upper().startswith("ACTIVE"):
        return {**base, "state": "NOT_ACTIVE", "detail": f"AGENTS.md {version} header is {status!r}"}
    cur = _row_status(text, version or "")
    if not cur or not cur.upper().startswith("ACTIVE"):
        return {**base, "state": "NOT_ACTIVE", "detail": f"AGENTS.md {version} version-history row is not ACTIVE"}
    own = _row_status(text, POLICY_VERSION_TEXT)
    if not own or not own.upper().startswith("ACTIVE"):
        return {
            **base,
            "state": "NOT_ACTIVE",
            "detail": f"no ACTIVE {POLICY_VERSION_TEXT} version-history row (ratification not recorded)",
        }
    return {
        **base,
        "state": "ACTIVE",
        "active": True,
        "detail": f"AGENTS.md {version} ACTIVE (>= {POLICY_VERSION_TEXT}, {POLICY_VERSION_TEXT} row ACTIVE)",
    }


def policy_state_from_path(path: Path | str) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return policy_state_from_text(None, source=f"{path}: {type(exc).__name__}")
    return policy_state_from_text(text, source=str(path))


def policy_state_from_git(
    ref: str = "origin/main", *, cwd: Path | str | None = None, runner: Callable[..., Any] = subprocess.run
) -> dict[str, Any]:
    """``git show <ref>:AGENTS.md`` -- main's ratified text, never the pushing branch's own edit."""
    try:
        cp = runner(
            ["git", "show", f"{ref}:AGENTS.md"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return policy_state_from_text(None, source=f"git {ref}: {type(exc).__name__}")
    if getattr(cp, "returncode", 1) != 0:
        return policy_state_from_text(None, source=f"git {ref}: rc={getattr(cp, 'returncode', '?')}")
    return policy_state_from_text(cp.stdout, source=f"git:{ref}:AGENTS.md")


# --------------------------------------------------------------------------- refs in PR text


def _clean_ref(ref: Optional[str]) -> Optional[str]:
    ref = (ref or "").strip().strip("`").strip()
    if not ref or _PLACEHOLDER.match(ref):
        return None
    return ref[:300]


def approval_ref(text: Optional[str]) -> Optional[str]:
    """The first non-placeholder ``Operator-approval:`` reference in ``text``, else None."""
    for m in APPROVAL_RE.finditer(text or ""):
        ref = _clean_ref(m.group("ref"))
        if ref:
            return ref
    return None


def real_layout_ref(text: Optional[str]) -> Optional[str]:
    for m in REAL_LAYOUT_RE.finditer(text or ""):
        ref = _clean_ref(m.group("ref"))
        if ref:
            return ref
    return None


def parse_receipt(text: Optional[str]) -> list[dict[str, str]]:
    """Every well-formed ``Adversarial-review: MERGE reviewer=.. head=.. coordinator=..`` line in ``text``."""
    out = []
    for m in RECEIPT_RE.finditer(text or ""):
        fields = dict(_FIELD_RE.findall(m.group("rest")))
        reviewer = _clean_ref(fields.get("reviewer"))
        head = (fields.get("head") or "").lower()
        coord = _clean_ref(fields.get("coordinator"))
        if reviewer and coord and re.fullmatch(r"[0-9a-f]{7,40}", head):
            out.append({"reviewer": reviewer, "head": head, "coordinator": coord})
    return out


# --------------------------------------------------------------------------- coordinator claims


def _claim_rows(claims_dir: Path | str | None) -> list[dict[str, Any]]:
    """Claim docs with their board state (live/stale/done/abandoned). Lazy import: the board is optional."""
    try:
        from scripts.lib import agent_claim_board as B  # type: ignore
    except ImportError:  # scripts/ on sys.path
        from lib import agent_claim_board as B  # type: ignore[no-redef]
    views, _bad = B.ClaimBoard(claims_dir).views()
    rows = []
    for v in views:
        doc = dict(v.doc)
        doc["_state"] = v.state
        doc["_path"] = str(v.path)
        rows.append(doc)
    return rows


def coordinator_claims(rows: Iterable[Mapping[str, Any]], *, live_only: bool = True) -> list[Mapping[str, Any]]:
    out = []
    for r in rows:
        paths = [str(p).strip().strip("/") for p in (r.get("paths") or [])]
        if COORDINATOR_CLAIM_PATH not in paths:
            continue
        if live_only and r.get("_state") != "live":
            continue
        if not live_only and r.get("_state") not in ("live", "stale", "done"):
            continue
        out.append(r)
    return out


def coordinator_session_ok(
    session: Optional[str], rows: Iterable[Mapping[str, Any]], *, live_only: bool = True
) -> Optional[Mapping[str, Any]]:
    """The coordinator claim held by ``session``, else None. Empty session never matches."""
    session = (session or "").strip()
    if not session:
        return None
    for r in coordinator_claims(rows, live_only=live_only):
        if str(r.get("session") or "").strip() == session:
            return r
    return None


def claim_plan_approval(
    rows: Iterable[Mapping[str, Any]],
    *,
    session: str,
    branch: str,
    worklog_reader: Callable[[Mapping[str, Any]], str] | None = None,
) -> Optional[str]:
    """An ``Operator-approval:`` ref in the note or worklog plan of ``session``'s live claim on ``branch``."""
    for r in rows:
        if r.get("_state") != "live" or str(r.get("session") or "") != session or str(r.get("branch") or "") != branch:
            continue
        ref = approval_ref(str(r.get("note") or ""))
        if not ref and worklog_reader is not None:
            try:
                ref = approval_ref(worklog_reader(r))
            except (OSError, ValueError):
                ref = None
        if ref:
            return ref
    return None


def default_worklog_reader(claims_dir: Path | str | None) -> Callable[[Mapping[str, Any]], str]:
    def read(row: Mapping[str, Any]) -> str:
        p = Path(str(row.get("_path") or ""))
        wl = p.with_name(f"{row.get('claim_id')}.worklog.md") if p.name else None
        return wl.read_text(encoding="utf-8") if wl and wl.is_file() else ""

    return read


def to_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)
