"""Command Center TOTP step-up (RFC 6238 over RFC 4226), 2026-10-16.

Second factor for the dangerous route classes in config/cc_auth.yaml ``step_up.routes``. Stdlib only
(hmac + hashlib + struct): pyotp is not in requirements, and this is ~40 lines checked against the
RFC 4226 / RFC 6238 test vectors in tests/test_cc_totp_step_up_20261016.py.

Trust model
-----------
* The shared secret lives in ONE 0600 file outside the repo (``step_up.totp.secret_file``), written
  only by the operator-run enrollment CLI (scripts/cc_totp_enroll.py) after a verified code. This
  module reads it only inside :meth:`StepUpManager.verify` / :meth:`StepUpManager.status`, never logs
  it, and refuses a file that is group/other accessible, not a regular file, or owned by another uid.
* Disabled unless config ``step_up.totp.enabled: true`` AND an activated secret file exists. Either
  missing => cc_auth refuses exactly as it did before this module existed.
* A verified code grants a short unlock bound to (tailnet login, action class) on the serve_proxy
  listener. The service-token listener never satisfies step-up, never verifies a code.
* Replay: the accepted time-step counter is persisted; a code at or below it is refused (so a code
  can never be used twice, including the one typed at enrollment).
* Rate limit: ``max_failures`` bad codes inside ``failure_window_seconds`` lock verification for
  ``lockout_seconds`` (persisted, so a restart does not reset it). A correct code during lockout is
  still refused. Every attempt is written to the cc_auth decision log (never the code).
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import struct
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlencode

DIGESTS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
SECRET_SCHEMA = "CcTotpSecret@v1"
STATE_SCHEMA = "CcTotpState@v1"


# ── RFC 4226 / RFC 6238 ──────────────────────────────────────────────────────

def hotp(key: bytes, counter: int, digits: int = 6, algorithm: str = "SHA1") -> str:
    """RFC 4226 HOTP value for ``counter`` (dynamic truncation, zero-padded)."""
    mac = hmac.new(key, struct.pack(">Q", int(counter)), DIGESTS[algorithm]).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def time_step(t: float, period: int = 30, t0: int = 0) -> int:
    return int((float(t) - t0) // period)


def totp(key: bytes, t: float, *, period: int = 30, digits: int = 6, algorithm: str = "SHA1") -> str:
    """RFC 6238 TOTP value at unix time ``t``."""
    return hotp(key, time_step(t, period), digits, algorithm)


def normalize_code(code: Any, digits: int = 6) -> str | None:
    s = re.sub(r"[\s-]", "", str(code or ""))
    return s if re.fullmatch(rf"\d{{{digits}}}", s) else None


def match_counter(key: bytes, code: Any, t: float, *, period: int = 30, digits: int = 6,
                  algorithm: str = "SHA1", window: int = 1) -> int | None:
    """The time-step counter in [now-window, now+window] whose TOTP equals ``code``, else None.

    Every candidate is compared in constant time; the highest matching counter wins.
    """
    norm = normalize_code(code, digits)
    if norm is None:
        return None
    now = time_step(t, period)
    found = None
    for c in range(now - window, now + window + 1):
        if c < 0:
            continue
        if hmac.compare_digest(hotp(key, c, digits, algorithm).encode(), norm.encode()):
            found = c
    return found


def decode_secret(b32: str) -> bytes:
    s = re.sub(r"\s", "", str(b32 or "")).upper().rstrip("=")
    if not s:
        raise ValueError("empty secret")
    try:
        return base64.b32decode(s + "=" * (-len(s) % 8))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("secret is not base32") from exc


def generate_secret(nbytes: int = 20) -> str:
    """A fresh base32 secret (160 bits by default, RFC 4226 §4 recommendation). Enrollment CLI only."""
    return base64.b32encode(secrets.token_bytes(nbytes)).decode().rstrip("=")


def provisioning_uri(secret_b32: str, *, account: str, issuer: str, digits: int = 6, period: int = 30,
                     algorithm: str = "SHA1") -> str:
    label = quote(f"{issuer}:{account}", safe="@:")
    q = urlencode({"secret": secret_b32, "issuer": issuer, "algorithm": algorithm,
                   "digits": digits, "period": period}, quote_via=quote)
    return f"otpauth://totp/{label}?{q}"


# ── settings ─────────────────────────────────────────────────────────────────

def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _path(v: Any) -> Path | None:
    if v in (None, ""):
        return None
    expanded = os.path.expanduser(os.path.expandvars(str(v)))
    if "$" in expanded or not os.path.isabs(expanded):
        return None
    return Path(expanded)


@dataclass(frozen=True)
class TotpSettings:
    enabled: bool = False
    secret_file: Path | None = None
    state_file: Path | None = None
    issuer: str = "TradeAI CC"
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"
    window: int = 1
    unlock_seconds: int = 600
    max_failures: int = 5
    failure_window_seconds: int = 300
    lockout_seconds: int = 900
    actions: frozenset[str] = field(default_factory=frozenset)


def settings_from_mapping(raw: Mapping[str, Any] | None) -> TotpSettings:
    """Parse ``cc_auth.step_up.totp``. Anything missing or malformed => disabled / safe bounds."""
    t = dict(raw or {})
    alg = str(t.get("algorithm") or "SHA1").upper()
    digits = int(t.get("digits") or 6) if str(t.get("digits") or 6) in {"6", "8"} else 6
    return TotpSettings(
        enabled=t.get("enabled") is True,  # only a literal YAML true enables it
        secret_file=_path(t.get("secret_file")),
        state_file=_path(t.get("state_file")),
        issuer=str(t.get("issuer") or "TradeAI CC"),
        digits=digits,
        period=_clamp(t.get("period"), 30, 60, 30),
        algorithm=alg if alg in DIGESTS else "SHA1",
        window=_clamp(t.get("window"), 0, 1, 1),  # never wider than ±1 step
        unlock_seconds=_clamp(t.get("unlock_seconds"), 60, 1800, 600),
        max_failures=_clamp(t.get("max_failures"), 1, 10, 5),
        failure_window_seconds=_clamp(t.get("failure_window_seconds"), 60, 3600, 300),
        lockout_seconds=_clamp(t.get("lockout_seconds"), 60, 86400, 900),
        actions=frozenset(str(a).strip() for a in (t.get("actions") or []) if str(a).strip()),
    )


# ── secret + state files ─────────────────────────────────────────────────────

def check_private_file(path: Path | None) -> str:
    """'' when ``path`` is a regular file, owned by this uid, with no group/other bits; else the problem."""
    if path is None:
        return "no path configured"
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return f"missing: {path}"
    except OSError as exc:
        return f"unreadable: {type(exc).__name__}"
    if not stat.S_ISREG(st.st_mode):
        return "not a regular file"
    if st.st_mode & 0o077:
        return f"mode {oct(st.st_mode & 0o777)} is group/other accessible; chmod 600"
    if st.st_uid != os.getuid():
        return "owned by another uid"
    return ""


def load_secret(path: Path | None) -> tuple[bytes | None, dict, str]:
    """(key, metadata-without-secret, problem). Only an ACTIVATED secret file is returned."""
    problem = check_private_file(path)
    if problem:
        return None, {}, problem
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))  # type: ignore[arg-type]
        if not isinstance(doc, dict) or doc.get("schema") != SECRET_SCHEMA:
            return None, {}, "secret file has the wrong schema"
        if not doc.get("activated_at"):
            return None, {}, "secret file not activated (enrollment not verified)"
        key = decode_secret(doc.get("secret_b32", ""))
        if len(key) < 16:
            return None, {}, "secret shorter than 128 bits"
    except Exception as exc:  # noqa: BLE001 — never echo file content
        return None, {}, f"secret file unparseable: {type(exc).__name__}"
    meta = {k: v for k, v in doc.items() if k != "secret_b32"}
    return key, meta, ""


def write_private_json(path: Path, doc: dict, *, exclusive: bool = False) -> None:
    """Atomic 0600 write (tmp + rename) in a 0700 parent. ``exclusive`` refuses to replace a file."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if exclusive and os.path.lexists(path):
        raise FileExistsError(str(path))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if exclusive:
            os.link(tmp, path)  # fails if path appeared meanwhile
            os.unlink(tmp)
        else:
            os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def _fresh_state() -> dict:
    return {"schema": STATE_SCHEMA, "last_counter": -1, "failures": [], "locked_until": 0.0}


