"""Release capability issuer (ReleaseCapability@v1): short-lived, single-train, single-phase. Library only.

Release Train v2, Phase 2 (enhanced design 2026-10-21 §3). The standing delegation (``release_delegation``) is a
policy record; this module turns it into authority one train and one phase at a time, and only while the control
state (``release_control``) has accepted that record's digest and is not stopped, paused or revoked. Nothing here
is wired into a live path: no timer, route, n8n lane or deploy script imports it.

Phases and what each may do (``PHASE_ACTIONS``). A capability's actions must be a subset of its phase's set, and a
reservation checks the action against BOTH the capability and the phase table, so a build/publish capability can
never merge or promote (phase confusion fails closed):

  build_publish  integrate, regenerate, local_test, build_artifact, push_train_ref, open_batch_pr
  merge          merge_batch_pr, update_main_ref
  promote        prepare_release, promote_release, verify_release, rollback_release, restart_service

Binding. Every capability binds the delegation id, policy digest and both epochs (the delegation's revocation
epoch and the control epoch), repository, environment, train id, the ordered PR heads, permitted actions, validity
window and attempt budget. A build/publish capability adds the base SHA and its output ref ``train/<train_id>``.
A merge or promote capability adds the expected base SHA, the candidate SHA, the artifact digest, the digest of
the qualifying CI evidence (every required check exactly ``success`` on the candidate), the named services (promote
only; a subset of the delegation's) and the exact rollback target.

Signature. HMAC-SHA256 over the canonical JSON body with a host key read from ``key_path`` (default
``~/.config/tradeai/release_train/capability.key``; a regular file, owned by this uid, mode 600, >= 32 bytes;
operator-created, never generated here). Tests pass a temp key. Environment variables never select the key, the
delegation or the authority (enhanced design §3: they may identify a request, never grant it).

Mutation order (``reserve``): verify the signature (no state) → take the ONE global release lock (``.lock`` in the
release_window state dir, non-blocking by default) → turn any intent a dead holder left RESERVED into UNCERTAIN →
refuse while any intent is UNCERTAIN (reconcile first) → check capability, budget, replay, delegation epoch and
digest, control epoch, STOP latch, pause and the observed remote state → only then write the intent record and
consume one attempt, in one atomic ledger write, and return a ``Reservation`` that keeps holding the lock through
the effect. Every refusal before that write consumes nothing. ``Reservation.recheck()`` re-reads revocation right
before the effect; a failed recheck refunds the attempt (no effect happened). An effect whose outcome is not known
is ``UNCERTAIN`` and blocks every reservation until ``reconcile`` records what actually happened.

Pre-build check (AGENTS §13.5): searched scripts/ and config/ for capability tokens, revocation epochs, release
delegation and HMAC signers; found ``cio_action_links`` and ``n8n_coordination_gateway`` HMAC signers (different
keys and purposes; not reused, so no key is shared across trust domains) and ``release_grant_binding`` (grant
text binding, unchanged). Nothing issued phase capabilities.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

try:
    from scripts.lib import release_control as RC
    from scripts.lib import release_delegation as RD
except ImportError:  # pragma: no cover - scripts/ on sys.path
    from lib import release_control as RC  # type: ignore[no-redef]
    from lib import release_delegation as RD  # type: ignore[no-redef]

SCHEMA = "ReleaseCapability@v1"
LEDGER_SCHEMA = "ReleaseCapabilityLedger@v1"
TOKEN_PREFIX = "rcap1"
LEDGER_NAME = "capabilities.json"
INTENT_JOURNAL_NAME = "capability_intents.jsonl"
DEFAULT_KEY_PATH = Path.home() / ".config" / "tradeai" / "release_train" / "capability.key"
MIN_KEY_BYTES = 32

PHASE_BUILD, PHASE_MERGE, PHASE_PROMOTE = "build_publish", "merge", "promote"
PHASE_ACTIONS: dict[str, frozenset[str]] = {
    PHASE_BUILD: frozenset({"integrate", "regenerate", "local_test", "build_artifact", "push_train_ref",
                            "open_batch_pr"}),
    PHASE_MERGE: frozenset({"merge_batch_pr", "update_main_ref"}),
    PHASE_PROMOTE: frozenset({"prepare_release", "promote_release", "verify_release", "rollback_release",
                              "restart_service"}),
}
EVIDENCE_PHASES = frozenset({PHASE_MERGE, PHASE_PROMOTE})

# Intent states
RESERVED, SUCCEEDED, FAILED_NO_EFFECT, UNCERTAIN = "RESERVED", "SUCCEEDED", "FAILED_NO_EFFECT", "UNCERTAIN"
ABORTED_NO_EFFECT, RECONCILED_APPLIED, RECONCILED_ABSENT = "ABORTED_NO_EFFECT", "RECONCILED_APPLIED", \
    "RECONCILED_ABSENT"
APPLIED_STATES = frozenset({SUCCEEDED, RECONCILED_APPLIED})

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
#: ``train-YYYYMMDD-HHMM[-x]`` (Phase 2 original) or ``rt-YYYYMMDD-HHMM-<suffix>``, the id the Phase 1 store and the
#: read-only Command Center view use (docs/ops/RELEASE_TRAIN_API.md §6). The controller issues ``rt-`` ids.
TRAIN_RE = re.compile(r"^(?:train-\d{8}-\d{4}(?:-[a-z0-9]{1,12})?|rt-\d{8}-\d{4}-[a-z0-9]{4,12})$")


class CapabilityRefused(RC.ControlRefused):
    """Refused. Stable ``code``. Unless the code says otherwise, nothing was consumed."""


# ── key ──────────────────────────────────────────────────────────────────────────────────────────────

def load_key(path: Path) -> bytes:
    """The host HMAC key, fail closed: a regular file (not a symlink), owned by this uid, no group/other bits,
    at least 32 bytes. Never created here: the operator provisions it (docs/ops/RELEASE_TRAIN_GITHUB_APP.md)."""
    p = Path(path)
    try:
        st = os.lstat(p)
    except FileNotFoundError as exc:
        raise CapabilityRefused("KEY_MISSING", str(p)) from exc
    except OSError as exc:
        raise CapabilityRefused("KEY_UNREADABLE", f"{p}: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise CapabilityRefused("KEY_NOT_REGULAR_FILE", str(p))
    if st.st_uid != os.getuid():
        raise CapabilityRefused("KEY_WRONG_OWNER", str(p))
    if st.st_mode & 0o077:
        raise CapabilityRefused("KEY_MODE_TOO_OPEN", f"{p} is {oct(st.st_mode & 0o777)}; must be 600")
    try:
        key = p.read_bytes().strip()
    except OSError as exc:
        raise CapabilityRefused("KEY_UNREADABLE", f"{p}: {exc}") from exc
    if len(key) < MIN_KEY_BYTES:
        raise CapabilityRefused("KEY_TOO_SHORT", f"{len(key)} < {MIN_KEY_BYTES} bytes")
    return key


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(key: bytes, body_bytes: bytes) -> str:
    return hmac.new(key, body_bytes, hashlib.sha256).hexdigest()


def decode(token: str, key: bytes) -> dict:
    """Signature check only (no state): returns the body or raises SIGNATURE_INVALID / TOKEN_MALFORMED."""
    if not isinstance(token, str) or token.count(".") != 2:
        raise CapabilityRefused("TOKEN_MALFORMED", "expected rcap1.<body>.<sig>")
    prefix, b64, sig = token.split(".")
    if prefix != TOKEN_PREFIX:
        raise CapabilityRefused("TOKEN_MALFORMED", f"prefix {prefix!r}")
    try:
        raw = _b64d(b64)
    except (ValueError, TypeError) as exc:
        raise CapabilityRefused("TOKEN_MALFORMED", "body is not base64url") from exc
    if not hmac.compare_digest(_sign(key, raw), sig):
        raise CapabilityRefused("SIGNATURE_INVALID", "capability was not issued by this host key")
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise CapabilityRefused("TOKEN_MALFORMED", "body is not JSON") from exc
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        raise CapabilityRefused("TOKEN_MALFORMED", "schema")
    return body


def evidence_digest(evidence: dict) -> str:
    return "sha256:" + hashlib.sha256(RD.canonical(evidence)).hexdigest()


def check_evidence(evidence: Any, candidate_sha: str, required: list[str]) -> list[str]:
    """Qualifying CI evidence: every required check has at least one run on exactly ``candidate_sha`` and every
    run of it on that SHA is completed with conclusion exactly ``success``. Neutral, skipped, cancelled, stale or
    another SHA's run never counts (enhanced design §10)."""
    if not isinstance(evidence, dict) or evidence.get("sha") != candidate_sha:
        return ["evidence is not for the candidate SHA"]
    checks = evidence.get("checks")
    if not isinstance(checks, list):
        return ["evidence.checks missing"]
    errs = []
    for name in required:
        runs = [c for c in checks if isinstance(c, dict) and c.get("name") == name
                and c.get("head_sha") == candidate_sha]
        if not runs:
            errs.append(f"{name}: no run on {candidate_sha[:9]}")
            continue
        bad = [c for c in runs if c.get("status") != "completed" or c.get("conclusion") != "success"]
        if bad:
            errs.append(f"{name}: {bad[0].get('status')}/{bad[0].get('conclusion')} (exactly success required)")
    return errs


