#!/usr/bin/env python3
"""home_approvals.py — Home v008 "Needs you": the request store, the CLOSED action list, and the executor (piece A).

The operator asked for decisions to arrive as one-tap approvals on the dashboard instead of Telegram text he will not
see while asleep. This module is the backend half; the HTTP route (B), the card (C) and the Telegram nudge (D) are
separate. Spec: SPEC_HOME_V008_NEEDS_YOU_APPROVALS_20261103.md.

Three rails are unconditional, and each has a test:

1. **Operator session + same-origin CSRF.** ``decide()`` takes an ``OperatorContext`` that only ``server_context()``
   can mint, and that factory accepts only a tailnet operator identity on the authenticated serve listener. ``decide()``
   then requires the recorded ``actor`` to *be* that verified login, so a caller cannot name the operator while holding
   an agent identity. The command line cannot mint a context at all: a decision is only ever made by the HTTP layer.
2. **The requester is never the approver.** Refused by identity *and* by session, so asking under one name and clicking
   under another does not work.
3. **Expiry re-asks.** An expired request moves to ``expired`` with ``reask_requested: true``; it is never
   auto-approved, and a click on it does nothing.

The action a button performs is a closed list (``ACTION_TYPES``). A request naming anything else is refused at creation
and never stored, so it can never be rendered as a button. Broker orders, credentials, live flags, force-push and
deletion are not on the list and have no code path here. MBI_BEHAVIOR = 0.

Store (under the persistent-state root; there is no /tmp default):

    <root>/needs_you/requests/<id>.json      one HomeApprovalRequest@v1, mode 0600, atomic replace
    <root>/needs_you/ledger.jsonl            append-only transitions and receipts
    <root>/coordination/digest_approvals.jsonl  append-only digest of every decision and outcome

A decision's receipt is written BEFORE the action runs and the outcome is appended after it, so an action that fails
halfway still leaves the decision on record.

Read path for the dashboard: ``list_open()``. It returns ``[]`` only when the store was readable and genuinely held no
open requests; a corrupt or unreadable record raises, because a decision that silently disappears into an empty-looking
board is worse than an error the card can show.
"""

from __future__ import annotations

import argparse
import contextlib
import inspect
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

SCHEMA = "HomeApprovalRequest@v1"
RECEIPT_SCHEMA = "HomeApprovalReceipt@v1"

# ── The closed action list ────────────────────────────────────────────────────────────────────────────────────────
# Exactly the reviewed set (spec §2). Widening it is a reviewed change to this literal; there is no runtime way to do it.
ACTION_TYPES: dict[str, str] = {
    "merge_pr": "merge a PR at exactly the reviewed head",
    "rerun_ci": "re-run the failed jobs of one CI run, once",
    "grant": "issue a guard grant exactly as shown (tier, duration, uses, reason)",
    "stop_job": "end one named stuck process on the stoppable list",
    "install_schedule": "install one reviewed scheduler line already in the lane registry",
    "restore_store": "run a reviewed restore packet (dry-run diff shown, evidence copy, rollback)",
    "policy_approval": "record the APPROVE line for an AGENTS/policy PR at its exact head",
}

REQUIRED_FACTS: dict[str, tuple[str, ...]] = {
    "merge_pr": ("pr", "head_sha"),
    "rerun_ci": ("run_id", "head_sha"),
    "grant": ("grant_id", "tier", "uses", "expires_at", "reason"),
    "stop_job": ("pid", "start_time_epoch", "cmd_sha256"),
    "install_schedule": ("lane_id", "schedule_expression", "file_sha256"),
    "restore_store": ("packet_sha256",),
    "policy_approval": ("pr", "head_sha"),
}

STATES = ("open", "approved", "executing", "executed", "failed", "declined", "expired", "cancelled")

DEFAULT_TTL_HOURS = 24.0
DEFAULT_EXECUTE_TIMEOUT_S = 120.0


