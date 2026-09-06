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

#: How long the operator has to answer before a request goes stale. Short on
#: purpose: a code that stays valid for hours is a standing authorisation.
DEFAULT_REQUEST_TTL_SECONDS = 900          # 15 minutes

#: A grant window this mechanism will never exceed, whatever is asked for.
#: Remote approval is for finishing a piece of work, not for handing over the
#: machine. Anything longer is a decision to make at the keyboard.
MAX_GRANT_SECONDS = 3600                   # 1 hour

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
    return doc


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
    if seconds > MAX_GRANT_SECONDS:
        raise ValueError(
            f"requested window {seconds}s exceeds the remote maximum "
            f"{MAX_GRANT_SECONDS}s — approve a longer window at the keyboard")

    code = mint_code()
    now = _now()
    rec: dict[str, Any] = {
        "request_id": secrets.token_hex(8),
        "scope": scope,
        "seconds": seconds,
        "uses": int(uses),
        "reason": str(reason),
        "code_sha256": code_fingerprint(code),
        "created_at": now,
        "expires_at": now + int(ttl),
        "status": "PENDING",
    }
    doc = _load()
    if doc.get("corrupt"):
        raise RuntimeError("remote request store is corrupt — refusing to mint")
    # Supersede any other pending request for the same scope: two live codes for
    # one scope means an operator cannot tell which they are approving.
    for r in doc["requests"]:
        if r.get("status") == "PENDING" and r.get("scope") == scope:
            r["status"] = "SUPERSEDED"
            r["superseded_by"] = rec["request_id"]
    doc["requests"].append(rec)
    doc["requests"] = doc["requests"][-200:]
    _save(doc)
    return {**rec, "code": code}


def find_pending(code: str) -> Optional[dict[str, Any]]:
    fp = code_fingerprint(code)
    for r in _load()["requests"]:
        if r.get("status") == "PENDING" and r.get("code_sha256") == fp:
            return r
    return None


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

    if rec.get("scope") in REMOTE_FORBIDDEN_SCOPES:
        # Belt and braces: the scope list could have changed since minting.
        rec["status"] = "DENIED_FORBIDDEN_SCOPE"
        _save(doc)
        return {"ok": False, "reason": "SCOPE_FORBIDDEN_REMOTELY"}

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
    rec = next((r for r in doc["requests"]
                if r.get("request_id") == str(request_id).strip()), None)
    if rec is None:
        return {"ok": False, "reason": "UNKNOWN_REQUEST"}
    if rec.get("status") != "PENDING":
        return {"ok": False, "reason": f"REQUEST_ALREADY_{rec.get('status')}"}
    if _now() >= int(rec.get("expires_at", 0)):
        rec["status"] = "EXPIRED"
        _save(doc)
        return {"ok": False, "reason": "REQUEST_EXPIRED"}
    if rec.get("scope") in REMOTE_FORBIDDEN_SCOPES:
        rec["status"] = "DENIED_FORBIDDEN_SCOPE"
        _save(doc)
        return {"ok": False, "reason": "SCOPE_FORBIDDEN_REMOTELY"}

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
    approved = {r.get("request_id") for r in _load()["requests"]
                if r.get("status") == "APPROVED"}
    out = []
    for g in grants or []:
        if g.get("origin") == "interactive":
            continue
        if g.get("remote_request_id") in approved:
            continue
        out.append(g)
    return out
