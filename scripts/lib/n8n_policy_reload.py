"""Versioned, bounded reload of the n8n host policy files (2026-10-15, third-party audit DD08 "revocation").

Before this module the gateway read ``config/n8n_run_allowlist.json`` once at serve time, the relay read it once in
``Relay.__init__`` and the executor read it (and ``config/n8n_effect_keys.json``) once before its long-running loop,
while the contracts design said "re-read per request/drain". A lane removed from the allowlist therefore stayed
runnable until each process restarted.

``PolicyFile`` is the one reader all three use:

* every ``get()`` stats the file; the parsed value is reused only while ``(st_mtime_ns, st_size, st_ino)`` is
  unchanged (bounded cost: one ``stat`` per request), otherwise the file is re-read and re-parsed;
* ``version`` is the sha256 of the bytes the current value was parsed from (first 16 hex), recorded by callers on
  their receipts as the *effective policy version*;
* a missing, unreadable or malformed replacement FAILS SAFE: ``get()`` returns the caller's ``fail_value`` (an empty
  allowlist = every run refused) and ``error`` names why. It never keeps serving the previous, possibly revoked,
  value.

Pure apart from the file read. Never writes, never spawns, never sends. AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")

UNREADABLE = "policy_unreadable"


class PolicyFile(Generic[T]):
    """A parsed policy file re-validated on every ``get()`` (stat-cached). ``parse(bytes) -> T`` raises
    ``ValueError`` / ``OSError`` on a malformed file; ``fail_value`` is what an unreadable file yields."""

    def __init__(self, path: Path | str, parse: Callable[[bytes], T], *, fail_value: T) -> None:
        self.path = Path(path)
        self._parse = parse
        self._fail = fail_value
        self._lock = threading.Lock()
        self._sig: tuple[int, int, int] | None = None
        self._value: T = fail_value
        self.version: str | None = None
        self.error: str | None = None
        self.loads = 0  # how many times the file was actually parsed (tests assert the cache)

    def _signature(self) -> tuple[int, int, int] | None:
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def get(self) -> T:
        with self._lock:
            sig = self._signature()
            if sig is None:
                self._sig, self._value, self.version, self.error = None, self._fail, None, UNREADABLE
                return self._value
            if sig == self._sig and self.error is None:
                return self._value
            try:
                raw = self.path.read_bytes()
                value = self._parse(raw)
            except (OSError, ValueError, TypeError, KeyError):
                self._sig, self._value, self.version, self.error = sig, self._fail, None, UNREADABLE
                return self._value
            self.loads += 1
            self._sig, self._value = sig, value
            self.version = hashlib.sha256(raw).hexdigest()[:16]
            self.error = None
            return value

    def __call__(self) -> T:
        return self.get()

    def __contains__(self, item: Any) -> bool:  # a set-valued policy reads like the set it holds
        return item in self.get()  # type: ignore[operator]

    def __iter__(self):
        return iter(self.get())  # type: ignore[call-overload]

    def __len__(self) -> int:
        return len(self.get())  # type: ignore[arg-type]

    def describe(self) -> dict[str, Any]:
        """{path, version, error}: the effective policy version block for a receipt or status file."""
        return {"path": str(self.path), "version": self.version, "error": self.error}
