"""FQ-143 / D32 §6 + D33: one CRITICAL event, three channels, a receipt for each.

The text channel belongs to the critical-text primitive (`scripts/lib/critical_texts.py` on `wt/critical-texts`): it owns
the operator's allowlist, the 160-character sentence, the dedupe window and the hourly cap. This module does not repeat any
of that. It adds the two channels the primitive does not own — email, and the Critical Telegram chat — and fans one event to
all three, so a detector calls once and the operator is reached however they are reachable.

Rules this module keeps:

  * nothing is sent that the allowlist does not enable; a class the operator turned off is reported, not quietly dropped;
  * a missing or failed channel never stops the others — the spec says so explicitly, and a degraded channel is a receipt,
    not an exception;
  * every send returns a per-channel receipt, including the ones that did not send, and no receipt carries an address;
  * senders are injected, so the tests exercise the fan-out without a network, a token or a mailbox.

It sends nothing on import and holds no state between events.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from scripts.lib import critical_delivery as cd

#: Channels in the order the plan reports them. The order is also the order they are attempted, so the cheapest failure
#: (no chat configured) is discovered before the text, which is the one that interrupts the operator.
CHANNELS = ("telegram_critical", "email", "text_gateway")


@dataclass
class Receipt:
    channel: str
    status: str           # sent | failed | skipped
    reason: str | None = None
    provider_receipt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"channel": self.channel, "status": self.status, "reason": self.reason,
                "provider_receipt": self.provider_receipt}


@dataclass
class Delivery:
    alert_class: str
    receipts: list[Receipt] = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        """True when at least one channel confirmed, which is the spec's bar for DELIVERED."""
        return any(r.status == "sent" for r in self.receipts)

    def as_dict(self) -> dict[str, Any]:
        return {"alert_class": self.alert_class, "delivered": self.delivered,
                "receipts": [r.as_dict() for r in self.receipts]}


def _default_email_sender(to: str, subject: str, body: str) -> str | None:
    """The email adapter that takes a recipient.

    Deliberately NOT ``scripts.alerting.send_email``: its signature is ``(subject, text, html, attachments)`` and takes no
    recipient, so passing one would put the operator's address in the subject line and the real subject in the body. The
    adapter that accepts a recipient is ``email_notifier.send_email(subject, body, to=...)``.
    """
    from email_notifier import send_email  # local import: keeps the import graph off the module load path

    result = send_email(subject, body, to=to)
    if result is False:
        raise RuntimeError("email_send_refused")
    return "gog-accepted" if result in (True, None) else str(result)


def _default_telegram_sender(chat_id: str, text: str) -> str | None:
    """The Critical chat, through the one approved Bot API owner.

    ``telegram_transport.send_message`` is keyword-only and requires the bot token explicitly — calling it positionally
    raises TypeError, which would have made every Critical-chat delivery a failed receipt for the one channel that exists
    because the normal Telegram is flooded.
    """
    import os

    from telegram_transport import send_message  # local import: the approved Telegram owner

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("telegram_token_not_configured")
    result = send_message(token=token, chat_id=chat_id, text=text)
    if isinstance(result, dict):
        if result.get("ok") is False:
            raise RuntimeError("telegram_send_refused")
        message_id = (result.get("result") or {}).get("message_id") if isinstance(result.get("result"), dict) else None
        return str(message_id) if message_id is not None else ("ok" if result.get("ok") else None)
    return str(result) if result is not None else None


def _confirms(provider: Any) -> bool:
    """A sender confirms by returning a receipt (a message id, an accepted marker). Anything else is not a delivery."""
    if isinstance(provider, dict):
        return provider.get("sent") is True or provider.get("ok") is True
    return bool(provider)