def read_state(path: Path | None) -> tuple[dict | None, str]:
    """(state, problem). Missing => fresh state. Present but unsafe/corrupt => (None, problem): fail closed."""
    if path is None:
        return None, "no state_file configured"
    if not os.path.lexists(path):
        return _fresh_state(), ""
    problem = check_private_file(path)
    if problem:
        return None, f"state file {problem}"
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("schema") != STATE_SCHEMA:
            return None, "state file has the wrong schema"
        doc["last_counter"] = int(doc.get("last_counter", -1))
        doc["failures"] = [float(x) for x in (doc.get("failures") or [])]
        doc["locked_until"] = float(doc.get("locked_until") or 0.0)
        return doc, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"state file unparseable: {type(exc).__name__}"


@contextmanager
def state_lock(path: Path):
    """Cross-process lock (server + enrollment CLI) on a sidecar file."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ── step-up manager ──────────────────────────────────────────────────────────

LogFn = Callable[[dict], None]


class StepUpManager:
    """Verification, replay/rate-limit state, and in-memory unlocks for one TOTP secret.

    Unlocks live in process memory only: a server restart clears every unlock (fail closed).
    """

    def __init__(self, settings: TotpSettings, *, log: LogFn | None = None,
                 clock: Callable[[], float] = time.time):
        self.settings = settings
        self.log = log or (lambda row: None)
        self.clock = clock
        self._lock = threading.Lock()
        self._unlocks: dict[tuple[str, str], float] = {}

    # -- availability ---------------------------------------------------------
    def status(self, *, read_secret: bool = True) -> tuple[bool, str]:
        """(active, why). Active only when config enables it AND an activated secret file exists.

        ``read_secret=False`` (diagnostic CLIs an agent may run) only stats the file: it never opens it.
        """
        s = self.settings
        if not s.enabled:
            return False, "totp disabled in config"
        if s.state_file is None:
            return False, "no state_file configured"
        if not read_secret:
            problem = check_private_file(s.secret_file)
            return (not problem), (f"secret file {problem}" if problem else "")
        key, _meta, problem = load_secret(s.secret_file)  # activated + 0600 + own uid; key discarded
        del key
        if problem:
            return False, f"secret file {problem}"
        return True, ""

    # -- unlocks --------------------------------------------------------------
    def unlocked_until(self, principal: str, action: str) -> float:
        now = self.clock()
        with self._lock:
            exp = self._unlocks.get((principal, action), 0.0)
            if exp and exp <= now:
                self._unlocks.pop((principal, action), None)
                return 0.0
            return exp

    def is_unlocked(self, principal: str, action: str) -> bool:
        return bool(principal) and self.unlocked_until(principal, action) > self.clock()

    def revoke_all(self) -> None:
        with self._lock:
            self._unlocks.clear()

    # -- verification ---------------------------------------------------------
    def verify(self, *, principal: str, action: str, code: Any) -> tuple[int, dict]:
        """Check one code for (principal, action). Caller has already enforced listener + identity."""
        s = self.settings
        now = self.clock()
        base = {"principal": principal, "step_up_action": action}

        def _out(status: int, outcome: str, body: dict) -> tuple[int, dict]:
            self.log({**base, "outcome": outcome, "status": status, "reason": body.get("error", "ok")})
            return status, {"ok": status == 200, "action": action, **body}

        active, why = self.status()
        if not active:
            return _out(403, "refused", {"error": f"step-up unavailable ({why})"})
        if normalize_code(code, s.digits) is None:
            return _out(400, "malformed", {"error": f"enter the {s.digits}-digit code from your authenticator"})
        with state_lock(s.state_file):  # type: ignore[arg-type]
            state, problem = read_state(s.state_file)
            if state is None:
                return _out(503, "refused", {"error": f"step-up state unusable ({problem}); nothing unlocked"})
            if state["locked_until"] > now:
                return _out(429, "lockout_active", {
                    "error": "too many wrong codes — step-up is locked", "locked_until": state["locked_until"]})
            key, _meta, kproblem = load_secret(s.secret_file)
            if key is None:
                return _out(403, "refused", {"error": f"step-up unavailable (secret file {kproblem})"})
            counter = match_counter(key, code, now, period=s.period, digits=s.digits,
                                    algorithm=s.algorithm, window=s.window)
            del key
            if counter is not None and counter > state["last_counter"]:
                state["last_counter"] = counter
                state["failures"] = []
                state["locked_until"] = 0.0
                write_private_json(s.state_file, state)  # type: ignore[arg-type]
                until = now + s.unlock_seconds
                with self._lock:
                    self._unlocks[(principal, action)] = until
                return _out(200, "unlocked", {"unlocked_until": until, "unlock_seconds": s.unlock_seconds})
            replay = counter is not None
            fails = [f for f in state["failures"] if f > now - s.failure_window_seconds] + [now]
            state["failures"] = fails
            locked = len(fails) >= s.max_failures
            if locked:
                state["locked_until"] = now + s.lockout_seconds
                state["failures"] = []
            write_private_json(s.state_file, state)  # type: ignore[arg-type]
            body: dict = {"error": "that code was already used — wait for the next one" if replay
                          else "wrong code"}
            if locked:
                body["error"] += f"; too many failures — step-up locked for {s.lockout_seconds // 60} min"
                body["locked_until"] = state["locked_until"]
                self.log({**base, "outcome": "lockout_start", "status": 429, "reason": body["error"]})
                return _out(429, "replay" if replay else "fail", body)
            body["attempts_left"] = s.max_failures - len(fails)
            return _out(401, "replay" if replay else "fail", body)
