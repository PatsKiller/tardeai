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
    """SMTP through the approved adapter. Imported here, not at module scope, so the chokepoint sees one owner."""
    from scripts.alerting import send_email  # local import: the approved SMTP adapter

    return send_email(to, subject, body)


def _default_telegram_sender(chat_id: str, text: str) -> str | None:
    """The Critical chat, through the one approved Bot API owner."""
    from telegram_transport import send_message  # local import: the approved Telegram owner

    return send_message(chat_id, text)


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
    allow = policy if policy is not None else cd.load_text_allowlist()
    plan = cd.fan_out_plan(alert_class, doc, allow)
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
            out.receipts.append(Receipt("telegram_critical", "sent", provider_receipt=str(provider) if provider else None))
        except Exception as exc:  # noqa: BLE001 — a channel failure is a receipt, never a lost event
            out.receipts.append(Receipt("telegram_critical", "failed", type(exc).__name__))

    # Email
    if not mail:
        out.receipts.append(Receipt("email", "skipped", "critical_email_not_configured"))
    else:
        try:
            provider = (email_sender or _default_email_sender)(mail, subject, what)
            out.receipts.append(Receipt("email", "sent", provider_receipt=str(provider) if provider else None))
        except Exception as exc:  # noqa: BLE001
            out.receipts.append(Receipt("email", "failed", type(exc).__name__))

    # Text gateway — the primitive owns the allowlist, the cap and the dedupe, so this module only hands it the event.
    if "text_gateway_not_configured" in plan["missing"]:
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
            status = "sent" if not isinstance(result, dict) or result.get("sent") is not False else "skipped"
            reason = None if status == "sent" else str((result or {}).get("reason") or "not_sent")
            out.receipts.append(Receipt("text_gateway", status, reason))
        except ImportError:
            # The primitive is not on this branch yet. Refusing is the safe direction: no text, and the receipt says why.
            out.receipts.append(Receipt("text_gateway", "skipped", "text_primitive_not_available"))
        except Exception as exc:  # noqa: BLE001
            out.receipts.append(Receipt("text_gateway", "failed", type(exc).__name__))

    return out