def deliver(
    event: dict[str, Any],
    *,
    contact: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    email_sender: Callable[[str, str, str], Any] | None = None,
    telegram_sender: Callable[[str, str], Any] | None = None,
    text_sender: Callable[..., Any] | None = None,
    now: Any = None,
) -> Delivery:
    """Fan one CRITICAL event to every channel that can carry it. Never raises for a channel that cannot."""
    alert_class = str(event.get("alert_class") or "").strip()
    doc = contact if contact is not None else cd.load_operator_contact()
    # cc-deepseek-8 F3: the allowlist is the TEXT channel's config. If it cannot be read, text is refused and the
    # other two channels still carry the event — a missing text allowlist must never stop email and the Critical chat.
    allow = policy
    allow_error: str | None = None
    if allow is None:
        try:
            allow = cd.load_text_allowlist()
        except cd.CriticalDeliveryRefused as exc:
            allow = None
            allow_error = str(exc) or "text_allowlist_missing"
    plan = cd.fan_out_plan(alert_class, doc,
                           allow if allow is not None else {"classes": {alert_class: {"enabled": False}}})
    out = Delivery(alert_class=alert_class)

    what = str(event.get("what") or event.get("trigger") or alert_class)
    subject = cd.subject(alert_class, what)
    mail = ""
    try:
        mail = cd.email_target(doc)
    except cd.CriticalDeliveryRefused:
        mail = ""

    # Telegram Critical chat
    if "critical_chat_not_configured" in plan["missing"]:
        out.receipts.append(Receipt("telegram_critical", "skipped", "critical_chat_not_configured"))
    else:
        chat = os.environ.get(cd.CRITICAL_CHAT_ENV, "").strip()
        try:
            provider = (telegram_sender or _default_telegram_sender)(chat, f"{subject}\n{what}")
            # cc-deepseek-2 F1: "returned without raising" is not "delivered". A sender that returns no receipt
            # (a capped or suppressed send, a gateway that did nothing) is recorded as unconfirmed, so
            # Delivery.delivered cannot publish it as a success on the channel that exists to assure the operator.
            status = "sent" if _confirms(provider) else "failed"
            out.receipts.append(Receipt("telegram_critical", status,
                                        None if status == "sent" else "sender_returned_no_receipt",
                                        provider_receipt=str(provider) if provider else None))
        except Exception as exc:  # noqa: BLE001 — a channel failure is a receipt, never a lost event
            out.receipts.append(Receipt("telegram_critical", "failed", type(exc).__name__))

    # Email
    if not mail:
        out.receipts.append(Receipt("email", "skipped", "critical_email_not_configured"))
    else:
        try:
            provider = (email_sender or _default_email_sender)(mail, subject, what)
            status = "sent" if _confirms(provider) else "failed"
            out.receipts.append(Receipt("email", status, None if status == "sent" else "sender_returned_no_receipt",
                                        provider_receipt=str(provider) if provider else None))
        except Exception as exc:  # noqa: BLE001
            out.receipts.append(Receipt("email", "failed", type(exc).__name__))

    # Text gateway — the primitive owns the allowlist, the cap and the dedupe, so this module only hands it the event.
    if allow_error is not None:
        out.receipts.append(Receipt("text_gateway", "skipped", allow_error))
    elif "text_gateway_not_configured" in plan["missing"]:
        out.receipts.append(Receipt("text_gateway", "skipped", "text_gateway_not_configured"))
    elif not cd.text_class_allowed(alert_class, allow):
        out.receipts.append(Receipt("text_gateway", "skipped", "class_not_enabled_for_text"))
    else:
        try:
            if text_sender is not None:
                result = text_sender(event)
            else:
                from scripts.lib.critical_texts import send_critical_text  # the primitive; present once its PR lands
                result = send_critical_text(event, now=now)
            # cc-deepseek-8 F2: the test is POSITIVE. Only an explicit {"sent": True} counts as sent; a dict that
            # merely lacks the key, or any other shape, is not a delivery. (The primitive is not on this branch, so
            # its return shape is unverified here — which is exactly why the default must be "not sent".)
            if isinstance(result, dict) and result.get("sent") is True:
                status, reason = "sent", None
            elif isinstance(result, dict) and result.get("sent") is False:
                status, reason = "skipped", str(result.get("reason") or "not_sent")
            else:
                status, reason = "failed", "sender_returned_no_confirmation"
            out.receipts.append(Receipt("text_gateway", status, reason))
        except ImportError:
            # The primitive is not on this branch yet. Refusing is the safe direction: no text, and the receipt says why.
            out.receipts.append(Receipt("text_gateway", "skipped", "text_primitive_not_available"))
        except Exception as exc:  # noqa: BLE001
            out.receipts.append(Receipt("text_gateway", "failed", type(exc).__name__))

    return out
