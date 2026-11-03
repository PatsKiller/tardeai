#!/usr/bin/env python3
"""needs_you.py — Home v008 "Needs you": operator decision requests, the CLOSED action list, and the executor.

A request is created by an agent or the coordinator and approved **only** by the operator from his logged-in
Command Center session. Three rails are unconditional and each has a test:

1. An approval is accepted only with the server-derived operator session *and* a same-origin CSRF pass
   (`Approval.operator_session` / `Approval.csrf_ok`); a caller cannot assert them from a request body, because the
   library takes them as explicit arguments that the CLI fills only from its own flags, and the HTTP layer (not this
   module) is the only place allowed to set them from a verified session.
2. The approver may never be the requester — the request carries its author's session, and `approve()` refuses when
   they match.
3. An expired request is *re-asked*, never auto-approved: `approve()` refuses an expired request with a plain-English
   reason and the request moves to "needs_reask" in the ledger.

What a button can do is a closed list (`ACTION_TYPES`). A request naming anything else cannot be stored, so it can
never be rendered as a button. Broker orders, credentials, live trading flags, force-push and deletion are not on the
list and have no code path. MBI_BEHAVIOR = 0.

Store (under the persistent-state root; never /tmp):

    <root>/needs_you/requests/<request_id>.json     one NeedsYouRequest@v1, mode 0600, atomic replace
    <root>/needs_you/ledger.jsonl                   append-only: created / approved / declined / expired / executed
    <root>/coordination/digest_approvals.jsonl      append-only digest of every click and its outcome

Every click writes a durable receipt BEFORE the action runs, and the execution result is appended after it, so an
action that fails halfway still leaves the decision on record.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

SCHEMA = "NeedsYouRequest@v1"
RECEIPT_SCHEMA = "NeedsYouReceipt@v1"

# ── The closed action list ────────────────────────────────────────────────────────────────────────────────────────
# Exactly the reviewed set from SPEC_HOME_V008_NEEDS_YOU_APPROVALS_20261103.md §2. Adding a type is a reviewed change
# to this file plus its bound-fact validator; there is no runtime way to widen it.
ACTION_TYPES: dict[str, str] = {
    "merge_pr": "merge a PR at exactly the reviewed head",
    "rerun_ci": "re-run the failed jobs of one CI run, once",
    "grant": "issue a guard grant exactly as shown (tier, duration, uses, reason)",
    "stop_job": "end one named stuck process on the stoppable list",
    "install_schedule": "install one reviewed scheduler line already in the lane registry",
    "restore_store": "run a reviewed restore packet (dry-run diff shown, evidence copy, rollback)",
    "policy_approval": "record the APPROVE line for an AGENTS/policy PR at its exact head",
}

# Facts each type must carry. A request missing one is refused at creation, so the card can never show a button whose
# bound facts are unknown.
REQUIRED_FACTS: dict[str, tuple[str, ...]] = {
    "merge_pr": ("pr", "head"),
    "rerun_ci": ("run_id", "head"),
    "grant": ("grant_id", "tier", "duration_hours", "uses"),
    "stop_job": ("pid", "process_start", "command"),
    "install_schedule": ("lane", "unit_sha256"),
    "restore_store": ("packet_id", "packet_sha256"),
    "policy_approval": ("pr", "head", "policy_version"),
}

DEFAULT_TTL_HOURS = 24.0


class Refused(Exception):
    """A refusal with a machine code and a plain-English sentence for the card."""

    def __init__(self, code: str, plain: str) -> None:
        super().__init__(f"{code}: {plain}")
        self.code = code
        self.plain = plain


def _iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
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


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass
class Store:
    root: Path

    @property
    def requests_dir(self) -> Path:
        return Path(self.root) / "needs_you" / "requests"

    @property
    def request_path(self) -> Path:
        return self.requests_dir

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

    def put(self, request: Mapping[str, Any]) -> None:
        _atomic_write(self.path(str(request["request_id"])), json.dumps(request, indent=1, sort_keys=True) + "\n")

    def get(self, request_id: str) -> dict[str, Any]:
        path = self.path(request_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise Refused("unknown_request", "There is no such request on the Needs-you board.") from exc
        except (OSError, ValueError) as exc:
            raise Refused("unreadable_request", "That request could not be read; the lead will re-ask.") from exc

    def all(self) -> list[dict[str, Any]]:
        if not self.requests_dir.is_dir():
            return []
        rows = []
        for path in sorted(self.requests_dir.glob("*.json")):
            with contextlib.suppress(OSError, ValueError):
                rows.append(json.loads(path.read_text(encoding="utf-8")))
        return rows


# ── Validation ───────────────────────────────────────────────────────────────────────────────────────────────────
def _check_type(action_type: str) -> str:
    kind = str(action_type or "").strip()
    if kind not in ACTION_TYPES:
        allowed = ", ".join(sorted(ACTION_TYPES))
        raise Refused(
            "unknown_action_type",
            f"“{kind or '(empty)'}” is not something a button may do. A click can only ever be one of: {allowed}.",
        )
    return kind


def _check_facts(action_type: str, facts: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    data = dict(facts or {})
    missing = [key for key in REQUIRED_FACTS[action_type] if data.get(key) in (None, "")]
    if missing:
        raise Refused(
            "facts_incomplete",
            "This request is missing the exact facts a button would act on ("
            + ", ".join(missing)
            + "), so it cannot be offered.",
        )
    head = data.get("head")
    if "head" in REQUIRED_FACTS[action_type] and (not isinstance(head, str) or len(head) != 40
                                                  or any(c not in "0123456789abcdef" for c in head.lower())):
        raise Refused("facts_invalid", "The commit this request is bound to is not a full 40-character SHA.")
    for key in ("pr", "run_id", "pid", "uses"):
        if key in data and data[key] is not None:
            try:
                data[key] = int(data[key])
            except (TypeError, ValueError) as exc:
                raise Refused("facts_invalid", f"The {key} in this request is not a number.") from exc
    if "duration_hours" in data:
        try:
            data["duration_hours"] = float(data["duration_hours"])
        except (TypeError, ValueError) as exc:
            raise Refused("facts_invalid", "The grant duration in this request is not a number of hours.") from exc
    return data


# ── Executor seam ───────────────────────────────────────────────────────────────────────────────────────────────
class Executor(Protocol):
    """The bridge to the real action. ``revalidate`` runs at click time and must re-read the live facts."""

    def revalidate(self, request: Mapping[str, Any]) -> tuple[bool, str]: ...

    def execute(self, request: Mapping[str, Any], *, approver: str) -> dict[str, Any]: ...


class RefuseAll:
    """Fail-closed default: without a configured executor no click performs anything."""

    def revalidate(self, request: Mapping[str, Any]) -> tuple[bool, str]:
        return False, ("No executor is configured for this action yet, so approving it would do nothing. "
                       "The lead will wire it before offering the button.")

    def execute(self, request: Mapping[str, Any], *, approver: str) -> dict[str, Any]:
        raise Refused("no_executor", "No executor is configured for this action yet.")


@dataclass
class CallbackExecutor:
    """Executor backed by two callables (used by tests and by the CLI adapters)."""

    revalidate_fn: Callable[[Mapping[str, Any]], tuple[bool, str]]
    execute_fn: Callable[[Mapping[str, Any], str], dict[str, Any]]

    def revalidate(self, request: Mapping[str, Any]) -> tuple[bool, str]:
        return self.revalidate_fn(request)

    def execute(self, request: Mapping[str, Any], *, approver: str) -> dict[str, Any]:
        return self.execute_fn(request, approver)


# ── Creation ───────────────────────────────────────────────────────────────────────────────────────────────────
def new_request_id(now: Optional[datetime] = None, *, seed: str = "") -> str:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"ny-{stamp}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"


def create_request(
    store: Store,
    *,
    action_type: str,
    title: str,
    why: str,
    approve_does: str,
    risk: str,
    undo: str,
    requester: Mapping[str, str],
    facts: Optional[Mapping[str, Any]] = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    now: Optional[datetime] = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    kind = _check_type(action_type)
    bound = _check_facts(kind, facts)
    created = now or datetime.now(timezone.utc)
    who = {key: str(requester.get(key) or "") for key in ("actor", "session", "vendor")}
    if not who["session"]:
        raise Refused("requester_unknown", "This request does not say which session asked, so nobody could verify "
                                           "that the approver is someone else.")
    rid = request_id or new_request_id(created, seed=json.dumps([kind, bound, who, title], sort_keys=True))
    request = {
        "schema": SCHEMA,
        "request_id": rid,
        "action_type": kind,
        "title": str(title),
        "why": str(why),
        "approve_does": str(approve_does),
        "risk": str(risk),
        "undo": str(undo),
        "requester": who,
        "facts": bound,
        "created_at": _iso(created),
        "expires_at": _iso(created + timedelta(hours=float(ttl_hours))),
        "status": "open",
    }
    store.put(request)
    _append_jsonl(store.ledger, {"event": "created", "at": request["created_at"], **request})
    return request


# ── Approval ───────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Approval:
    """What the HTTP layer hands to ``approve`` — the server derives both from a verified session, never a body."""

    approver: str                                   # e.g. "operator" / the operator's login
    operator_session: bool = False                  # server-derived: a verified Command Center operator session
    csrf_ok: bool = False                           # server-derived: same-origin CSRF check passed
    session: str = ""                               # the approving session id (for the receipt)


def approve(
    store: Store,
    request_id: str,
    approval: Approval,
    *,
    executor: Optional[Executor] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    request = store.get(request_id)

    if not approval.operator_session:
        raise Refused(
            "operator_session_required",
            "A button click only counts from the operator's own logged-in Command Center session. This click did not "
            "come from one, so nothing was approved.",
        )
    if not approval.csrf_ok:
        raise Refused(
            "csrf_required",
            "This request did not pass the same-origin check, so it was refused. Reload Command Center and try again.",
        )
    if not approval.approver or approval.approver == request["requester"].get("actor"):
        raise Refused(
            "approver_is_requester",
            "The person who asked cannot also approve: this request was created by the same identity that clicked. "
            "The lead must re-ask it from a different session.",
        )
    if approval.session and approval.session == request["requester"].get("session"):
        raise Refused(
            "approver_is_requester",
            "The session that created this request cannot approve it. The lead must re-ask it from a different session.",
        )
    if request.get("status") != "open":
        raise Refused(
            "not_open",
            f"This request is already {request.get('status')}; nothing further happens until the lead re-asks.",
        )
    try:
        expired = moment >= _parse(str(request["expires_at"]))
    except (KeyError, TypeError, ValueError):
        expired = True
    if expired:
        request["status"] = "needs_reask"
        request["reask_reason"] = "expired"
        store.put(request)
        _append_jsonl(store.ledger, {"event": "expired", "at": _iso(moment), "request_id": request_id,
                                     "approver": approval.approver})
        raise Refused(
            "request_expired",
            "This request expired, so it was not approved. Nothing happened; the lead will ask again.",
        )

    bridge = executor or RefuseAll()
    ok, plain = bridge.revalidate(request)
    if not ok:
        request["status"] = "stale"
        request["blocked_reason"] = plain
        store.put(request)
        _append_jsonl(store.ledger, {"event": "facts_moved", "at": _iso(moment), "request_id": request_id,
                                     "reason": plain})
        raise Refused("facts_moved", plain or "This changed since it was asked. The lead will re-ask.")

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "event": "approved",
        "at": _iso(moment),
        "request_id": request_id,
        "action_type": request["action_type"],
        "facts": request["facts"],
        "requester": request["requester"],
        "approver": approval.approver,
        "approver_session": approval.session,
        "approval_source": "operator_session+csrf",
        "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
    }
    _append_jsonl(store.ledger, receipt)
    _append_jsonl(store.digest, receipt)

    request["status"] = "approved"
    request["approved_at"] = receipt["at"]
    request["approved_by"] = approval.approver
    store.put(request)

    try:
        result = bridge.execute(request, approver=approval.approver)
    except Exception as exc:  # noqa: BLE001 - a failed action must still leave the decision on record
        request["status"] = "failed"
        request["result"] = {"ok": False, "plain": f"The action did not complete: {exc}"}
        store.put(request)
        _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "failed", "at": _iso(moment),
                                     "request_id": request_id, "plain": request["result"]["plain"]})
        return request

    request["status"] = "done"
    request["result"] = dict(result or {})
    store.put(request)
    _append_jsonl(store.ledger, {"schema": RECEIPT_SCHEMA, "event": "executed", "at": _iso(moment),
                                 "request_id": request_id, "result": request["result"]})
    return request


def decline(store: Store, request_id: str, approval: Approval, *, note: str = "",
            now: Optional[datetime] = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    if not approval.operator_session or not approval.csrf_ok:
        raise Refused("operator_session_required", "A decline also has to come from the operator's own session.")
    request = store.get(request_id)
    if approval.approver and approval.approver == request["requester"].get("actor"):
        raise Refused("approver_is_requester", "The requester cannot decline their own request.")
    request["status"] = "declined"
    request["declined_at"] = _iso(moment)
    request["declined_by"] = approval.approver
    request["decline_note"] = str(note)
    store.put(request)
    row = {"schema": RECEIPT_SCHEMA, "event": "declined", "at": request["declined_at"], "request_id": request_id,
           "approver": approval.approver, "note": str(note)}
    _append_jsonl(store.ledger, row)
    _append_jsonl(store.digest, row)
    return request


def expire_due(store: Store, *, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Mark open requests whose deadline passed as needs_reask. Never approves anything."""
    moment = now or datetime.now(timezone.utc)
    changed = []
    for request in store.all():
        if request.get("status") != "open":
            continue
        try:
            if moment < _parse(str(request["expires_at"])):
                continue
        except (KeyError, TypeError, ValueError):
            pass
        request["status"] = "needs_reask"
        request["reask_reason"] = "expired"
        store.put(request)
        _append_jsonl(store.ledger, {"event": "expired", "at": _iso(moment), "request_id": request["request_id"]})
        changed.append(request)
    return changed