def open_window(delegation: dict, now_ts: float) -> Optional[dict]:
    """The enabled window containing ``now`` (America/New_York, DST-aware), else None. No catch-up."""
    tz = ZoneInfo(delegation["windows"]["timezone"])
    now = datetime.fromtimestamp(now_ts, tz)
    for slot in delegation["windows"]["slots"]:
        if not slot.get("enabled"):
            continue
        hh, mm = (int(x) for x in slot["start_et"].split(":"))
        for day in (now.date(), now.date() - timedelta(days=1)):
            start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            end = start + timedelta(minutes=int(slot["duration_min"]))
            if start <= now < end:
                return {**slot, "start_ts": start.timestamp(), "end_ts": end.timestamp()}
    return None


# ── the authority ────────────────────────────────────────────────────────────────────────────────────

class CapabilityAuthority:
    def __init__(self, state_dir: Path, *, key_path: Path = DEFAULT_KEY_PATH,
                 delegation_path: Optional[Path] = None, clock: Callable[[], float] = time.time,
                 lock_timeout_s: float = 0.0, allow_repo_delegation: bool = False) -> None:
        self.root = Path(state_dir)
        self.key_path = Path(key_path)
        self.delegation_path = delegation_path
        self.clock = clock
        self.lock_timeout_s = lock_timeout_s
        self.allow_repo_delegation = allow_repo_delegation
        self.control = RC.ReleaseControl(self.root, clock=clock)
        self.ledger_path = self.root / LEDGER_NAME
        self.journal_path = self.root / INTENT_JOURNAL_NAME

    # -- issuance ------------------------------------------------------------------------------------
    def issue_build(self, train_id: str, *, base_sha: str, pr_heads: list[dict], actions: list[str],
                    ttl_s: Optional[int] = None, attempts: int = 1, candidate_sha: Optional[str] = None) -> str:
        binding = {"base_sha": _sha(base_sha, "base_sha"), "output_ref": f"refs/heads/train/{train_id}",
                   "candidate_sha": _sha(candidate_sha, "candidate_sha") if candidate_sha else None}
        return self._issue(PHASE_BUILD, train_id, pr_heads, actions, ttl_s, attempts, binding)

    def issue_merge(self, train_id: str, *, expected_base_sha: str, pr_heads: list[dict], candidate_sha: str,
                    artifact_digest: str, evidence: dict, rollback_target: dict, actions: list[str],
                    ttl_s: Optional[int] = None, attempts: int = 1) -> str:
        binding = self._evidence_binding(expected_base_sha, candidate_sha, artifact_digest, evidence,
                                         rollback_target, services=[])
        return self._issue(PHASE_MERGE, train_id, pr_heads, actions, ttl_s, attempts, binding, evidence=evidence)

    def issue_promote(self, train_id: str, *, expected_base_sha: str, pr_heads: list[dict], candidate_sha: str,
                      artifact_digest: str, evidence: dict, rollback_target: dict, services: list[str],
                      actions: list[str], ttl_s: Optional[int] = None, attempts: int = 1,
                      batch_candidate_sha: Optional[str] = None, batch_evidence: Optional[dict] = None) -> str:
        """Qualification v1 (plan Phase 3): the batch PR head ``batch_candidate_sha`` carries every required check
        including the batch qualifier (``ci-gate``, a pull_request-only workflow), and the resulting main commit
        ``candidate_sha`` carries the exact-SHA push/main checks. When both are given, the main evidence must cover
        every required check except the batch qualifier and the batch evidence must cover all of them; both digests
        are bound. Without them, ``evidence`` alone must cover every required check (unchanged behaviour). This is
        not a tree-equivalence fallback: each SHA is qualified by runs on exactly that SHA."""
        if not services:
            raise CapabilityRefused("SERVICES_REQUIRED", "a promote capability names the services it restarts")
        binding = self._evidence_binding(expected_base_sha, candidate_sha, artifact_digest, evidence,
                                         rollback_target, services=services)
        if (batch_candidate_sha is None) != (batch_evidence is None):
            raise CapabilityRefused("BATCH_EVIDENCE_INCOMPLETE", "batch_candidate_sha and batch_evidence go together")
        if batch_candidate_sha is not None:
            if not isinstance(batch_evidence, dict):
                raise CapabilityRefused("EVIDENCE_MISSING", "batch evidence must be an object")
            binding["batch_candidate_sha"] = _sha(batch_candidate_sha, "batch_candidate_sha")
            binding["batch_evidence_digest"] = evidence_digest(batch_evidence)
        return self._issue(PHASE_PROMOTE, train_id, pr_heads, actions, ttl_s, attempts, binding, evidence=evidence,
                           batch_evidence=batch_evidence)

    def _evidence_binding(self, base: str, cand: str, artifact: str, evidence: dict, rollback: dict,
                          services: list[str]) -> dict:
        if not (isinstance(artifact, str) and DIGEST_RE.match(artifact)):
            raise CapabilityRefused("ARTIFACT_DIGEST_INVALID", "sha256:<64 hex> required")
        if not (isinstance(rollback, dict) and rollback.get("kind") in ("main_ref", "release")
                and isinstance(rollback.get("sha"), str) and SHA_RE.match(rollback["sha"])):
            raise CapabilityRefused("ROLLBACK_TARGET_INVALID", "{kind: main_ref|release, sha: <40 hex>} required")
        if not isinstance(evidence, dict):
            raise CapabilityRefused("EVIDENCE_MISSING", "qualifying CI evidence is required")
        return {"expected_base_sha": _sha(base, "expected_base_sha"), "candidate_sha": _sha(cand, "candidate_sha"),
                "artifact_digest": artifact, "evidence_digest": evidence_digest(evidence),
                "services": sorted(services), "rollback_target": {"kind": rollback["kind"], "sha": rollback["sha"],
                                                                  "release": rollback.get("release")}}

    def _issue(self, phase: str, train_id: str, pr_heads: Any, actions: Any, ttl_s: Optional[int],
               attempts: int, binding: dict, *, evidence: Optional[dict] = None,
               batch_evidence: Optional[dict] = None) -> str:
        key = load_key(self.key_path)
        if not (isinstance(train_id, str) and TRAIN_RE.match(train_id)):
            raise CapabilityRefused("TRAIN_ID_INVALID", str(train_id)[:60])
        heads = _pr_heads(pr_heads)
        acts = sorted(set(actions or []))
        if not acts or not set(acts) <= PHASE_ACTIONS[phase]:
            raise CapabilityRefused("ACTIONS_OUTSIDE_PHASE", f"{phase} permits {sorted(PHASE_ACTIONS[phase])}")
        dv = self._delegation()
        d = dv.delegation or {}
        lim = d["limits"]
        if len(heads) > lim["max_prs_per_train"]:
            raise CapabilityRefused("TOO_MANY_PRS", f"{len(heads)} > {lim['max_prs_per_train']}")
        ttl = int(ttl_s if ttl_s is not None else lim["capability_ttl_s"])
        if not 1 <= ttl <= lim["capability_ttl_s"]:
            raise CapabilityRefused("TTL_OUT_OF_POLICY", f"{ttl} > {lim['capability_ttl_s']}")
        if not (isinstance(attempts, int) and 1 <= attempts <= lim["max_attempts_per_capability"]):
            raise CapabilityRefused("ATTEMPTS_OUT_OF_POLICY", f"{attempts} > {lim['max_attempts_per_capability']}")
        if binding.get("services") and not set(binding["services"]) <= set(lim["named_services"]):
            raise CapabilityRefused("SERVICE_NOT_NAMED", f"{sorted(set(binding['services']) - set(lim['named_services']))}")
        if phase in EVIDENCE_PHASES:
            required = list(d["verification_policy"]["required_checks"])
            if binding.get("batch_candidate_sha"):
                qualifier = d["verification_policy"]["batch_qualifier"]
                errs = check_evidence(batch_evidence, binding["batch_candidate_sha"], required)
                errs += check_evidence(evidence, binding["candidate_sha"], [c for c in required if c != qualifier])
            else:
                errs = check_evidence(evidence, binding["candidate_sha"], required)
            if errs:
                raise CapabilityRefused("EVIDENCE_NOT_QUALIFYING", "; ".join(errs)[:400])
        now = self.clock()
        window = open_window(d, now)
        if window is None:
            raise CapabilityRefused("OUTSIDE_WINDOW", "no enabled release window is open")
        if phase == PHASE_BUILD and window.get("latest_start_et"):
            hh, mm = (int(x) for x in window["latest_start_et"].split(":"))
            ws = datetime.fromtimestamp(window["start_ts"], ZoneInfo(d["windows"]["timezone"]))
            if now > ws.replace(hour=hh, minute=mm).timestamp():
                raise CapabilityRefused("PAST_LATEST_START", window["window_id"])
        view = self.control.view()
        refusal = view.mutation_refusal(train_id)
        if refusal:
            raise CapabilityRefused(refusal, "control state forbids issuance")
        if view.current_train_id != train_id:
            raise CapabilityRefused("TRAIN_NOT_CLAIMED", f"current train is {view.current_train_id!r}")
        if view.accepted_policy_digest != dv.digest:
            raise CapabilityRefused("POLICY_NOT_ACCEPTED", "delegation digest differs from the one the operator armed")
        body = {
            "schema": SCHEMA, "capability_id": uuid.uuid4().hex, "phase": phase,
            "delegation_id": d["delegation_id"], "policy_digest": dv.digest,
            "delegation_epoch": d["revocation_epoch"], "control_epoch": view.epoch,
            "repository": d["repository"], "environment": d["environment"], "train_id": train_id,
            "pr_heads": heads, "permitted_actions": acts, "window_id": window["window_id"],
            "issued_at": now, "not_before": now, "expires_at": now + ttl, "attempt_budget": attempts,
            **binding,
        }
        raw = RD.canonical(body)
        token = f"{TOKEN_PREFIX}.{_b64e(raw)}.{_sign(key, raw)}"
        with RC.GlobalReleaseLock(self.root, self.lock_timeout_s):
            ledger = self._load_ledger(create=True)
            ledger["caps"][body["capability_id"]] = {
                "phase": phase, "train_id": train_id, "attempt_budget": attempts, "attempts_used": 0,
                "issued_at": now, "expires_at": body["expires_at"], "status": "ISSUED",
                "control_epoch": view.epoch, "token_sha256": hashlib.sha256(token.encode()).hexdigest()}
            self._save_ledger(ledger)
            self._journal({"event": "ISSUED", "capability_id": body["capability_id"], "phase": phase,
                           "train_id": train_id, "control_epoch": view.epoch})
        return token

    # -- reservation -------------------------------------------------------------------------------
    def reserve(self, token: str, action: str, *, observed: dict,
                held_lock: Optional[RC.GlobalReleaseLock] = None) -> "Reservation":
        key = load_key(self.key_path)
        cap = decode(token, key)                                  # no state touched yet
        lock = held_lock if held_lock is not None else RC.GlobalReleaseLock(self.root, self.lock_timeout_s)
        own = held_lock is None
        if own:
            lock.acquire()
        elif not lock.held:
            raise CapabilityRefused("LOCK_NOT_HELD", "held_lock must be acquired by the caller")
        try:
            ledger = self._load_ledger(create=False)
            self._mark_abandoned(ledger)
            pending = [i for i, r in ledger["intents"].items() if r.get("status") == UNCERTAIN]
            if pending:
                raise CapabilityRefused("RECONCILIATION_REQUIRED", f"uncertain intents: {sorted(pending)}")
            entry = ledger["caps"].get(cap["capability_id"])
            if entry is None:
                raise CapabilityRefused("CAPABILITY_UNKNOWN", "not in the ledger")
            if entry.get("token_sha256") != hashlib.sha256(token.encode()).hexdigest():
                raise CapabilityRefused("CAPABILITY_UNKNOWN", "token does not match the issued record")
            self._check(cap, entry, ledger, action, observed)
            now = self.clock()
            view = self.control.view()
            intent_id = uuid.uuid4().hex
            intent = {"intent_id": intent_id, "capability_id": cap["capability_id"], "phase": cap["phase"],
                      "train_id": cap["train_id"], "action": action, "status": RESERVED, "reserved_at": now,
                      "pid": os.getpid(), "control_epoch": view.epoch, "control_version": view.version,
                      "observed": _clip(observed)}
            entry["attempts_used"] = int(entry.get("attempts_used", 0)) + 1
            ledger["intents"][intent_id] = intent
            self._save_ledger(ledger)                              # intent + consumption: one atomic write
            self._journal({"event": "RESERVED", **{k: intent[k] for k in ("intent_id", "capability_id", "action",
                                                                         "control_epoch", "control_version")}})
            return Reservation(self, cap, intent_id, action, lock, own)
        except BaseException:
            if own:
                lock.release()
            raise

    def _check(self, cap: dict, entry: dict, ledger: dict, action: str, observed: dict) -> None:
        phase = cap.get("phase")
        if phase not in PHASE_ACTIONS or action not in PHASE_ACTIONS[phase]:
            raise CapabilityRefused("PHASE_CONFUSION", f"{action!r} is not a {phase} action")
        if action not in cap.get("permitted_actions", []):
            raise CapabilityRefused("ACTION_NOT_PERMITTED", action)
        if entry.get("status") != "ISSUED":
            raise CapabilityRefused("CAPABILITY_NOT_ISSUED", str(entry.get("status")))
        now = self.clock()
        if not cap["not_before"] <= now < cap["expires_at"]:
            raise CapabilityRefused("CAPABILITY_EXPIRED", "outside its validity window")
        done = [i for i in ledger["intents"].values() if i.get("capability_id") == cap["capability_id"]
                and i.get("action") == action and i.get("status") in APPLIED_STATES]
        if done:
            raise CapabilityRefused("REPLAY", f"{action} already applied under this capability")
        if int(entry.get("attempts_used", 0)) >= int(entry.get("attempt_budget", 0)):
            raise CapabilityRefused("BUDGET_EXHAUSTED", f"{entry.get('attempts_used')}/{entry.get('attempt_budget')}")
        # Revocation: STOP latch, control epoch, pause/revoke, delegation epoch and digest.
        view = self.control.view()
        refusal = view.mutation_refusal(cap["train_id"])
        if refusal:
            raise CapabilityRefused(refusal, "control state forbids the mutation")
        if view.epoch != cap["control_epoch"]:
            raise CapabilityRefused("EPOCH_STALE", f"capability epoch {cap['control_epoch']} != {view.epoch}")
        dv = self._delegation()
        d = dv.delegation or {}
        if d.get("delegation_id") != cap["delegation_id"]:
            raise CapabilityRefused("DELEGATION_MISMATCH", "different delegation")
        if d.get("revocation_epoch") != cap["delegation_epoch"]:
            raise CapabilityRefused("DELEGATION_EPOCH_STALE", f"{cap['delegation_epoch']} != {d.get('revocation_epoch')}")
        if dv.digest != cap["policy_digest"] or view.accepted_policy_digest != cap["policy_digest"]:
            raise CapabilityRefused("POLICY_DIGEST_CHANGED", "delegation changed since issuance")
        # Observed remote state: environment variables and branch names identify; they never authorize.
        if not isinstance(observed, dict):
            raise CapabilityRefused("OBSERVED_MISSING", "observed state is required")
        if observed.get("repository") != cap["repository"]:
            raise CapabilityRefused("WRONG_REPOSITORY", str(observed.get("repository")))
        if observed.get("environment") != cap["environment"]:
            raise CapabilityRefused("WRONG_ENVIRONMENT", str(observed.get("environment")))
        if observed.get("train_id") != cap["train_id"]:
            raise CapabilityRefused("WRONG_TRAIN", str(observed.get("train_id")))
        main = observed.get("main_sha")
        if phase == PHASE_BUILD:
            if main != cap["base_sha"]:
                raise CapabilityRefused("WRONG_SHA", "main moved since the train froze its base")
            return
        if observed.get("pr_heads") is not None and _pr_heads(observed["pr_heads"]) != cap["pr_heads"]:
            raise CapabilityRefused("PR_HEADS_CHANGED", "a member PR head moved")
        if observed.get("candidate_sha") != cap["candidate_sha"]:
            raise CapabilityRefused("WRONG_SHA", "candidate differs from the qualified one")
        if observed.get("artifact_digest") != cap["artifact_digest"]:
            raise CapabilityRefused("WRONG_ARTIFACT", "artifact digest differs")
        expect_main = cap["expected_base_sha"] if phase == PHASE_MERGE else cap["candidate_sha"]
        if main != expect_main:
            raise CapabilityRefused("WRONG_SHA", f"main is {str(main)[:9]}, capability expects {expect_main[:9]}")
        if phase == PHASE_PROMOTE and action == "restart_service":
            svc = observed.get("service")
            if svc not in cap["services"]:
                raise CapabilityRefused("SERVICE_NOT_NAMED", str(svc))

    # -- completion and reconciliation ----------------------------------------------------------------
    def _finish(self, intent_id: str, status: str, detail: Any, *, refund: bool) -> dict:
        ledger = self._load_ledger(create=False)
        intent = ledger["intents"].get(intent_id)
        if intent is None:
            raise CapabilityRefused("INTENT_UNKNOWN", intent_id)
        intent.update(status=status, finished_at=self.clock(), detail=_clip(detail))
        if refund:
            entry = ledger["caps"][intent["capability_id"]]
            entry["attempts_used"] = max(0, int(entry.get("attempts_used", 0)) - 1)
            intent["refunded"] = True
        self._save_ledger(ledger)
        self._journal({"event": status, "intent_id": intent_id, "capability_id": intent["capability_id"],
                       "refunded": refund})
        return intent

    def reconcile(self, intent_id: str, *, disposition: str, observed_evidence: dict, reconciled_by: str) -> dict:
        """After a crash or an UNCERTAIN effect: record what GitHub main / CURRENT / the services actually show.
        EFFECT_APPLIED keeps the attempt consumed (and the action counts as done: no replay); EFFECT_ABSENT
        refunds it. Only then may anything retry."""
        if disposition not in ("EFFECT_APPLIED", "EFFECT_ABSENT"):
            raise CapabilityRefused("DISPOSITION_INVALID", disposition)
        if not observed_evidence or not str(reconciled_by or "").strip():
            raise CapabilityRefused("RECONCILE_EVIDENCE_REQUIRED", "observed evidence and an actor are required")
        with RC.GlobalReleaseLock(self.root, self.lock_timeout_s):
            ledger = self._load_ledger(create=False)
            self._mark_abandoned(ledger)
            intent = ledger["intents"].get(intent_id)
            if intent is None or intent.get("status") != UNCERTAIN:
                raise CapabilityRefused("NOT_UNCERTAIN", str((intent or {}).get("status")))
            applied = disposition == "EFFECT_APPLIED"
            return self._finish(intent_id, RECONCILED_APPLIED if applied else RECONCILED_ABSENT,
                                {"observed": observed_evidence, "by": reconciled_by}, refund=not applied)

    def _mark_abandoned(self, ledger: dict) -> None:
        """Called with the global lock held: a RESERVED intent now has no live holder (flock is released when its
        process dies), so whether its effect happened is unknown."""
        changed = False
        for intent in ledger["intents"].values():
            if intent.get("status") == RESERVED:
                intent["status"] = UNCERTAIN
                intent["detail"] = "holder lost the global lock before recording an outcome (crash?)"
                changed = True
        if changed:
            self._save_ledger(ledger)
            self._journal({"event": "ABANDONED_TO_UNCERTAIN"})

    # -- storage ---------------------------------------------------------------------------------------
    def _delegation(self) -> RD.DelegationVerdict:
        dv = RD.load(self.delegation_path, allow_repo_path=self.allow_repo_delegation)
        if not dv.authorized:
            raise CapabilityRefused(f"DELEGATION_{dv.code}", dv.detail)
        return dv

    def _load_ledger(self, *, create: bool) -> dict:
        if not os.path.lexists(self.ledger_path):
            if create:
                return {"schema": LEDGER_SCHEMA, "caps": {}, "intents": {}}
            raise CapabilityRefused("CAPABILITY_UNKNOWN", "no capability ledger (nothing was issued)")
        try:
            body = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CapabilityRefused("STATE_CORRUPT", f"{self.ledger_path}: {type(exc).__name__}") from exc
        if not (isinstance(body, dict) and body.get("schema") == LEDGER_SCHEMA and isinstance(body.get("caps"), dict)
                and isinstance(body.get("intents"), dict)):
            raise CapabilityRefused("STATE_CORRUPT", f"{self.ledger_path}: not a {LEDGER_SCHEMA}")
        return body

    def _save_ledger(self, ledger: dict) -> None:
        RC._atomic_write_json(self.ledger_path, ledger)

    def _journal(self, row: dict) -> None:
        try:
            RC._append_jsonl(self.journal_path, {"at": RC.utc_iso(self.clock()), **row})
        except OSError:
            pass


