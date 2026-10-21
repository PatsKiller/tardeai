"""Release-train STOP / pause / resume / revoke state machine (ReleaseControl@v1). Library only; wired into nothing.

Release Train v2, Phase 2 (plan `joyful-skipping-wilkes.md`; enhanced design 2026-10-21 §7). Operator decisions
2026-10-21: D1 standing revocable authorization; D3 resume and scope changes only via the host CLI or a Telegram
button confirmation (TOTP declined). The Command Center may only *request* STOP or pause.

State (one directory, the same one ``scripts/release_window.py`` uses as its state dir):

* ``STOP.json``      the release_window STOP latch. Read with release_window's fail-closed semantics (branch
                     ``ops/release-train-20261021`` 9dde41745 ``State.read_latch``): ABSENT only when no path
                     exists; SET for a readable JSON object; UNREADABLE (a STOP) for anything else. A STOP request
                     writes it, so release_window refuses with REFUSED_STOP_LATCHED; clearing archives it by rename
                     into ``windows/`` exactly as ``release_window.py clear-stop`` does. Never deleted.
* ``control.json``   ReleaseControl@v1: mode, epoch, monotonic ``version``, the accepted delegation digest, the
                     stop / pause record with requested → acknowledged → settling → stopped timestamps.
* ``control.lock``   flock for control read-modify-write (short critical sections only).
* ``.lock``          the ONE global release mutation lock (the file release_window.py already flocks for a
                     window run). ``GlobalReleaseLock`` is the shared helper; release_capability reserves under it.
* ``control_journal.jsonl``  append-only audit of every accepted and refused command.

Fail closed: a missing control.json means "never armed" (not authorized); a corrupt one, an unknown mode or a
non-integer epoch is ``CORRUPT`` (not authorized). A SET or UNREADABLE latch is a STOP whatever control.json says.

Epoch: STOP increments it; resume, re-arm and scope change each issue a NEW epoch; nothing ever lowers it, so a
capability bound to an older epoch never becomes valid again. Pause does not change the epoch (the current train
may finish); revoke increments it.

Who may call what (``Actor.kind``):
  request_stop, request_pause          cc, host_cli, telegram, controller
  acknowledge / settle (controller)    controller
  arm (also re-arms after revoke),     host_cli (a ``HostCliProof``) or telegram (a ``TelegramConfirmation``
  resume, change_scope, revoke         verified by the hook; the shipped hook is a stub that always refuses)

Pre-build check (AGENTS §13.5): searched scripts/ and config/ for revocation_epoch, ReleaseControl, release
capability, STOP latch writers; found only release_window.py's STOP.json latch (reused here, not cloned) and
release_grant_binding.py (grant-text binding; different concept, untouched).
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

SCHEMA = "ReleaseControl@v1"
LATCH_NAME = "STOP.json"
CONTROL_NAME = "control.json"
CONTROL_LOCK_NAME = "control.lock"
GLOBAL_LOCK_NAME = ".lock"            # == scripts/release_window.py Runner.run's lock file
JOURNAL_NAME = "control_journal.jsonl"

# Modes
UNARMED = "UNARMED"                   # no control.json: never armed (derived, never written)
CORRUPT = "CORRUPT"                   # control.json unreadable / invalid (derived, never written)
RUNNING = "RUNNING"
PAUSE_REQUESTED = "PAUSE_REQUESTED"   # current train may finish; no later train is claimed
PAUSED = "PAUSED"
STOP_REQUESTED = "STOP_REQUESTED"
STOP_ACKNOWLEDGED = "STOP_ACKNOWLEDGED"
SETTLING = "SETTLING"
STOPPED = "STOPPED"
REVOKED = "REVOKED"
WRITTEN_MODES = frozenset({RUNNING, PAUSE_REQUESTED, PAUSED, STOP_REQUESTED, STOP_ACKNOWLEDGED, SETTLING,
                           STOPPED, REVOKED})
STOP_MODES = frozenset({STOP_REQUESTED, STOP_ACKNOWLEDGED, SETTLING, STOPPED})
#: UI vocabulary (enhanced design §7): requested → acknowledged → settling → stopped.
STOP_PHASE = {STOP_REQUESTED: "requested", STOP_ACKNOWLEDGED: "acknowledged", SETTLING: "settling",
              STOPPED: "stopped"}

LATCH_ABSENT, LATCH_SET, LATCH_UNREADABLE = "ABSENT", "SET", "UNREADABLE"

ACTOR_KINDS = frozenset({"cc", "host_cli", "telegram", "controller"})
REQUEST_KINDS = frozenset({"cc", "host_cli", "telegram", "controller"})   # STOP / pause: the safe direction
OPERATOR_KINDS = frozenset({"host_cli", "telegram"})                    # D3


class ControlRefused(Exception):
    """A control command was refused. ``code`` is stable; nothing was written except the journal line."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class LockBusy(ControlRefused):
    def __init__(self, path: Path) -> None:
        super().__init__("LOCK_BUSY", str(path))


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


