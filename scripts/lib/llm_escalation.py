"""Lane escalation with an operator stop before a second paid provider.

OPERATOR POLICY, 2026-09-06
---------------------------
    1. FREE OAUTH LANES        grok -> chatgpt
    2. DEEPSEEK FLASH          the one paid lane enterable automatically
    3. NOTIFY THE OPERATOR     Telegram, and STOP
    4. any further paid API    never automatic

**Step 3 is a hard stop, not a warning.** The run yields nothing and waits.
Silently walking up a cost ladder is how a research backlog becomes a bill nobody
authorised — this system already carries a daily provider spend cap for the same
reason, and an escalation that notifies while continuing would defeat it.

WHY PER-RUN AND NOT PER-CALL
---------------------------
A batch of 2,000 documents that lost its free lanes would send 2,000 identical
notifications, which is indistinguishable from a broken loop and trains the
operator to ignore the channel. One notification per run, then stop.

WHY THE NOTIFICATION BYPASSES THE ROUTER
----------------------------------------
An approval prompt classified `P1_DIGEST` and archived into a store nothing
delivers is a decision the operator never sees, reported as sent. That happened
to guard approvals on 2026-09-05 and the fix is the same here: interrupt
delivery, and honest wording — "accepted", never "sent".
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

SCHEMA = "LlmEscalation@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Paid lanes reachable WITHOUT asking. Exactly one, by operator decision.
AUTO_PAID: tuple[str, ...] = ("deepseek-flash",)

#: Paid lanes that require the operator to be asked first. Empty until a lane is
#: added deliberately — a provider must never arrive here by default.
GATED_PAID: tuple[str, ...] = tuple(
    x.strip() for x in os.environ.get("LLM_GATED_PAID_LANES", "").split(",") if x.strip())


class EscalationStopped(RuntimeError):
    """Free lanes and the auto-paid lane failed. The operator was notified and
    the run stopped rather than entering a further paid provider."""

    def __init__(self, attempts: list[dict[str, Any]], notified: bool):
        self.attempts = attempts
        self.notified = notified
        tried = ", ".join(str(a.get("lane")) for a in attempts) or "none"
        super().__init__(
            f"stopped before a gated paid lane; tried {tried}; "
            f"operator {'notified' if notified else 'NOT notified'}")


def _default_notify(message: str) -> bool:
    from telegram_alert import send_telegram  # noqa: PLC0415
    # bypass_router: an escalation prompt suppressed into a digest is a decision
    # the operator never sees.
    return bool(send_telegram(message, bypass_router=True))


def build_message(*, attempts: list[dict[str, Any]], purpose: str,
                  gated: tuple[str, ...], now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        "\U0001f6d1 LLM lanes exhausted — run STOPPED before a paid provider",
        "",
        f"purpose : {purpose}",
        f"as_of   : {now.replace(microsecond=0).isoformat()}",
        "",
        "tried, in order:",
    ]
    for a in attempts:
        lines.append(f"  · {a.get('lane')}: {str(a.get('error'))[:110]}")
    lines += [
        "",
        f"next would be PAID: {', '.join(gated) or '(none configured)'}",
        "",
        "Nothing was spent and nothing was produced. This run stopped rather than",
        "entering a further paid provider. Re-run with the lane explicitly allowed",
        "if you want it.",
    ]
    return "\n".join(lines)


def run_with_escalation(
    prompt: str,
    *,
    purpose: str,
    generate_fn: Optional[Callable[..., Any]] = None,
    notify_fn: Optional[Callable[[str], bool]] = None,
    allow_gated: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Free lanes, then deepseek-flash, then STOP and tell the operator.

    Returns {"ok": True, "text": ..., "lane": ...} or raises EscalationStopped.
    `allow_gated=True` is the operator's explicit re-run and is never set by a
    scheduled job.
    """
    from lib.llm_fallback import generate_with_fallback  # noqa: PLC0415

    gen = generate_fn or generate_with_fallback
    attempts: list[dict[str, Any]] = []

    # Steps 1 and 2. allow_paid=True admits AUTO_PAID (deepseek-flash) only —
    # llm_fallback's PAID_CHAIN is exactly that one lane.
    try:
        res = gen(prompt, allow_paid=True, **kwargs)
        text = getattr(res, "text", None) or getattr(res, "output", None) or (
            res if isinstance(res, str) else None)
        if text:
            return {"ok": True, "text": text,
                    "lane": getattr(res, "lane", None), "escalated": False}
        attempts.append({"lane": "chain", "error": "empty response"})
    except Exception as exc:
        attempts.extend(getattr(exc, "attempts", None)
                        or [{"lane": "chain", "error": f"{type(exc).__name__}: {exc}"}])

    # Step 3. The operator decides whether to pay more. Notify, then STOP.
    notified = False
    try:
        notified = bool((notify_fn or _default_notify)(
            build_message(attempts=attempts, purpose=purpose, gated=GATED_PAID)))
    except Exception:
        notified = False

    if allow_gated and GATED_PAID:
        # Only reachable on an explicit operator re-run.
        res = gen(prompt, allow_paid=True, extra_lanes=list(GATED_PAID), **kwargs)
        text = getattr(res, "text", None) or getattr(res, "output", None) or (
            res if isinstance(res, str) else None)
        if text:
            return {"ok": True, "text": text,
                    "lane": getattr(res, "lane", None), "escalated": True}

    raise EscalationStopped(attempts, notified)
