"""FQ-143 / D32 §6 (as amended by D33): the CRITICAL tier and the three channels it reaches.

The operator's words (2026-11-04 18:25 ET): "I'm flooded with Telegram messages. Could we also send an SMS message to my
Google Voice and an email so I'm assured to see it for these critical type of alerts?" D33 amended the transport: no
Twilio, no new SMS vendor — the text goes to the operator's Google Fi email-to-text gateway address, which is an email.

Three channels, one event:

  telegram_critical   the Critical chat, its own notification sound, so it stands out from the flood
  email               subject starts "CRITICAL —"; the body carries what happened, then the action and link
  text_gateway        every email-to-text address on file; each carries the operator's own ``verified`` flag,
                      and ``gateway_unverified_count`` surfaces how many were not verified. An unverified
                      gateway is still attempted — dropping an alert target on a config flag would lose
                      delivery silently, which is the worse failure — but it is never counted as verified.

This module owns the parts that must not be got wrong twice: which alerts may use the text channel at all, where the
targets come from, and what a message says. It sends nothing and writes nothing — the dispatcher does that, and it does it
from a durable outbox so a crash cannot lose an alert.

HOUSE RULE E, binding: the text channel carries ONLY the classes in ``CRITICAL_CLASSES``. Never a test, a status, a digest
or an FYI. The addresses are private — they live in ``coordinator/operator_contact.json`` under the persistent-state root,
never in this repository, which is public. Nothing in this module may print, log or return a raw address in an error.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: The operator's allowlist — which classes may use the TEXT channel — lives in ONE file, `config/critical_text_classes.json`
#: (A1, A2, B1–B10), owned by the critical-text primitive. This module does not keep a second copy of that list: two
#: vocabularies for "may this interrupt the phone" is how a class silently stops being critical.
ALLOWLIST_REL = ("config", "critical_text_classes.json")

#: What the subject line starts with, so the operator can triage from a phone notification without opening anything.
SUBJECT_PREFIX = "CRITICAL —"

#: At most 300 characters, per the spec: what, price/time, dollars at risk, and the action.
TEXT_MAX_CHARS = 300

CONTACT_ENV = "TRADEAI_OPERATOR_CONTACT"
#: The Critical Telegram chat, the same secret-reference pattern the general/proposal chats already use
#: (``config/operator_alert_policy.yaml``). A chat id is configuration, so it is an environment reference, never a file.
CRITICAL_CHAT_ENV = "TRADEAI_CRITICAL_ALERT_CHAT_ID"


class CriticalDeliveryRefused(RuntimeError):
    """A fixed safe reason; never carries an address, a token or a message body."""


@dataclass(frozen=True)
class TextTarget:
    """One email-to-text gateway address. ``label`` is safe to log; ``address`` is not."""
    label: str
    address: str
    verified: bool


def contact_path() -> Path:
    """The private operator contact file. Env override first, then the persistent-state root."""
    override = os.environ.get(CONTACT_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return (Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "coordination"
            / "coordinator" / "operator_contact.json")


def load_operator_contact(path: Path | str | None = None) -> dict:
    """Read and validate the private contact file.

    Refuses rather than defaults. An alert that cannot name its target must not be sent to a guessed one, and it must not
    be silently dropped either — the caller turns this refusal into a failed receipt on the outbox row.
    """
    target = Path(path).expanduser() if path is not None else contact_path()
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CriticalDeliveryRefused("operator_contact_missing") from None
    except (OSError, ValueError):
        raise CriticalDeliveryRefused("operator_contact_unreadable") from None
    if not isinstance(doc, dict) or doc.get("schema") != "OperatorContact@v1":
        raise CriticalDeliveryRefused("operator_contact_schema_invalid")
    return doc


def text_targets(contact: dict) -> list[TextTarget]:
    """Every gateway address on file, deduplicated, in file order.

    ``critical_sms_email_gateways`` is the list the operator maintains; ``critical_sms_email_gateway`` is the single
    older key kept for back-compat and equals line 1. Reading only the list would drop an operator who filled in the
    single key; reading only the single key would drop the second line. Both, deduplicated, is the honest read.
    """
    out: list[TextTarget] = []
    seen: set[str] = set()

    def add(address: object, label: object, verified: object) -> None:
        text = str(address or "").strip()
        if not text or text in seen:
            return
        if "@" not in text:  # an email-to-text gateway is an email address; anything else is a configuration error
            raise CriticalDeliveryRefused("text_gateway_not_an_address")
        seen.add(text)
        out.append(TextTarget(label=str(label or "").strip() or "text gateway", address=text,
                              verified=verified is True))

    for entry in contact.get("critical_sms_email_gateways") or []:
        if isinstance(entry, dict):
            add(entry.get("address"), entry.get("label"), entry.get("verified"))
    add(contact.get("critical_sms_email_gateway"), contact.get("critical_sms_email_gateway_label"),
        contact.get("critical_sms_email_gateway_verified"))
    return out


def email_target(contact: dict) -> str:
    """The operator's email address. Refused when absent — never defaulted to anyone else's."""
    address = str(contact.get("critical_email_to") or "").strip()
    if "@" not in address:
        raise CriticalDeliveryRefused("critical_email_not_configured")
    return address


def critical_chat_configured() -> bool:
    """Whether the Critical Telegram chat is configured. Absence is a degraded channel, not a delivery failure."""
    return bool(os.environ.get(CRITICAL_CHAT_ENV, "").strip())


def load_text_allowlist(path: Path | str | None = None, *, repo_root: Path | str | None = None) -> dict:
    """The operator's text-channel allowlist. Refuses rather than assuming an empty list means "nothing is critical"."""
    target = Path(path) if path is not None else Path(repo_root or Path(__file__).resolve().parents[2]).joinpath(*ALLOWLIST_REL)
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CriticalDeliveryRefused("text_allowlist_missing") from None
    except (OSError, ValueError):
        raise CriticalDeliveryRefused("text_allowlist_unreadable") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("classes"), dict):
        raise CriticalDeliveryRefused("text_allowlist_invalid")
    return doc