class Deadline:
    """An enforceable deadline handed to the executor.

    ``check()`` raises before an effect is started once the deadline has passed, and ``subprocess_timeout()`` gives the
    remaining budget for a subprocess call. A deadline cannot un-issue a remote effect that has already been sent — the
    contract is that an adapter calls ``check()`` immediately before every external action, so nothing *starts* late.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = float(seconds)
        self.started = time.monotonic()

    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def check(self) -> None:
        if self.expired():
            raise Refused("deadline_exceeded",
                          "The time allowed for this action ran out before it could start, so nothing was done.")

    def subprocess_timeout(self, cap: float = 60.0) -> float:
        self.check()
        return max(0.1, min(float(cap), self.remaining()))
TEXT_FIELDS = ("title", "why", "rule", "what_happens", "risk", "undo")


# ── Server-only decision context ─────────────────────────────────────────────────────────────────────────────────
# ``decide()`` will not accept a plain dict, a pair of booleans, or nothing: it requires an OperatorContext that only
# ``server_context()`` can mint, and that factory is for the API layer alone. Python has no privilege boundary inside one
# process — a determined caller can import anything — so this is not a sandbox; it is a shape that makes an accidental
# client-side approval impossible and makes an intentional one an explicit, reviewable call in the server module.
_SEAL = object()


class Refused(Exception):
    """A refusal with a machine code and a plain-English sentence the card can show."""

    def __init__(self, code: str, plain: str) -> None:
        super().__init__(f"{code}: {plain}")
        self.code = code
        self.plain = plain


@dataclass(frozen=True)
class OperatorContext:
    """Proof that the HTTP layer verified the operator. Construct it only through ``server_context()``."""

    principal: str
    session: str
    csrf_ok: bool
    listener: str
    _seal: object = None

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise Refused(
                "server_context_required",
                "An approval can only be decided by the Command Center server after it verified the operator's "
                "session. This call did not come from there, so nothing was decided.",
            )


def server_context(*, principal: str, session: str = "", csrf_ok: bool, listener: str) -> OperatorContext:
    """Mint the server-side context. Called by the Command Center API route (piece B) and by nothing else.

    The factory refuses anything that is not a verified operator request: the principal must be a tailnet identity
    (``tailnet:<login>``), and the listener must be the authenticated serve proxy. An agent identity
    (``agent:…``), a service token, or an unauthenticated listener cannot produce a context at all — the shape check is
    here as well as in ``_check_context`` so a caller that skips one still meets the other.
    """
    login = _tailnet_login(principal)
    if not login:
        raise Refused("operator_session_required",
                      "Only the operator's tailnet identity from the authenticated Command Center listener can decide a "
                      "request. This caller is not one, so nothing was decided.")
    if str(listener or "") != SERVE_LISTENER:
        raise Refused("operator_session_required",
                      "Only the authenticated Command Center listener can decide a request. This call came from "
                      f"“{listener or '(none)'}”, so nothing was decided.")
    if login.lower() not in allowed_logins():
        raise Refused("operator_session_required",
                      "That tailnet login is not on the operator allowlist, so nothing was decided.")
    return OperatorContext(principal=f"tailnet:{login}", session=str(session or ""), csrf_ok=bool(csrf_ok),
                           listener=str(listener), _seal=_SEAL)


SERVE_LISTENER = "serve_proxy"
CC_AUTH_REL = Path("config/cc_auth.yaml")
_ALLOWED_LOGINS_CACHE: Optional[frozenset[str]] = None


def allowed_logins() -> frozenset[str]:
    """The operator logins from config/cc_auth.yaml. Unreadable policy refuses rather than allowing everyone."""
    global _ALLOWED_LOGINS_CACHE
    if _ALLOWED_LOGINS_CACHE is None:
        try:
            import yaml
            doc = yaml.safe_load(CC_AUTH_REL.read_text(encoding="utf-8")) or {}
            rows = (((doc.get("cc_auth") or {}) if isinstance(doc, dict) else {}).get("allowed_logins")) or []
            logins = frozenset(str(x).strip().lower() for x in rows if str(x).strip())
        except (OSError, ValueError, ImportError) as exc:
            raise Refused("operator_policy_unreadable",
                          f"The operator login list could not be read ({exc}), so no decision can be authorised.") from exc
        if not logins:
            raise Refused("operator_policy_empty", "The operator login list is empty, so no decision can be authorised.")
        _ALLOWED_LOGINS_CACHE = logins
    return _ALLOWED_LOGINS_CACHE


def reset_allowed_logins_cache() -> None:
    """Tests only: forget the cached allowlist after editing the policy file."""
    global _ALLOWED_LOGINS_CACHE
    _ALLOWED_LOGINS_CACHE = None


def _tailnet_login(principal: Any) -> str:
    text = str(principal or "").strip()
    if not text.startswith("tailnet:"):
        return ""
    return text.split(":", 1)[1].strip()


def _check_context(ctx: Any) -> OperatorContext:
    if not isinstance(ctx, OperatorContext):
        raise Refused(
            "server_context_required",
            "An approval can only be decided by the Command Center server after it verified the operator's session. "
            "This call did not come from there, so nothing was decided.",
        )
    if not _tailnet_login(ctx.principal):
        raise Refused("operator_session_required",
                      "A button click only counts from the operator's own logged-in Command Center session. This click "
                      "did not name one, so nothing was decided.")
    if ctx.listener != SERVE_LISTENER:
        raise Refused("operator_session_required",
                      "Only the authenticated Command Center listener can decide a request, so nothing was decided.")
    if not ctx.csrf_ok:
        raise Refused("csrf_required",
                      "This request did not pass the same-origin check, so it was refused. Reload Command Center and "
                      "try again.")
    return ctx


def _utc(now: Optional[datetime] = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(now: Optional[datetime] = None) -> str:
    return _utc(now).isoformat(timespec="seconds")


def _parse(value: Any) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


# ── Store ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
    with contextlib.suppress(OSError):
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(row, sort_keys=True, default=str)
    digest = hashlib.sha256(body.encode()).hexdigest()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (body + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest


@dataclass
class Store:
    root: Path

    @property
    def requests_dir(self) -> Path:
        return Path(self.root) / "needs_you" / "requests"

    @property
    def events(self) -> Path:
        """The stream the Telegram edge (piece D, scripts/approvals_notify.py) reads.

        Vocabulary agreed with that lane: open = created|updated|pending|open|requested; closed =
        resolved|declined|approved|expired|cancelled|done. ``requester`` is a plain string there, so the event carries
        the session string and the richer mapping under ``requester_detail``.
        """
        return Path(self.root) / "approvals" / "requests.jsonl"

    @property
    def ledger(self) -> Path:
        return Path(self.root) / "needs_you" / "ledger.jsonl"

    @property
    def digest(self) -> Path:
        return Path(self.root) / "coordination" / "digest_approvals.jsonl"

    def path(self, request_id: str) -> Path:
        if not request_id or "/" in request_id or request_id.startswith("."):
            raise Refused("invalid_request_id", "That request id is not one this board could have issued.")
        return self.requests_dir / f"{request_id}.json"

    def put(self, record: Mapping[str, Any]) -> None:
        _atomic_write(self.path(str(record["id"])), json.dumps(record, indent=1, sort_keys=True) + "\n")

    def get(self, request_id: str) -> Optional[dict[str, Any]]:
        path = self.path(request_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise Refused("store_unreadable",
                          "That request could not be read, so it is shown as an error rather than as nothing.") from exc

    def require(self, request_id: str) -> dict[str, Any]:
        record = self.get(request_id)
        if record is None:
            raise Refused("unknown_request", "There is no such request on the Needs-you board.")
        return record

    def all(self) -> list[dict[str, Any]]:
        """Every stored record. A corrupt record or a directory that cannot be listed is an ERROR, never an empty board.

        ``Path.glob`` swallows a permission error on directory iteration and yields nothing, which turns "cannot read"
        into "nothing needs you" — the exact false all-clear this board must never show. ``os.scandir`` raises, and the
        raise is translated into the same plain refusal the API already maps to an error state.
        """
        if not self.requests_dir.exists():
            return []
        if not self.requests_dir.is_dir():
            raise Refused("store_unreadable", "The Needs-you store is not a directory; nothing can be shown safely.")
        try:
            with os.scandir(self.requests_dir) as entries:
                paths = sorted((Path(entry.path) for entry in entries if entry.name.endswith(".json")),
                               key=lambda p: p.name)
        except OSError as exc:
            raise Refused(
                "store_unreadable",
                "The Needs-you store could not be read, so decisions cannot be shown until it is repaired.",
            ) from exc
        rows = []
        for path in paths:
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                raise Refused("store_unreadable",
                              f"The Needs-you store has an unreadable record ({path.name}); decisions cannot be "
                              f"shown until it is repaired.") from exc
            if not isinstance(rows[-1], dict):
                raise Refused("store_unreadable",
                              f"The Needs-you store has a record that is not an object ({path.name}); decisions "
                              f"cannot be shown until it is repaired.")
            # A syntactically valid record with no schema/type/state is not evidence of an empty board:
            # it was filtered out of every projection and a decision disappeared silently (cx-openai-3 F2).
            try:
                _validate_record(rows[-1])
            except Refused as exc:
                raise Refused("store_unreadable",
                              f"The Needs-you store has a corrupt record ({path.name}: {exc.plain}); decisions "
                              f"cannot be shown until it is repaired.") from exc
            if rows[-1].get("state") not in STATES:
                raise Refused("store_unreadable",
                              f"The Needs-you store has a record in an unknown state ({path.name}); decisions "
                              f"cannot be shown until it is repaired.")
        return rows


# ── Validation ───────────────────────────────────────────────────────────────────────────────────────────────────
def _check_type(kind: Any) -> str:
    value = str(kind or "").strip()
    if value not in ACTION_TYPES:
        raise Refused(
            "unknown_action_type",
            f"“{value or '(empty)'}” is not something a button may do. A click can only ever be one of: "
            + ", ".join(sorted(ACTION_TYPES))
            + ".",
        )
    return value


def _check_text(fields: Mapping[str, Any]) -> dict[str, str]:
    out = {}
    missing = [key for key in TEXT_FIELDS if not str(fields.get(key) or "").strip()]
    if missing:
        raise Refused(
            "text_incomplete",
            "This request is missing words the operator needs before he can decide (" + ", ".join(missing) + ").",
        )
    for key in TEXT_FIELDS:
        out[key] = str(fields[key]).strip()
    return out


def _check_facts(kind: str, facts: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    data = dict(facts or {})
    missing = [key for key in REQUIRED_FACTS[kind] if data.get(key) in (None, "")]
    if missing:
        raise Refused(
            "facts_incomplete",
            "This request is missing the exact facts a button would act on (" + ", ".join(missing) + ").",
        )
    for key in ("head_sha", "cmd_sha256", "file_sha256", "packet_sha256"):
        if data.get(key) is not None:
            text = str(data[key]).lower()
            want = 40 if key == "head_sha" else 64
            if len(text) != want or any(c not in "0123456789abcdef" for c in text):
                raise Refused("facts_invalid", f"The {key} in this request is not a full hexadecimal hash.")
            data[key] = text
    for key in ("pr", "run_id", "pid", "uses"):
        if key in data and data[key] is not None:
            try:
                data[key] = int(data[key])
            except (TypeError, ValueError) as exc:
                raise Refused("facts_invalid", f"The {key} in this request is not a number.") from exc
    for key in ("expires_at", "start_time_epoch"):
        if key in data and data[key] is not None and not isinstance(data[key], (int, float)):
            try:
                _parse(data[key])
            except (TypeError, ValueError) as exc:
                raise Refused("facts_invalid", f"The {key} in this request is not a timestamp.") from exc
    return data


# ── Executor seam ───────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Progress:
    """What the executor had already done when it stopped — recorded on every failure and timeout receipt."""

    steps: list[dict[str, Any]] = field(default_factory=list)

    def reached(self, step: str) -> None:
        self.steps.append({"step": str(step), "at": _iso()})

    def last(self) -> str:
        return self.steps[-1]["step"] if self.steps else "unknown"


class Executor(Protocol):
    """Bridge to the real action. ``revalidate`` runs at click time and must re-read the live facts."""

    def revalidate(self, record: Mapping[str, Any], *, now: datetime) -> tuple[bool, str]: ...

    def execute(self, record: Mapping[str, Any], *, actor: str, now: datetime,
                progress: Progress, deadline: Deadline) -> dict[str, Any]: ...


class RefuseAll:
    """Fail-closed default: with no registered executor a click cannot do anything."""

    def revalidate(self, record: Mapping[str, Any], *, now: datetime) -> tuple[bool, str]:
        return False, ("No executor is configured for this action yet, so approving it would do nothing. "
                       "The lead will wire it before offering the button.")

    def execute(self, record: Mapping[str, Any], *, actor: str, now: datetime,
                progress: Progress, deadline: Deadline) -> dict[str, Any]:
        raise Refused("no_executor", "No executor is configured for this action yet.")


@dataclass
class CallbackExecutor:
    """Executor backed by two callables, both with fixed arities.

    There is deliberately **no TypeError fallback**: catching a TypeError and retrying at another arity means a callback
    that already performed its effect and then raised TypeError gets called a second time. Adapt a two-argument handler
    with ``two_arg`` at construction instead, so the signature is settled before anything runs.
    """

    revalidate_fn: Callable[[Mapping[str, Any]], tuple[bool, str]]
    execute_fn: Callable[..., dict[str, Any]]
    _arity: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        # Settle the handler's arity ONCE, before anything runs. There is no TypeError retry after a call: a handler
        # that performed its effect and then raised TypeError must never be invoked twice.
        try:
            count = len([p for p in inspect.signature(self.execute_fn).parameters.values()
                         if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
        except (TypeError, ValueError):
            count = 4
        self._arity = min(max(count, 0), 4)

    def revalidate(self, record: Mapping[str, Any], *, now: datetime) -> tuple[bool, str]:
        return self.revalidate_fn(record)

    def execute(self, record: Mapping[str, Any], *, actor: str, now: datetime,
                progress: Progress, deadline: Deadline) -> dict[str, Any]:
        if self._arity >= 4:
            return self.execute_fn(record, actor, progress, deadline)
        if self._arity == 3:
            return self.execute_fn(record, actor, progress)
        if self._arity == 2:
            return self.execute_fn(record, actor)
        return self.execute_fn(record)


def two_arg(fn: Callable[[Mapping[str, Any], str], dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Adapt a (record, actor) handler to the three-argument executor signature, once, before anything runs."""

    def _adapted(record: Mapping[str, Any], actor: str, progress: Progress,  # noqa: ARG001
                 deadline: Deadline) -> dict[str, Any]:  # noqa: ARG001
        return fn(record, actor)

    return _adapted