def open_requests(store: Store, *, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    moment = now or datetime.now(timezone.utc)
    rows = []
    for request in store.all():
        if request.get("status") != "open":
            continue
        with contextlib.suppress(KeyError, TypeError, ValueError):
            if moment >= _parse(str(request["expires_at"])):
                continue
        rows.append(request)
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return rows


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _store(args: argparse.Namespace) -> Store:
    root = args.state_root or os.environ.get("TRADEAI_STATE_ROOT")
    if not root:
        raise SystemExit("needs_you: --state-root (or TRADEAI_STATE_ROOT) is required; this module never writes to /tmp")
    return Store(Path(root))


def _print(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=1, sort_keys=True, default=str))
    elif isinstance(payload, list):
        for row in payload:
            print(f"{row.get('request_id')}  {row.get('action_type'):<16} {row.get('status'):<11} {row.get('title','')}")
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
    ask.add_argument("--type", required=True, dest="action_type", choices=sorted(ACTION_TYPES))
    ask.add_argument("--title", required=True)
    ask.add_argument("--why", required=True)
    ask.add_argument("--approve-does", required=True)
    ask.add_argument("--risk", default="")
    ask.add_argument("--undo", default="")
    ask.add_argument("--requester", required=True, help="the asking session, e.g. cc-deepseek-5")
    ask.add_argument("--actor", default="", help="the asking identity (defaults to --requester)")
    ask.add_argument("--vendor", default="")
    ask.add_argument("--facts", default="{}", help="JSON object of the exact bound facts")
    ask.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)

    listing = sub.add_parser("list", help="open requests")
    listing.add_argument("--all", action="store_true")

    show = sub.add_parser("show")
    show.add_argument("request_id")

    for name in ("approve", "decline"):
        command = sub.add_parser(name)
        command.add_argument("request_id")
        command.add_argument("--approver", required=True)
        command.add_argument("--session", default="")
        command.add_argument("--note", default="")
        command.add_argument("--operator-session", action="store_true",
                             help="set by the Command Center server from a verified operator session")
        command.add_argument("--csrf-ok", action="store_true",
                             help="set by the Command Center server after the same-origin check")

    sub.add_parser("expire", help="mark due requests needs_reask (never approves)")

    args = parser.parse_args(argv)
    store = _store(args)
    try:
        if args.cmd == "ask":
            facts = json.loads(args.facts)
            if not isinstance(facts, dict):
                raise Refused("facts_invalid", "The bound facts must be a JSON object.")
            request = create_request(
                store,
                action_type=args.action_type,
                title=args.title,
                why=args.why,
                approve_does=args.approve_does,
                risk=args.risk,
                undo=args.undo,
                requester={"actor": args.actor or args.requester,
                           "session": args.requester, "vendor": args.vendor},
                facts=facts,
                ttl_hours=args.ttl_hours,
            )
            _print(request, as_json=args.json)
            return 0
        if args.cmd == "list":
            rows = store.all() if args.all else open_requests(store)
            _print(rows, as_json=args.json)
            return 0
        if args.cmd == "show":
            _print(store.get(args.request_id), as_json=args.json)
            return 0
        if args.cmd == "expire":
            _print(expire_due(store), as_json=args.json)
            return 0
        approval = Approval(approver=args.approver, operator_session=args.operator_session,
                            csrf_ok=args.csrf_ok, session=args.session)
        if args.cmd == "approve":
            _print(approve(store, args.request_id, approval), as_json=args.json)
        else:
            _print(decline(store, args.request_id, approval, note=args.note), as_json=args.json)
        return 0
    except Refused as exc:
        print(json.dumps({"ok": False, "code": exc.code, "plain": exc.plain}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