def text_class_allowed(alert_class: str, policy: dict) -> bool:
    """True only when the allowlist entry exists AND is enabled. Absent is refused, not defaulted open."""
    entry = (policy.get("classes") or {}).get(str(alert_class or ""))
    return bool(isinstance(entry, dict) and entry.get("enabled") is True)


def is_critical_class(alert_class: str, policy: dict) -> bool:
    """Whether the class is in the operator's CRITICAL taxonomy at all — present in the allowlist file, enabled or not.

    The file is the one place the class ids exist, so a class absent from it is not a critical class, and nothing is sent.
    """
    return isinstance((policy.get("classes") or {}).get(str(alert_class or "")), dict)


def assert_critical_class(alert_class: str, policy: dict | None = None) -> None:
    """Refuse an event that is not on the operator's critical taxonomy. Nothing is fanned out for it."""
    effective = policy if policy is not None else load_text_allowlist()
    if not is_critical_class(alert_class, effective):
        raise CriticalDeliveryRefused("not_a_critical_class")


def assert_text_allowed(alert_class: str, policy: dict | None = None) -> None:
    """HOUSE RULE E, in code. Everything the operator's allowlist does not ENABLE is refused the text channel.

    Disabling a class stops its texts and nothing else — email and the Critical chat still carry the event — which is what
    the allowlist file's own header says. A class absent from the file is refused everywhere, by assert_critical_class.

    The refusal is unconditional: there is no ``override`` argument, and adding one would be a decision for the operator.
    """
    effective = policy if policy is not None else load_text_allowlist()
    if not is_critical_class(alert_class, effective):
        raise CriticalDeliveryRefused("not_a_critical_class")
    if not text_class_allowed(alert_class, effective):
        raise CriticalDeliveryRefused("text_channel_reserved_for_critical")


def subject(alert_class: str, what: str) -> str:
    """The email subject; it starts with the prefix even for a class name nobody expected."""
    head = " ".join(str(what or "").split()).strip()
    return f"{SUBJECT_PREFIX} {head}".strip() if head else SUBJECT_PREFIX


def text_body(*, what: str, price: str | None = None, at: str | None = None,
              dollars_at_risk: str | None = None, action: str | None = None,
              max_chars: int = TEXT_MAX_CHARS) -> str:
    """One text message: what, price/time, dollars at risk, the action. Cut at a word boundary, never mid-word.

    Order matters — the action is the reason the phone buzzed, so it is placed before the numbers when the message has to
    be shortened. That is why the tail is dropped by building from the front, not by slicing the finished string.
    """
    parts = [str(what or "").strip()]
    if action:
        parts.append(str(action).strip())
    if price or at:
        parts.append(" ".join(x for x in (str(price or "").strip(), str(at or "").strip()) if x))
    if dollars_at_risk:
        parts.append(f"{str(dollars_at_risk).strip()} at risk")
    line = " · ".join(p for p in parts if p)
    if len(line) <= max_chars:
        return line
    cut = line[:max_chars]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut).rstrip(" ·,") + "…"


def fan_out_plan(alert_class: str, contact: dict, policy: dict | None = None) -> dict[str, object]:
    """The channels one CRITICAL event goes to, and what is missing. Never raises for a degraded channel.

    A missing channel is reported, not fatal: the spec is explicit that if one channel fails the others still carry the
    alert and the failure is flagged. Only a caller asking for the text channel with a non-critical class is refused.
    """
    assert_critical_class(alert_class, policy)
    text_enabled = text_class_allowed(alert_class, policy)
    missing: list[str] = []
    # F4/codex P2: a malformed gateway address is the TEXT channel's configuration error. It must be recorded against
    # the text channel, not raised out of the plan and take the valid email and Critical-chat targets with it.
    gateway_error: str | None = None
    try:
        gateways = text_targets(contact)
    except CriticalDeliveryRefused as exc:
        gateways = []
        gateway_error = str(exc) or "text_gateway_invalid"
    if not gateways and gateway_error is None:
        missing.append("text_gateway_not_configured")
    try:
        mail = email_target(contact)
    except CriticalDeliveryRefused:
        mail = ""
        missing.append("critical_email_not_configured")
    if not critical_chat_configured():
        missing.append("critical_chat_not_configured")
    # cc-deepseek F7: ``channels`` is what a dry run and a reviewer read first, so it must be the configured-and-
    # permitted list — the same channels that will actually be attempted — never a tier wish-list that names a channel
    # with no target. ``attempted`` is kept as the explicit spelling of the same list.
    attempted: list[str] = []
    if critical_chat_configured():
        attempted.append("telegram_critical")
    if mail:
        attempted.append("email")
    if gateways and text_enabled:
        attempted.append("text_gateway")
    return {
        "channels": list(attempted),
        "attempted": attempted,
        "gateway_count": len(gateways),
        # P2 (cc-deepseek-3): ``verified`` was recorded and read by nothing. It is read here rather than enforced in the
        # send loop: the operator's flag is a statement about the address, and a false one must be visible without the
        # alert silently disappearing.
        "gateway_unverified_count": sum(1 for target in gateways if not target.verified),
        "gateway_error": gateway_error,
        "email_configured": bool(mail),
        "text_enabled": text_enabled,
        "missing": missing,
    }
