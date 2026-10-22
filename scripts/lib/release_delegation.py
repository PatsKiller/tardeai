"""Standing release delegation (ReleaseDelegation@v1): the operator-owned policy record, loaded fail closed.

Release Train v2, Phase 2. Operator decision D1 (2026-10-21): standing, revocable authorization — valid until the
operator pauses or revokes it; no daily or 7-day renewal. The delegation is a POLICY RECORD, not a credential: it
names the repository, environment, permitted release classes, windows, limits, verification policy, revocation
epoch, status and the operator who signed it off. Authority to mutate anything is issued per train and per phase
by ``scripts/lib/release_capability.py``, and only while ``scripts/lib/release_control.py`` has accepted this
record's digest.

The real file is operator-created on the host, OUTSIDE the repository (default
``~/.config/tradeai/release_train/delegation.json``, mode 600), so that no train candidate can edit the record
that authorizes it (enhanced design §10: "candidate changes to its own verifier"). The repository ships only
``config/release_train_delegation.example.json`` (status PAUSED, every window disabled) and the schema
``config/schemas/release_delegation_v1.schema.json``.

Fail closed: missing, unreadable, not an object, wrong schema, unknown status, a missing or mistyped field, a
forbidden class (broker / order / execution / Active Trader / secret, AGENTS §0 rule 2), a path inside the
repository, or status PAUSED / REVOKED -> ``authorized`` is False. Only a valid ACTIVE record is authorized.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

SCHEMA = "ReleaseDelegation@v1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = Path.home() / ".config" / "tradeai" / "release_train" / "delegation.json"
EXAMPLE_PATH = ROOT / "config" / "release_train_delegation.example.json"
SCHEMA_PATH = ROOT / "config" / "schemas" / "release_delegation_v1.schema.json"

ACTIVE, PAUSED, REVOKED = "ACTIVE", "PAUSED", "REVOKED"
STATUSES = frozenset({ACTIVE, PAUSED, REVOKED})
#: Optional rollout phase (arming finding 8). Only "canary" admits an operator-forced off-window run.
PHASES = frozenset({"shadow", "canary", "expand"})
REPOSITORY = "PatsKiller/tardeai"
ENVIRONMENTS = frozenset({"production"})
#: The four operator windows (2026-10-21): 00:00, 06:00, 08:00, 18:00 America/New_York.
WINDOW_IDS = ("0000", "0600", "0800", "1800")
TIMEZONE = "America/New_York"
#: Required branch-protection contexts on main (gh api .../branches/main/protection, 2026-10-21) + the batch
#: qualifier ci-gate (D4: required later). Each must read exactly "success" on the candidate SHA.
REQUIRED_CHECKS_FLOOR = frozenset({"cio-hardening", "agent-governance", "release-readiness"})
#: Never delegable, whatever the record says (AGENTS §0 rules 1-2; §23.14). Matched as whole words.
FORBIDDEN_CLASS_WORDS = ("broker", "order", "orders", "execution", "active_trader", "activetrader", "trading",
                         "secret", "secrets", "credential", "credentials", "stop_manager", "daemon", "guard",
                         "policy", "agents_md")
HARD_MAX_TTL_S = 3600
HARD_MAX_ATTEMPTS = 3
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CLASS_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


@dataclass
class DelegationVerdict:
    authorized: bool
    code: str                       # AUTHORIZED | MISSING | UNREADABLE | INVALID | PAUSED | REVOKED | IN_REPO
    detail: str = ""
    status: Optional[str] = None
    delegation: Optional[dict] = None
    digest: Optional[str] = None
    errors: list[str] = field(default_factory=list)


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def policy_digest(delegation: dict) -> str:
    """sha256 of the canonical JSON: any edit to any field changes it (and so invalidates every capability)."""
    return hashlib.sha256(canonical(delegation)).hexdigest()


def _is_int(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def forbidden_class(name: str) -> bool:
    words = set(re.split(r"[^a-z0-9]+", name.lower())) | {name.lower()}
    return any(w in words for w in FORBIDDEN_CLASS_WORDS)


def validate(d: Any) -> list[str]:
    """Every problem with the record; empty means structurally valid (status is judged separately)."""
    errs: list[str] = []
    if not isinstance(d, dict):
        return [f"delegation is {type(d).__name__}, not an object"]
    if d.get("schema") != SCHEMA:
        errs.append(f"schema {d.get('schema')!r} != {SCHEMA!r}")
    if d.get("status") not in STATUSES:
        errs.append(f"unknown status {d.get('status')!r}")
    did = d.get("delegation_id")
    if not (isinstance(did, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{5,63}", did)):
        errs.append("delegation_id must be 6-64 chars [a-z0-9-]")
    if d.get("repository") != REPOSITORY:
        errs.append(f"repository must be {REPOSITORY!r}")
    if d.get("environment") not in ENVIRONMENTS:
        errs.append(f"environment must be one of {sorted(ENVIRONMENTS)}")
    if not _is_int(d.get("revocation_epoch"), 1, 10**9):
        errs.append("revocation_epoch must be an integer >= 1")
    op = d.get("operator")
    if not (isinstance(op, dict) and isinstance(op.get("github_login"), str) and op.get("github_login")
            and isinstance(op.get("approved_at"), str) and op.get("approved_at")
            and op.get("approved_via") in ("host_cli", "telegram")):
        errs.append("operator needs github_login, approved_at and approved_via in {host_cli, telegram}")
    classes = d.get("permitted_classes")
    if not (isinstance(classes, list) and classes and all(isinstance(c, str) and CLASS_RE.match(c) for c in classes)):
        errs.append("permitted_classes must be a non-empty list of lower_snake names")
    else:
        bad = [c for c in classes if forbidden_class(c)]
        if bad:
            errs.append(f"permitted_classes names never-delegable classes: {bad}")
        if len(set(classes)) != len(classes):
            errs.append("permitted_classes has duplicates")
    errs += _validate_windows(d.get("windows"))
    errs += _validate_freeze(d.get("merge_freeze"))
    errs += _validate_limits(d.get("limits"))
    errs += _validate_verification(d.get("verification_policy"))
    if "phase" in d and d.get("phase") not in PHASES:
        errs.append(f"phase must be one of {sorted(PHASES)} (optional)")
    known = {"schema", "delegation_id", "status", "repository", "environment", "revocation_epoch", "operator",
             "permitted_classes", "windows", "merge_freeze", "limits", "verification_policy", "notes", "phase"}
    extra = sorted(set(d) - known)
    if extra:
        errs.append(f"unknown fields {extra}")
    return errs


def _validate_windows(w: Any) -> list[str]:
    if not isinstance(w, dict) or w.get("timezone") != TIMEZONE or not isinstance(w.get("slots"), list):
        return [f"windows needs timezone {TIMEZONE!r} and a slots list"]
    errs = []
    ids = []
    for s in w["slots"]:
        if not isinstance(s, dict):
            errs.append("window slot is not an object")
            continue
        ids.append(s.get("window_id"))
        if s.get("window_id") not in WINDOW_IDS:
            errs.append(f"window_id {s.get('window_id')!r} not in {WINDOW_IDS}")
        if not (isinstance(s.get("start_et"), str) and HHMM_RE.match(s["start_et"])):
            errs.append(f"{s.get('window_id')}: start_et must be HH:MM")
        elif s.get("window_id") in WINDOW_IDS and s["start_et"].replace(":", "") != s["window_id"]:
            errs.append(f"{s.get('window_id')}: start_et {s['start_et']} does not match the window id")
        if not _is_int(s.get("duration_min"), 5, 240):
            errs.append(f"{s.get('window_id')}: duration_min must be 5..240")
        if not isinstance(s.get("enabled"), bool):
            errs.append(f"{s.get('window_id')}: enabled must be a boolean")
        if s.get("window_id") == "0800":
            if not (isinstance(s.get("latest_start_et"), str) and HHMM_RE.match(s["latest_start_et"])):
                errs.append("0800: latest_start_et (09:00 minus promote+verify+rollback minus buffer) required")
            if s.get("skip_on_macro_days") is not True:
                errs.append("0800: skip_on_macro_days must be true")
    if len(set(ids)) != len(ids):
        errs.append("duplicate window ids")
    if w.get("catch_up") is not False:
        errs.append("windows.catch_up must be false (no catch-up after a missed window)")
    return errs


def _validate_freeze(f: Any) -> list[str]:
    if not isinstance(f, dict):
        return ["merge_freeze must be an object"]
    errs = []
    if not _is_int(f.get("starts_min_before_window"), 0, 120):
        errs.append("merge_freeze.starts_min_before_window must be 0..120")
    if f.get("ends") != "train_terminal":
        errs.append("merge_freeze.ends must be 'train_terminal'")
    if f.get("applies_to") != "all_non_train_merges_to_main":
        errs.append("merge_freeze.applies_to must be 'all_non_train_merges_to_main'")
    return errs


def _validate_limits(lim: Any) -> list[str]:
    if not isinstance(lim, dict):
        return ["limits must be an object"]
    errs = []
    for k, lo, hi in (("max_prs_per_train", 1, 50), ("max_trains_per_window", 1, 1),
                      ("capability_ttl_s", 60, HARD_MAX_TTL_S), ("max_attempts_per_capability", 1, HARD_MAX_ATTEMPTS),
                      ("max_changed_files_per_train", 1, 5000)):
        if not _is_int(lim.get(k), lo, hi):
            errs.append(f"limits.{k} must be {lo}..{hi}")
    svc = lim.get("named_services")
    if not (isinstance(svc, list) and svc and all(isinstance(s, str) and s.endswith(".service") for s in svc)):
        errs.append("limits.named_services must list systemd *.service units")
    return errs


def _validate_verification(v: Any) -> list[str]:
    if not isinstance(v, dict):
        return ["verification_policy must be an object"]
    errs = []
    req = v.get("required_checks")
    if not (isinstance(req, list) and all(isinstance(c, str) for c in req)):
        errs.append("verification_policy.required_checks must be a list of check names")
    elif not REQUIRED_CHECKS_FLOOR <= set(req):
        errs.append(f"verification_policy.required_checks must include {sorted(REQUIRED_CHECKS_FLOOR)}")
    if v.get("batch_qualifier") != "ci-gate":
        errs.append("verification_policy.batch_qualifier must be 'ci-gate'")
    if v.get("conclusion_required") != "success":
        errs.append("verification_policy.conclusion_required must be 'success' (neutral/skipped never pass)")
    if v.get("exact_sha") is not True:
        errs.append("verification_policy.exact_sha must be true")
    if v.get("tree_equivalence_fallback") is not False:
        errs.append("verification_policy.tree_equivalence_fallback must be false")
    post = v.get("post_promote")
    if not (isinstance(post, list) and post):
        errs.append("verification_policy.post_promote must list the verifications")
    if v.get("rollback_on_failure") is not True or v.get("latch_stop_on_rollback") is not True:
        errs.append("verification_policy: rollback_on_failure and latch_stop_on_rollback must be true")
    return errs


def _inside_repo(path: Path) -> bool:
    try:
        rp = path.resolve()
    except OSError:
        return True
    try:
        rp.relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def load(path: Optional[Path] = None, *, allow_repo_path: bool = False) -> DelegationVerdict:
    """Load and judge the delegation. Never raises; every failure is a NOT-authorized verdict."""
    p = Path(path) if path is not None else DEFAULT_PATH
    if not allow_repo_path and _inside_repo(p):
        return DelegationVerdict(False, "IN_REPO", f"{p} is inside the repository; a train could edit its own "
                                                   "authority. The real record lives on the host only")
    if not os.path.lexists(p):
        return DelegationVerdict(False, "MISSING", f"{p} does not exist (never armed)")
    try:
        raw = p.read_text(encoding="utf-8")
        d = json.loads(raw)
    except (OSError, ValueError) as exc:
        return DelegationVerdict(False, "UNREADABLE", f"{type(exc).__name__}: {str(exc)[:160]}")
    errs = validate(d)
    if errs:
        status = d.get("status") if isinstance(d, dict) else None
        return DelegationVerdict(False, "INVALID", "; ".join(errs)[:600], status=status if status in STATUSES
                                 else None, errors=errs)
    digest = policy_digest(d)
    if d["status"] != ACTIVE:
        return DelegationVerdict(False, d["status"], f"delegation {d['delegation_id']} is {d['status']}",
                                 status=d["status"], delegation=d, digest=digest)
    return DelegationVerdict(True, "AUTHORIZED", "", status=ACTIVE, delegation=d, digest=digest)
