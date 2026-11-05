"""The critical "act now" text channel (SPEC_CRITICAL_TEXT_ACTION_ALERTS_20261104).

One place decides whether a class may text, formats the sentence, and fans it out to every Fi
email-to-text gateway. Producers call ``send_critical_text``; they never address a phone or a
gateway themselves, and no address is ever stored in the repository.

Rules this module owns, all from the spec:
  * the class allowlist is ``config/critical_text_classes.json`` (the operator turns classes on/off there);
  * an unknown or disabled class is not sent — the channel fails closed to Telegram-only;
  * at most ``max_per_hour`` texts per hour, and one text per event id inside ``dedupe_hours``;
  * the text is plain, at most 160 characters, carries symbol/account/trigger/one action, no HTML and no links
    except the one D35 B4 carries: the full https Command Center reauth URL, built from the runtime tailnet base
    (TRADEAI_CC_LINK_BASE), never truncated and never from the repository.

Agents never place, change or cancel an order, and nothing here does: it sends words.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

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


CC_REAUTH_PATH = "/v3/system/schwab-reauth"
# D35 B4: the Schwab-login text must carry the full one-tap Command Center link. Only this class may carry a link, and the
# link is built from a runtime base URL — the tailnet hostname is an address, so it never lives in the repository.
LINK_CLASSES = frozenset({"B4_schwab_login_expiring"})
LINK_BASE_ENV = "TRADEAI_CC_LINK_BASE"
LINK_HOST_SUFFIX = ".ts.net"
# Any URL-shaped token, so a link smuggled through a producer's wording is caught where the operator would read it
# (the rendered trigger/action), not only on the dedicated `link`/`link_base` fields.
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://|\bwww\.", re.IGNORECASE)


def critical_link(base: Any) -> str:
    """The one-tap reauth URL: https, tailnet host, no dev port. Anything else is refused, never repaired."""
    from urllib.parse import urlsplit

    raw = " ".join(str(base or "").split())
    if not raw:
        raise CriticalTextError(f"{sorted(LINK_CLASSES)[0]} needs the Command Center link base ({LINK_BASE_ENV})")
    try:
        parts = urlsplit(raw)
        port = parts.port  # raises ValueError for a non-numeric/out-of-range port
    except ValueError as exc:
        # A malformed base is a policy refusal, not a crash: send_critical_text catches CriticalTextError only.
        raise CriticalTextError(f"the reauth link base is not a valid URL ({exc})") from exc
    if parts.scheme != "https":
        raise CriticalTextError(f"the reauth link must be https, not {parts.scheme or 'no scheme'!r}")
    if port not in (None, 443):
        # Covers the :7777 dev port and every other explicit port in one rule.
        raise CriticalTextError(f"the reauth link must not carry a port ({port}), including :7777")
    host = (parts.hostname or "").rstrip(".")
    if not host.endswith(LINK_HOST_SUFFIX):
        raise CriticalTextError(f"the reauth link must be the tailnet host ({LINK_HOST_SUFFIX}), not {host or 'no host'!r}")
    return f"https://{host}{CC_REAUTH_PATH}"


def _with_trigger(head: str, trigger: str, action: str, tail: str) -> str:
    """``head <trigger>. Suggest <action>.`` + tail, shortening the TRIGGER only — never the action or the tail.

    ``head``/``action``/``tail`` are fixed: the caller has already refused when they cannot fit. A trigger with no
    spaces cannot be cut on a word boundary, so it is cut hard (plus an ellipsis) rather than dropped silently; when
    there is no room left at all it is omitted, leaving the action and any link intact.
    """
    fixed = f"{head}. Suggest {action}."
    room = MAX_TEXT_CHARS - len(fixed) - len(tail) - 2  # -2 leaves one spare for the ellipsis and one for a space
    if len(trigger) <= room:
        sentence = f"{head} {trigger}. Suggest {action}." + tail
    elif room < 2:
        sentence = fixed + tail
    else:
        piece = trigger[:room]
        if " " in piece:
            piece = piece.rsplit(" ", 1)[0]
        piece = piece.rstrip(" ,.;") + "…"
        sentence = f"{head} {piece}. Suggest {action}." + tail
    return sentence.replace("..", ".")  # a trigger that ends in "." must not become ".. Suggest"


def format_text(event: dict[str, Any], *, link_base: Any = None) -> str:
    """`ACT NOW SPCX (Roth) ext-hrs 131.20, stop 130.00 inactive till 9:30. Suggest EXT limit sell 130.90. CC Risk`"""
    import os

    def clean(value: Any) -> str:
        return " ".join(str(value or "").split())

    alert_class = clean(event.get("alert_class"))
    symbol = clean(event.get("symbol")).upper() or "PORTFOLIO"
    account = clean(event.get("account"))
    trigger = clean(event.get("trigger") or event.get("what"))
    action = clean(event.get("action") or event.get("suggested_action"))
    if not trigger:
        raise CriticalTextError("a critical text needs the number that triggered it")
    if not action:
        raise CriticalTextError("a critical text needs one suggested action")
    head = f"ACT NOW {symbol}" + (f" ({account})" if account else "")
    if alert_class in LINK_CLASSES:
        # D35 B4: the login text is useless without the one-tap page, so the link is required and is never truncated.
        # A producer may hand in the finished page (critical_producers._b4 sets ``link``); it is normalised through the
        # same validation, so a prebuilt URL can be a convenience but never a way around the https/tailnet/no-port rule.
        link = critical_link(link_base or os.environ.get(LINK_BASE_ENV) or event.get("link_base")
                             or event.get("link"))
    else:
        if event.get("link") or event.get("link_base"):
            raise CriticalTextError(f"{alert_class or 'this class'} may not carry a link; only {sorted(LINK_CLASSES)} do")
        # The invariant is about the sentence the operator reads, not only the two fields it was stored in.
        if _URL_IN_TEXT.search(f"{head} {trigger} {action}"):
            raise CriticalTextError(f"{alert_class or 'this class'} may not carry a link; only {sorted(LINK_CLASSES)} do")
        link = ""

    refuse_link = "the reauth link does not fit in one 160-character text"
    if link:
        if link in trigger:
            # The URL sits in the trigger; shortening it would cut the link, so fit whole or refuse.
            sentence = f"{head} {trigger}. Suggest {action}."
            if len(sentence) + len(" CC Risk") > MAX_TEXT_CHARS:
                raise CriticalTextError(refuse_link)
            return (sentence + " CC Risk").replace("..", ".")
        if link in action:
            # The producer's sentence already carries the finished URL: never repeat it, and never shorten the action.
            # If even ``head + action + CC Risk`` cannot fit, refuse — a cut URL is worse than no text.
            tail = " CC Risk"
            if len(f"{head}. Suggest {action}.") + len(tail) > MAX_TEXT_CHARS:
                raise CriticalTextError(refuse_link)
            return _with_trigger(head, trigger, action, tail)
        # Append the URL, reserving its room before the trigger is shortened. The action must survive whole; if the
        # action plus the link cannot fit, refuse rather than slice the sentence (and possibly the link) to 160.
        tail = f" Log in: {link} CC Risk"
        if len(f"{head}. Suggest {action}.") + len(tail) > MAX_TEXT_CHARS:
            raise CriticalTextError(refuse_link)
        return _with_trigger(head, trigger, action, tail)

    # No link: the action survives and the trigger is shortened first. If even the action cannot fit, a cut action is
    # the only honest option left (there is no URL to break, and dropping the alert would be worse).
    fixed = f"{head}. Suggest {action}."
    tail = " CC Risk"
    if len(fixed) + len(tail) > MAX_TEXT_CHARS:
        return (fixed + tail)[:MAX_TEXT_CHARS]
    return _with_trigger(head, trigger, action, tail)


def _parse_stamp(value: Any) -> Optional[datetime]:
    """A recorded dispatch timestamp, or None when it cannot be read. Stamps are written with a Z suffix."""
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def _hourly_texts(state: dict[str, Any], hour_ago: datetime) -> int:
    """Texts already dispatched in the last hour, from the dispatch history.

    Codex cloud at 649467060: this counted ``sent`` — the event-dedupe map — so repeating ONE event overwrote its
    single timestamp and the cap kept seeing one event. With dedupe_hours 0.1 and two gateways, nine sends seven
    minutes apart put 18 texts on the two lines against a cap of 10. The two questions are different records: "have
    I already texted this event?" is `sent`; "how many texts left in the last hour?" is `history`.
    """
    total = 0
    for entry in state.get("history") or []:
        if not isinstance(entry, dict):
            continue
        at = _parse_stamp(entry.get("at"))
        if at is not None and at >= hour_ago:
            total += int(entry.get("texts") or 0)
    return total


def _load_state(path: Path) -> dict[str, Any]:
    doc, _error = _read_json(path)
    if not isinstance(doc, dict):
        doc = {}
    if not isinstance(doc.get("sent"), dict):
        doc["sent"] = {}
    if not isinstance(doc.get("history"), list):
        doc["history"] = []
    return doc


def _save_state(path: Path, doc: dict[str, Any]) -> None:
    """Replace the state file atomically from a temp file unique to this write.

    A shared ``<name>.tmp`` was itself a race: two overlapping saves wrote the same path, so one replaced the
    file with the other's partial content. ``mkstemp`` gives every write its own name in the same directory,
    which is what makes the final ``replace`` atomic.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


