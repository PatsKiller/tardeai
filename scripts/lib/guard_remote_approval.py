"""guard_remote_approval.py — operator approves a guard scope from Telegram.

THE PROBLEM THIS SOLVES
-----------------------
`bin/guard grant` asks the operator to type APPROVE at an interactive terminal.
That is the right shape when they are at the machine, and useless when they are
not: work that is finished, verified and green then waits hours for someone to
walk to a keyboard.

This moves the *typing* to Telegram. It does not move the *deciding* anywhere.

WHAT IS AND IS NOT WEAKENED
---------------------------
The standing rule is that the agent must never type, pipe, simulate, automate or
infer APPROVE. That rule is intact, and this module is built so the agent cannot
route around it:

  * `mint_request()` creates a PENDING record and nothing else. It grants no
    authority. An agent may call it freely.
  * The one-time code is sent to Telegram and **only a SHA-256 of it is stored**.
    `mint_request` returns the code to its immediate caller so `bin/guard
    request` can send it, and that caller must not print or persist it.
  * Converting PENDING -> APPROVED requires a real Telegram message, from a chat
    on the existing allowlist, carrying that code. The operator types the
    approval, on their own device, against a described scope and duration.
  * The approval is bound to the scope, window and uses that were *requested*.
    An agent cannot widen a grant after the fact, because the numbers are fixed
    in the pending record the operator saw before replying.

HONEST LIMITATION, STATED PLAINLY
---------------------------------
The agent runs as the same OS user as this code. Nothing here is a sandbox: an
agent determined to defeat it could call `bin/guard grant --yes` directly, or
read the code out of its own process. This mechanism is **auditable, not
impregnable**. What it guarantees is that every legitimately-obtained grant
carries Telegram provenance — chat id, message id, update id, and the operator's
own words — so a grant that appeared *without* either an interactive terminal or
that provenance is a detectable anomaly. `unprovenanced_grants()` finds them.

Do not weaken this to "the agent asked and nobody objected". Silence is not
approval, an expired request is not approval, and a reply from an unlisted chat
is not approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = "GuardRemoteApproval@v1"

#: How long the operator has to answer before a request goes stale.
#:
#: Was 900s. Fifteen minutes is the right number for someone at their desk and
#: the wrong one for every other case: on 2026-09-06 a request for work the
#: operator had explicitly asked for expired unanswered overnight, and the window
#: length was never the constraint — the ANSWER DEADLINE was. A request nobody
#: can reach in time is not a control, it is a dropped message.
#:
#: The countervailing risk is real: an outstanding code is a bearer secret, and a
#: longer TTL means a longer theft window. What bounds it is not the clock — it is
#: that settling requires a reply from a chat on TELEGRAM_CHAT_ID, the code is
#: stored only as SHA-256, it works exactly once, and REMOTE_FORBIDDEN_SCOPES
#: still refuses the scopes that matter.
DEFAULT_REQUEST_TTL_SECONDS = int(
    os.environ.get("GUARD_REMOTE_REQUEST_TTL_SECONDS", "14400"))   # 4 hours

#: Ceiling on the answer deadline. A request may not outlive the longest window
#: it could grant.
MAX_REQUEST_TTL_SECONDS = int(
    os.environ.get("GUARD_REMOTE_MAX_REQUEST_TTL_SECONDS", "43200"))  # 12 hours

#: A grant window this mechanism will never exceed, whatever is asked for.
#:
#: Raised from 3600 to 43200 on 2026-09-06 at the operator's explicit direction,
#: so an overnight or full-day autonomous run can be authorised from a phone
#: instead of requiring a keyboard the operator is not at.
#:
#: This is a real widening and it is recorded as one. A stolen or misdelivered
#: code now buys twelve hours rather than one. The rails that make that
#: acceptable are unchanged and MUST STAY unchanged:
#:   · REMOTE_FORBIDDEN_SCOPES still refuses sudo, destructive, file-delete,
#:     frozen-v2 and — critically — guard-config, so a phone still cannot widen
#:     what a phone may do. Raising THIS constant required a keyboard.
#:   · The grant is bound to the scope, window and uses the operator saw.
#:   · A reply from an unlisted chat burns the code.
MAX_GRANT_SECONDS = int(
    os.environ.get("GUARD_REMOTE_MAX_GRANT_SECONDS", "43200"))     # 12 hours

#: Uses a remote grant may carry. Previously UNBOUNDED — `int(uses)` with no
#: check — which mattered little against a one-hour window and matters a great
#: deal against twelve. Generous enough for a long autonomous run (500 over 12h
#: is ~40/hour) while still being a number rather than infinity.
MAX_GRANT_USES = int(os.environ.get("GUARD_REMOTE_MAX_GRANT_USES", "500"))

#: Scopes that may NEVER be granted remotely, regardless of what is requested.
#: These either move money, change who can approve, or destroy things. A phone
#: is the wrong place to reason about them.
REMOTE_FORBIDDEN_SCOPES: frozenset[str] = frozenset({
    "sudo",            # root
    "destructive",     # irreversible
    "file-delete",     # irreversible
    "guard-config",    # would let a remote approval widen remote approval
    "frozen-v2",       # frozen by explicit operator decision
})


def approvals_dir() -> Path:
    return Path(os.environ.get("GUARD_APPROVALS_DIR", str(Path.home() / ".cursor" / "approvals")))


def requests_path() -> Path:
    return approvals_dir() / "remote_requests.json"


def _now() -> int:
    return int(time.time())


def code_fingerprint(code: str) -> str:
    """SHA-256 of the code. The plaintext is never written to disk."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def _load() -> dict[str, Any]:
    p = requests_path()
    if not p.is_file():
        return {"schema": SCHEMA, "requests": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # A corrupt request store must not grant anything and must not be
        # silently rebuilt as empty — that would erase evidence. Callers get an
        # empty view, and the file is left alone for `bin/guard doctor`.
        return {"schema": SCHEMA, "requests": [], "corrupt": True}
    if not isinstance(doc, dict):
        return {"schema": SCHEMA, "requests": [], "corrupt": True}
    doc.setdefault("requests", [])
    if not isinstance(doc["requests"], list):
        return {"schema": SCHEMA, "requests": [], "corrupt": True}
    doc["requests"] = [normalize_request(r) for r in doc["requests"] if isinstance(r, dict)]
    return doc


# ── field normalization (2026-10-21) ─────────────────────────────────────────
# This store wrote `scope` and `request_id`; the guard ledger, release_grant_binding
# and release_grant_preflight read `tier` (and some readers `id`). Measured on the
# live store 2026-10-21: 200 of 200 rows carried `scope` and `request_id`, 0 carried
# `tier` or `id`, so `release_grant_binding.pending_requests_for` (which filtered on
# `tier`) could never see a pending release-write request. Rows are now written with
# BOTH `scope` and `tier`, and every reader goes through normalize_request(): the
# fields are copied, never renamed (old readers keep `scope`/`request_id`). A row whose
# `scope` and `tier` DISAGREE is unusable: it matches nothing and is refused on settle.

def normalize_request(r: dict[str, Any]) -> dict[str, Any]:
    """Additive in place: scope<->tier and request_id<-id. Returns the same dict."""
    scope, tier = r.get("scope"), r.get("tier")
    if scope is not None and tier is not None and str(scope).strip() != str(tier).strip():
        r["scope_conflict"] = True
    elif scope is not None or tier is not None:
        value = str(scope if scope is not None else tier).strip()
        r["scope"] = value
        r["tier"] = value
    if not r.get("request_id") and r.get("id"):
        r["request_id"] = str(r["id"])
    return r


def request_scope(r: dict[str, Any]) -> Optional[str]:
    """The request's one scope, or None when it has none or `scope` and `tier` disagree."""
    if r.get("scope_conflict"):
        return None
    value = r.get("scope") if r.get("scope") is not None else r.get("tier")
    return str(value).strip() if value is not None and str(value).strip() else None


def request_id_of(r: dict[str, Any]) -> str:
    return str(r.get("request_id") or r.get("id") or "").strip()


def _rrid_from_reason(reason: str) -> Optional[str]:
    """The callback paths append "[remote_request_id=<id> ...]" to the grant reason."""
    import re
    m = re.search(r"\[remote_request_id=([0-9A-Za-z_-]{4,64})\b", reason or "")
    return m.group(1) if m else None


#: Rows the store keeps inline; older rows move to the archive file, never dropped (AGENTS.md §0 rule 6).
MAX_INLINE_REQUESTS = 200


def archive_path() -> Path:
    return approvals_dir() / "remote_requests.archive.jsonl"


def _archive_overflow(doc: dict[str, Any]) -> None:
    """Move rows beyond MAX_INLINE_REQUESTS to the append-only archive before trimming."""
    overflow = doc["requests"][:-MAX_INLINE_REQUESTS] if len(doc["requests"]) > MAX_INLINE_REQUESTS else []
    if not overflow:
        return
    ap = archive_path()
    ap.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(ap), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        for r in overflow:
            os.write(fd, (json.dumps(r, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    doc["requests"] = doc["requests"][-MAX_INLINE_REQUESTS:]


def _save(doc: dict[str, Any]) -> None:
    p = requests_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(tmp, p)          # atomic
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def mint_code() -> str:
    """A short, unambiguous, single-use code.

    Alphabet excludes O/0 and I/1: this gets read off a phone screen and typed
    back by a human, and a code that is easy to mistype is a code that gets
    retried, which is how a one-shot secret becomes a repeated one.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def mint_request(scope: str, *, seconds: int, uses: int, reason: str,
                 ttl: int = DEFAULT_REQUEST_TTL_SECONDS) -> dict[str, Any]:
    """Create a PENDING approval request. Grants nothing.

    Returns the record plus the plaintext `code`, which the caller must send to
    Telegram and must not print or persist.
    """
    scope = str(scope).strip()
    if scope in REMOTE_FORBIDDEN_SCOPES:
        raise ValueError(
            f"scope '{scope}' may never be approved remotely — approve it at the keyboard")
    seconds = int(seconds)
    if seconds <= 0:
        raise ValueError("grant window must be positive")
    uses = int(uses)
    if uses <= 0:
        raise ValueError("grant uses must be positive")
    if uses > MAX_GRANT_USES:
        raise ValueError(
            f"requested {uses} uses exceeds the remote maximum {MAX_GRANT_USES} — "
            "approve an unbounded grant at the keyboard")
    ttl = int(ttl)
    if ttl <= 0:
        raise ValueError("answer deadline must be positive")
    if ttl > MAX_REQUEST_TTL_SECONDS:
        raise ValueError(
            f"answer deadline {ttl}s exceeds the remote maximum "
            f"{MAX_REQUEST_TTL_SECONDS}s")
    if seconds > MAX_GRANT_SECONDS:
        raise ValueError(
            f"requested window {seconds}s exceeds the remote maximum "
            f"{MAX_GRANT_SECONDS}s — approve a longer window at the keyboard")

    code = mint_code()
    now = _now()
    rec: dict[str, Any] = {
        "request_id": secrets.token_hex(8),
        "scope": scope,
        "tier": scope,          # same value; the ledger and release binding read `tier`
        "seconds": seconds,
        "uses": uses,
        "reason": str(reason),
        "code_sha256": code_fingerprint(code),
        "created_at": now,
        "expires_at": now + ttl,
        "status": "PENDING",
    }
    doc = _load()
    if doc.get("corrupt"):
        raise RuntimeError("remote request store is corrupt — refusing to mint")
    # Supersede any other pending request for the same scope: two live codes for
    # one scope means an operator cannot tell which they are approving.
    for r in doc["requests"]:
        if r.get("status") != "PENDING":
            continue
        if request_scope(r) == scope or (r.get("scope_conflict") and scope in (r.get("scope"), r.get("tier"))):
            r["status"] = "SUPERSEDED"
            r["superseded_by"] = rec["request_id"]
    doc["requests"].append(rec)
    _archive_overflow(doc)
    _save(doc)
    return {**rec, "code": code}


def find_pending(code: str) -> Optional[dict[str, Any]]:
    fp = code_fingerprint(code)
    for r in _load()["requests"]:
        if r.get("status") == "PENDING" and r.get("code_sha256") == fp:
            return r
    return None


# ── one active grant per tier: a remote approval never replaces (operator 2026-10-21) ──────────
# `bin/guard grant` refuses a second active grant of a tier unless --replace is given, and
# --replace is a keyboard decision. A Telegram approval for a tier that already has an active
# grant is therefore REFUSED before the request is settled: the request stays PENDING (the code
# or button still works once the operator revokes or replaces at the machine), and the reply
# names the active grant and the exact CLI that would replace it.

GUARD_BIN = Path(__file__).resolve().parents[2] / "bin" / "guard"


def _guard_ledger_module():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / ".cursor" / "hooks" / "guard_ledger.py"
    spec = importlib.util.spec_from_file_location("_gra_guard_ledger", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def active_grant_for(scope: str) -> Optional[dict[str, Any]]:
    """The tier's active grant (or its ambiguous active ids), read-only; None when there is none."""
    try:
        listed = _guard_ledger_module().ledger_list(approvals_dir())
    except Exception:
        return None  # an unreadable ledger is reported by the grant path itself, which refuses
    if scope in (listed.get("ambiguous") or []):
        return {"tier": scope, "ambiguous": True, "grant_id": "", "uses": 0, "expires": 0,
                "reason": (listed.get("grants") or {}).get(scope, {}).get("reason", "")}
    rec = (listed.get("active") or {}).get(scope)
    if not isinstance(rec, dict):
        return None
    return {"tier": scope, "grant_id": str(rec.get("grant_id") or ""), "uses": int(rec.get("uses") or 0),
            "expires": int(rec.get("expires") or 0), "reason": str(rec.get("reason") or "")}


def active_grant_refusal_text(rec: dict[str, Any], active: dict[str, Any], *, chat_id: Any = "",
                              via: str = "", now: Optional[int] = None) -> str:
    """Operator-facing reply: which grant blocks the approval, and the exact command that replaces it."""
    import shlex
    from datetime import datetime
    now = _now() if now is None else now
    tier = active["tier"]
    reason = f"{rec.get('reason') or ''} [remote_request_id={request_id_of(rec)} chat={chat_id}" \
             f"{' via=' + via if via else ''}]"
    cmd = (f"{GUARD_BIN} grant {shlex.quote(tier)} --for {int(rec.get('seconds') or 0)} "
           f"--uses {int(rec.get('uses') or 0)} --reason {shlex.quote(reason)} --replace")
    if active.get("ambiguous"):
        head = (f"⛔ Not granted: `{tier}` has MORE THAN ONE active grant (ambiguous; nothing is consumed "
                f"from it). Run `{GUARD_BIN} doctor` and revoke all but one with "
                f"`{GUARD_BIN} revoke {tier} --grant-id <id>`.")
    else:
        exp = int(active.get("expires") or 0)
        left_min = max(0, (exp - now) // 60)
        uses = int(active.get("uses") or 0)
        head = (f"⛔ Not granted: an active `{tier}` grant already exists.\n"
                f"  id: {active.get('grant_id')}\n"
                f"  uses left: {'unlimited' if uses < 0 else uses}\n"
                f"  expires: {datetime.fromtimestamp(exp).astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
                f"({left_min} min left)\n"
                f"A remote approval never replaces a grant. Request {request_id_of(rec)} stays PENDING; "
                f"approve it again after revoking (`{GUARD_BIN} revoke {tier} --grant-id {active.get('grant_id')}`).")
    return f"{head}\nTo replace it now, at the machine:\n`{cmd}`"


def _refuse_if_active_grant(doc: dict[str, Any], rec: dict[str, Any], *, chat_id: Any,
                            via: str = "") -> Optional[dict[str, Any]]:
    scope = request_scope(rec) or ""
    active = active_grant_for(scope)
    if not active:
        return None
    rec["last_refusal"] = {"reason": "ACTIVE_GRANT_EXISTS", "at": _now(),
                           "active_grant_id": active.get("grant_id") or "", "ambiguous": bool(active.get("ambiguous"))}
    _save(doc)  # the request stays PENDING; only the refusal is recorded
    return {"ok": False, "reason": "ACTIVE_GRANT_EXISTS", "active_grant": active, "request": rec,
            "message": active_grant_refusal_text(rec, active, chat_id=chat_id, via=via)}


def verify_and_consume(code: str, *, chat_id: Any, allowed_chats: Any,
                       telegram: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Turn a Telegram reply into an authorised grant instruction.

    Returns ``{"ok": True, "request": {...}}`` when the code is good, or
    ``{"ok": False, "reason": "..."}``. **Never raises for a bad code** — a
    refusal is a normal outcome and must be reportable back to the chat.

    The code is consumed on success AND on a chat-rejection: a code that leaked
    to the wrong chat is burnt, not left live for a second attempt.
    """
    allowed = {str(c).strip() for c in (allowed_chats or set()) if str(c).strip()}
    chat = str(chat_id).strip()

    doc = _load()
    if doc.get("corrupt"):
        return {"ok": False, "reason": "REQUEST_STORE_CORRUPT"}

    fp = code_fingerprint(code)
    rec = None
    for r in doc["requests"]:
        if r.get("code_sha256") == fp:
            rec = r
            break
    if rec is None:
        return {"ok": False, "reason": "UNKNOWN_CODE"}
    if rec.get("status") != "PENDING":
        return {"ok": False, "reason": f"CODE_ALREADY_{rec.get('status')}"}

    if not allowed:
        # No allowlist configured means we cannot tell who is speaking. Deny.
        rec["status"] = "DENIED_NO_ALLOWLIST"
        _save(doc)
        return {"ok": False, "reason": "NO_CHAT_ALLOWLIST_CONFIGURED"}
    if chat not in allowed:
        rec["status"] = "DENIED_WRONG_CHAT"
        rec["denied_chat"] = chat
        _save(doc)
        return {"ok": False, "reason": "CHAT_NOT_ALLOWED"}

    # `>=`, not `>`: timestamps here are whole seconds, so at the expiry instant
    # the two are equal and `>` would still admit the code. For a control whose
    # job is to refuse, the boundary belongs on the refusing side.
    if _now() >= int(rec.get("expires_at", 0)):
        rec["status"] = "EXPIRED"
        _save(doc)
        return {"ok": False, "reason": "CODE_EXPIRED"}

    if request_scope(rec) is None:
        # scope and tier disagree (or neither is set): the operator cannot know what they approve.
        rec["status"] = "DENIED_SCOPE_UNRESOLVED"
        _save(doc)
        return {"ok": False, "reason": "SCOPE_UNRESOLVED"}
    if request_scope(rec) in REMOTE_FORBIDDEN_SCOPES:
        # Belt and braces: the scope list could have changed since minting.
        rec["status"] = "DENIED_FORBIDDEN_SCOPE"
        _save(doc)
        return {"ok": False, "reason": "SCOPE_FORBIDDEN_REMOTELY"}

    refused = _refuse_if_active_grant(doc, rec, chat_id=chat)
    if refused:
        return refused

    rec["status"] = "APPROVED"
    rec["approved_at"] = _now()
    rec["approved_by_chat"] = chat
    rec["telegram"] = (
        {k: telegram.get(k) for k in
         ("update_id", "message_id", "from_id", "from_username", "text")}
        if telegram else {"note": "no telegram metadata supplied"}
    )
    _save(doc)
    return {"ok": True, "request": rec}


def settle_by_request_id(request_id: str, *, approve: bool, chat_id: Any,
                        allowed_chats: Any,
                        telegram: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Settle a PENDING request identified by id rather than by code.

    This exists for the Telegram inline BUTTON. A tap carries no secret, and
    that is the point: the authority is Telegram's authentication of the person
    who tapped, not knowledge of a string. Telegram delivers `callback_query`
    with the sender's own user id, from a chat on the allowlist, and a bot token
    cannot fabricate one — callbacks originate at Telegram's servers, not at
    whoever holds the token.

    So the button is not a weaker door than the code. It is the same door with
    the lock moved from "knows a secret" to "is the operator", which is the
    property actually wanted. What must NEVER carry this authority is a plain
    URL: any holder of the link, any prefetcher, any preview crawler would be
    able to approve, and this agent could mint its own signed token and walk
    straight through. See `guard_request_approval` for why the tailnet button is
    read-only.
    """
    allowed = {str(c).strip() for c in (allowed_chats or set()) if str(c).strip()}
    chat = str(chat_id).strip()
    if not allowed:
        return {"ok": False, "reason": "NO_CHAT_ALLOWLIST_CONFIGURED"}
    if chat not in allowed:
        return {"ok": False, "reason": "CHAT_NOT_ALLOWED"}

    doc = _load()
    if doc.get("corrupt"):
        return {"ok": False, "reason": "REQUEST_STORE_CORRUPT"}
    want = str(request_id).strip()
    rec = next((r for r in doc["requests"] if want and request_id_of(r) == want), None)
    if rec is None:
        return {"ok": False, "reason": "UNKNOWN_REQUEST"}
    if rec.get("status") != "PENDING":
        return {"ok": False, "reason": f"REQUEST_ALREADY_{rec.get('status')}"}
    if _now() >= int(rec.get("expires_at", 0)):
        rec["status"] = "EXPIRED"
        _save(doc)
        return {"ok": False, "reason": "REQUEST_EXPIRED"}
    if approve and request_scope(rec) is None:
        rec["status"] = "DENIED_SCOPE_UNRESOLVED"
        _save(doc)
        return {"ok": False, "reason": "SCOPE_UNRESOLVED"}
    if request_scope(rec) in REMOTE_FORBIDDEN_SCOPES:
        rec["status"] = "DENIED_FORBIDDEN_SCOPE"
        _save(doc)
        return {"ok": False, "reason": "SCOPE_FORBIDDEN_REMOTELY"}
    if approve:
        refused = _refuse_if_active_grant(doc, rec, chat_id=chat, via="button")
        if refused:
            return refused

    rec["status"] = "APPROVED" if approve else "DENIED_BY_OPERATOR"
    rec["approved_at" if approve else "denied_at"] = _now()
    rec["approved_by_chat"] = chat
    rec["settled_via"] = "telegram_button"
    rec["telegram"] = (
        {k: telegram.get(k) for k in
         ("update_id", "message_id", "from_id", "from_username", "text")}
        if telegram else {"note": "no telegram metadata supplied"}
    )
    _save(doc)
    return {"ok": True, "request": rec}


# ── settle, then grant: a failed grant must not spend the request (2026-10-22) ────────────────
# Both reply paths settle the request APPROVED and only then run `bin/guard grant`. When that grant
# failed (corrupt or locked ledger, a tier refused under the ledger lock, a timeout), the row stayed
# APPROVED with no grant behind it: the code and the button were spent and the operator had to go to
# the keyboard. A failed grant now re-opens the request, with the failure recorded on the row, so the
# same tap or code works once the cause is fixed. Past its answer deadline it closes as GRANT_FAILED
# rather than ever claiming APPROVED without a grant.

def reopen_after_grant_failure(request_id: str, *, detail: str) -> dict[str, Any]:
    """APPROVED -> PENDING after `bin/guard grant` failed; GRANT_FAILED when the deadline has passed."""
    doc = _load()
    if doc.get("corrupt"):
        return {"ok": False, "reason": "REQUEST_STORE_CORRUPT"}
    want = str(request_id).strip()
    rec = next((r for r in doc["requests"] if want and request_id_of(r) == want), None)
    if rec is None:
        return {"ok": False, "reason": "UNKNOWN_REQUEST"}
    if rec.get("status") != "APPROVED":
        return {"ok": False, "reason": "REQUEST_NOT_APPROVED"}
    failure = {"reason": "GRANT_FAILED", "at": _now(), "detail": str(detail or "")[:300],
               "approved_at": rec.get("approved_at"), "approved_by_chat": rec.get("approved_by_chat")}
    rec.setdefault("grant_failures", []).append(failure)
    rec["last_refusal"] = failure
    for k in ("approved_at", "approved_by_chat", "settled_via"):
        rec.pop(k, None)
    if _now() >= int(rec.get("expires_at", 0)):
        rec["status"] = "GRANT_FAILED"
        _save(doc)
        return {"ok": False, "reason": "REQUEST_EXPIRED", "request": rec}
    rec["status"] = "PENDING"
    _save(doc)
    return {"ok": True, "request": rec}


def record_delivery(request_id: str, *, accepted: bool, message_ids: Any) -> None:
    """Record on the request row whether its Telegram prompt got a provider message id.

    `accepted` alone (the old `telegram=accepted for interrupt delivery`) cannot tell a delivered prompt
    from one the transport never posted; a message id can. Best-effort: never raises.
    """
    try:
        doc = _load()
        if doc.get("corrupt"):
            return
        want = str(request_id).strip()
        rec = next((r for r in doc["requests"] if want and request_id_of(r) == want), None)
        if rec is None:
            return
        rec["delivery"] = {"accepted": bool(accepted), "at": _now(),
                           "message_ids": [str(m) for m in (message_ids or []) if m is not None]}
        _save(doc)
    except Exception:
        return


def deny(code: str, *, chat_id: Any, allowed_chats: Any) -> dict[str, Any]:
    """Operator explicitly refuses. Burns the code."""
    allowed = {str(c).strip() for c in (allowed_chats or set()) if str(c).strip()}
    if str(chat_id).strip() not in allowed:
        return {"ok": False, "reason": "CHAT_NOT_ALLOWED"}
    doc = _load()
    fp = code_fingerprint(code)
    for r in doc["requests"]:
        if r.get("code_sha256") == fp and r.get("status") == "PENDING":
            r["status"] = "DENIED_BY_OPERATOR"
            r["denied_at"] = _now()
            _save(doc)
            return {"ok": True, "request": r}
    return {"ok": False, "reason": "UNKNOWN_OR_SETTLED_CODE"}


def unprovenanced_grants(grants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Grants carrying neither an interactive nor a Telegram origin.

    This is the audit this module exists to make possible. A grant should be
    explicable: someone typed APPROVE at a terminal, or someone approved a coded
    request from an allowlisted chat. One that matches neither is worth asking
    about.
    """
    approved = {request_id_of(r) for r in _load()["requests"]
                if r.get("status") == "APPROVED"} - {""}
    out = []
    for g in grants or []:
        if g.get("origin") == "interactive":
            continue
        # The ledger row carries remote_request_id (schema v2); older rows only in the reason text.
        rrid = g.get("remote_request_id") or _rrid_from_reason(str(g.get("reason") or ""))
        if rrid in approved:
            continue
        out.append(g)
    return out
