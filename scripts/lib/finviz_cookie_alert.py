"""One operator alert per ET day while the Finviz session cookie is dead (LQ-20261107-1289).

2026-11-08: the operator got no text and no Telegram when FINVIZ_COOKIE expired, because a dead
cookie with a working Elite API token was graded `token_ok` — healthy, `show_banner=false`, and the
health agent filed it as an `info` finding with `operator_action=false`. Every screener kept running,
so no source went stale and nothing else had a reason to speak.

This module takes the credential-health verdict the Command Center already computed and sends, at
most once per ET calendar day while the cookie stays dead:

* one Telegram message (the count and the named features), and
* one email-to-text per verified Fi line, through the communications gateway.

Both are `send_via_gateway(..., message_class="operator_alert", severity="P1")` intents: the gateway
owns delivery, the mode gate (OFF/SHADOW) blocks it before any provider I/O, and the attempt is in
the Communications ledger. **No fetch happens here** — the caller hands in the verdict, so this
module can never add a Finviz request of its own.

Dedupe is a durable state file under the persistent state root, written under a thread lock and an
exclusive ``flock`` (the same transaction `critical_texts` uses for its cap) so a restart, two
polling tabs or two server processes cannot send twice. The day key is the ET date, not the UTC
date: "today" for the operator is the New York calendar.

AUTHORITY: READ_ONLY_ADVISORY. MBI = 0. Sends words; never sizes, orders or writes to a broker.
"""
from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

STATE_REL = "data/runtime/finviz_cookie_alert_state.json"
STATE_ENV = "TRADEAI_FINVIZ_COOKIE_ALERT_STATE"
DISABLE_ENV = "TRADEAI_FINVIZ_COOKIE_ALERT"
PRODUCER = "finviz_cookie_alert"
ET_ZONE = "America/New_York"
_DEGRADED = frozenset({"expired", "missing"})


def _persistent_root() -> Path:
    try:
        from .persistent_state_root import good_persistent_root  # noqa: PLC0415
    except ImportError:
        from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415
    return good_persistent_root()


