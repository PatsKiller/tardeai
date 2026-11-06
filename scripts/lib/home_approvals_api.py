"""Home v008 "Needs you" approvals — HTTP layer (piece B).

This module does exactly three things: authenticate the HTTP request, call the store's single
decision entry (``scripts/lib/home_approvals.py::decide``), and shape the response. It never
executes an action, never writes a receipt, and never decides anything itself.

Design of record: ``persistent-state/handoffs/DESIGN_HOME_V008_APPROVALS_A_B_BOUNDARY_20261103.md``
(lead-ratified 2026-11-03).

Trust rails, all enforced in A's ``decide()`` and re-checked here at the HTTP edge:
  1. a decision counts only from the operator's logged-in Command Center session (``tailnet:<login>``
     principal, ``serve_proxy`` listener, login in ``cc_auth`` allowed_logins) plus same-origin CSRF;
  2. requester != approver;
  3. every bound fact is revalidated at execution time and a moved fact refuses with a plain reason.

No route here accepts a free-text command, an action type, or a fact override from the body: the only
writable inputs are the request id in the path, the note, and the decision verb.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

PREFIX = "/api/v2/home/approvals"
QUEUE_SCHEMA = "HomeApprovalsQueue@v1"

#: A complete read of the live open set. A's ``list_open()`` pages at 100 by default; totals and the
#: queue's reachability must never inherit that page size (codex-cloud CX2, PR 2551).
COMPLETE_READ_LIMIT = 2 ** 31 - 1

#: The queue's own page. A caller may ask for another page, but never beyond ``MAX_PAGE``.
DEFAULT_PAGE = 100
MAX_PAGE = 500

#: Status + code for every refusal this layer can produce. A's refusals are mapped onto the same set.
REFUSALS = {
    "NOT_OPERATOR": 403,
    "AGENT_CALLER_REFUSED": 403,
    "CSRF_REFUSED": 403,
    "SELF_APPROVAL_REFUSED": 403,
    "NOT_FOUND": 404,
    "NOT_OPEN": 409,
    "CHANGED": 409,
    "EXPIRED": 410,
    "EXECUTOR_TIMEOUT": 504,
    "STORE_UNAVAILABLE": 503,
    "STORE_ERROR": 500,
    "BAD_REQUEST": 400,
    "DECISION_IN_PROGRESS": 409,
    "ALREADY_EXECUTING": 409,
    "RECORD_NOT_APPROVED": 409,
}

#: A's refusal codes -> this layer's HTTP codes. A owns the decision; B only translates.
STORE_CODES = {
    "actor_not_authenticated": "NOT_OPERATOR",
    "card_changed": "CHANGED",
    "no_recorded_approval": "RECORD_NOT_APPROVED",
    "binding_mismatch": "CHANGED",
    "decision_in_progress": "DECISION_IN_PROGRESS",
    "already_executing": "ALREADY_EXECUTING",
    "duplicate_request_id": "NOT_OPEN",
    "approver_is_requester": "SELF_APPROVAL_REFUSED",
    "csrf_required": "CSRF_REFUSED",
    "operator_session_required": "NOT_OPERATOR",
    "server_context_required": "NOT_OPERATOR",
    "facts_moved": "CHANGED",
    "request_expired": "EXPIRED",
    "unknown_request": "NOT_FOUND",
    "not_open": "NOT_OPEN",
    "not_approved": "NOT_OPEN",
    "store_unreadable": "STORE_ERROR",
    "facts_invalid": "BAD_REQUEST",
    "unknown_action_type": "BAD_REQUEST",
    "unknown_decision": "BAD_REQUEST",
    "invalid_request_id": "BAD_REQUEST",
    "question_empty": "BAD_REQUEST",
    "requester_unknown": "BAD_REQUEST",
    "no_executor": "STORE_ERROR",
}

DECISION_VERBS = {"approve": "approve", "decline": "decline"}


@dataclass
class Ctx:
    """The subset of the server gate this layer needs (mirrors operator_approvals_api.Ctx)."""

    principal: Callable[[], Optional[str]]
    listener: Callable[[], Optional[str]]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: Iterable[str]
    can_read: Callable[[], bool]
    clock: Callable[[], Any]
    session: Callable[[], str] = lambda: ""


def _refused(code: str, reason: str) -> tuple[int, dict]:
    return REFUSALS.get(code, 500), {"ok": False, "code": code, "reason": reason}


def _operator(ctx: Ctx) -> Optional[str]:
    """The operator's logged-in Command Center session, or None.

    Same rule as the existing Approve/Hold/Push routes (operator_approvals_api._operator): a tailnet
    identity, arriving through the serve proxy, whose login is allowed. An agent principal can never
    satisfy this, which is why an agent cannot approve even if it could reach the route.
    """
    actor = ctx.principal() or ""
    allowed = {str(login).strip().lower() for login in (ctx.allowed_logins or ())}
    if actor.startswith("tailnet:") and ctx.listener() == "serve_proxy" and actor[8:].strip().lower() in allowed:
        return actor
    return None


def default_ctx() -> Ctx:
    from lib import cc_auth  # type: ignore  # the server gate's own module object/thread-local

    cfg = cc_auth.load_config()

    def _clock():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    return Ctx(
        principal=cc_auth.current_principal,
        listener=lambda: (cc_auth.current_request_context() or {}).get("listener"),
        csrf=lambda method, path: cc_auth.command_csrf_check(cfg, method, path),
        allowed_logins=cfg.allowed_logins,
        can_read=lambda: cc_auth.current_principal() == "service-token",
        clock=_clock,
        session=lambda: str((cc_auth.current_request_context() or {}).get("session") or ""),
    )


def _store_module():
    """A's module, imported lazily so this file has no import-time dependency on the store."""
    from lib import home_approvals  # type: ignore  # noqa: PLC0415

    return home_approvals