class Reservation:
    """Holds the global release lock from reservation until an outcome is recorded."""

    def __init__(self, authority: CapabilityAuthority, cap: dict, intent_id: str, action: str,
                 lock: RC.GlobalReleaseLock, owns_lock: bool) -> None:
        self.authority, self.cap, self.intent_id, self.action = authority, cap, intent_id, action
        self._lock, self._owns = lock, owns_lock
        self.done = False

    def recheck(self, observed: dict) -> None:
        """Immediately before the main mutation / production activation. A refusal here refunds the attempt
        (no effect happened) and ends the reservation."""
        a = self.authority
        ledger = a._load_ledger(create=False)
        entry = dict(ledger["caps"][self.cap["capability_id"]])
        entry["attempts_used"] = max(0, int(entry.get("attempts_used", 0)) - 1)   # judge as before this attempt
        ledger["intents"].pop(self.intent_id, None)
        try:
            a._check(self.cap, entry, ledger, self.action, observed)
        except RC.ControlRefused as exc:
            self._end(ABORTED_NO_EFFECT, {"recheck": exc.code}, refund=True)
            raise CapabilityRefused(exc.code, f"recheck: {exc.detail}") from exc

    def succeeded(self, evidence: dict) -> dict:
        return self._end(SUCCEEDED, evidence, refund=False)

    def failed_no_effect(self, detail: dict) -> dict:
        """The effect definitely did not happen (e.g. the API refused before writing). The attempt stays spent."""
        return self._end(FAILED_NO_EFFECT, detail, refund=False)

    def uncertain(self, detail: dict) -> dict:
        return self._end(UNCERTAIN, detail, refund=False)

    def _end(self, status: str, detail: Any, *, refund: bool) -> dict:
        if self.done:
            raise CapabilityRefused("RESERVATION_CLOSED", self.intent_id)
        try:
            return self.authority._finish(self.intent_id, status, detail, refund=refund)
        finally:
            self.done = True
            if self._owns:
                self._lock.release()

    def __enter__(self) -> "Reservation":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self.done:
            self._end(UNCERTAIN, {"exit": getattr(exc_type, "__name__", "no outcome recorded")}, refund=False)


def _sha(v: Any, name: str) -> str:
    if not (isinstance(v, str) and SHA_RE.match(v)):
        raise CapabilityRefused("SHA_INVALID", f"{name} must be a full 40-hex SHA")
    return v


def _pr_heads(heads: Any) -> list[dict]:
    if not isinstance(heads, list) or not heads:
        raise CapabilityRefused("PR_HEADS_INVALID", "an ordered, non-empty list of {pr, head_sha}")
    out, seen = [], set()
    for h in heads:
        if not (isinstance(h, dict) and isinstance(h.get("pr"), int) and not isinstance(h.get("pr"), bool)
                and h["pr"] > 0 and isinstance(h.get("head_sha"), str) and SHA_RE.match(h["head_sha"])):
            raise CapabilityRefused("PR_HEADS_INVALID", str(h)[:80])
        if h["pr"] in seen:
            raise CapabilityRefused("PR_HEADS_INVALID", f"duplicate PR #{h['pr']}")
        seen.add(h["pr"])
        out.append({"pr": h["pr"], "head_sha": h["head_sha"]})
    return out


def _clip(v: Any) -> Any:
    try:
        s = json.dumps(v, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(v)[:400]
    return v if len(s) <= 4000 else {"truncated": s[:4000]}
