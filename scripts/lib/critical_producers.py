"""FQ-150 / D35: the producers that raise the ten B1–B10 act-now events, and the one link B4 must carry.

A producer's job is to turn a detected condition into one event with the class id the operator's allowlist uses, the numbers
that triggered it, and one suggested action. It decides nothing else: the text channel's 160-character sentence, its dedupe
window and its hourly cap belong to `critical_texts.py`, and the fan-out to Fi/email/Telegram belongs to
`critical_channels.deliver`. Keeping the split this way is what stops a detector growing its own idea of "critical".

**B4 is the one producer with a hard requirement on its text.** The operator must be able to re-authorise Schwab from the
message itself, so the action carries the full Command Center URL — https, tailnet host, no :7777 — and never a reply-to-paste
path: a text that asks the operator to reply with a token or a code would put a credential through a text message.

The base URL is read from the operator alert policy (`canonical_reports_url`), so the host is configured in one place rather
than repeated here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

#: The Command Center route that starts the Schwab re-authorisation.
REAUTH_PATH = "/v3/system/schwab-reauth"

#: The port the Development server listens on. It must never appear in a link the operator is given: that server is not the
#: one the tailnet serves, and a link to it fails exactly when the operator needs it to work.
DEV_PORT = ":7777"

POLICY_REL = ("config", "operator_alert_policy.yaml")


class ProducerError(ValueError):
    """A fixed reason. Never carries a URL, a symbol's account number or a message body."""


def _policy_path(repo_root: Path | str | None = None) -> Path:
    return Path(repo_root or Path(__file__).resolve().parents[2]).joinpath(*POLICY_REL)


def _read_canonical_url(path: Path | str | None = None, *, repo_root: Path | str | None = None) -> str:
    text = _policy_path(repo_root).read_text(encoding="utf-8") if path is None else Path(path).read_text(encoding="utf-8")
    # A one-key read: PyYAML is not imported here so this module stays importable in a bare test environment. The line is
    # quoted in the file, and the parser below refuses anything it cannot read unambiguously.
    values = [ln.split(":", 1)[1].strip().strip('"').strip("'") for ln in text.splitlines()
              if ln.strip().startswith("canonical_reports_url:")]
    if len(values) != 1:
        raise ProducerError("canonical_url_not_found")
    return values[0]


def command_center_base(*, path: Path | str | None = None, repo_root: Path | str | None = None) -> str:
    """`scheme://host[:port]` of the Command Center the operator can actually reach."""
    raw = _read_canonical_url(path, repo_root=repo_root)
    parts = urlsplit(raw)
    if parts.scheme != "https":
        raise ProducerError("command_center_not_https")
    if not parts.hostname:
        raise ProducerError("command_center_host_unreadable")
    port = f":{parts.port}" if parts.port else ""
    if f":{parts.port}" == DEV_PORT:
        raise ProducerError("command_center_on_dev_port")
    return f"https://{parts.hostname}{port}"


def reauth_url(**kwargs: Any) -> str:
    """The full https link the B4 text carries."""
    url = f"{command_center_base(**kwargs)}{REAUTH_PATH}"
    if DEV_PORT in url or not url.startswith("https://"):
        raise ProducerError("reauth_url_unusable")
    return url


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _event(alert_class: str, finding: Mapping[str, Any], *, action: str) -> dict[str, Any]:
    trigger = _clean(finding.get("trigger") or finding.get("what"))
    if not trigger:
        raise ProducerError("producer_needs_a_trigger")
    if not action:
        raise ProducerError("producer_needs_an_action")
    return {
        "alert_class": alert_class,
        "symbol": _clean(finding.get("symbol")).upper(),
        "account": _clean(finding.get("account")),
        "what": trigger,
        "trigger": trigger,
        "action": action,
        "evidence": dict(finding.get("evidence") or {}),
    }