def et_day(now: Optional[datetime] = None) -> str:
    """The New York calendar date of `now` as YYYY-MM-DD. Never the UTC date."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415 — import cost belongs to the call, not the module

    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(ZoneInfo(ET_ZONE)).date().isoformat()


def cookie_state(health: Optional[dict]) -> str:
    """`ok` | `expired` | `missing` | `unknown` from a credential-health verdict.

    `unknown` never alerts: without a cookie-specific verdict the module cannot tell a dead session
    from a failed probe, and a text that guesses is worse than one that waits.
    """
    doc = health if isinstance(health, dict) else {}
    explicit = str(doc.get("cookie_status") or "").strip().lower()
    if str(doc.get("status") or "").strip().lower() == "check_failed":
        return "unknown"
    if explicit in ("ok", "expired", "missing"):
        return explicit
    status = str(doc.get("status") or "").strip().lower()
    if status == "ok":
        return "ok"
    if status == "token_ok":
        # The pre-LQ-1289 shape: cookie dead, Elite API token carrying every export.
        return "expired"
    if status == "check_failed":
        # LQ-20261107-2220: the probe itself errored; it says nothing about the cookie.
        return "unknown"
    if status in ("expired", "error"):
        return "expired"
    if status == "missing":
        return "missing"
    return "unknown"


CONFIG_REL = "config/finviz_cookie_alert.json"
_DEFAULT_THRESHOLD = 3
_DEFAULT_FAILING = ("error", "failed", "degraded", "down", "stale", "unhealthy")


def _config() -> dict:
    try:
        doc = json.loads((Path(__file__).resolve().parents[2] / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def check_failed_threshold() -> int:
    """Consecutive errored checks needed before an errored check may alert (config; never below 2)."""
    try:
        return max(2, int(_config().get("check_failed_consecutive_min", _DEFAULT_THRESHOLD)))
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD


def source_failing(health: Optional[dict]) -> bool:
    """True only when data_source_health[finviz] was READ and is in a failing status.

    An unreadable or absent status is not failing: unknown beats wrong."""
    status = str((health or {}).get("source_status") or "").strip().lower()
    if not status:
        return False
    failing = _config().get("source_failing_statuses") or _DEFAULT_FAILING
    return status in {str(x).lower() for x in failing}


def _features() -> tuple[int, list[str], str]:
    try:
        from . import finviz_cookie_features as feats  # noqa: PLC0415
    except ImportError:
        from scripts.lib import finviz_cookie_features as feats  # noqa: PLC0415
    names = feats.labels()
    return len(names), names, feats.paragraph()


def text_body(health: Optional[dict], *, count: int, names: list[str]) -> str:
    """The Fi text: plain, short, no link. Names at most the first few features so it fits a text."""
    state = cookie_state(health)
    if state == "missing":
        lead = "FINVIZ_COOKIE is not set"
    elif str((health or {}).get("status") or "").lower() == "token_ok":
        lead = "FINVIZ COOKIE EXPIRED (Elite token OK)"
    else:
        lead = "FINVIZ COOKIE AND TOKEN FAILING (screeners empty)"
    if count:
        named = ", ".join(names[:3]) + (f" +{count - 3} more" if count > 3 else "")
        body = f"{lead}: {count} features degraded ({named}). Renew FINVIZ_COOKIE in CC Admin."
    else:
        body = f"{lead}. Renew FINVIZ_COOKIE in CC Admin."
    return " ".join(body.split())[:280]


def telegram_body(health: Optional[dict], *, count: int, paragraph: str) -> str:
    """The Telegram message: HTML, the same facts, one line per degraded feature."""
    doc = health if isinstance(health, dict) else {}
    state = cookie_state(doc)
    if state == "missing":
        headline = "FINVIZ_COOKIE NOT SET"
        note = "No Finviz session cookie is configured. Only the Elite API token path can work."
    elif str(doc.get("status") or "").lower() == "token_ok":
        headline = "FINVIZ COOKIE EXPIRED"
        note = "Elite API token OK — screeners keep working. These still need the cookie:"
    else:
        headline = "FINVIZ COOKIE AND TOKEN FAILING"
        note = "Screeners and social scalp are empty. Operator action needed:"
    lines = [f"🍪 <b>{html.escape(headline)}</b>", html.escape(note)]
    if count and paragraph:
        lines.append(f"<b>{count} feature{'s' if count != 1 else ''} degraded</b>")
        for row in paragraph.splitlines():
            lines.append(html.escape(row))
    lines.append("Renew: Command Center → System → Admin → FINVIZ_COOKIE")
    detail = " ".join(str(doc.get("detail") or "").split())[:200]
    if detail:
        lines.append(f"<i>{html.escape(detail)}</i>")
    return "\n".join(lines)


def _gateway_send(channel: str, *, body: str, subject: Optional[str], to: Optional[str],
                  subject_key: str) -> dict:
    try:
        from .comms.channel_adapters import send_via_gateway  # noqa: PLC0415
    except ImportError:
        from scripts.lib.comms.channel_adapters import send_via_gateway  # noqa: PLC0415
    kwargs = {"to": to} if to else {}
    result = send_via_gateway(
        channel,
        body=body,
        subject=subject,
        producer=PRODUCER,
        subject_key=subject_key,
        event_type="operator_alert",
        message_class="operator_alert",  # the canonical vocabulary folds this to `ops` for the gate
        retention_class="operational_30d",
        severity="P1",
        deliver=True,
        **kwargs,
    )
    return result if isinstance(result, dict) else {"ok": False, "error": "invalid_gateway_result"}


def _read_state(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    return doc if isinstance(doc, dict) else {}


def _write_state(path: Path, doc: dict) -> None:
    """Atomic replace from a temp file unique to this write (same rationale as `critical_texts`)."""
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
    """Serialize read/decide/send/write for one state file (thread lock + process flock)."""
    key = os.path.realpath(path)
    with _STATE_LOCKS_GUARD:
        lock = _STATE_LOCKS.setdefault(key, threading.Lock())
    with lock:
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def maybe_alert(
    health: Optional[dict],
    *,
    now: Optional[datetime] = None,
    state_path: Path | str | None = None,
    gateways: Optional[list[str]] = None,
    contact_path: Path | str | None = None,
    send: Optional[Callable[..., dict]] = None,
) -> dict[str, Any]:
    """Evaluate one verdict and, at most once per ET day, send the operator alert.

    `health` is the Command Center credential-health result. No network read happens here.
    Returns what was decided and what each channel reported — never raises for a send failure.
    """
    if (os.environ.get(DISABLE_ENV) or "").strip().lower() in ("0", "off", "false"):
        return {"alerted": False, "reason": f"disabled by {DISABLE_ENV}", "cookie_state": cookie_state(health)}

    state = cookie_state(health)
    day = et_day(now)
    is_check_failed = str((health or {}).get("status") or "").strip().lower() == "check_failed"
    if state not in _DEGRADED and not is_check_failed:
        _reset_check_failed(health, now=now, state_path=state_path)
        return {"alerted": False, "reason": f"cookie {state}", "cookie_state": state, "et_date": day}

    if state_path:
        path = Path(state_path)
    else:
        custom = (os.environ.get(STATE_ENV) or "").strip()
        try:
            path = Path(custom) if custom else _persistent_root() / STATE_REL
        except Exception:
            return {"alerted": False, "reason": "the persistent state root could not be resolved",
                    "cookie_state": state, "et_date": day}

    sender = send or _gateway_send
    if gateways is None:
        try:
            from .critical_texts import load_gateways  # noqa: PLC0415
        except ImportError:
            from lib.critical_texts import load_gateways  # noqa: PLC0415
        gateways, gateway_error = load_gateways(contact_path)
    else:
        gateway_error = None

    count, names, paragraph = _features()

    with _state_transaction(path):
        doc = _read_state(path)
        if is_check_failed:
            return _handle_check_failed(doc, path, health, day=day, now=now, sender=sender,
                                        gateways=gateways, gateway_error=gateway_error,
                                        count=count, names=names)
        doc["check_failed_consecutive"] = 0
        transitioned = doc.get("last_cookie_state") not in _DEGRADED
        if doc.get("last_alert_et_date") == day:
            # Keep the observed state current even when the day's alert already went out.
            if doc.get("last_cookie_state") != state:
                doc["last_cookie_state"] = state
                doc["last_seen_at"] = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
                _write_state(path, doc)
            return {"alerted": False, "reason": f"already alerted on {day}", "cookie_state": state,
                    "et_date": day, "transition": False}

        at = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
        subject = "Finviz cookie expired — renew FINVIZ_COOKIE"
        results: dict[str, Any] = {"telegram": None, "texts": []}
        try:
            results["telegram"] = sender(
                "telegram",
                body=telegram_body(health, count=count, paragraph=paragraph),
                subject=subject,
                to=None,
                subject_key=f"{PRODUCER}:{day}:telegram",
            )
        except Exception as exc:  # noqa: BLE001 — one channel failing must not stop the other
            results["telegram"] = {"ok": False, "delivered": False, "error": type(exc).__name__}
        for address in gateways or []:
            slot = hashlib.sha256(str(address).encode("utf-8")).hexdigest()[:12]
            try:
                results["texts"].append(sender(
                    "email",
                    body=text_body(health, count=count, names=names),
                    subject=subject,
                    to=address,
                    subject_key=f"{PRODUCER}:{day}:sms:{slot}",
                ))
            except Exception as exc:  # noqa: BLE001 — one line failing must not stop the others
                results["texts"].append({"ok": False, "delivered": False, "error": type(exc).__name__})

        delivered = bool((results["telegram"] or {}).get("delivered")) or any(
            (r or {}).get("delivered") for r in results["texts"])
        attempted = bool(results["telegram"]) or bool(results["texts"])
        doc.update({
            "schema": "FinvizCookieAlertState@v1",
            "last_alert_et_date": day,
            "last_alert_at": at,
            "last_cookie_state": state,
            "last_transition_from": doc.get("last_cookie_state"),
            "last_alert": {
                "status": str((health or {}).get("status") or ""),
                "degraded_features": count,
                "telegram": _outcome(results["telegram"]),
                "texts": [_outcome(r) for r in results["texts"]],
                "gateways": len(gateways or []),
                "gateway_error": gateway_error,
            },
        })
        _write_state(path, doc)

    return {"alerted": attempted, "delivered": delivered, "reason": "sent" if delivered else "attempted",
            "cookie_state": state, "et_date": day, "transition": transitioned,
            "degraded_features": count, "telegram": _outcome(results["telegram"]),
            "texts": [_outcome(r) for r in results["texts"]], "gateway_error": gateway_error}


def _outcome(result: Optional[dict]) -> dict:
    """Channel result with never a recipient: ok / delivered / error only."""
    doc = result if isinstance(result, dict) else {}
    return {
        "ok": bool(doc.get("ok")),
        "delivered": bool(doc.get("delivered")),
        "error": str(doc.get("error") or "")[:120] or None,
        "gateway_mode": str(doc.get("gateway_mode") or "")[:20] or None,
    }


def _reset_check_failed(health, *, now, state_path) -> None:
    """A verdict that is not a failed check ends the consecutive run (only when a state file exists)."""
    try:
        path = Path(state_path) if state_path else None
        if path is None:
            custom = (os.environ.get(STATE_ENV) or "").strip()
            path = Path(custom) if custom else _persistent_root() / STATE_REL
        if not path.exists():
            return
        with _state_transaction(path):
            doc = _read_state(path)
            if int(doc.get("check_failed_consecutive") or 0) > 0:
                doc["check_failed_consecutive"] = 0
                _write_state(path, doc)
    except Exception:  # noqa: BLE001 — bookkeeping must not break the health route
        return


def check_failed_text(health: Optional[dict], *, telegram: bool = False) -> str:
    cls = str((health or {}).get("error_class") or "unknown error")[:60]
    body = (f"FINVIZ HEALTH CHECK ERRORING ({cls}) and the finviz data source is failing. "
            "The cookie state is UNKNOWN. Check Command Center → System → Admin.")
    return html.escape(body) if telegram else " ".join(body.split())[:280]


def _handle_check_failed(doc, path, health, *, day, now, sender, gateways, gateway_error, count, names):
    """An errored check: record class+time, count the run, alert only past the threshold AND with the
    source failing. Never says the cookie expired. Called under the state transaction."""
    at = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    n = int(doc.get("check_failed_consecutive") or 0) + 1
    doc.update({
        "schema": "FinvizCookieAlertState@v1",
        "check_failed_consecutive": n,
        "last_check_failed_class": str((health or {}).get("error_class") or "unknown")[:60],
        "last_check_failed_at": at,
    })
    need = check_failed_threshold()
    base = {"cookie_state": "unknown", "et_date": day, "check_failed_consecutive": n}
    if n < need or not source_failing(health):
        _write_state(path, doc)
        why = "below threshold" if n < need else "data source not failing"
        return {"alerted": False, "reason": f"check_failed: {why}", **base}
    if doc.get("last_check_failed_alert_et_date") == day:
        _write_state(path, doc)
        return {"alerted": False, "reason": f"already alerted on {day}", **base}
    subject = "Finviz health check erroring — cookie state unknown"
    results: dict[str, Any] = {"telegram": None, "texts": []}
    try:
        results["telegram"] = sender("telegram", body=check_failed_text(health, telegram=True), subject=subject,
                                     to=None, subject_key=f"{PRODUCER}:{day}:check_failed:telegram")
    except Exception as exc:  # noqa: BLE001
        results["telegram"] = {"ok": False, "delivered": False, "error": type(exc).__name__}
    for address in gateways or []:
        slot = hashlib.sha256(str(address).encode("utf-8")).hexdigest()[:12]
        try:
            results["texts"].append(sender("email", body=check_failed_text(health), subject=subject, to=address,
                                           subject_key=f"{PRODUCER}:{day}:check_failed:sms:{slot}"))
        except Exception as exc:  # noqa: BLE001
            results["texts"].append({"ok": False, "delivered": False, "error": type(exc).__name__})
    delivered = bool((results["telegram"] or {}).get("delivered")) or any(
        (r or {}).get("delivered") for r in results["texts"])
    doc["last_check_failed_alert_et_date"] = day
    doc["last_check_failed_alert_at"] = at
    _write_state(path, doc)
    return {"alerted": True, "delivered": delivered, "reason": "sent" if delivered else "attempted", **base,
            "telegram": _outcome(results["telegram"]), "texts": [_outcome(r) for r in results["texts"]],
            "gateway_error": gateway_error}