# ── latch (release_window.py compatible) ─────────────────────────────────────────────────────────────

def read_latch(path: Path) -> tuple[str, Optional[dict]]:
    """release_window's STOP latch, fail closed (same contract as ``State.read_latch`` on 9dde41745).

    ("ABSENT", None) only when no path exists at all (a dangling symlink is not absent); ("SET", body) for a
    readable JSON object; ("UNREADABLE", {"error", "path"}) when the path exists but cannot be read or parsed
    (corrupt, permission denied, a directory, a non-object). UNREADABLE is a STOP."""
    if not os.path.lexists(path):
        return LATCH_ABSENT, None
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return LATCH_UNREADABLE, {"error": f"{type(exc).__name__}: {str(exc)[:160]}", "path": str(path)}
    if not isinstance(body, dict):
        return LATCH_UNREADABLE, {"error": f"latch is {type(body).__name__}, not an object", "path": str(path)}
    return LATCH_SET, body


# ── locks ────────────────────────────────────────────────────────────────────────────────────────────

class _Flock:
    def __init__(self, path: Path, timeout_s: float) -> None:
        self.path = Path(path)
        self.timeout_s = timeout_s
        self._fh: Any = None

    def acquire(self) -> "_Flock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.path, "a+")  # noqa: SIM115 - held across the critical section
        except OSError as exc:      # a directory, a permission problem, a broken parent: fail closed
            raise ControlRefused("LOCK_ERROR", f"{self.path}: {type(exc).__name__}: {exc}") from exc
        deadline = time.monotonic() + max(0.0, self.timeout_s)
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fh = fh
                return self
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    fh.close()
                    raise ControlRefused("LOCK_ERROR", f"{self.path}: {exc}") from exc
                if time.monotonic() >= deadline:
                    fh.close()
                    raise LockBusy(self.path) from exc
                time.sleep(0.02)

    @property
    def held(self) -> bool:
        return self._fh is not None

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "_Flock":
        return self.acquire()

    def __exit__(self, *exc: Any) -> None:
        self.release()


class GlobalReleaseLock(_Flock):
    """The one global release mutation lock: ``<state_dir>/.lock``, the file release_window.py flocks for a
    window run, so a manual window, a train mutation and an emergency path serialize on one inode. Default is a
    non-blocking try (timeout 0): a busy lock is a refusal that consumes nothing, never a queue."""

    def __init__(self, state_dir: Path, timeout_s: float = 0.0) -> None:
        super().__init__(Path(state_dir) / GLOBAL_LOCK_NAME, timeout_s)