EXECUTORS: dict[str, Executor] = {}


def executor_for(kind: str) -> Executor:
    return EXECUTORS.get(kind) or RefuseAll()


def register_executor(kind: str, executor: Executor) -> None:
    """Wire one action type. Called by the CLI adapters and by tests; unknown types are refused."""
    if kind not in ACTION_TYPES:
        raise Refused("unknown_action_type", f"“{kind}” is not on the closed action list.")
    EXECUTORS[kind] = executor


# ── Creation ───────────────────────────────────────────────────────────────────────────────────────────────────
def publish_event(store: Store, record: Mapping[str, Any], event: str) -> None:
    """Append one ApprovalRequestEvent@v1 row for the Telegram nudge lane. Never fails a decision.

    The nudge is an edge, not a gate: a failure to write the stream must not turn a recorded decision into an error, but
    a missing row would leave the operator un-nudged, so callers publish before the action runs.
    """
    row = {
        "schema": "ApprovalRequestEvent@v1",
        "event": str(event),
        "id": record.get("id"),
        "type": record.get("type"),
        "title": record.get("title"),
        "why": record.get("why"),
        "rule": record.get("rule"),
        "requester": str((record.get("requester") or {}).get("session") or ""),
        "requester_detail": record.get("requester"),
        "created_at": record.get("created_at"),
        "expires_at": record.get("expires_at"),
        "state": record.get("state"),
        "facts": record.get("facts"),
    }
    with contextlib.suppress(OSError):
        _append_jsonl(store.events, row)