_STATE_LOCKS: dict[str, threading.Lock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


@contextmanager
def _state_transaction(path: Path) -> Iterator[None]:
    """Serialize dedupe + cap + dispatch + save for one state file.

    Two overlapping producers (threads in one process, or separate poller processes) used to load the same
    previous state before either recorded its send, so both passed dedupe and the hourly cap and the same
    alert left twice. Atomic replacement does not help a read/check/send/write transaction: the decision and
    the write must be under one lock. A thread lock covers threads (``flock`` is per-process on some systems
    and does not order two threads that opened the file separately); an exclusive ``flock`` on a sibling
    ``.lock`` file covers processes. Both are held across dispatch, because the cap is a reservation made
    before the send, not a note written after it.
    """
    key = os.path.realpath(path)
    with _STATE_LOCKS_GUARD:
        thread_lock = _STATE_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _gateway_sender(event_key: str) -> Callable[..., bool]:
    """The default dispatch: one communications-gateway email intent per Fi line.

    AGENTS.md 24.1: a sender hands the host communications gateway an intent (producer, subject key, class,
    severity, body), never a provider call. ``send_via_gateway`` publishes the CommunicationEvent (the
    operator's communications history) and its ChannelDelivery ledger row; delivery belongs to the gateway,
    so an attempt and its failure are recorded even when the gateway mode blocks the send. The critical-text
    policy — allowlist, dedupe, hourly cap and the 160-character sentence — has already decided above; this
    function only carries the finished sentence to the gateway.
    """

    def send(subject: str, body: str, to: Optional[str] = None, attachments: Any = None) -> bool:
        from scripts.lib.comms.channel_adapters import send_via_gateway  # noqa: PLC0415 — call time, not import time

        recipient = str(to or "").strip()
        # Per-line subject key without storing the carrier address: the hash is stable for a given line.
        slot = hashlib.sha256(recipient.encode("utf-8")).hexdigest()[:12]
        result = send_via_gateway(
            "email",
            body=body,
            subject=subject,
            producer="critical_texts",
            subject_key=f"critical_text:{event_key}:{slot}",
            event_type="critical_text",
            message_class="ops",
            retention_class="operational_30d",
            severity="P1",
            deliver=True,
            to=recipient,
        )
        return bool(result.get("delivered"))

    return send


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
        text = format_text(event, link_base=event.get("link_base"))
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

    with _state_transaction(state_file):
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
        # The cap is on TEXTS, not events: one event fans out to every verified Fi line, so counting events
        # would report 10/10 while 20 texts left the building (review, 2026-11-05). It is counted from the
        # dispatch history, never from the event-dedupe map: a repeated event overwrites its own dedupe stamp, so
        # counting that map let the same event send without limit (cloud at 649467060).
        texts_in_hour = _hourly_texts(state, hour_ago)
        if texts_in_hour + len(gateways) > cap:
            return {"sent": False, "reason": f"hourly text cap reached ({texts_in_hour}/{cap} texts in the last hour)"}

        send = sender if sender is not None else _gateway_sender(key)

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
            stamp = now.isoformat().replace("+00:00", "Z")
            history = [entry for entry in state.get("history") or [] if isinstance(entry, dict)]
            history.append({"at": stamp, "texts": sum(1 for r in results if r.get("ok"))})
            # Two hours is enough to answer the one-hour question across a clock step, and bounds the file.
            horizon = now - timedelta(hours=2)
            state["history"] = [entry for entry in history
                                if (_parse_stamp(entry.get("at")) or horizon) >= horizon]
            _save_state(state_file, state)
    # The carrier gives no delivery receipt; the receipt is the send result per line, as the spec says.
    return {"sent": any(r.get("ok") for r in results), "text": text, "receipts": results,
            "class": alert_class, "gateways": len(gateways)}