# ── actors and operator proofs (D3) ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Actor:
    kind: str                 # cc | host_cli | telegram | controller
    identity: str             # server-derived (CC: tailnet login; host: uid/login; controller: unit name)

    def __post_init__(self) -> None:
        if self.kind not in ACTOR_KINDS:
            raise ControlRefused("ACTOR_UNKNOWN", self.kind)
        if not str(self.identity or "").strip():
            raise ControlRefused("ACTOR_IDENTITY_MISSING", self.kind)


@dataclass(frozen=True)
class HostCliProof:
    """Evidence that a human typed this at the host. Built only by ``scripts/release_control_cli.py``:
    stdin is a TTY (``tty`` is its name), the process uid owns the state dir, and the operator re-typed the
    confirmation phrase the library expects for this exact command (which names the next epoch)."""

    tty: str
    uid: int
    confirmation: str


@dataclass(frozen=True)
class TelegramConfirmation:
    """A Telegram button confirmation as the hook returns it. Only a hook's ``verify`` may vouch for one."""

    request_id: str
    confirmed_by: str
    confirmed_at: str
    confirmation: str


class TelegramConfirmationHook(Protocol):
    def verify(self, confirmation: TelegramConfirmation, *, expected_phrase: str) -> bool: ...


class TelegramConfirmationStub:
    """D3 hook stub. Not implemented: always refuses, so the Telegram path stays closed until a real hook (the
    host communications gateway's button callback, matched to a pending request id) is built and reviewed."""

    def verify(self, confirmation: TelegramConfirmation, *, expected_phrase: str) -> bool:  # noqa: ARG002
        return False


@dataclass
class ControlView:
    mode: str
    epoch: Optional[int]
    version: Optional[int]
    latch_state: str
    latch: Optional[dict]
    accepted_policy_digest: Optional[str]
    current_train_id: Optional[str]
    stop: Optional[dict]
    pause: Optional[dict]
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def stop_phase(self) -> Optional[str]:
        if self.mode in STOP_PHASE:
            return STOP_PHASE[self.mode]
        if self.latch_state != LATCH_ABSENT:
            return "stopped"       # latched by release_window itself, or unreadable: stopped, fail closed
        return None

    def mutation_refusal(self, train_id: Optional[str] = None) -> Optional[str]:
        """None when a release mutation for ``train_id`` may proceed; else the refusal code (fail closed)."""
        if self.latch_state == LATCH_UNREADABLE:
            return "STOP_LATCH_UNREADABLE"
        if self.latch_state == LATCH_SET:
            return "STOP_LATCHED"
        if self.mode == UNARMED:
            return "CONTROL_UNARMED"
        if self.mode == CORRUPT:
            return "CONTROL_CORRUPT"
        if self.mode in STOP_MODES:
            return "STOPPED"
        if self.mode == REVOKED:
            return "REVOKED"
        if self.mode == PAUSED:
            return "PAUSED"
        if self.mode == PAUSE_REQUESTED:
            if train_id is None or train_id != self.current_train_id:
                return "PAUSED_AFTER_CURRENT"
            return None
        if self.mode == RUNNING:
            return None
        return "CONTROL_MODE_UNKNOWN"