def _store_handle(module):
    """The store A operates on. The state root is the persistent-state root, never a checkout path."""
    import os
    from pathlib import Path

    root = os.environ.get("TRADEAI_STATE_ROOT") or os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    if root:
        return module.Store(Path(root))
    try:
        from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415

        return module.Store(Path(good_persistent_root()))
    except Exception:  # noqa: BLE001 — no resolvable root is an unavailable store, never an empty board
        raise module.Refused("store_unreadable", "The persistent-state root could not be resolved, so approvals cannot be read.")


def _item(record: dict, now) -> dict:
    """One card item: the record plus the derived fields the UI must not compute for itself."""
    out = dict(record)
    state = str(record.get("state") or "")
    expires = _parse(record.get("expires_at"))
    created = _parse(record.get("created_at"))
    expired = state == "expired" or (state == "open" and expires is not None and expires <= now)
    out["state"] = "expired" if expired else state
    out["age_seconds"] = int((now - created).total_seconds()) if created is not None else None
    out["expires_in_seconds"] = int((expires - now).total_seconds()) if expires is not None else None
    open_ = out["state"] == "open" and not expired
    out["can_act"] = bool(open_ and not record.get("blocked_reason"))
    out["blocked_reason"] = record.get("blocked_reason")
    out.setdefault("question", None)
    out["reask_requested"] = bool(expired and record.get("reask_requested"))
    out.setdefault("result", None)
    out.setdefault("decided_at", (record.get("decision") or {}).get("at") if isinstance(record.get("decision"), dict) else None)
    return out


def _parse(value) -> Optional[Any]:
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _open_records(module, store, now) -> list[dict]:
    """Every live open request, not A's default page of 100 (codex-cloud CX2, PR 2551).

    A's ``list_open()`` slices to ``limit`` (100 unless told otherwise). Both the badge and the queue
    need the complete live set: the badge so old-but-urgent requests are counted, the queue so a
    caller can page to the requests past the first hundred.
    """
    return module.list_open(store, now=now, limit=COMPLETE_READ_LIMIT) or []


def _page_number(value, *, default: int, minimum: int, maximum: int) -> int:
    """A query-string page bound, clamped rather than trusted. A bad value falls back to the default."""
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _queue(module, store, now, query=None) -> tuple[int, dict]:
    records = _open_records(module, store, now)
    limit = DEFAULT_PAGE
    offset = 0
    if isinstance(query, dict):
        limit = _page_number(query.get("limit"), default=DEFAULT_PAGE, minimum=1, maximum=MAX_PAGE)
        offset = _page_number(query.get("offset"), default=0, minimum=0, maximum=COMPLETE_READ_LIMIT)
    page = records[offset:offset + limit]
    items = [_item(record, now) for record in page]
    return 200, {
        "ok": True,
        "data": {
            "schema": QUEUE_SCHEMA,
            "as_of": now.isoformat().replace("+00:00", "Z"),
            # ``count`` is this response's rows (unchanged contract); ``total`` is the complete live
            # set, so a caller can tell that a page is not the whole board.
            "count": len(items),
            "total": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < len(records),
            "empty_text": "Nothing needs you",
            "items": items,
        },
    }


