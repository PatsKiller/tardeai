"""trading_lock.py — the READ-ONLY broker lock (incident SPCX 2026-10-14).

Operator directive 2026-10-14: "lock it, block cancels too". The system is READ-ONLY toward every
broker. Every order write (place, replace AND cancel) on every write path calls

    assert_trading_unlocked(action, broker=..., account=..., caller=...)

as its FIRST statement, and that call raises ``TradingLocked`` unless an operator-only unlock is in
force. Principle: stopping is easy, re-enabling is hard. Fail secure: when the lock state is missing,
unreadable, malformed, expired or ambiguous, trading is LOCKED.

Lock state
----------
LOCKED unless ALL of these hold:
  1. no PANIC file at ``PANIC_LOCK_PATH`` (``~/.local/state/tradeai/TRADING_LOCKED``). Its presence —
     or any error other than "does not exist" while checking it — locks, whatever the unlock file says.
     Any process may create it; creating it is how a future PANIC button stops trading.
  2. an unlock file at ``UNLOCK_PATH`` (``~/.config/tradeai/trading_unlock.json``, outside every repo,
     worktree and release dir) that is a regular file (not a symlink), owned by this uid, not group- or
     world-writable, at most 4 KiB, and holds a JSON object with:
        "unlocked_until": ISO-8601 timestamp WITH a timezone, in the future, and no more than
                          ``MAX_UNLOCK_HOURS`` ahead (a "2099" standing unlock is malformed → locked)
        "reason":         non-empty string
        "operator":       non-empty string
        "brokers":        non-empty list of broker names this unlock covers (e.g. ["schwab"])
        "actions":        optional list from {"place","replace","cancel"}; absent = all three
     Anything else → LOCKED.

No code path creates the unlock file. Neither does this module (it only reads it). The unlock UI
(WebAuthn + TOTP + cool-down) is a later step; until then the operator writes the file by hand — see
``docs/runbooks/TRADING_LOCK.md``.

Alpaca PAPER is training, not trading (operator rule): ``broker="alpaca_paper"`` or
``broker="alpaca", environment="paper"`` is ALLOWED while locked. Use ``alpaca_environment(base_url)``
to classify a base URL — only the exact host ``paper-api.alpaca.markets`` is paper; every other host
(``api.alpaca.markets`` included) is LIVE and locked.

Every refusal appends one JSONL row to the audit ledger
(``<persistent-state>/data/runtime/trading_lock_audit.jsonl``) and sends a P0 operator alert at most
once per hour per caller through the house send path (``telegram_alert.send_telegram`` with an explicit
``priority="P1"`` intent, the highest intent priority: never digested, never quiet-held, never capped).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

# One module object whichever way it is imported (``lib.trading_lock`` from scripts/ on sys.path,
# ``scripts.lib.trading_lock`` from the repo root), so a test seam patched on one is seen by both.
for _alias in ("lib.trading_lock", "scripts.lib.trading_lock"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

UNLOCK_PATH = Path.home() / ".config" / "tradeai" / "trading_unlock.json"
PANIC_LOCK_PATH = Path.home() / ".local" / "state" / "tradeai" / "TRADING_LOCKED"
MAX_UNLOCK_HOURS = 24
MAX_UNLOCK_BYTES = 4096
ALERT_INTERVAL_SECONDS = 3600

WRITE_ACTIONS = ("place", "replace", "cancel")
_ACTION_ALIASES = {
    "place": "place", "submit": "place", "order": "place", "execute": "place", "route": "place",
    "confirm": "place", "approve": "place", "request": "place", "arm": "place",
    "replace": "replace", "modify": "replace",
    "cancel": "cancel", "delete": "cancel", "close": "place",
}
PAPER_BROKERS = ("alpaca_paper",)
ALPACA_PAPER_HOST = "paper-api.alpaca.markets"

# Test seams (in-process only; there is deliberately NO environment variable that moves the unlock path).
_ALERT_SENDER: Callable[[str], Any] | None = None
_CLOCK: Callable[[], _dt.datetime] = lambda: _dt.datetime.now(_dt.timezone.utc)


class TradingLocked(RuntimeError):
    """Raised by assert_trading_unlocked when a broker write is refused."""

    def __init__(self, message: str, *, action: str, broker: str, account: str | None,
                 caller: str | None, lock_reason: str):
        super().__init__(message)
        self.action = action
        self.broker = broker
        self.account = account
        self.caller = caller
        self.lock_reason = lock_reason

    def payload(self) -> dict:
        """A structured refusal for routes/handlers that return dicts instead of raising."""
        return {"ok": False, "status": "trading_locked", "mode": "trading_locked", "locked": True,
                "broker_submitted": False,
                "stage": "trading_lock", "action": self.action, "broker": self.broker,
                "reason": self.lock_reason, "error": str(self)}


def normalize_action(action: str | None) -> str:
    a = str(action or "").strip().lower()
    return _ACTION_ALIASES.get(a, a or "unknown")


def alpaca_environment(base_url: str | None) -> str:
    """'paper' only for the exact Alpaca paper host; anything else (including unparsable) is 'live'."""
    try:
        host = (urlparse(str(base_url or "")).hostname or "").lower()
    except Exception:
        return "live"
    return "paper" if host == ALPACA_PAPER_HOST else "live"


def is_paper(broker: str | None, environment: str | None = None) -> bool:
    b = str(broker or "").strip().lower()
    if b in PAPER_BROKERS:
        return True
    return b == "alpaca" and str(environment or "").strip().lower() == "paper"


def _parse_ts(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ts = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None          # a naive timestamp is ambiguous → locked
    return ts


def lock_state(*, broker: str | None = None, action: str | None = None) -> dict:
    """Pure read of the lock. Never raises. ``locked`` is True unless every unlock condition holds
    (for ``broker``/``action`` when given)."""
    now = _CLOCK()
    # 1. PANIC file — presence (or an unexplained stat error) locks unconditionally.
    try:
        os.lstat(PANIC_LOCK_PATH)
        return {"locked": True, "reason": f"panic lock present at {PANIC_LOCK_PATH}"}
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — unreadable lock state is LOCKED
        return {"locked": True, "reason": f"panic lock state unreadable ({type(e).__name__})"}
    # 2. Unlock file.
    try:
        st = os.lstat(UNLOCK_PATH)
    except FileNotFoundError:
        return {"locked": True, "reason": "no operator unlock file (default: locked)"}
    except Exception as e:  # noqa: BLE001
        return {"locked": True, "reason": f"unlock file unreadable ({type(e).__name__})"}
    try:
        if not stat.S_ISREG(st.st_mode):
            return {"locked": True, "reason": "unlock file is not a regular file (symlinks refused)"}
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return {"locked": True, "reason": "unlock file not owned by this user"}
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return {"locked": True, "reason": "unlock file is group/world writable"}
        if st.st_size > MAX_UNLOCK_BYTES:
            return {"locked": True, "reason": "unlock file too large"}
        with open(UNLOCK_PATH, "r", encoding="utf-8") as fh:
            doc = json.loads(fh.read(MAX_UNLOCK_BYTES + 1))
    except Exception as e:  # noqa: BLE001
        return {"locked": True, "reason": f"unlock file unreadable/malformed ({type(e).__name__})"}
    if not isinstance(doc, dict):
        return {"locked": True, "reason": "unlock file is not a JSON object"}
    until = _parse_ts(doc.get("unlocked_until"))
    if until is None:
        return {"locked": True, "reason": "unlock file has no valid timezone-aware unlocked_until"}
    if until <= now:
        return {"locked": True, "reason": f"unlock expired at {until.isoformat()}"}
    if until - now > _dt.timedelta(hours=MAX_UNLOCK_HOURS):
        return {"locked": True,
                "reason": f"unlock horizon exceeds {MAX_UNLOCK_HOURS}h (standing unlocks are refused)"}
    reason = doc.get("reason")
    operator = doc.get("operator")
    if not (isinstance(reason, str) and reason.strip()):
        return {"locked": True, "reason": "unlock file has no reason"}
    if not (isinstance(operator, str) and operator.strip()):
        return {"locked": True, "reason": "unlock file has no operator"}
    brokers = doc.get("brokers")
    if not (isinstance(brokers, list) and brokers and all(isinstance(b, str) and b.strip() for b in brokers)):
        return {"locked": True, "reason": "unlock file has no explicit brokers list"}
    brokers_n = {b.strip().lower() for b in brokers}
    actions = doc.get("actions")
    if actions is None:
        actions_n = set(WRITE_ACTIONS)
    elif isinstance(actions, list) and actions and all(isinstance(a, str) for a in actions):
        actions_n = {normalize_action(a) for a in actions}
        if not actions_n <= set(WRITE_ACTIONS):
            return {"locked": True, "reason": "unlock file lists an unknown action"}
    else:
        return {"locked": True, "reason": "unlock file actions is malformed"}
    if broker is not None and str(broker).strip().lower() not in brokers_n:
        return {"locked": True, "reason": f"unlock does not cover broker {broker!r}"}
    if action is not None and normalize_action(action) not in actions_n:
        return {"locked": True, "reason": f"unlock does not cover action {normalize_action(action)!r}"}
    return {"locked": False, "reason": reason.strip(), "operator": operator.strip(),
            "unlocked_until": until.isoformat(), "brokers": sorted(brokers_n), "actions": sorted(actions_n)}


def is_trading_locked(*, broker: str | None = None, action: str | None = None,
                      environment: str | None = None) -> bool:
    """Non-raising, non-alerting query (for status pages and arm-state precedence)."""
    if is_paper(broker, environment):
        return False
    try:
        return bool(lock_state(broker=broker, action=action).get("locked", True))
    except Exception:  # noqa: BLE001
        return True


# ── audit + alert ─────────────────────────────────────────────────────────────────────────────────
def audit_path() -> Path:
    env = os.environ.get("TRADEAI_TRADING_LOCK_AUDIT_PATH")
    if env:
        return Path(env)
    try:
        try:
            from lib.canonical_store_registry import production_state_root
        except ImportError:
            from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
        root = production_state_root()
    except Exception:  # noqa: BLE001
        root = Path(__file__).resolve().parents[2]
    return Path(root) / "data" / "runtime" / "trading_lock_audit.jsonl"


def _alert_state_path() -> Path:
    return audit_path().with_name("trading_lock_alert_state.json")


def _audit(row: dict) -> None:
    try:
        p = audit_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except Exception as e:  # noqa: BLE001 — an audit failure never unlocks anything
        print(f"[trading_lock] audit write failed: {type(e).__name__}: {e}", file=sys.stderr)


def _under_test() -> bool:
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _send_alert(message: str) -> bool:
    if _ALERT_SENDER is not None:
        _ALERT_SENDER(message)
        return True
    if _under_test():
        return False         # never page the operator from a test process
    try:
        try:
            from telegram_alert import send_telegram
        except ImportError:
            from scripts.telegram_alert import send_telegram  # type: ignore
        return bool(send_telegram(message, message_class="operator_alert", priority="P1",
                                  dedupe_minutes=0, producer="trading_lock"))
    except Exception as e:  # noqa: BLE001
        print(f"[trading_lock] alert send failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def _maybe_alert(caller: str, message: str) -> bool:
    """At most one alert per caller per ALERT_INTERVAL_SECONDS (state beside the audit ledger)."""
    now = time.time()
    path = _alert_state_path()
    state: dict = {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except Exception:  # noqa: BLE001
        state = {}
    last = state.get(caller)
    if isinstance(last, (int, float)) and now - last < ALERT_INTERVAL_SECONDS:
        return False
    state[caller] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass
    try:
        return _send_alert(message)
    except Exception:  # noqa: BLE001
        return False


def assert_trading_unlocked(action: str, *, broker: str, account: str | None = None,
                            caller: str | None = None, environment: str | None = None) -> dict:
    """THE broker write gate. Call it FIRST on every place/replace/cancel path.

    Returns the lock state when the write may proceed (Alpaca paper, or a valid operator unlock that
    covers this broker and action). Otherwise audits, alerts (≤1/h per caller) and raises TradingLocked.
    """
    act = normalize_action(action)
    b = str(broker or "").strip().lower() or "unknown"
    who = str(caller or "unknown")
    if is_paper(b, environment):
        return {"locked": False, "paper": True, "reason": "alpaca paper is training (always allowed)"}
    try:
        state = lock_state(broker=b, action=act)
    except Exception as e:  # noqa: BLE001
        state = {"locked": True, "reason": f"lock state error ({type(e).__name__})"}
    now = _CLOCK().isoformat()
    if not state.get("locked", True):
        _audit({"ts": now, "event": "allowed_by_operator_unlock", "action": act, "broker": b,
                "account": account, "caller": who, "unlocked_until": state.get("unlocked_until"),
                "unlock_operator": state.get("operator"), "unlock_reason": state.get("reason")})
        return state
    reason = str(state.get("reason") or "locked")
    msg = (f"TRADING LOCKED: refused {act} on {b}"
           + (f" account {account}" if account else "") + f" (caller {who}) — {reason}. "
           "The system is read-only toward brokers; nothing was sent.")
    _audit({"ts": now, "event": "refused", "action": act, "broker": b, "account": account,
            "caller": who, "lock_reason": reason, "pid": os.getpid()})
    _maybe_alert(who, "P0 URGENT " + msg + " Unlock is operator-only (docs/runbooks/TRADING_LOCK.md).")
    raise TradingLocked(msg, action=act, broker=b, account=account, caller=who, lock_reason=reason)


def status() -> dict:
    """Read-only summary for status endpoints."""
    st = lock_state()
    return {"locked": bool(st.get("locked", True)), **st, "unlock_path": str(UNLOCK_PATH),
            "panic_lock_path": str(PANIC_LOCK_PATH), "max_unlock_hours": MAX_UNLOCK_HOURS}


if __name__ == "__main__":
    print(json.dumps(status(), indent=2, default=str))
