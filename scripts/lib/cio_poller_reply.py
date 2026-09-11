#!/usr/bin/env python3
"""Answer a free-text operator question on the bot that received it.

WHY THIS EXISTS. On 2026-09-11 the operator asked two real questions --
"ADBE — what did Q3 actually show on user growth?" (18:24Z) and "What are the
latest analyst predictions on Walmart" (19:20Z). Both were received,
identity-resolved, bound to the right subject, receipted, and the ADBE one
changed the agent's next question at 20:00Z. Neither got a reply. The operator
asked twice and got silence.

The responder was never missing. `process_operator_message` classifies the
intent, gathers context from what is already stored, composes through the
governed bridge, validates against invention and stamps the READ_ONLY_ADVISORY
footer. It was simply never called: the poller persists free text, commits the
checkpoint, leaves `handled` False and falls off the end of the loop.

THE CRUX, AND THE REASON THIS ADAPTER EXISTS RATHER THAN A ONE-LINE CALL.
`cio_telegram_converse.send_cio_message` DISCARDS chat_id and reply_to
(`_ = (chat_id, reply_to)`) and fans out to `cio_chat_ids()` on
`cio_bot_token()`. Telegram's single-consumer rule is per TOKEN, and these are
two different bots -- 8653682012 receives the operator's messages, 8751620457 is
what the CIO sender writes to. Routing a reply through that helper would answer
a question asked on one bot by speaking into a different bot's room, to a
different list, with no thread. So the receiving token and the asking chat are
carried THROUGH the call as arguments. Whichever bot was asked, answers.

Egress goes through `telegram_transport.send_message` and nothing else. The
poller's own `_post_message`/`_send`/`_send_reply` build their own HTTP and
therefore bypass `CIO_TELEGRAM_INTERDICT`; a kill switch that some paths ignore
is not a kill switch.

Default OFF. `CIO_REPLY_ENABLED` unset means the hook is inert and the poller
behaves exactly as it does today. Rollback is unsetting one variable, no deploy.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0 -- this module never sizes,
orders, stops, weights, or reaches a broker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

FEATURE_FLAG = "CIO_REPLY_ENABLED"
CHATS_ENV = "CIO_REPLY_CHAT_IDS"

_log = logging.getLogger(__name__)

#: Short bare acknowledgements. Once a free-text hook exists it starts receiving
#: the ATM/proposal confirmations that used to fall off the end of the loop, and
#: "YES" is an instruction to another subsystem, not a question for the desk.
_BARE_CONFIRMATIONS = {
    "y", "n", "yes", "no", "ok", "okay", "k", "yep", "nope", "confirm",
    "cancel", "stop", "approve", "deny", "ack",
}


def enabled(env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FEATURE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


def reply_allowlist(default: set[str] | None = None,
                    env: Mapping[str, str] | None = None) -> set[str]:
    """Which chats may be answered.

    `CIO_REPLY_CHAT_IDS` narrows it explicitly; otherwise the caller's own
    allowlist is inherited, so this can never answer a chat the poller was not
    already willing to accept commands from.
    """
    src = env if env is not None else os.environ
    raw = str(src.get(CHATS_ENV, "") or "").strip()
    if raw:
        return {c.strip() for c in raw.split(",") if c.strip()}
    return set(default or set())


def should_answer(text: str) -> tuple[bool, str]:
    """Is this free text a question for the desk, or someone else's traffic?

    Returns (answer, reason) so a skip is reportable rather than silent.
    """
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if t.lower().strip(" .!") in _BARE_CONFIRMATIONS:
        # Belongs to the ATM / proposal confirmation flow.
        return False, "bare_confirmation"
    if "code=" in t.lower():
        # The Schwab OAuth branch matches this substring anywhere in the body.
        # Keep the two in agreement: whatever that branch would claim, this
        # declines, so a paste cannot be answered AND redeemed.
        return False, "oauth_callback_shape"
    return True, "free_text"


def make_send_fn(*, token: str, reply_to_message_id: Any = None,
                 transport: Any = None, capture: Any = None) -> Any:
    """A send closure bound to the bot that was asked.

    `chat_id` still arrives per call because the converse core owns it; the
    TOKEN is what is closed over, and that is the whole point.
    """
    def _deliver(chat_id: str, body: str, reply_to: Optional[str] = None) -> dict:
        tx = transport
        if tx is None:
            from scripts import telegram_transport as tx  # noqa: PLC0415
        target_reply = reply_to if reply_to is not None else reply_to_message_id
        res = tx.send_message(
            token=token,
            chat_id=str(chat_id),
            text=body,
            reply_to_message_id=target_reply,
        )
        # The AGENT half of the conversation. Captured here because this is the
        # single point every reply on this path passes through.
        try:
            cap = capture
            if cap is None:
                from scripts.lib.cio_telegram_converse import (  # noqa: PLC0415
                    _best_effort_capture_turn as cap,
                )
            mid = (res or {}).get("message_id") if isinstance(res, dict) else None
            if body:
                cap(body, role="agent", chat_id=str(chat_id), message_id=mid,
                    reply_to_message_id=target_reply)
        except Exception:
            pass
        return res

    return _deliver


def maybe_answer(msg: Mapping[str, Any], *, text: str, chat_id: str, token: str,
                 allowlist: set[str] | None = None,
                 env: Mapping[str, str] | None = None,
                 transport: Any = None, capture: Any = None,
                 processor: Any = None) -> dict:
    """Answer one unrouted free-text message. Never raises.

    Called from the poller under `if not handled:`, AFTER the durable checkpoint
    is committed on both the atomic and legacy paths -- so a failure here can
    neither lose the message nor replay it.
    """
    out: dict[str, Any] = {"answered": False, "reason": "", "authority": AUTHORITY}
    try:
        if not enabled(env):
            out["reason"] = "flag_off"
            return out

        ok, why = should_answer(text)
        if not ok:
            out["reason"] = why
            return out

        allowed = reply_allowlist(allowlist, env)
        if not allowed or str(chat_id) not in allowed:
            out["reason"] = "not_allowlisted"
            return out

        if not token:
            out["reason"] = "no_token"
            return out

        proc = processor
        if proc is None:
            from scripts.lib.cio_converse_core import (  # noqa: PLC0415
                process_operator_message as proc,
            )
        from scripts.lib.cio_telegram_converse import wakes_per_hour  # noqa: PLC0415

        # NOTE: the OPERATOR half of this turn is deliberately NOT captured
        # here. `cio_telegram_converse.process_telegram_message` captures it
        # because it is the entry point on ITS path; on THIS path the poller's
        # inbound intake already wrote the event, the turn and the receipt
        # before the checkpoint advanced. Capturing again would put two records
        # of one message in the store, and every consumer that counts operator
        # turns would then disagree with the one that reads events.
        message_id = msg.get("message_id")
        from_user = msg.get("from") or {}
        reply_to = msg.get("reply_to_message") or {}

        send_fn = make_send_fn(
            token=token,
            reply_to_message_id=message_id,
            transport=transport,
            capture=capture,
        )

        res = proc(
            channel="telegram",
            chat_id=str(chat_id),
            message_id=message_id or "",
            text=text,
            reply_to_message_id=reply_to.get("message_id"),
            reply_to_text=(reply_to.get("text") or None),
            user_id=str(from_user.get("id") or ""),
            username=str(from_user.get("username") or ""),
            allowlist=allowed,
            converse_on=True,
            dry_run=False,
            send_fn=send_fn,
            wakes_limit=wakes_per_hour(),
            actor_id="cio_poller_reply",
        )
        out["answered"] = bool((res or {}).get("handled"))
        out["reason"] = str((res or {}).get("reason") or "")
        out["result"] = res
        return out
    except Exception as exc:
        # The poll loop must not stall on an answer that failed to compose.
        _log.error("cio_poller_reply failed: %s: %s", type(exc).__name__, exc)
        out["reason"] = f"error:{type(exc).__name__}"
        return out


__all__ = [
    "AUTHORITY", "MBI", "FEATURE_FLAG", "CHATS_ENV",
    "enabled", "reply_allowlist", "should_answer", "make_send_fn", "maybe_answer",
]