def _summary(module, store, now) -> tuple[int, dict]:
    records = _open_records(module, store, now)
    urgent = 0
    for record in records:
        expires = _parse(record.get("expires_at"))
        if expires is not None and (expires - now).total_seconds() <= 2 * 3600:
            urgent += 1
    return 200, {
        "ok": True,
        "data": {
            "count": len(records),
            "urgent_count": urgent,
            "as_of": now.isoformat().replace("+00:00", "Z"),
        },
    }


def _one(module, store, request_id: str, now, query) -> tuple[int, dict]:
    """One request for the confirm sheet. ``?revalidate=1`` runs A's single read-only fact check.

    No list route revalidates: a dashboard render must not fan out to one network check per item. The
    confirm sheet asks for one item, so it may pay for one check and show the operator the exact
    sentence a click would have produced.
    """
    record = module.get(store, request_id)
    if record is None:
        return _refused("NOT_FOUND", "That request does not exist.")
    item = _item(record, now)
    binding_of = getattr(module, "_binding_of", None)
    if callable(binding_of):
        try:
            item["binding"] = binding_of(record)
        except Exception:  # noqa: BLE001 — a binding helper failure must not break the sheet
            item["binding"] = None
    wants = isinstance(query, dict) and str(query.get("revalidate") or "").lower() in ("1", "true", "yes")
    if wants:
        ok, plain = module.revalidate(store, record, now=now)
        item["revalidated"] = True
        if not ok:
            item["can_act"] = False
            item["blocked_reason"] = str(plain)
    return 200, {"ok": True, "data": item}


