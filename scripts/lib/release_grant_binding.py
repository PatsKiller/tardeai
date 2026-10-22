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
  * SHA wins over PR (2026-10-09, due diligence B §2 / R2): when the grant's
    reason names one or more commit SHAs, the target SHA MUST be one of them.
    A PR match alone no longer binds such a grant — a train grant that lists
    ten PRs and one SHA used to authorize ANY SHA for any of those ten PRs,
    because ``--pr`` comes from ``TRADEAI_RELEASE_PR``, which the actor sets.
    A grant that names no SHA keeps the PR match (``matched_by`` says
    ``pr:#N`` without a ``sha:`` entry). A campaign match (the actor runs under
    ``TRADEAI_RELEASE_CAMPAIGN`` and the grant names that campaign) still binds
    on its own: campaign grants authorize a series of releases by design.
    Hex values bound to a key (``remote_request_id=0e7f…``, ``chat=8797…``)
    and all-digit runs are not treated as SHAs.
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
# A SHA the grant NAMES: a free-standing 9–40 hex run that is not the value of a
# key=value pair (request ids, chat ids) and contains at least one a–f letter
# (a 10-digit chat id or a dollar amount is not a commit).
_NAMED_SHA_RE = re.compile(r"(?<![=0-9a-z_])([0-9a-f]{9,40})(?![0-9a-z_])")
_ACTION_RE = re.compile(r"\b(prepare|promote|rollback|roll back|verify)\b", re.IGNORECASE)
# Release-window campaign (2026-10-16 runner; second spelling 2026-10-21 release train). A grant reason may name a
# window as the campaign id itself ("release-window-20261021-1200") or as "RELEASE_WINDOW <date> <window>"
# ("RELEASE_WINDOW 20261021 1200" / "RELEASE_WINDOW 2026-10-21 12:00"). Both normalize to the same campaign id;
# the id only binds when the action runs under that campaign (TRADEAI_RELEASE_CAMPAIGN, set by
# scripts/release_window.py), so a window grant never authorizes a release outside its window.
_WINDOW_ID_RE = re.compile(r"\brelease-window-(\d{8})-(\d{4})\b", re.IGNORECASE)
_WINDOW_TOKEN_RE = re.compile(r"\bRELEASE_WINDOW\s+(\d{4})-?(\d{2})-?(\d{2})\s+(\d{2}):?(\d{2})\b")


def window_campaigns(text: str) -> list[str]:
    """Every release-window campaign id a grant reason names, in either spelling, sorted and de-duplicated."""
    ids = {f"release-window-{d}-{t}" for d, t in _WINDOW_ID_RE.findall(text or "")}
    ids |= {f"release-window-{y}{m}{d}-{hh}{mm}" for y, m, d, hh, mm in _WINDOW_TOKEN_RE.findall(text or "")}
    return sorted(ids)


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


_RRID_RE = re.compile(r"\[remote_request_id=([0-9A-Za-z_-]{4,64})\b")
_CLOSED_STATUSES = ("revoked", "replaced")