def new_id(now: Optional[datetime] = None, *, seed: str = "") -> str:
    stamp = _utc(now).strftime("%Y%m%dT%H%M%SZ")
    return f"apr-{stamp}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"


def create(
    store: Store,
    payload: Mapping[str, Any],
    *,
    requester: Mapping[str, Any] | str,
    now: Optional[datetime] = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    moment = _utc(now)
    kind = _check_type(payload.get("type"))
    text = _check_text(payload)
    facts = _check_facts(kind, payload.get("facts"))
    who = requester if isinstance(requester, Mapping) else {"session": str(requester)}
    who = {"session": str(who.get("session") or "").strip(),
           "claim": (str(who.get("claim")).strip() if who.get("claim") else None),
           "actor": (str(who.get("actor")).strip() if who.get("actor") else None),
           "vendor": (str(who.get("vendor")).strip() if who.get("vendor") else None)}
    if not who["session"]:
        raise Refused("requester_unknown",
                      "This request does not say which session asked, so nobody could verify the approver is "
                      "someone else.")
    rid = request_id or new_id(moment, seed=secrets.token_hex(16))
    if store.path(rid).exists():
        raise Refused("duplicate_request_id",
                      "A request with this id already exists. A new request never overwrites an older decision.")
    ttl = float(payload.get("ttl_hours") or DEFAULT_TTL_HOURS)
    record = {
        "schema": SCHEMA,
        "id": rid,
        "type": kind,
        **text,
        "facts": facts,
        "requester": who,
        "created_at": _iso(moment),
        "expires_at": _iso(moment + timedelta(hours=ttl)),
        "state": "open",
        "decided_by": None,
        "decided_at": None,
        "decision": None,
        "decline_reason": None,
        "receipt": None,
        "result": None,
        "blocked_reason": None,
        "reask_requested": False,
        "question": None,
    }
    store.put(record)
    record["receipt"] = _append_jsonl(store.ledger, {
        "schema": RECEIPT_SCHEMA, "event": "created", "at": record["created_at"], "id": rid, "type": kind,
        "requester": who, "facts": facts,
    })
    store.put(record)
    publish_event(store, record, "created")
    return record


# ── Reads ─────────────────────────────────────────────────────────────────────────────────────────────────────
def get(store: Store, request_id: str) -> Optional[dict[str, Any]]:
    return store.get(request_id)


def list_open(store: Store, *, now: Optional[datetime] = None, limit: int = 100) -> list[dict[str, Any]]:
    """The dashboard projection. [] means the store was readable and empty — a read failure raises instead."""
    moment = _utc(now)
    rows = [row for row in store.all() if row.get("state") == "open"]
    live = []
    for row in rows:
        try:
            if moment >= _parse(row.get("expires_at")):
                continue
        except (TypeError, ValueError):
            raise Refused("store_unreadable",
                          f"Request {row.get('id')} has an unusable expiry; it cannot be shown.") from None
        live.append(row)
    live.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return live[: max(1, int(limit))]


def revalidate(store: Store, record: Mapping[str, Any], *, now: Optional[datetime] = None,
               executor: Optional[Executor] = None) -> tuple[bool, str]:
    """Ask the executor whether the bound facts still hold. Changes nothing."""
    bridge = executor or executor_for(str(record.get("type")))
    return bridge.revalidate(record, now=_utc(now))


# ── Decisions ────────────────────────────────────────────────────────────────────────────────────────────────
def _binding_of(record: Mapping[str, Any]) -> str:
    """The immutable core of a request: what was approved is these fields and nothing else."""
    core = {key: record.get(key) for key in ("id", "type", "facts", "requester", "created_at", "expires_at")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def _acquire(path: Path, code: str, plain: str) -> None:
    """Create an exclusive marker file. EEXIST means someone else already holds this transition."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise Refused(code, plain) from exc
    os.close(fd)


def _has_recorded_approval(store: Store, request_id: str, binding: Any) -> bool:
    """An execution is only allowed on evidence of an approval actually written to the ledger.

    A record crafted directly on disk (state approved, self-computed binding) has no such row, so it cannot execute.
    """
    if not binding:
        return False
    try:
        lines = store.ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (row.get("event") == "approved" and row.get("id") == request_id
                and row.get("binding") == binding and row.get("approval_source") == "operator_session+csrf"):
            return True
    return False


def _release(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _canonical_actor(value: Any) -> str:
    """One identity representation, so case or a transport prefix cannot split one operator into two.

    Authentication admits a login case-insensitively and stamps the context as ``tailnet:<login>``, while the
    requester's actor may be stored with either spelling. Comparing raw strings let the same operator ask as
    ``operator@x`` and approve as ``OPERATOR@x`` (or approve a ``tailnet:``-prefixed requester under the bare
    login) — one identity, two strings, separation check silent (cx-openai-3 F1, 2026-11-03).
    """
    text = str(value or "").strip()
    if text.lower().startswith("tailnet:"):
        text = text.split(":", 1)[1]
    return text.casefold()


def _validate_record(record: Mapping[str, Any]) -> str:
    """Refuse a record whose own shape is wrong — a tampered or corrupt record never reaches an executor."""
    if record.get("schema") != SCHEMA:
        raise Refused("record_invalid", "This request is not in the form this board writes, so nothing was done.")
    kind = record.get("type")
    if kind not in ACTION_TYPES:
        raise Refused("record_invalid",
                      "This request names an action that is not on the closed list, so nothing was done.")
    try:
        _check_facts(str(kind), record.get("facts"))
    except Refused as exc:
        raise Refused("record_invalid", f"This request's bound facts are not valid ({exc.plain})") from exc
    return str(kind)


def decide(
    store: Store,
    request_id: str,
    *,
    ctx: OperatorContext,
    actor: str,
    decision: str,
    note: str = "",
    now: Optional[datetime] = None,
    executor: Optional[Executor] = None,
    timeout_s: float = DEFAULT_EXECUTE_TIMEOUT_S,
    expected_binding: Optional[str] = None,
) -> dict[str, Any]:
    """The single decision entry point. Server-only (``ctx``), and it owns all three rails so no caller can skip them.

    The transition lock is taken **before** the record is read, and the record is re-read under it: a decision that
    paused while another click executed must not resume against the state it saw on the way in and overwrite a terminal
    row. ``expected_binding`` is the digest of the card the operator actually saw (B passes it from the confirm sheet);
    it is compared under the lock, so a request edited between render and click is refused instead of executed.
    """
    moment = _utc(now)
    context = _check_context(ctx)
    login = _tailnet_login(context.principal)
    if not actor or actor != login:
        raise Refused("actor_not_authenticated",
                      "The name recorded for this decision must be the operator identity the server verified; this "
                      "call named someone else, so nothing was decided.")
    # The id is validated before any path is built from it: a traversal-shaped id used to reach a
    # lock path containing ".." before being refused (cx-openai-3, 2026-11-03).
    store.path(request_id)
    decision_claim = store.requests_dir / f"{request_id}.deciding"
    _acquire(decision_claim, "decision_in_progress",
             "This request is already being decided, so it was not decided twice.")
    try:
        return _decide_locked(store, request_id, context=context, actor=actor, decision=decision, note=note,
                              moment=moment, executor=executor, timeout_s=timeout_s,
                              expected_binding=expected_binding)
    finally:
        _release(decision_claim)


def _decide_locked(store: Store, request_id: str, *, context: OperatorContext, actor: str, decision: str,
                   note: str, moment: datetime, executor: Optional[Executor], timeout_s: float,
                   expected_binding: Optional[str]) -> dict[str, Any]:
    record = store.require(request_id)
    choice = str(decision or "").strip().lower()
    if choice not in ("approve", "decline"):
        raise Refused("unknown_decision", "A decision is either approve or decline.")

    requester = record.get("requester") or {}
    approver_identity = _canonical_actor(actor)
    requester_actor = _canonical_actor(requester.get("actor")) if requester.get("actor") else ""
    requester_session = str(requester.get("session") or "")
    if (requester_actor and approver_identity == requester_actor) or \
            (requester_session and approver_identity == _canonical_actor(requester_session)):
        raise Refused("approver_is_requester",
                      "The session that asked cannot also decide: this request was created by the same identity that "
                      "clicked. The lead must re-ask it from a different session.")
    if context.session and requester_session and str(context.session) == requester_session:
        raise Refused("approver_is_requester",
                      "The session that created this request cannot decide it. The lead must re-ask it from a "
                      "different session.")
    if record.get("state") != "open":
        raise Refused("not_open",
                      f"This request is already {record.get('state')}; nothing further happens until the lead re-asks.")
    try:
        expired = moment >= _parse(record.get("expires_at"))
    except (TypeError, ValueError):
        expired = True
    if expired:
        record.update({"state": "expired", "reask_requested": True})
        store.put(record)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "expired", "at": _iso(moment),
                                     "id": request_id, "actor": actor})
        publish_event(store, record, "expired")
        raise Refused("request_expired",
                      "This request expired, so nothing was approved; the lead will ask again.")

    kind = _validate_record(record)
    if expected_binding and str(expected_binding) != _binding_of(record):
        raise Refused("card_changed",
                      "This card changed since it was shown to you, so nothing was decided. Open Home and check it "
                      "again.")
    if True:
        if choice == "decline":
            at = _iso(moment)
            record.update({"state": "declined", "decision": "decline", "decided_by": actor, "decided_at": at,
                           "decline_reason": str(note or "") or None})
            store.put(record)
            row = {"schema": RECEIPT_SCHEMA, "event": "declined", "at": at, "id": request_id, "actor": actor,
                   "note": str(note or "")}
            record["receipt"] = _append_jsonl(store.ledger, row)
            _append_jsonl(store.digest, row)
            store.put(record)
            publish_event(store, record, "declined")
            return record

        bridge = executor or executor_for(kind)
        ok, plain = bridge.revalidate(record, now=moment)
        if not ok:
            record["blocked_reason"] = plain or "This changed since it was asked. The lead will re-ask."
            store.put(record)
            _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "facts_moved", "at": _iso(moment),
                                         "id": request_id, "reason": record["blocked_reason"]})
            publish_event(store, record, "updated")
            raise Refused("facts_moved", record["blocked_reason"])

        binding = _binding_of(record)
        receipt = _append_jsonl(store.ledger, {
            "schema": RECEIPT_SCHEMA, "event": "approved", "at": _iso(moment), "id": request_id,
            "type": kind, "facts": record.get("facts"), "requester": requester, "actor": actor,
            "approver_session": context.session, "approval_source": "operator_session+csrf",
            "binding": binding,
        })
        _append_jsonl(store.digest, {"schema": RECEIPT_SCHEMA, "event": "approved", "at": _iso(moment),
                                     "id": request_id, "type": kind, "facts": record.get("facts"), "actor": actor,
                                     "binding": binding})
        record.update({"state": "approved", "decision": "approve", "decided_by": actor, "decided_at": _iso(moment),
                       "receipt": receipt, "blocked_reason": None, "binding": binding})
        store.put(record)
        publish_event(store, record, "approved")
        return execute(store, record, actor=actor, now=moment, executor=bridge, timeout_s=timeout_s,
                       binding=binding)


def execute(store: Store, record: Mapping[str, Any], *, actor: str, now: Optional[datetime] = None,
            executor: Optional[Executor] = None, timeout_s: float = DEFAULT_EXECUTE_TIMEOUT_S,
            binding: Optional[str] = None) -> dict[str, Any]:
    """Run an approved action exactly once, at the exact facts that were approved.

    The execution boundary re-validates everything the approval relied on: the record's schema and type must still be
    the closed-list action that was approved, its facts must hash to the approved binding, and the executor must confirm
    the live facts again here (not only before the decision). An exclusive per-request marker makes a second execution
    impossible, including from a concurrent click, a resumed record, or a retried call.

    A timeout does not stop work that is already running: it is recorded as ``timed_out_unconfirmed`` with
    ``needs_reconciliation`` so a half-done action is never mistaken for a stopped one, and the marker keeps it from being
    started a second time.
    """
    moment = _utc(now)
    current = store.require(str(record.get("id")))
    rid = str(current.get("id"))
    settled = ("executed", "failed", "declined", "expired", "cancelled")
    if current.get("state") in settled:
        return current

    try:
        kind = _validate_record(current)
    except Refused as exc:
        current.update({"state": "open", "blocked_reason": exc.plain})
        store.put(current)
        raise
    expected = binding or current.get("binding")
    actual = _binding_of(current)
    if not expected or expected != actual or current.get("binding") != actual:
        current.update({"state": "open", "blocked_reason":
                        "This changed after it was approved. The lead will re-ask."})
        store.put(current)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "binding_mismatch", "at": _iso(moment),
                                     "id": rid, "expected": expected, "actual": actual})
        publish_event(store, current, "updated")
        raise Refused("binding_mismatch",
                      "The request on disk is not the one that was approved (its type or facts changed), so nothing "
                      "was executed. The lead will re-ask.")
    if current.get("state") not in ("approved", "executing"):
        raise Refused("not_approved", f"This request is {current.get('state')}, so there is nothing to execute.")
    if not _has_recorded_approval(store, rid, current.get("binding")):
        current.update({"state": "open", "blocked_reason":
                        "There is no recorded operator approval for this request, so nothing was executed."})
        store.put(current)
        raise Refused("no_recorded_approval",
                      "This request has no recorded operator approval in the ledger, so nothing was executed.")

    exec_claim = store.requests_dir / f"{rid}.executed"
    _acquire(exec_claim, "already_executing",
             "This action is already running or has already run; it will not be started twice.")
    bridge = executor or executor_for(kind)
    try:
        ok, plain = bridge.revalidate(current, now=moment)
    except Exception as exc:  # noqa: BLE001 — any pre-effect failure must not strand the marker
        # The marker is ours and the action never started: record it, release the claim and let the
        # caller retry. Leaving it behind made a corrected retry impossible (cx-openai-3 F3).
        _release(exec_claim)
        current.update({"blocked_reason": "The action could not be revalidated before it ran, so it was not started. "
                                          "It stays approved and can be retried."})
        store.put(current)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "revalidation_failed", "at": _iso(moment),
                                     "id": rid, "reason": current["blocked_reason"],
                                     "error_type": type(exc).__name__, "at_execution": True})
        publish_event(store, current, "updated")
        raise Refused("revalidation_failed", current["blocked_reason"]) from exc
    if not ok:
        _release(exec_claim)
        current.update({"state": "open", "blocked_reason": plain or
                        "This changed before the action ran. The lead will re-ask."})
        store.put(current)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "facts_moved", "at": _iso(moment),
                                     "id": rid, "reason": current["blocked_reason"], "at_execution": True})
        publish_event(store, current, "updated")
        raise Refused("facts_moved", current["blocked_reason"])

    current["state"] = "executing"
    store.put(current)

    progress = Progress()
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = bridge.execute(current, actor=actor, now=moment, progress=progress, deadline=deadline)
        except BaseException as exc:  # noqa: BLE001 - reported through the receipt, never swallowed
            box["error"] = exc

    deadline = Deadline(float(timeout_s))
    worker = threading.Thread(target=_run, name=f"home-approvals-{rid}", daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(float(timeout_s))
    elapsed = round(time.monotonic() - started, 3)
    attempted = {
        "type": kind,
        "facts": current.get("facts"),
        "steps": list(progress.steps),
        "step_reached": progress.last(),
        "timeout_s": float(timeout_s),
        "elapsed_s": elapsed,
    }

    def _finish(state: str, outcome: str, plain: str, *, extra: Optional[Mapping[str, Any]] = None) -> None:
        body = {"ok": outcome == "executed", "outcome": outcome, "plain": plain, "attempted": attempted}
        body.update(extra or {})
        current.update({"state": state, "result": body})
        store.put(current)
        row = {"schema": RECEIPT_SCHEMA, "event": outcome, "at": _iso(moment), "id": rid,
               "outcome": outcome, "plain": plain, "attempted": attempted}
        _append_jsonl(store.ledger, row)
        _append_jsonl(store.digest, {"schema": RECEIPT_SCHEMA, "event": outcome, "at": _iso(moment), "id": rid,
                                     "outcome": outcome})

    if worker.is_alive():
        _finish("failed", "timed_out_unconfirmed",
                (f"The action did not confirm within {float(timeout_s):.0f}s. It may still be running, so it is marked "
                 f"for reconciliation and will not be started again; what had already run is recorded."),
                extra={"needs_reconciliation": True})
        return current

    if "error" in box:
        _finish("failed", "failed", f"The action did not complete: {box['error']}")
        return current

    result = box.get("result") or {}
    if result.get("ok") is True:
        current.update({"state": "executed", "result": {**dict(result), "outcome": "executed",
                                                        "attempted": attempted}})
        store.put(current)
        row = {"schema": RECEIPT_SCHEMA, "event": "executed", "at": _iso(moment), "id": rid,
               "outcome": "executed", "attempted": attempted}
        _append_jsonl(store.ledger, row)
        _append_jsonl(store.digest, {"schema": RECEIPT_SCHEMA, "event": "executed", "at": _iso(moment), "id": rid,
                                     "outcome": "executed"})
        return current
    if result.get("ok") is False:
        _finish("failed", "refused", str(result.get("plain") or "The action refused to run."))
        return current
    _finish("failed", "unknown_result",
            "The action returned without saying whether it succeeded, so it is treated as failed and will not be "
            "retried automatically.")
    return current


def question(store: Store, request_id: str, *, actor: str, note: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """Record an "Ask a question" note on the request. Changes no state; delivery to the lead is the API's job."""
    moment = _utc(now)
    text = str(note or "").strip()
    if not text:
        raise Refused("question_empty", "A question needs words the lead can answer.")
    # A question is a transition over the same record: without the lock and a re-read, a concurrent
    # decide() that reached a terminal state was overwritten with this stale open snapshot
    # (cx-openai-3 F4).
    store.path(request_id)
    question_claim = store.requests_dir / f"{request_id}.questioning"
    _acquire(question_claim, "question_in_progress",
             "Another update to this request is in progress, so the question was not recorded.")
    try:
        record = store.require(request_id)
        if record.get("state") not in ("open", "approved"):
            raise Refused("not_open",
                          f"This request is already {record.get('state')}, so a question cannot change it.")
        record["question"] = {"at": _iso(moment), "by": str(actor or ""), "note": text}
        store.put(record)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "question", "at": record["question"]["at"],
                                     "id": request_id, "by": record["question"]["by"], "note": text})
        publish_event(store, record, "updated")
        return record
    finally:
        _release(question_claim)