def _deliver_question(request_id: str, actor: str, note: str, now) -> bool:
    """Hand the operator's note to the lead. A never messages anyone; delivery is B's job."""
    import os
    from pathlib import Path

    # The default is the same host path, resolved from the running user's home rather than written as a literal.
    root = os.environ.get("TRADEAI_COORDINATION_ROOT") or str(
        Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "coordination")
    inbox = Path(root) / "coordinator" / "inbox" / "cc-deepseek-7"
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        path = inbox / f"{stamp}-cc-deepseek-2-v008-question-{request_id}.md"
        path.write_text(
            f"# Operator question on approval request `{request_id}`\n\n"
            f"**From:** {actor} (operator, via Home v008) · **At:** {now.isoformat()}\n\n{note}\n",
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _decision_response(record: dict) -> tuple[int, dict]:
    """A decision is three different facts, never one 200 (codex safety review, 2026-11-03).

    - executed / declined: the action is confirmed — 200, ok:true, outcome named.
    - failed: the server answered but the action did not happen — ok:false, code ACTION_FAILED,
      the store's own plain sentence, and the record so the card can show what was attempted.
      Returning 200/ok:true here would let a refused or failed action read as done downstream.
    - approved / executing: not confirmed either way — 202, ok:true, outcome "uncertain", with the
      state so the card says "result pending" rather than "done".
    """
    record = record if isinstance(record, dict) else {}
    state = str(record.get("state") or "")
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    reported = str(result.get("outcome") or "")
    if reported == "timed_out_unconfirmed":
        outcome = "uncertain"
    elif reported in ("executed", "declined", "failed", "unknown_result"):
        outcome = reported
    elif state == "executed":
        outcome = "executed"
    elif state == "declined":
        outcome = "declined"
    elif state == "failed" or result.get("ok") is False:
        outcome = "failed"
    else:
        outcome = "uncertain"
    if outcome == "unknown_result":
        outcome = "uncertain"
    data = {"state": state, "outcome": outcome, "decision": record.get("decision"),
            "message": record.get("message"), "result": record.get("result"),
            "receipt": record.get("receipt"), "attempted": result.get("attempted")}
    if outcome == "failed":
        return 502, {"ok": False, "code": "ACTION_FAILED",
                     "reason": str(result.get("plain") or record.get("message") or "The action did not complete."),
                     "data": data}
    if outcome == "uncertain":
        return 202, {"ok": True, "data": data}
    return 200, {"ok": True, "data": data}


def _store_error(exc: Exception) -> tuple[int, dict]:
    mapped = STORE_CODES.get(str(getattr(exc, "code", "") or ""))
    if mapped:
        # A's Refused carries `.plain` — the sentence the card shows verbatim. Never reword it here.
        plain = getattr(exc, "plain", None) or getattr(exc, "reason", None) or mapped
        status, payload = _refused(mapped, str(plain))
        attempted = getattr(exc, "attempted", None)
        if attempted:
            payload["attempted"] = attempted
        if mapped == "CHANGED":
            # The card disables the buttons from this field after a moved fact; the record stays open.
            payload["blocked_reason"] = str(plain)
            payload["state"] = "open"
        elif mapped == "EXPIRED":
            payload["state"] = "expired"
            payload["reask_requested"] = True
        return status, payload
    return _refused("STORE_ERROR", f"The approval store could not complete that ({type(exc).__name__}).")


def handle(path: str, method: str, body=None, query=None, *, ctx: Optional[Ctx] = None):
    base = (path or "").split("?", 1)[0].rstrip("/")
    if not (base == PREFIX or base.startswith(PREFIX + "/")):
        return None
    ctx = ctx or default_ctx()
    method = (method or "GET").upper()
    sub = base[len(PREFIX):]

    if method == "GET":
        actor = _operator(ctx)
        if actor is None and not ctx.can_read():
            return _refused("AGENT_CALLER_REFUSED", "Sign in to the Command Center to read approvals.")
        if sub not in ("", "/summary") and not (sub.count("/") == 1 and len(sub) > 1):
            return _refused("NOT_FOUND", "No such approvals route.")
        try:
            module = _store_module()
            store = _store_handle(module)
            now = ctx.clock()
            if sub == "/summary":
                return _summary(module, store, now)
            if sub in ("", "/"):
                return _queue(module, store, now, query)
            return _one(module, store, sub.lstrip("/"), now, query)
        except Exception as exc:  # noqa: BLE001 — an unreadable store is never an empty list
            return _store_error(exc)

    if method != "POST":
        return 405, {"ok": False, "code": "METHOD_NOT_ALLOWED", "reason": "Approvals accept GET and POST only."}

    parts = [part for part in sub.split("/") if part]
    if len(parts) != 2:
        return _refused("NOT_FOUND", "No such approvals route.")
    request_id, verb = parts
    if verb not in ("approve", "decline", "question"):
        return _refused("NOT_FOUND", "No such approvals route.")

    actor = _operator(ctx)
    if actor is None:
        return _refused("AGENT_CALLER_REFUSED", "Only the operator's signed-in Command Center session can decide a request.")
    csrf_ok, why = ctx.csrf("POST", base)
    if not csrf_ok:
        return _refused("CSRF_REFUSED", why or "The request did not come from the Command Center page.")

    note = ""
    expected_binding = None
    if isinstance(body, dict):
        note = str(body.get("note") or "")[:2000]
        expected_binding = str(body.get("binding") or "").strip() or None
    # A decision is only meaningful against the card the operator was shown. If the confirm sheet's
    # binding is missing or blank, A's decide() treats it as "no expectation" and a request edited
    # between render and click would be decided silently (codex-cloud CX1, PR 2551; AGENTS §25.10.3).
    # Refuse here, before the store is touched. Asking a question is not a decision and needs none.
    if verb in DECISION_VERBS and not expected_binding:
        return _refused("BAD_REQUEST",
                        "Reload Home and decide again: this decision must name the card you were shown.")
    login = actor[8:] if actor.startswith("tailnet:") else actor

    try:
        module = _store_module()
        store = _store_handle(module)
        now = ctx.clock()
        # The ONLY source of this context is this route: the principal and listener were verified just above,
        # CSRF was checked just above, and none of it is ever read from the request body.
        operator_ctx = module.server_context(
            principal=actor, session=ctx.session(), csrf_ok=True, listener=ctx.listener() or "",
        )
        if verb == "question":
            record = module.question(store, request_id, actor=login, note=note, now=now)
            delivered = _deliver_question(request_id, actor, note, now)
            return 200, {"ok": True, "data": {
                "state": (record or {}).get("state"),
                "note_recorded": True,
                "delivered": delivered,
                "question": {"at": now.isoformat(), "by": actor, "note": note},
            }}
        record = module.decide(
            store, request_id, ctx=operator_ctx, actor=login, decision=DECISION_VERBS[verb], note=note, now=now,
            expected_binding=expected_binding,
        )
        return _decision_response(record)
    except Exception as exc:  # noqa: BLE001 — A's typed refusal is the contract
        return _store_error(exc)


__all__ = ["PREFIX", "QUEUE_SCHEMA", "REFUSALS", "STORE_CODES", "Ctx", "default_ctx", "handle"]
