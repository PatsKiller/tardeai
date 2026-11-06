"""Wall-clock containment for one watchlist drain; no routing or spend authority."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import json
import math
import os
import signal
import threading
import time
from unittest.mock import patch

DEADLINE_ENV = "WATCHLIST_DRAIN_DEADLINE_EPOCH"
CLEANUP_MARGIN_S = 15.0
MIN_START_S = 5.0
DEFERRED_EXIT = 75
_ACTIVE = ContextVar("watchlist_drain_deadline", default=None)


class DrainDeadlineExpired(BaseException):
    """Control flow, deliberately outside legacy provider fallback handlers."""


def child_environment(command: str, hard_timeout_s: float, env=None, *, now=None):
    """Keep the caller's hard cap; reserve time for rollback and child cleanup."""
    if "process_watchlist_agent_jobs.py" not in str(command):
        return None
    result = dict(os.environ if env is None else env)
    deadline = (time.time() if now is None else now) + max(0.0, float(hard_timeout_s) - CLEANUP_MARGIN_S)
    if DEADLINE_ENV in result:
        inherited = float(result[DEADLINE_ENV])
        if not math.isfinite(inherited):
            raise ValueError("invalid inherited watchlist deadline")
        deadline = min(deadline, inherited)
    result[DEADLINE_ENV] = str(deadline)
    return result


def last_json_object(text: str):
    """Read complete objects, skipping their nested braces and trailing log text."""
    decoder, found, offset = json.JSONDecoder(), None, 0
    while offset < len(text or ""):
        start = text.find("{", offset)
        if start < 0:
            break
        try:
            value, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            offset = start + 1
            continue
        if isinstance(value, dict):
            found = value
        offset = start + length
    return found


class DrainBudget:
    def __init__(self, deadline=None, *, clock=time.monotonic):
        self.deadline = deadline
        self.clock = clock

    @classmethod
    def for_cleanup(cls):
        """Independent rollback interval, still inside the caller's kill margin."""
        return cls(time.monotonic() + min(10.0, CLEANUP_MARGIN_S - 2.0))

    @classmethod
    def from_environment(cls, env=None):
        value = (os.environ if env is None else env).get(DEADLINE_ENV)
        if value is None:
            return cls()
        epoch = float(value)
        if not math.isfinite(epoch):
            raise ValueError("invalid watchlist deadline")
        return cls(time.monotonic() + epoch - time.time())

    def remaining(self):
        return math.inf if self.deadline is None else max(0.0, self.deadline - self.clock())

    def check(self, minimum=0.0):
        if self.remaining() <= minimum:
            raise DrainDeadlineExpired("watchlist drain deadline reached")

    def timeout(self, requested=None):
        self.check()
        left = self.remaining()
        if requested is None:
            return None if math.isinf(left) else left
        if isinstance(requested, tuple):
            return tuple(self.timeout(value) for value in requested)
        return min(float(requested), left)

    @contextmanager
    def enforce(self):
        """Bound opaque nested waits as well as explicit HTTP/provider timeouts.

        This is scoped to the single-flight worker, never a caller/server thread.
        The exception unwinds before the caller's reserved cleanup interval.
        """
        if self.deadline is None:
            yield
            return
        if threading.current_thread() is not threading.main_thread():
            raise ValueError("bounded watchlist drain requires the main thread")
        self.check()
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if previous_timer[0] or previous_timer[1]:
            raise ValueError("watchlist deadline cannot replace an active timer")
        previous_handler = signal.getsignal(signal.SIGALRM)
        token = _ACTIVE.set(self)

        def expire(_signum, _frame):
            raise DrainDeadlineExpired("watchlist drain deadline reached")

        try:
            signal.signal(signal.SIGALRM, expire)
            signal.setitimer(signal.ITIMER_REAL, self.remaining())
            with ExitStack() as stack:
                import urllib.request

                original_urlopen = urllib.request.urlopen

                def bounded_urlopen(url, data=None, timeout=None, *args, **kwargs):
                    return original_urlopen(url, data, self.timeout(timeout), *args, **kwargs)

                stack.enter_context(patch.object(urllib.request, "urlopen", bounded_urlopen))
                try:
                    import requests.sessions
                except ImportError:
                    pass
                else:
                    original_request = requests.sessions.Session.request

                    def bounded_request(session, *args, **kwargs):
                        kwargs["timeout"] = self.timeout(kwargs.get("timeout"))
                        return original_request(session, *args, **kwargs)

                    stack.enter_context(patch.object(requests.sessions.Session, "request", bounded_request))
                yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            _ACTIVE.reset(token)


def bounded_timeout(requested):
    budget = _ACTIVE.get()
    return budget.timeout(requested) if budget is not None else requested
