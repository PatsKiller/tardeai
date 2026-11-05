"""FQ-143 / D32 §6 + D33: one CRITICAL event, three channels, a receipt for each.

The text channel belongs to the critical-text primitive (`scripts/lib/critical_texts.py` on `wt/critical-texts`): it owns
the operator's allowlist, the 160-character sentence, the dedupe window and the hourly cap. This module does not repeat any
of that. It adds the two channels the primitive does not own — email, and the Critical Telegram chat — and fans one event to
all three, so a detector calls once and the operator is reached however they are reachable.

Rules this module keeps:

  * nothing is sent that the allowlist does not enable; a class the operator turned off is reported, not quietly dropped;
  * a missing or failed channel never stops the others — the spec says so explicitly, and a degraded channel is a receipt,
    not an exception. That includes a *configuration* failure: an unreadable contact file or one malformed gateway address
    is a receipt against the channel that needed it, never a reason to skip the channels that were configured correctly;
  * a Telegram message counts only when the transport returns a message id; a Communications Editor hold or duplicate is
    recorded as skipped, because it reached nobody;
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


class ChannelSuppressed(RuntimeError):
    """A channel held the message deliberately (Communications Editor hold or duplicate).

    Not a delivery and not a failure to retry: the receipt vocabulary already has the word ``skipped`` for this. The
    reason is a fixed token, never the message body, so it is safe to write into ``delivery_reason``.
    """


def _safe_token(value: Any, fallback: str = "held") -> str:
    """A short identifier from transport-supplied text, or ``fallback`` when it is not one."""
    text = str(value or "").strip()
    return text if text and len(text) <= 60 and all(c.isalnum() or c in "_-." for c in text) else fallback


def _safe_reason(exc: BaseException) -> str:
    """The exception's own reason when it is safe to persist, else its class name.

    The default senders raise fixed reasons (``telegram_token_not_configured``, ``email_send_refused``) that the operator
    can act on; a class name alone is a dead end on the Home page. A third-party exception's message may embed a
    recipient address, and no receipt may carry one, so anything with an ``@`` or an implausible length falls back.
    """
    text = str(exc).strip()
    if text and "@" not in text and len(text) <= 200:
        return text
    return type(exc).__name__


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
        # The transport's success shape carries `message_id` at the top level. A held or deduplicated message is
        # `{"ok": True, "message_id": None, "suppressed": ...}` — ok and nothing sent — so ok alone is never a receipt.
        message_id = result.get("message_id")
        if message_id in (None, "", 0) and isinstance(result.get("result"), dict):
            message_id = result["result"].get("message_id")
        if message_id in (None, "", 0):
            if result.get("suppressed") is not None or "suppressed" in result:
                raise ChannelSuppressed(f"telegram_suppressed:{_safe_token(result.get('suppressed'))}")
            raise RuntimeError("telegram_message_id_missing")
        return str(message_id)
    return str(result) if result is not None else None


def _confirms(provider: Any) -> bool:
    """A sender confirms by returning a receipt (a message id, an accepted marker). Anything else is not a delivery."""
    if isinstance(provider, dict):
        return provider.get("sent") is True or provider.get("ok") is True
    return bool(provider)


def _telegram_outcome(provider: Any) -> tuple[str, str | None]:
    """Classify a Telegram sender's answer. Only a message id proves something was sent.

    ``telegram_transport.deliver_text`` returns ``ok=True, message_id=None, suppressed=...`` when the Communications
    Editor holds or de-duplicates a message: it reached nobody, and the truthy ``ok`` must not become a sent receipt. A
    hold maps to ``skipped`` (the receipt vocabulary's word for "deliberately not sent") with the suppression reason.
    """
    if isinstance(provider, dict):
        message_id = provider.get("message_id")
        if message_id in (None, "", 0) and isinstance(provider.get("result"), dict):
            message_id = provider["result"].get("message_id")
        if message_id not in (None, "", 0):
            return "sent", None
        if provider.get("suppressed") is not None or "suppressed" in provider:
            return "skipped", f"telegram_suppressed:{_safe_token(provider.get('suppressed'))}"
        if provider.get("sent") is True:
            return "sent", None
        return "failed", "sender_returned_no_receipt"
    if _confirms(provider):
        return "sent", None
    return "failed", "sender_returned_no_receipt"


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
    """Fan one CRITICAL event to every channel that can carry it. Never raises for a channel that cannot.

    The one refusal is the event itself: when the CRITICAL taxonomy cannot be read, nothing is fanned out, because a
    class nobody can verify must not be labelled CRITICAL. That is the same posture as a class outside the allowlist.
    """
    alert_class = str(event.get("alert_class") or "").strip()
    # F4/codex P2: the private contact file is email's and the text gateways' configuration. The Critical chat is
    # configured independently, so a broken contact file is recorded against those two channels and the chat still
    # sends; otherwise one unreadable file silently removes the one channel the operator asked for.
    doc: dict[str, Any] = {}
    contact_error: str | None = None
    if contact is not None:
        doc = contact
    else:
        try:
            doc = cd.load_operator_contact()
        except cd.CriticalDeliveryRefused as exc:
            contact_error = str(exc) or "operator_contact_unreadable"
    # cc-deepseek F3: this file is BOTH the text-channel config and the CRITICAL taxonomy. If it cannot be read the
    # taxonomy is unknown, and inventing it from the caller's own argument would let any class be labelled CRITICAL.
    # The honest, safe reading of "a class absent from the file is refused everywhere" is to refuse the event.
    allow = policy if policy is not None else cd.load_text_allowlist()
    plan = cd.fan_out_plan(alert_class, doc, allow)
    out = Delivery(alert_class=alert_class)

    what = str(event.get("what") or event.get("trigger") or alert_class)
    # codex P2: `what` is only the trigger. The suggested action, and B4's re-authorisation link, live in
    # `event["action"]` / `event["link"]`; without them both fallbacks drop the one thing the operator must do.
    action = " ".join(str(event.get("action") or "").split()).strip()
    link = str(event.get("link") or "").strip()
    body_lines = [what]
    if action and action not in what:
        body_lines.append(action)
    if link and link not in "\n".join(body_lines):
        body_lines.append(link)
    body_text = "\n".join(body_lines)
    subject = cd.subject(alert_class, what)
    mail = ""
    if contact_error is None:
        try:
            mail = cd.email_target(doc)
        except cd.CriticalDeliveryRefused:
            mail = ""

    # Telegram Critical chat — independent of the contact file, so it is attempted even when that file is unreadable.
    if "critical_chat_not_configured" in plan["missing"]:
        out.receipts.append(Receipt("telegram_critical", "skipped", "critical_chat_not_configured"))
    else:
        chat = os.environ.get(cd.CRITICAL_CHAT_ENV, "").strip()
        try:
            provider = (telegram_sender or _default_telegram_sender)(chat, f"{cd.SUBJECT_PREFIX} {body_text}")
            # cc-deepseek-2 F1 / codex P1: "returned without raising" is not "delivered". A held or deduplicated
            # message returns ok=True with no message id; it reached nobody and is recorded as skipped.
            status, reason = _telegram_outcome(provider)
            out.receipts.append(Receipt("telegram_critical", status, reason,
                                        provider_receipt=str(provider) if provider else None))
        except ChannelSuppressed as exc:
            out.receipts.append(Receipt("telegram_critical", "skipped", _safe_reason(exc)))
        except Exception as exc:  # noqa: BLE001 — a channel failure is a receipt, never a lost event
            out.receipts.append(Receipt("telegram_critical", "failed", _safe_reason(exc)))

    # Email
    if contact_error is not None:
        out.receipts.append(Receipt("email", "failed", contact_error))
    elif not mail:
        out.receipts.append(Receipt("email", "skipped", "critical_email_not_configured"))
    else:
        try:
            provider = (email_sender or _default_email_sender)(mail, subject, body_text)
            status = "sent" if _confirms(provider) else "failed"
            out.receipts.append(Receipt("email", status, None if status == "sent" else "sender_returned_no_receipt",
                                        provider_receipt=str(provider) if provider else None))
        except Exception as exc:  # noqa: BLE001
            out.receipts.append(Receipt("email", "failed", _safe_reason(exc)))

    # Text gateway — the primitive owns the allowlist, the cap and the dedupe, so this module only hands it the event.
    if contact_error is not None:
        out.receipts.append(Receipt("text_gateway", "failed", contact_error))
    elif plan.get("gateway_error"):
        out.receipts.append(Receipt("text_gateway", "skipped", str(plan["gateway_error"])))
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
            out.receipts.append(Receipt("text_gateway", "failed", _safe_reason(exc)))

    return out