def _grant_row(key: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """One grant row, normalized: tier from the row or its key ("<tier>" v1, "<tier>@<grant_id>" v2),
    remote_request_id from the row or (older rows) the "[remote_request_id=...]" reason suffix."""
    out = dict(row)
    out["tier"] = row.get("tier") or (key.split("@", 1)[0] if "@" in key else key)
    if not out.get("remote_request_id"):
        m = _RRID_RE.search(str(row.get("reason") or ""))
        if m:
            out["remote_request_id"] = m.group(1)
    return out


def load_grants(path: Path = GRANTS_PATH) -> list[dict[str, Any]]:
    """Grant rows as the guard stores them: v1 {tier: row}, v2 {"<tier>@<grant_id>": row}, or a list.

    Closed v2 rows (status revoked / replaced) are not grants and are left out."""
    raw = _load_json(path)
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for key, row in raw.items():
            if isinstance(row, dict):
                rows.append(_grant_row(str(key), row))
            elif isinstance(row, list):
                rows.extend(_grant_row(str(key), r) for r in row if isinstance(r, dict))
    elif isinstance(raw, list):
        rows = [_grant_row(str(r.get("tier") or ""), r) for r in raw if isinstance(r, dict)]
    return [r for r in rows if str(r.get("status") or "active") not in _CLOSED_STATUSES]


def normalize_request(r: Mapping[str, Any]) -> dict[str, Any]:
    """`scope` and `tier` are one field (guard_remote_approval wrote `scope`; this module and the ledger
    read `tier`); `request_id` and `id` likewise. Copied, never renamed. When `scope` and `tier`
    disagree the row gets tier None and binds nothing."""
    out = dict(r)
    scope, tier = r.get("scope"), r.get("tier")
    if scope is not None and tier is not None and str(scope).strip() != str(tier).strip():
        out["tier"] = None
        out["scope_conflict"] = True
    elif scope is not None or tier is not None:
        out["tier"] = out["scope"] = str(scope if scope is not None else tier).strip()
    rid = r.get("request_id") or r.get("id")
    if rid:
        out["request_id"] = str(rid)
    return out


def load_requests(path: Path = REQUESTS_PATH) -> list[dict[str, Any]]:
    raw = _load_json(path)
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        vals = raw.get("requests") if isinstance(raw.get("requests"), (list, dict)) else raw
        if isinstance(vals, dict):
            rows = [{**v, "request_id": v.get("request_id") or v.get("id") or k}
                    for k, v in vals.items() if isinstance(v, dict)]
        elif isinstance(vals, list):
            rows = [r for r in vals if isinstance(r, dict)]
    elif isinstance(raw, list):
        rows = [r for r in raw if isinstance(r, dict)]
    return [normalize_request(r) for r in rows]


def named_shas(reason: str) -> list[str]:
    """The commit SHAs a grant/request text names (lower-case, in order, de-duplicated)."""
    out: list[str] = []
    for cand in _NAMED_SHA_RE.findall((reason or "").lower()):
        if any(c in "abcdef" for c in cand) and cand not in out:
            out.append(cand)
    return out


def _sha_matches(target: str, cand: str) -> bool:
    return target.startswith(cand[:9]) or cand.startswith(target[:9])


def _names_action(reason: str, act: ReleaseAction) -> list[str]:
    """Which of the action's binding facts the grant text names."""
    text = reason or ""
    hit: list[str] = []
    if act.pr_number is not None and any(int(n) == int(act.pr_number) for n in _PR_RE.findall(text)):
        hit.append(f"pr:#{act.pr_number}")
    sha = (act.target_sha or "").lower()
    if sha and len(sha) >= 9:
        for cand in named_shas(text):
            if _sha_matches(sha, cand):
                hit.append(f"sha:{cand[:12]}")
                break
    if act.campaign and (act.campaign.lower() in text.lower() or act.campaign.lower() in window_campaigns(text)):
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
        r = normalize_request(r)  # rows from the store carry `scope`; before 2026-10-21 this never matched
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
    grants = list(grants)
    live = []
    for g in grants:
        if str(g.get("tier") or "") != TIER or str(g.get("status") or "active") in _CLOSED_STATUSES:
            continue
        try:
            if float(g.get("expires") or g.get("expires_at") or 0) > now and int(g.get("uses") or 0) != 0:
                live.append(str(g.get("grant_id") or g.get("id") or ""))
        except (TypeError, ValueError):
            continue
    if len(live) > 1:
        # One active grant per tier (guard ledger v2). More than one is a broken invariant: never pick
        # one silently and never let two answer for each other.
        return Verdict(False, f"ambiguous: {len(live)} active release-write grants ({', '.join(live)}); "
                       "revoke all but one (bin/guard revoke release-write --grant-id <id>)",
                       pending_request_ids=pend_ids)
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
        listed_shas = named_shas(reason)
        campaign_bound = any(m.startswith("campaign:") for m in named)
        if listed_shas and not campaign_bound and not any(m.startswith("sha:") for m in named):
            # SHA wins over PR: the grant names the commit(s) it approves and
            # this is not one of them. A PR (or settled-request) match cannot
            # widen it to another SHA.
            refused.append({"grant_id": gid, "why": "grant names SHA(s) "
                            + ", ".join(c[:12] for c in listed_shas[:5])
                            + f"; target {act.target_sha[:12]} is not one of them (a PR match alone does not bind)",
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


# ── the standing-release binding: the host capability ledger (arming packet §K) ───────────────────────────
#
# PROPOSED, inert. While ``CAPABILITY_BINDING_STATUS`` is not "ACTIVE", ``release_grant_preflight.py`` never calls
# ``decide_capability`` and its output is byte-identical to the grant-only behaviour above. The flag is a code
# constant in this protected surface (release_train_controller.PROTECTED_SURFACES): it moves only by a reviewed PR
# released by the manual path (packet L.1), after the operator says so. No environment variable, argument or file
# turns it on.
#
# When ACTIVE, a train's ``prepare`` / ``promote`` with no binding grant is accepted only when ALL of these hold
# (packet §K; AGENTS §25.2 "checks first, then one reservation, then the effect"):
#   * the action runs under campaign ``release-train-<train_id>`` (the campaign IDENTIFIES the train; it grants
#     nothing);
#   * ``<state_dir>/trains/<train_id>/capability/<action>_release.rcap`` holds a ReleaseCapability@v1 token whose
#     HMAC verifies with the host key and whose sha256 equals the ledger's issued record (a forged, edited or
#     substituted token is refused);
#   * the capability is a ``promote``-phase capability for THIS train, permits ``prepare_release`` /
#     ``promote_release``, binds exactly ``--sha`` as its candidate, is inside its validity window, and names a
#     non-empty service set inside the delegation's ``limits.named_services``;
#   * the capability ledger ``<state_dir>/capabilities.json`` holds exactly one RESERVED intent for that capability,
#     train and action, observed at reservation with the same candidate SHA and the capability's artifact digest
#     (and ``--artifact-digest``, when the caller passes it); no intent under that capability and action is already
#     applied (replay) and no intent anywhere is UNCERTAIN (reconcile first);
#   * the reservation's holder is alive: the global release ``.lock`` is held (a RESERVED intent whose holder died
#     is an UNCERTAIN effect, never an authority);
#   * the control state: latch ABSENT, no mutation refusal for this train (RUNNING; PAUSE_REQUESTED lets the
#     current train finish, as the capability issuer allows), current train == this train, control epoch == the
#     capability's and the intent's, accepted policy digest == the capability's;
#   * the delegation on the host loads authorized, and its digest, id and revocation epoch equal the capability's.
# The guard ledger is not consumed (the capability's attempt budget is the accounting). A per-PR grant keeps
# working unchanged and is tried first. The state dir is the default one; an environment override that resolves to
# a different directory is refused (a planted state dir must not stand in for the real control and ledger).

CAPABILITY_BINDING_STATUS = "PROPOSED"
CAPABILITY_BINDING_SCHEMA = "ReleaseCapabilityBinding@v1"
CAPABILITY_ACTIONS = {"prepare": "prepare_release", "promote": "promote_release"}
TRAIN_CAMPAIGN_PREFIX = "release-train-"
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def default_release_state_dir() -> Path:
    """The release-window state dir as ``release_window.py`` resolves it with no override."""
    root = Path(os.environ.get("TRADEAI_STATE_ROOT", str(Path.home() / "trade-ai-releases" / "persistent-state")))
    return root / "data" / "runtime" / "release_window"


def capability_binding_active(status: Optional[str] = None) -> bool:
    return (status if status is not None else CAPABILITY_BINDING_STATUS) == "ACTIVE"


def train_id_from_campaign(campaign: Optional[str]) -> Optional[str]:
    """``release-train-<train id>`` -> the train id (a valid ReleaseCapability train id), else None."""
    from scripts.lib import release_capability as CAP  # noqa: PLC0415 - lazy: inert unless the binding is ACTIVE

    c = str(campaign or "")
    if not c.startswith(TRAIN_CAMPAIGN_PREFIX):
        return None
    tid = c[len(TRAIN_CAMPAIGN_PREFIX):]
    return tid if CAP.TRAIN_RE.match(tid) else None


def reservation_token_path(state_dir: Path, train_id: str, cap_action: str) -> Path:
    return Path(state_dir) / "trains" / train_id / "capability" / f"{cap_action}.rcap"


def write_reservation_token(state_dir: Path, train_id: str, cap_action: str, token: str) -> Path:
    """For the controller, while it holds the reservation: put the signed token where the preflight looks
    (mode 600, atomic). The token alone grants nothing: the preflight also needs the RESERVED intent, a live lock
    holder and the current control and delegation."""
    p = reservation_token_path(state_dir, train_id, cap_action)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(token)
    os.replace(tmp, p)
    return p


@dataclass
class CapabilityVerdict:
    allowed: bool
    code: str
    reason: str
    train_id: Optional[str] = None
    capability_id: Optional[str] = None
    intent_id: Optional[str] = None
    matched_by: list[str] = field(default_factory=list)
    schema: str = CAPABILITY_BINDING_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "allowed": self.allowed, "code": self.code, "reason": self.reason,
                "train_id": self.train_id, "capability_id": self.capability_id, "intent_id": self.intent_id,
                "matched_by": list(self.matched_by)}


class _Refuse(Exception):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(code)
        self.code, self.reason = code, reason


def _read_token(path: Path) -> str:
    import stat as _stat  # noqa: PLC0415

    try:
        st = os.lstat(path)
    except OSError:
        raise _Refuse("TOKEN_MISSING", f"no reservation token at {path}") from None
    if not _stat.S_ISREG(st.st_mode):
        raise _Refuse("TOKEN_UNSAFE", f"{path} is not a regular file")
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise _Refuse("TOKEN_UNSAFE", f"{path} must be owned by this user, mode 600")
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        raise _Refuse("TOKEN_UNREADABLE", str(path)) from None


def _lock_holder_alive(state_dir: Path, lock_name: str) -> bool:
    """True when another open file description holds the global release lock. Read-only: never creates it."""
    import fcntl  # noqa: PLC0415

    try:
        fd = os.open(Path(state_dir) / lock_name, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True                        # busy: the reservation's holder still has it
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def decide_capability(action: str, sha: str, campaign: Optional[str], *, state_dir: Optional[Path] = None,
                      key_path: Optional[Path] = None, delegation_path: Optional[Path] = None,
                      artifact_digest: Optional[str] = None, now: Optional[float] = None,
                      status: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> CapabilityVerdict:
    """The packet-§K verdict for one train ``prepare``/``promote``. Read-only and fail closed: every unmet
    condition is a refusal with a stable ``code``; nothing is written, consumed or created."""
    try:
        return _decide_capability(action, sha, campaign, state_dir=state_dir, key_path=key_path,
                                  delegation_path=delegation_path, artifact_digest=artifact_digest, now=now,
                                  status=status, env=env)
    except _Refuse as r:
        return CapabilityVerdict(False, r.code, r.reason)


def _decide_capability(action: str, sha: str, campaign: Optional[str], *, state_dir: Optional[Path],
                       key_path: Optional[Path], delegation_path: Optional[Path], artifact_digest: Optional[str],
                       now: Optional[float], status: Optional[str],
                       env: Optional[Mapping[str, str]]) -> CapabilityVerdict:
    if not capability_binding_active(status):
        raise _Refuse("BINDING_NOT_ACTIVE", f"CAPABILITY_BINDING_STATUS={status or CAPABILITY_BINDING_STATUS}")
    from scripts.lib import release_capability as CAP  # noqa: PLC0415
    from scripts.lib import release_control as RC  # noqa: PLC0415
    from scripts.lib import release_delegation as RD  # noqa: PLC0415

    cap_action = CAPABILITY_ACTIONS.get(action)
    if cap_action is None:
        raise _Refuse("ACTION_NOT_BOUND", f"{action!r}: only prepare and promote bind to a capability")
    train_id = train_id_from_campaign(campaign)
    if train_id is None:
        raise _Refuse("CAMPAIGN_NOT_TRAIN", f"campaign {campaign!r} is not release-train-<train id>")
    sha = str(sha or "").lower()
    if not _FULL_SHA_RE.match(sha):
        raise _Refuse("SHA_INVALID", "a capability binds a full 40-hex SHA")
    if artifact_digest is not None and not _DIGEST_RE.match(str(artifact_digest)):
        raise _Refuse("ARTIFACT_DIGEST_INVALID", "sha256:<64 hex>")
    default_sd = default_release_state_dir()
    if state_dir is None:
        e = os.environ if env is None else env
        override = e.get("TRADEAI_RELEASE_WINDOW_STATE_DIR")
        if override and os.path.realpath(override) != os.path.realpath(default_sd):
            raise _Refuse("STATE_DIR_OVERRIDDEN", "TRADEAI_RELEASE_WINDOW_STATE_DIR names another directory; the "
                          "binding reads only the default release state dir")
        state_dir = default_sd
    state_dir = Path(state_dir)
    now = time.time() if now is None else float(now)

    # 1. the token: signed by the host key, equal to the issued record
    token = _read_token(reservation_token_path(state_dir, train_id, cap_action))
    try:
        key = CAP.load_key(Path(key_path) if key_path is not None else CAP.DEFAULT_KEY_PATH)
        cap = CAP.decode(token, key)
    except RC.ControlRefused as exc:
        raise _Refuse(exc.code, str(exc.detail)[:200]) from None
    cid = str(cap.get("capability_id") or "")
    if cap.get("train_id") != train_id:
        raise _Refuse("WRONG_TRAIN", f"capability is for {cap.get('train_id')!r}, campaign names {train_id!r}")
    if cap.get("phase") != CAP.PHASE_PROMOTE:
        raise _Refuse("WRONG_PHASE", f"{cap.get('phase')!r} capability cannot {cap_action}")
    if cap_action not in (cap.get("permitted_actions") or []):
        raise _Refuse("ACTION_NOT_PERMITTED", f"{cap_action} not in {cap.get('permitted_actions')}")
    if cap.get("candidate_sha") != sha:
        raise _Refuse("WRONG_SHA", f"capability binds {str(cap.get('candidate_sha'))[:12]}, not {sha[:12]}")
    try:
        if not float(cap["not_before"]) <= now < float(cap["expires_at"]):
            raise _Refuse("CAPABILITY_EXPIRED", "outside its validity window")
    except (KeyError, TypeError, ValueError):
        raise _Refuse("TOKEN_MALFORMED", "validity window") from None
    services = cap.get("services")
    if not isinstance(services, list) or not services:
        raise _Refuse("SERVICES_REQUIRED", "a promote capability names its services")
    if artifact_digest is not None and cap.get("artifact_digest") != artifact_digest:
        raise _Refuse("WRONG_ARTIFACT", "artifact digest differs from the capability's")

    # 2. the ledger: issued record, one live RESERVED intent, no replay, nothing uncertain
    import hashlib  # noqa: PLC0415

    ledger_path = state_dir / CAP.LEDGER_NAME
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        caps, intents = ledger["caps"], ledger["intents"]
        if ledger.get("schema") != CAP.LEDGER_SCHEMA or not isinstance(caps, dict) or not isinstance(intents, dict):
            raise ValueError("schema")
    except (OSError, ValueError, KeyError, TypeError):
        raise _Refuse("LEDGER_UNREADABLE", f"{ledger_path}") from None
    entry = caps.get(cid)
    if not isinstance(entry, dict) or entry.get("token_sha256") != hashlib.sha256(token.encode()).hexdigest():
        raise _Refuse("CAPABILITY_UNKNOWN", "token is not the issued record")
    if entry.get("status") != "ISSUED" or entry.get("train_id") != train_id:
        raise _Refuse("CAPABILITY_NOT_ISSUED", str(entry.get("status")))
    rows = [i for i in intents.values() if isinstance(i, dict)]
    if any(i.get("status") == CAP.UNCERTAIN for i in rows):
        raise _Refuse("RECONCILIATION_REQUIRED", "an UNCERTAIN intent blocks every release mutation")
    mine = [i for i in rows if i.get("capability_id") == cid and i.get("action") == cap_action]
    if any(i.get("status") in CAP.APPLIED_STATES for i in mine):
        raise _Refuse("REPLAY", f"{cap_action} already applied under this capability")
    reserved = [i for i in mine if i.get("status") == CAP.RESERVED and i.get("train_id") == train_id]
    if len(reserved) != 1:
        raise _Refuse("RESERVATION_MISSING", f"{len(reserved)} RESERVED intents for {cap_action} (exactly 1 needed)")
    intent = reserved[0]
    obs = intent.get("observed") if isinstance(intent.get("observed"), dict) else {}
    if obs.get("candidate_sha") != sha or obs.get("artifact_digest") != cap.get("artifact_digest"):
        raise _Refuse("RESERVATION_MISMATCH", "the reservation observed another candidate or artifact")
    if not _lock_holder_alive(state_dir, RC.GLOBAL_LOCK_NAME):
        raise _Refuse("RESERVATION_HOLDER_GONE", "the global release lock is free: no live holder of this reservation")

    # 3. control: STOP latch, mode, train, epoch, accepted digest
    view = RC.ReleaseControl(state_dir).view()
    if view.latch_state != RC.LATCH_ABSENT:
        raise _Refuse("STOP_LATCHED" if view.latch_state == RC.LATCH_SET else "STOP_LATCH_UNREADABLE",
                      f"latch {view.latch_state}")
    refusal = view.mutation_refusal(train_id)
    if refusal:
        raise _Refuse(refusal, f"control mode {view.mode}")
    if view.current_train_id != train_id:
        raise _Refuse("TRAIN_NOT_CLAIMED", f"current train is {view.current_train_id!r}")
    if view.epoch != cap.get("control_epoch") or intent.get("control_epoch") != view.epoch:
        raise _Refuse("EPOCH_STALE", f"control epoch {view.epoch} != capability {cap.get('control_epoch')}")
    if view.accepted_policy_digest != cap.get("policy_digest"):
        raise _Refuse("POLICY_DIGEST_CHANGED", "accepted digest differs from the capability's")

    # 4. delegation on the host
    dv = RD.load(delegation_path)
    if not dv.authorized:
        raise _Refuse(f"DELEGATION_{dv.code}", str(dv.detail)[:200])
    d = dv.delegation or {}
    if dv.digest != cap.get("policy_digest"):
        raise _Refuse("POLICY_DIGEST_CHANGED", "delegation changed since issuance")
    if d.get("delegation_id") != cap.get("delegation_id"):
        raise _Refuse("DELEGATION_MISMATCH", "different delegation")
    if d.get("revocation_epoch") != cap.get("delegation_epoch"):
        raise _Refuse("DELEGATION_EPOCH_STALE", f"{cap.get('delegation_epoch')} != {d.get('revocation_epoch')}")
    named = set((d.get("limits") or {}).get("named_services") or [])
    if not set(services) <= named:
        raise _Refuse("SERVICE_NOT_NAMED", f"{sorted(set(services) - named)}")

    return CapabilityVerdict(True, "CAPABILITY_RESERVED", f"RESERVED {cap_action} capability for train {train_id}",
                             train_id=train_id, capability_id=cid, intent_id=str(intent.get("intent_id") or ""),
                             matched_by=[f"campaign:{campaign}", f"capability:{cid}",
                                         f"intent:{intent.get('intent_id')}", f"sha:{sha[:12]}"])


__all__ = ["SCHEMA", "TIER", "ACTIONS", "ReleaseAction", "Verdict", "decide", "decide_from_disk",
           "load_grants", "load_requests", "named_shas", "pending_requests_for", "window_campaigns",
           "CAPABILITY_BINDING_STATUS", "CapabilityVerdict", "capability_binding_active", "decide_capability",
           "default_release_state_dir", "reservation_token_path", "train_id_from_campaign",
           "write_reservation_token"]