def expire_due(store: Store, *, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Mark open requests past their deadline expired (re-ask). Never approves anything."""
    moment = _utc(now)
    changed = []
    for record in store.all():
        if record.get("state") != "open":
            continue
        if (store.requests_dir / f"{record['id']}.deciding").exists():
            continue  # a decision is in flight under its lock; expiry must not race it
        try:
            if moment < _parse(record.get("expires_at")):
                continue
        except (TypeError, ValueError):
            pass
        record.update({"state": "expired", "reask_requested": True})
        store.put(record)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "expired", "at": _iso(moment),
                                     "id": record["id"]})
        publish_event(store, record, "expired")
        changed.append(record)
    return changed


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _store_from(args: argparse.Namespace) -> Store:
    root = args.state_root or os.environ.get("TRADEAI_STATE_ROOT")
    if not root:
        raise SystemExit("home_approvals: --state-root (or TRADEAI_STATE_ROOT) is required; no /tmp default exists")
    return Store(Path(root))


def _print(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=1, sort_keys=True, default=str))
    elif isinstance(payload, list):
        for row in payload:
            print(f"{row.get('id')}  {row.get('type'):<16} {row.get('state'):<9} {row.get('title', '')}")
        if not payload:
            print("Nothing needs you.")
    else:
        print(json.dumps(payload, indent=1, sort_keys=True, default=str))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Home v008 Needs-you: create and answer operator decisions.")
    parser.add_argument("--state-root")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="create a request (agents and the lead)")
    ask.add_argument("--type", required=True, dest="kind", choices=sorted(ACTION_TYPES))
    ask.add_argument("--title", required=True)
    ask.add_argument("--why", required=True)
    ask.add_argument("--rule", required=True)
    ask.add_argument("--what-happens", required=True, dest="what_happens")
    ask.add_argument("--risk", required=True)
    ask.add_argument("--undo", required=True)
    ask.add_argument("--requester", required=True, help="the asking session, e.g. cc-deepseek-5")
    ask.add_argument("--claim", default="")
    ask.add_argument("--facts", default="{}", help="JSON object of the exact bound facts")
    ask.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)

    listing = sub.add_parser("list", help="open requests (the dashboard projection)")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--limit", type=int, default=100)

    show = sub.add_parser("show")
    show.add_argument("request_id")

    for name in ("approve", "decline"):
        command = sub.add_parser(name)
        command.add_argument("request_id")
        command.add_argument("--actor", required=True)
        command.add_argument("--session", default="")
        command.add_argument("--note", default="")

    q = sub.add_parser("question")
    q.add_argument("request_id")
    q.add_argument("--actor", required=True)
    q.add_argument("--note", required=True)

    sub.add_parser("expire", help="mark due requests expired (never approves)")

    args = parser.parse_args(argv)
    store = _store_from(args)
    try:
        if args.cmd == "ask":
            facts = json.loads(args.facts)
            if not isinstance(facts, dict):
                raise Refused("facts_invalid", "The bound facts must be a JSON object.")
            record = create(store, {
                "type": args.kind, "title": args.title, "why": args.why, "rule": args.rule,
                "what_happens": args.what_happens, "risk": args.risk, "undo": args.undo,
                "facts": facts, "ttl_hours": args.ttl_hours,
            }, requester={"session": args.requester, "claim": args.claim or None})
            _print(record, as_json=args.json)
            return 0
        if args.cmd == "list":
            rows = store.all() if args.all else list_open(store, limit=args.limit)
            _print(rows, as_json=args.json)
            return 0
        if args.cmd == "show":
            _print(store.require(args.request_id), as_json=args.json)
            return 0
        if args.cmd == "expire":
            _print(expire_due(store), as_json=args.json)
            return 0
        if args.cmd == "question":
            _print(question(store, args.request_id, actor=args.actor, note=args.note), as_json=args.json)
            return 0
        raise Refused("server_context_required",
                      "A decision can only be made from the operator's logged-in Command Center session. This command "
                      "line cannot prove one, so nothing was decided.")
    except Refused as exc:
        print(json.dumps({"ok": False, "code": exc.code, "plain": exc.plain}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
