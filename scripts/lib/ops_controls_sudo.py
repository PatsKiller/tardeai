"""Ops -> Controls sudo window: one passkey assertion opens a short window in which a risky act needs only the phrase.

Operator decision 2026-10-22, verbatim: "approve sudo window". The policy text ships in AGENTS.md 19.1.0, so this is
built INERT: the window opens only while BOTH hold, read at call time —

* AGENTS.md 19.1.0 is ACTIVE with its sudo-window heading present (``ops_controls_core.policy_state`` with
  ``required=SUDO_POLICY_VERSION`` and ``anchor=SUDO_POLICY_ANCHOR``; no environment override), and
* the operator setting ``ops_controls.sudo_window_enabled`` is true in ``operator_settings`` (default false).

The window (``SudoWindows``):

* is opened by the passkey step-up of a risky request when the operator asks for it (``open_window``); that one
  assertion is the window's proof, recorded as ``assertion_id`` with its credential and time;
* lasts ``ops_controls.sudo_window_minutes`` (default 60, hard ceiling 120) from opening, and ends after 15 minutes
  without use, on "End window now", when its credential is revoked, when the setting is turned off or the policy is
  not ACTIVE, or when the Command Center process restarts (windows live in memory only: a restart fails closed);
* is bound to the operator identity, the opening credential and the browser session: the server returns a random
  window token once, keeps only its SHA-256, and the page keeps the token in ``sessionStorage`` (gone when the browser
  session ends). A window used without its token, by another identity, or after any end condition is refused;
* never covers the always-fresh kinds (``needs_fresh_passkey``): grant issue, kill-switch clear, passkey add and
  revoke, the release-train operator kinds, and changing either sudo-window setting. Those need a fresh assertion
  even inside a window, and the host applier re-checks the factor of every signed approval.

Every act made in a window is audited with the window id and the opening assertion id, credential and time. Agents
are refused before any of this runs (``ops_controls_api._post``). AUTHORITY: OPERATOR_ONLY. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

SUDO_POLICY_VERSION = "19.1.0"
#: The heading the 19.1.0 policy text must carry; without it the window stays inert even if a 19.1.0 row is ACTIVE.
SUDO_POLICY_ANCHOR = "## 27.6 Sudo window"
SETTING_ENABLED = "ops_controls.sudo_window_enabled"
SETTING_MINUTES = "ops_controls.sudo_window_minutes"
SUDO_SETTING_KEYS = frozenset({SETTING_ENABLED, SETTING_MINUTES})
DEFAULT_MINUTES = 60
HARD_MAX_MINUTES = 120
IDLE_S = 15 * 60
FACTOR = "sudo_window"
#: Kinds that need a fresh passkey assertion even inside an open window (operator decision 2026-10-22, plus the
#: release-train operator kinds, which AGENTS.md 19.0.0 §25.4 makes "a WebAuthn passkey and a typed phrase" act and
#: whose release-train proof hook accepts only factor ``passkey``).
ALWAYS_FRESH_KINDS = frozenset({
    "grant.issue", "kill_switch.clear", "passkey.register", "passkey.revoke",
    "release_train.resume", "release_train.arm", "release_train.change_scope", "release_train.revoke",
})


def needs_fresh_passkey(kind: str, params: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """The reason ``kind`` needs a fresh passkey assertion even inside a window, or None."""
    if kind in ALWAYS_FRESH_KINDS:
        return f"{kind} always needs a fresh passkey assertion, even inside a sudo window"
    if kind in ("setting.set", "setting.unset") and str((params or {}).get("key") or "") in SUDO_SETTING_KEYS:
        return "changing a sudo-window setting always needs a fresh passkey assertion"
    return None


def _setting(store: Any, key: str) -> Any:
    try:
        row = store.setting_get(key)
    except Exception:  # noqa: BLE001 — unreadable is "not enabled" (fail closed)
        return None
    return row.get("value") if row and row.get("active") else None


def gate(store: Any, agents_path: Optional[Path] = None) -> dict:
    """ACTIVE only when AGENTS.md 19.1.0 is ACTIVE (with its heading) AND the operator turned the window on."""
    from scripts.lib import ops_controls_core as C

    pol = C.policy_state(agents_path, required=SUDO_POLICY_VERSION, anchor=SUDO_POLICY_ANCHOR)
    enabled = _setting(store, SETTING_ENABLED) is True
    raw = _setting(store, SETTING_MINUTES)
    try:
        minutes = int(raw) if raw is not None and not isinstance(raw, bool) else DEFAULT_MINUTES
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES
    minutes = max(1, min(HARD_MAX_MINUTES, minutes))
    if pol["state"] != C.POLICY_ACTIVE:
        state, reason = "INERT", (f"AGENTS.md {SUDO_POLICY_VERSION} is not ACTIVE ({pol['detail']}); the sudo-window "
                                  f"policy text ships in {SUDO_POLICY_VERSION}")
    elif not enabled:
        state, reason = "INERT", f"operator setting {SETTING_ENABLED} is false (the default)"
    else:
        state, reason = "ACTIVE", None
    return {"state": state, "reason": reason, "policy": pol, "enabled": enabled, "minutes": minutes,
            "max_minutes": HARD_MAX_MINUTES, "idle_minutes": IDLE_S // 60}


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def assertion_id(credential_id: str, challenge: str) -> str:
    """A stable id for one WebAuthn assertion: its credential and its single-use challenge."""
    return "asrt_" + hashlib.sha256(f"{credential_id}|{challenge}".encode("utf-8")).hexdigest()[:24]


class SudoRefused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class Window:
    window_id: str
    token_hash: str
    operator: str
    credential_id: str
    credential_name: Optional[str]
    assertion_id: str
    opening_request_id: str
    opened_at: datetime
    expires_at: datetime
    last_used_at: datetime
    minutes: int
    uses: int = 0
    ended_at: Optional[datetime] = None
    end_reason: Optional[str] = None
    acts: list = field(default_factory=list)

    def idle_expires_at(self) -> datetime:
        return self.last_used_at + timedelta(seconds=IDLE_S)

    def linkage(self) -> dict:
        """What every act in this window is audited with."""
        from scripts.lib import ops_controls_core as C

        return {"window_id": self.window_id, "opening_assertion_id": self.assertion_id,
                "opening_credential_id8": self.credential_id[:8], "opening_credential_name": self.credential_name,
                "opened_at": C.iso(self.opened_at), "opening_request_id": self.opening_request_id}

    def view(self, now: datetime) -> dict:
        from scripts.lib import ops_controls_core as C

        end = min(self.expires_at, self.idle_expires_at())
        return {"window_id8": self.window_id[:12], "opened_at": C.iso(self.opened_at),
                "expires_at": C.iso(self.expires_at), "idle_expires_at": C.iso(self.idle_expires_at()),
                "remaining_s": max(0, int((end - now).total_seconds())), "minutes": self.minutes,
                "credential_id8": self.credential_id[:8], "credential_name": self.credential_name,
                "opening_assertion_id": self.assertion_id, "opening_request_id": self.opening_request_id,
                "uses": self.uses}


class SudoWindows:
    """In-memory window registry of one Command Center process (thread-safe). A restart ends every window."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._windows: dict[str, Window] = {}

    def open(self, *, operator: str, credential_id: str, credential_name: Optional[str], assertion: str,
             opening_request_id: str, now: datetime, minutes: int) -> tuple[Window, str, list[Window]]:
        """Open a window (ending any the operator already has). Returns (window, token, windows it replaced)."""
        minutes = max(1, min(HARD_MAX_MINUTES, int(minutes)))
        token = secrets.token_urlsafe(32)
        w = Window(window_id="sudo_" + secrets.token_hex(10), token_hash=token_hash(token), operator=operator,
                   credential_id=credential_id, credential_name=credential_name, assertion_id=assertion,
                   opening_request_id=opening_request_id, opened_at=now, expires_at=now + timedelta(minutes=minutes),
                   last_used_at=now, minutes=minutes)
        with self._lock:
            replaced = self.end(operator, "replaced by a new window", now)
            self._windows[w.window_id] = w
        return w, token, replaced

    def end(self, operator: str, reason: str, now: datetime) -> list[Window]:
        with self._lock:
            out = []
            for wid, w in list(self._windows.items()):
                if w.operator == operator:
                    w.ended_at, w.end_reason = now, reason
                    out.append(self._windows.pop(wid))
            return out

    def sweep(self, now: datetime, *, gate_state: str, gate_minutes: int,
              active_credentials: Optional[set] = None) -> list[Window]:
        """End every window whose time, idle limit, gate or credential has gone. Returns the windows ended now."""
        with self._lock:
            out = []
            for wid, w in list(self._windows.items()):
                why = self._end_reason(w, now, gate_state=gate_state, gate_minutes=gate_minutes,
                                       active_credentials=active_credentials)
                if why:
                    w.ended_at, w.end_reason = now, why
                    out.append(self._windows.pop(wid))
            return out

    @staticmethod
    def _end_reason(w: Window, now: datetime, *, gate_state: str, gate_minutes: int,
                    active_credentials: Optional[set]) -> Optional[str]:
        if gate_state != "ACTIVE":
            return "sudo window inert (policy or setting)"
        if now >= min(w.expires_at, w.opened_at + timedelta(minutes=gate_minutes)):
            return "expired"
        if now >= w.idle_expires_at():
            return f"idle {IDLE_S // 60} minutes"
        if active_credentials is not None and w.credential_id not in active_credentials:
            return "opening passkey revoked"
        return None

    def active_for(self, operator: str) -> Optional[Window]:
        with self._lock:
            for w in self._windows.values():
                if w.operator == operator:
                    return w
            return None

    def use(self, *, operator: str, token: Any, now: datetime, request_id: str) -> Window:
        """Spend one use of the operator's window. The caller sweeps first, so an ended window is already gone."""
        if not isinstance(token, str) or not token:
            raise SudoRefused("SUDO_WINDOW_TOKEN_MISSING", "this browser session holds no sudo-window token")
        th = token_hash(token)
        with self._lock:
            w = next((x for x in self._windows.values() if hmac.compare_digest(x.token_hash, th)), None)
            if w is None:
                raise SudoRefused("SUDO_WINDOW_NOT_OPEN", "no open sudo window matches this browser session (it "
                                                          "expired, idled out, was ended or the server restarted)")
            if w.operator != operator:
                raise SudoRefused("SUDO_WINDOW_NOT_OPEN", "that window belongs to another identity")
            w.uses += 1
            w.last_used_at = now
            w.acts.append(request_id)
            return w