class ReleaseControl:
    def __init__(self, state_dir: Path, *, clock: Callable[[], float] = time.time,
                 telegram_hook: Optional[TelegramConfirmationHook] = None,
                 lock_timeout_s: float = 5.0) -> None:
        self.root = Path(state_dir)
        self.latch_path = self.root / LATCH_NAME
        self.path = self.root / CONTROL_NAME
        self.journal_path = self.root / JOURNAL_NAME
        self.clock = clock
        self.telegram_hook: TelegramConfirmationHook = telegram_hook or TelegramConfirmationStub()
        self.lock_timeout_s = lock_timeout_s

    # -- reading ---------------------------------------------------------------------------------------
    def view(self) -> ControlView:
        latch_state, latch = read_latch(self.latch_path)
        if not os.path.lexists(self.path):
            return ControlView(UNARMED, None, None, latch_state, latch, None, None, None, None)
        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return ControlView(CORRUPT, None, None, latch_state, latch, None, None, None, None,
                               error=f"{type(exc).__name__}: {str(exc)[:160]}")
        err = _validate_control(body)
        if err:
            return ControlView(CORRUPT, None, None, latch_state, latch, None, None, None, None, error=err)
        return ControlView(body["mode"], body["epoch"], body["version"], latch_state, latch,
                           body.get("accepted_policy_digest"), body.get("current_train_id"), body.get("stop"),
                           body.get("pause"), raw=body)

    # -- the safe direction: anyone authenticated may request STOP or pause ------------------------------
    def request_stop(self, actor: Actor, reason: str, *, idempotency_key: Optional[str] = None,
                     expected_version: Optional[int] = None) -> dict:
        """Persist the STOP latch and increment the epoch. Never blocks on the global mutation lock: the
        controller acknowledges at its next mutation boundary. Works even when control.json is corrupt or
        missing (the latch alone stops release_window and every capability reservation)."""
        self._require(actor, REQUEST_KINDS, "request_stop")
        reason = _reason(reason)
        now = self.clock()
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            prior = self._idempotent(idempotency_key)
            if prior is not None:
                return prior
            v = self.view()
            # The latch first: if anything below fails, the system is already stopped.
            if v.latch_state == LATCH_ABSENT:
                _atomic_write_json(self.latch_path, {
                    "latched_at": utc_iso(now), "window_id": None, "outcome": "STOP_REQUESTED",
                    "source": "release_control", "actor": {"kind": actor.kind, "identity": actor.identity},
                    "reason": reason,
                    "detail": "release train STOP; operator resumes via scripts/release_control_cli.py resume"})
            if v.mode in (UNARMED, CORRUPT):
                result = {"outcome": "STOP_LATCHED", "mode": v.mode, "latch": "SET",
                          "detail": "control state is not readable/armed; latch written, epoch unchanged"}
                self._journal("request_stop", actor, result, idempotency_key)
                return result
            self._check_version(v, expected_version, "request_stop", actor)
            body = dict(v.raw)
            if v.mode in STOP_MODES or v.mode == REVOKED:
                result = {"outcome": "ALREADY_STOPPING" if v.mode != REVOKED else "ALREADY_REVOKED",
                          "mode": v.mode, "epoch": v.epoch}
                self._journal("request_stop", actor, result, idempotency_key)
                return result
            body["prior_mode"] = v.mode
            body["mode"] = STOP_REQUESTED
            body["epoch"] = int(v.epoch or 0) + 1
            body["stop"] = {"requested_at": utc_iso(now), "requested_ts": now, "acknowledged_at": None,
                            "settling_at": None, "stopped_at": None, "reason": reason,
                            "actor": {"kind": actor.kind, "identity": actor.identity}}
            self._commit(body, v)
            result = {"outcome": "STOP_REQUESTED", "mode": STOP_REQUESTED, "epoch": body["epoch"],
                      "version": body["version"]}
            self._journal("request_stop", actor, result, idempotency_key)
            return result

    def request_pause(self, actor: Actor, reason: str, *, idempotency_key: Optional[str] = None,
                      expected_version: Optional[int] = None) -> dict:
        """Pause after the current train: no later train is claimed; the current one may reach its bounded
        verified / rolled-back terminal state. Epoch unchanged."""
        self._require(actor, REQUEST_KINDS, "request_pause")
        reason = _reason(reason)
        now = self.clock()
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            prior = self._idempotent(idempotency_key)
            if prior is not None:
                return prior
            v = self._writable_view("request_pause", actor)
            self._check_version(v, expected_version, "request_pause", actor)
            if v.mode != RUNNING:
                result = {"outcome": "NO_CHANGE", "mode": v.mode, "epoch": v.epoch}
                self._journal("request_pause", actor, result, idempotency_key)
                return result
            body = dict(v.raw)
            body["mode"] = PAUSE_REQUESTED if v.current_train_id else PAUSED
            body["pause"] = {"requested_at": utc_iso(now), "reason": reason, "train_may_finish": v.current_train_id,
                             "actor": {"kind": actor.kind, "identity": actor.identity}}
            self._commit(body, v)
            result = {"outcome": body["mode"], "mode": body["mode"], "epoch": body["epoch"],
                      "current_train_may_finish": v.current_train_id, "version": body["version"]}
            self._journal("request_pause", actor, result, idempotency_key)
            return result

    # -- controller side -------------------------------------------------------------------------------
    def claim_train(self, actor: Actor, train_id: str) -> dict:
        """The controller marks the train it is running (what "pause after current" lets finish)."""
        self._require(actor, {"controller"}, "claim_train")
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self._writable_view("claim_train", actor)
            refusal = v.mutation_refusal(train_id)
            if refusal:
                self._journal("claim_train", actor, {"outcome": "REFUSED", "code": refusal})
                raise ControlRefused(refusal, f"cannot claim {train_id}")
            if v.current_train_id and v.current_train_id != train_id:
                self._journal("claim_train", actor, {"outcome": "REFUSED", "code": "TRAIN_ALREADY_CLAIMED"})
                raise ControlRefused("TRAIN_ALREADY_CLAIMED", f"{v.current_train_id} is current")
            body = dict(v.raw)
            body["current_train_id"] = train_id
            self._commit(body, v)
            self._journal("claim_train", actor, {"outcome": "CLAIMED", "train_id": train_id})
            return {"outcome": "CLAIMED", "train_id": train_id, "epoch": body["epoch"]}

    def train_terminal(self, actor: Actor, train_id: str, outcome: str) -> dict:
        """The current train reached a terminal state; a pending pause completes."""
        self._require(actor, {"controller"}, "train_terminal")
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self._writable_view("train_terminal", actor)
            if v.current_train_id != train_id:
                raise ControlRefused("TRAIN_NOT_CURRENT", f"{train_id} != {v.current_train_id}")
            body = dict(v.raw)
            body["current_train_id"] = None
            body["last_train"] = {"train_id": train_id, "outcome": str(outcome)[:80], "at": utc_iso(self.clock())}
            if v.mode == PAUSE_REQUESTED:
                body["mode"] = PAUSED
            self._commit(body, v)
            self._journal("train_terminal", actor, {"outcome": body["mode"], "train_id": train_id})
            return {"outcome": body["mode"], "train_id": train_id}

    def acknowledge_stop(self, actor: Actor) -> dict:
        self._require(actor, {"controller"}, "acknowledge_stop")
        return self._advance_stop(actor, STOP_REQUESTED, STOP_ACKNOWLEDGED, "acknowledged_at")

    def settle(self, actor: Actor, *, in_flight: bool) -> dict:
        """After acknowledging: SETTLING while an activation already started finishes its bounded verification
        or restores the known-good artifact; STOPPED once nothing is in flight."""
        self._require(actor, {"controller"}, "settle")
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self._writable_view("settle", actor)
            if v.mode not in (STOP_ACKNOWLEDGED, SETTLING):
                raise ControlRefused("STOP_NOT_ACKNOWLEDGED", v.mode)
            body = dict(v.raw)
            stop = dict(body.get("stop") or {})
            now = utc_iso(self.clock())
            if in_flight:
                body["mode"] = SETTLING
                stop["settling_at"] = stop.get("settling_at") or now
            else:
                body["mode"] = STOPPED
                stop["settling_at"] = stop.get("settling_at") or now
                stop["stopped_at"] = now
                body["current_train_id"] = None
            body["stop"] = stop
            self._commit(body, v)
            self._journal("settle", actor, {"outcome": body["mode"]})
            return {"outcome": body["mode"], "stop": stop}

    def stop_overdue(self, ack_slo_s: float) -> bool:
        """True when a STOP request has gone unacknowledged past the SLO: the host notifier escalates."""
        v = self.view()
        if v.mode != STOP_REQUESTED:
            return False
        ts = (v.stop or {}).get("requested_ts")
        return isinstance(ts, (int, float)) and self.clock() - ts > ack_slo_s

    # -- operator only (D3): host CLI or Telegram confirmation ----------------------------------------
    def expected_phrase(self, command: str) -> str:
        """The phrase the operator must re-type; it names the epoch the command will create."""
        v = self.view()
        nxt = int(v.epoch or 0) + 1
        return f"{command.upper()} EPOCH {nxt}"

    def arm(self, actor: Actor, proof: Any, *, policy_digest: str, reason: str) -> dict:
        """First arming (or re-arming after REVOKED): writes control.json RUNNING with a fresh epoch and the
        accepted delegation digest. Refuses while a STOP latch is present (resume clears it)."""
        self._operator(actor, proof, "arm")
        _digest(policy_digest)
        reason = _reason(reason)
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self.view()
            if v.mode not in (UNARMED, REVOKED):
                raise ControlRefused("ALREADY_ARMED", v.mode)
            if v.latch_state != LATCH_ABSENT:
                raise ControlRefused("STOP_LATCH_PRESENT", "resume or clear the latch first")
            body = dict(v.raw) if v.mode == REVOKED else {"schema": SCHEMA, "version": 0, "epoch": 0}
            body.update(mode=RUNNING, epoch=int(body.get("epoch") or 0) + 1, accepted_policy_digest=policy_digest,
                        current_train_id=None, stop=None, pause=None,
                        armed={"at": utc_iso(self.clock()), "reason": reason,
                               "actor": {"kind": actor.kind, "identity": actor.identity}})
            self._commit(body, v)
            result = {"outcome": "ARMED", "epoch": body["epoch"], "policy_digest": policy_digest}
            self._journal("arm", actor, result)
            return result

    def resume(self, actor: Actor, proof: Any, *, reason: str, readiness: dict) -> dict:
        """Clear STOP / pause: archive the latch (rename, never delete), issue a NEW epoch, RUNNING. Requires the
        caller to have shown the stop reason, current state and fresh readiness (recorded verbatim)."""
        self._operator(actor, proof, "resume")
        reason = _reason(reason)
        if not isinstance(readiness, dict) or not readiness.get("checked_at"):
            raise ControlRefused("READINESS_MISSING", "resume shows fresh readiness first")
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self.view()
            if v.mode in (UNARMED, CORRUPT, REVOKED):
                raise ControlRefused("RESUME_NOT_APPLICABLE", f"{v.mode}: use arm/reinstate")
            if v.mode in (STOP_REQUESTED, STOP_ACKNOWLEDGED, SETTLING):
                raise ControlRefused("STOP_NOT_SETTLED", f"{v.mode}: the controller has not reached stopped")
            if v.mode == RUNNING and v.latch_state == LATCH_ABSENT:
                raise ControlRefused("NOT_STOPPED", "nothing to resume")
            archived = self._archive_latch(v, reason) if v.latch_state != LATCH_ABSENT else None
            body = dict(v.raw)
            body.update(mode=RUNNING, epoch=int(v.epoch or 0) + 1, stop=None, pause=None,
                        resumed={"at": utc_iso(self.clock()), "reason": reason, "readiness": readiness,
                                 "prior_mode": v.mode, "prior_stop": v.stop, "latch_archived": archived,
                                 "actor": {"kind": actor.kind, "identity": actor.identity}})
            self._commit(body, v)
            result = {"outcome": "RESUMED", "epoch": body["epoch"], "latch_archived": archived}
            self._journal("resume", actor, result)
            return result

    def change_scope(self, actor: Actor, proof: Any, *, policy_digest: str, reason: str) -> dict:
        """Accept a changed delegation (scope expansion or narrowing): new digest, NEW epoch."""
        self._operator(actor, proof, "change_scope")
        _digest(policy_digest)
        reason = _reason(reason)
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self._writable_view("change_scope", actor)
            if v.mode == REVOKED:
                raise ControlRefused("REVOKED", "reinstate with arm")
            body = dict(v.raw)
            body.update(epoch=int(v.epoch or 0) + 1, accepted_policy_digest=policy_digest,
                        scope_changed={"at": utc_iso(self.clock()), "reason": reason,
                                       "from_digest": v.accepted_policy_digest,
                                       "actor": {"kind": actor.kind, "identity": actor.identity}})
            self._commit(body, v)
            result = {"outcome": "SCOPE_CHANGED", "epoch": body["epoch"], "policy_digest": policy_digest}
            self._journal("change_scope", actor, result)
            return result

    def revoke(self, actor: Actor, proof: Any, *, reason: str) -> dict:
        """Revoke automation: no further capability issuance; NEW epoch; queue/history stay readable."""
        self._operator(actor, proof, "revoke")
        reason = _reason(reason)
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self._writable_view("revoke", actor)
            body = dict(v.raw)
            body.update(mode=REVOKED, epoch=int(v.epoch or 0) + 1, current_train_id=None,
                        revoked={"at": utc_iso(self.clock()), "reason": reason, "prior_mode": v.mode,
                                 "actor": {"kind": actor.kind, "identity": actor.identity}})
            self._commit(body, v)
            result = {"outcome": "REVOKED", "epoch": body["epoch"]}
            self._journal("revoke", actor, result)
            return result

    # -- internals -------------------------------------------------------------------------------------
    def _require(self, actor: Actor, kinds: Any, command: str) -> None:
        if not isinstance(actor, Actor) or actor.kind not in kinds:
            kind = getattr(actor, "kind", type(actor).__name__)
            self._journal(command, actor if isinstance(actor, Actor) else None,
                          {"outcome": "REFUSED", "code": "ACTOR_NOT_PERMITTED", "kind": kind})
            raise ControlRefused("ACTOR_NOT_PERMITTED", f"{kind} may not {command}")

    def _operator(self, actor: Actor, proof: Any, command: str) -> None:
        self._require(actor, OPERATOR_KINDS, command)
        expected = self.expected_phrase(command)
        ok = False
        if actor.kind == "host_cli" and isinstance(proof, HostCliProof):
            ok = bool(proof.tty) and proof.uid == os.getuid() and proof.confirmation == expected
            if ok and self.root.exists():
                ok = self.root.stat().st_uid == proof.uid
        elif actor.kind == "telegram" and isinstance(proof, TelegramConfirmation):
            try:
                ok = bool(self.telegram_hook.verify(proof, expected_phrase=expected))
            except Exception:  # noqa: BLE001 - a hook failure is a refusal
                ok = False
        if not ok:
            self._journal(command, actor, {"outcome": "REFUSED", "code": "OPERATOR_PROOF_REFUSED"})
            raise ControlRefused("OPERATOR_PROOF_REFUSED", f"{command} needs a host CLI or Telegram confirmation "
                                                           f"of {expected!r}")

    def _writable_view(self, command: str, actor: Actor) -> ControlView:
        v = self.view()
        if v.mode in (UNARMED, CORRUPT):
            self._journal(command, actor, {"outcome": "REFUSED", "code": f"CONTROL_{v.mode}"})
            raise ControlRefused(f"CONTROL_{v.mode}", v.error or "")
        return v

    def _check_version(self, v: ControlView, expected: Optional[int], command: str, actor: Actor) -> None:
        if expected is not None and expected != v.version:
            self._journal(command, actor, {"outcome": "REFUSED", "code": "VERSION_CONFLICT"})
            raise ControlRefused("VERSION_CONFLICT", f"expected {expected}, current {v.version}")

    def _commit(self, body: dict, prior: ControlView) -> None:
        body["schema"] = SCHEMA
        body["version"] = int(prior.version or 0) + 1
        if prior.epoch is not None and int(body["epoch"]) < int(prior.epoch):
            raise ControlRefused("EPOCH_REGRESSION", f"{body['epoch']} < {prior.epoch}")
        body["updated_at"] = utc_iso(self.clock())
        body.pop("_idem", None)
        _atomic_write_json(self.path, body)

    def _archive_latch(self, v: ControlView, reason: str) -> str:
        stamp = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        windows = self.root / "windows"
        windows.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(windows / f"STOP-cleared-{stamp}.json",
                           {**(v.latch or {}), "latch_state": v.latch_state, "cleared_at": stamp,
                            "cleared_reason": reason, "cleared_by": "release_control.resume"})
        dest = windows / f"STOP-{stamp}.json.archived"
        n = 1
        while os.path.lexists(dest):
            dest = windows / f"STOP-{stamp}-{n}.json.archived"
            n += 1
        os.rename(self.latch_path, dest)          # archived, never deleted (AGENTS §0 rule 6)
        return str(dest)

    def _advance_stop(self, actor: Actor, frm: str, to: str, stamp_key: str) -> dict:
        with _Flock(self.root / CONTROL_LOCK_NAME, self.lock_timeout_s):
            v = self._writable_view(f"advance_{to.lower()}", actor)
            if v.mode == to:
                return {"outcome": "NO_CHANGE", "mode": to}
            if v.mode != frm:
                raise ControlRefused("STOP_STATE_MISMATCH", f"{v.mode} != {frm}")
            body = dict(v.raw)
            stop = dict(body.get("stop") or {})
            stop[stamp_key] = utc_iso(self.clock())
            body["stop"], body["mode"] = stop, to
            self._commit(body, v)
            self._journal(f"advance_{to.lower()}", actor, {"outcome": to})
            return {"outcome": to, "stop": stop}

    def _idempotent(self, key: Optional[str]) -> Optional[dict]:
        if not key:
            return None
        try:
            with open(self.journal_path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("idempotency_key") == key and row.get("result", {}).get("outcome") != "REFUSED":
                        return {**row["result"], "idempotent_replay": True}
        except OSError:
            return None
        return None

    def _journal(self, command: str, actor: Optional[Actor], result: dict,
                 idempotency_key: Optional[str] = None) -> None:
        row = {"at": utc_iso(self.clock()), "command": command, "result": result,
               "actor": {"kind": actor.kind, "identity": actor.identity} if actor else None}
        if idempotency_key:
            row["idempotency_key"] = idempotency_key
        try:
            _append_jsonl(self.journal_path, row)
        except OSError:
            pass   # the journal is audit; the state transition itself is in control.json / STOP.json


def _validate_control(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return "control state is not an object"
    if body.get("schema") != SCHEMA:
        return f"schema {body.get('schema')!r} != {SCHEMA}"
    if body.get("mode") not in WRITTEN_MODES:
        return f"unknown mode {body.get('mode')!r}"
    for k in ("epoch", "version"):
        if not isinstance(body.get(k), int) or isinstance(body.get(k), bool) or body[k] < 0:
            return f"{k} is not a non-negative integer"
    if body["mode"] != REVOKED and body["epoch"] < 1:
        return "armed state with epoch < 1"
    d = body.get("accepted_policy_digest")
    if body["mode"] != REVOKED and not (isinstance(d, str) and len(d) == 64):
        return "accepted_policy_digest missing"
    return None


def _reason(reason: Any) -> str:
    r = " ".join(str(reason or "").split())
    if len(r) < 4:
        raise ControlRefused("REASON_REQUIRED", "a reason of at least 4 characters is recorded")
    return r[:400]


def _digest(d: Any) -> None:
    if not (isinstance(d, str) and len(d) == 64 and all(c in "0123456789abcdef" for c in d)):
        raise ControlRefused("POLICY_DIGEST_INVALID", str(d)[:80])
