"""The critical "act now" text channel (SPEC_CRITICAL_TEXT_ACTION_ALERTS_20261104).

One place decides whether a class may text, formats the sentence, and fans it out to every Fi
email-to-text gateway. Producers call ``send_critical_text``; they never address a phone or a
gateway themselves, and no address is ever stored in the repository.

Rules this module owns, all from the spec:
  * the class allowlist is ``config/critical_text_classes.json`` (the operator turns classes on/off there);
  * an unknown or disabled class is not sent — the channel fails closed to Telegram-only;
  * at most ``max_per_hour`` texts per hour, and one text per event id inside ``dedupe_hours``;
  * the text is plain, at most 160 characters, carries symbol/account/trigger/one action, no HTML and no links.

Agents never place, change or cancel an order, and nothing here does: it sends words.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_REL = "config/critical_text_classes.json"
CONTACT_REL = "data/coordination/coordinator/operator_contact.json"
STATE_REL = "data/runtime/critical_texts_sent.json"
MAX_TEXT_CHARS = 160
DEFAULT_MAX_PER_HOUR = 10
DEFAULT_DEDUPE_HOURS = 12


class CriticalTextError(ValueError):
    """The channel was asked to send something it must not."""


def _persistent_root() -> Path:
    """The durable state root. Resolved, never hardcoded — a channel that cannot find it refuses."""
    from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415 — resolved at call time

    return good_persistent_root()


def _read_json(path: Path) -> tuple[Any, Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"missing: {path.name}"
    except (OSError, ValueError):
        return None, f"unreadable: {path.name}"


def load_policy(path: Optional[Path] = None) -> dict[str, Any]:
    """The class allowlist and its limits. A missing or broken file disables every class."""
    doc, error = _read_json(Path(path) if path else PROJECT_ROOT / CONFIG_REL)
    if not isinstance(doc, dict) or not isinstance(doc.get("classes"), dict):
        return {"classes": {}, "max_per_hour": DEFAULT_MAX_PER_HOUR,
                "dedupe_hours": DEFAULT_DEDUPE_HOURS, "error": error or "no classes"}
    return {
        "classes": doc["classes"],
        "max_per_hour": int(doc.get("max_per_hour") or DEFAULT_MAX_PER_HOUR),
        "dedupe_hours": float(doc.get("dedupe_hours") or DEFAULT_DEDUPE_HOURS),
    }


def load_gateways(contact_path: Optional[Path] = None) -> tuple[list[str], Optional[str]]:
    """Every Fi email-to-text address, in order. Never falls back to an address in the repo."""
    try:
        path = Path(contact_path) if contact_path else _persistent_root() / CONTACT_REL
    except Exception:
        return [], "the persistent state root could not be resolved"
    doc, error = _read_json(path)
    if not isinstance(doc, dict):
        return [], error or "contact file unreadable"
    raw = doc.get("critical_sms_email_gateways")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raw = [doc.get("critical_sms_email_gateway")] if doc.get("critical_sms_email_gateway") else []
    seen, out = set(), []
    for value in raw:
        address = str(value or "").strip()
        if "@" in address and address.lower() not in seen:
            seen.add(address.lower())
            out.append(address)
    return out, None if out else "no gateway configured"


def class_enabled(policy: dict[str, Any], alert_class: str) -> bool:
    entry = (policy.get("classes") or {}).get(str(alert_class or ""))
    return bool(isinstance(entry, dict) and entry.get("enabled") is True)


def format_text(event: dict[str, Any]) -> str:
    """`ACT NOW SPCX (Roth) ext-hrs 131.20, stop 130.00 inactive till 9:30. Suggest EXT limit sell 130.90. CC Risk`"""
    def clean(value: Any) -> str:
        return " ".join(str(value or "").split())

    symbol = clean(event.get("symbol")).upper() or "PORTFOLIO"
    account = clean(event.get("account"))
    trigger = clean(event.get("trigger") or event.get("what"))
    action = clean(event.get("action") or event.get("suggested_action"))
    if not trigger:
        raise CriticalTextError("a critical text needs the number that triggered it")
    if not action:
        raise CriticalTextError("a critical text needs one suggested action")
    head = f"ACT NOW {symbol}" + (f" ({account})" if account else "")
    body = f"{head} {trigger}.".rstrip(".") + f". Suggest {action}. CC Risk"
    body = body.replace("..", ".")
    if len(body) <= MAX_TEXT_CHARS:
        return body
    room = MAX_TEXT_CHARS - len("… CC Risk")
    cut = body[:room].rsplit(" ", 1)[0].rstrip(" ,.;")
    return f"{cut}… CC Risk"


def _load_state(path: Path) -> dict[str, Any]:
    doc, _error = _read_json(path)
    if not isinstance(doc, dict):
        doc = {}
    if not isinstance(doc.get("sent"), dict):
        doc["sent"] = {}
    return doc


def _save_state(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def send_critical_text(
    event: dict[str, Any],
    *,
    sender: Optional[Callable[..., Any]] = None,
    contact_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """One event -> one text per gateway, or a refusal with the reason. Never raises for a policy stop."""
    now = now or datetime.now(timezone.utc)
    alert_class = str(event.get("alert_class") or "").strip()
    policy = load_policy(config_path)
    if not alert_class or alert_class not in (policy.get("classes") or {}):
        return {"sent": False, "reason": f"class not in the allowlist: {alert_class or '<empty>'}"}
    if not class_enabled(policy, alert_class):
        return {"sent": False, "reason": f"class switched off: {alert_class}"}
    gateways, gateway_error = load_gateways(contact_path)
    if not gateways:
        return {"sent": False, "reason": gateway_error or "no gateway configured"}
    try:
        text = format_text(event)
    except CriticalTextError as exc:
        return {"sent": False, "reason": str(exc)}

    key = str(event.get("event_id") or event.get("key") or "").strip()
    if not key:
        return {"sent": False, "reason": "a critical text needs an event id for dedupe"}
    if state_path:
        state_file = Path(state_path)
    else:
        try:
            state_file = _persistent_root() / STATE_REL
        except Exception:
            return {"sent": False, "reason": "the persistent state root could not be resolved"}
    state = _load_state(state_file)
    sent = state["sent"]
    dedupe_hours = float(policy.get("dedupe_hours") or DEFAULT_DEDUPE_HOURS)
    earlier = sent.get(key)
    if earlier:
        try:
            earlier_at = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        except ValueError:
            earlier_at = None
        if earlier_at and now - earlier_at < timedelta(hours=dedupe_hours):
            return {"sent": False, "reason": f"already texted this event at {earlier}", "deduped": key}

    cap = int(policy.get("max_per_hour") or DEFAULT_MAX_PER_HOUR)
    hour_ago = now - timedelta(hours=1)
    recent = 0
    for stamp in sent.values():
        try:
            if datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) >= hour_ago:
                recent += 1
        except ValueError:
            continue
    if recent >= cap:
        return {"sent": False, "reason": f"hourly cap reached ({recent}/{cap})"}

    send = sender
    if send is None:
        from scripts.email_notifier import send_email as send  # the existing plain-text sender

    results = []
    for gateway in gateways:
        try:
            ok = bool(send("CRITICAL", text, to=gateway))
        except Exception as exc:  # one gateway failing must not stop the other line
            ok = False
            results.append({"to": len(results), "ok": False, "error": str(exc)[:120]})
            continue
        results.append({"to": len(results), "ok": ok})

    if any(r.get("ok") for r in results):
        sent[key] = now.isoformat().replace("+00:00", "Z")
        _save_state(state_file, state)
    # The carrier gives no delivery receipt; the receipt is the send result per line, as the spec says.
    return {"sent": any(r.get("ok") for r in results), "text": text, "receipts": results,
            "class": alert_class, "gateways": len(gateways)}