def _simple(action_key: str) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Most producers differ only in which field names the suggested action and how it is worded."""
    def produce(finding: Mapping[str, Any], *, alert_class: str) -> dict[str, Any]:
        action = _clean(finding.get(action_key) or finding.get("action"))
        return _event(alert_class, finding, action=action)
    return produce


def _b4(finding: Mapping[str, Any]) -> dict[str, Any]:
    """B4 — the Schwab refresh token needs the operator's own re-login, and the link must work from a phone.

    The action is built from the live URL rather than a field, so a producer cannot accidentally text a stale or absolute
    path, and the message never asks for a reply: re-authorisation happens behind the link, not in a text thread.
    """
    url = reauth_url()
    quote = _clean(finding.get("renewal_wording") or "renew it")
    action = f"Re-authorise at {url}"
    event = _event("B4_schwab_login_expiring", finding, action=action)
    event["action"] = f"Schwab login expiring — {quote}: {url}"
    event["link"] = url
    return event


#: Every class D35 turns on, and the producer that raises it. A class with no producer is a class the operator enabled and
#: nothing can raise, which is why the dry run below refuses to pass on a partial map.
PRODUCERS: dict[str, Callable[..., dict[str, Any]]] = {
    "A1_extended_hours_near_stop": _simple("suggested_action"),
    "A2_stop_not_raised_after_move": _simple("suggested_action"),
    "B1_no_protective_stop_or_wrong_size": _simple("suggested_action"),
    "B2_stop_cancelled_expired_rejected": _simple("suggested_action"),
    "B3_stop_above_market_premarket": _simple("suggested_action"),
    "B4_schwab_login_expiring": _b4,
    "B5_trading_halt": _simple("suggested_action"),
    "B6_options_expiry_or_assignment": _simple("suggested_action"),
    "B7_margin_or_cash": _simple("suggested_action"),
    "B8_order_rejected_or_partial": _simple("suggested_action"),
    "B9_monitoring_blind": _simple("suggested_action"),
    "B10_concentration_breach": _simple("suggested_action"),
}


def produce(alert_class: str, finding: Mapping[str, Any]) -> dict[str, Any]:
    """One event for one class, or a refusal naming the class that has no producer."""
    fn = PRODUCERS.get(str(alert_class or ""))
    if fn is None:
        raise ProducerError("no_producer_for_class")
    if fn is _b4:
        return _b4(finding)
    return fn(finding, alert_class=alert_class)


def dry_run(*, policy: Mapping[str, Any], contact: Mapping[str, Any], channels: Any = None) -> dict[str, Any]:
    """Every enabled class, produced from a fake finding, fanned out with a fake sender. Sends nothing.

    Returns one row per class with the event and the delivery plan, so a missing producer or a class the config forgot shows
    up as a named failure instead of silence.
    """
    from scripts.lib import critical_channels as chan  # local: keeps this module importable alone

    out: list[dict[str, Any]] = []
    ok = True
    for alert_class, entry in sorted((policy.get("classes") or {}).items()):
        if not isinstance(entry, dict) or entry.get("enabled") is not True:
            out.append({"alert_class": alert_class, "ok": False, "reason": "class_disabled"})
            ok = False
            continue
        finding = {"symbol": "ZZTEST", "account": "Test", "trigger": f"dry run for {alert_class}",
                   "suggested_action": "No action — dry run", "evidence": {"dry_run": True}}
        try:
            event = produce(alert_class, finding)
        except ProducerError as exc:
            out.append({"alert_class": alert_class, "ok": False, "reason": str(exc)})
            ok = False
            continue
        delivery = (channels or chan).deliver(
            event, contact=dict(contact), policy=dict(policy),
            email_sender=lambda *a, **k: "dry-run-email",
            telegram_sender=lambda *a, **k: "dry-run-telegram",
            text_sender=lambda e, **k: {"sent": True, "reason": "dry_run"},
        )
        body = str(event.get("action") or "")
        out.append({"alert_class": alert_class, "ok": True, "event": event,
                    "delivery": delivery.as_dict(), "action": body})
    return {"ok": ok, "classes": out}
