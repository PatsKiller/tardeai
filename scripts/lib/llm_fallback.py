"""llm_fallback.py — when one LLM lane fails, try the next, and say so.

READ_ONLY_ADVISORY with respect to the trading system: this routes text
generation. It places no orders and writes no financial state.

WHY THIS DID NOT EXIST, AND WHY IT DOES NOW
-------------------------------------------
`llm_lane.generate()` takes ONE lane and never tries another. On 2026-09-05 the
chatgpt lane failed every one of 11 attempts — its proxy was pinned to a model
the account cannot use — and every caller that named `lane="chatgpt"` simply got
nothing. grok was healthy the whole time and was never asked.

Worse, nothing could tell. `llm_lane.available("chatgpt")` returned **True**
throughout, because `oauth_lane_status.lane_available` asks whether the proxy is
AUTHENTICATED and the token unexpired. It is. Authentication is not the ability
to answer, and a lane can be perfectly logged in and reject every request. So the
one signal a caller could consult said "fine" while the lane was totally broken.

    measured 2026-09-05:
      available("grok")           = True    (and it worked)
      available("chatgpt")        = True    (and it failed 11/11 with HTTP 400)
      available("deepseek-flash") = True

THE RULES THIS KEEPS
--------------------
The existing design deliberately forbids SILENT degradation —
`llm_lane.generate` documents that "DeepSeek failures raise RuntimeError; they
never fall through to local Gemma". A fallback chain could easily become exactly
the silent substitution that rule exists to prevent, so:

  * every attempt is recorded, and the provenance names the lane that actually
    answered plus every lane that failed and why. A caller can always tell it
    did not get what it asked for.
  * `local` is never in a chain. Falling back to a local model changes the
    quality of an answer without changing its shape, which is the least
    detectable substitution available.
  * PAID lanes are opt-in. deepseek is a metered API with a daily USD cap;
    silently rerouting a free-lane outage onto it turns an outage into a bill.
    `allow_paid=True` is required, and the caller has then chosen the spend.
  * a lane that raises is not retried within the same call. One failure is
    enough information; hammering a broken lane is how a rate limit becomes a
    ban.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

SCHEMA = "LlmFallback@v1"

#: Free OAuth lanes, in preference order. Both are no-cost per call, so trying
#: the second after the first fails costs only latency.
FREE_CHAIN: tuple[str, ...] = ("grok", "chatgpt")

#: Metered. Only ever appended when the caller opts in.
PAID_CHAIN: tuple[str, ...] = ("deepseek-flash",)

#: Never in any chain, at any time. See the module docstring.
NEVER_CHAIN: frozenset[str] = frozenset({"local", "gemma", "ollama"})


class AllLanesFailed(RuntimeError):
    """Every lane in the chain was tried and none produced text."""

    def __init__(self, attempts: list[dict]):
        self.attempts = attempts
        tried = ", ".join(f"{a['lane']}({a['error']})" for a in attempts) or "none"
        super().__init__(f"all lanes failed: {tried}")


@dataclass
class Attempt:
    lane: str
    ok: bool
    error: str = ""
    elapsed_s: float = 0.0
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "ok": self.ok,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 2),
            "skipped_reason": self.skipped_reason,
        }


@dataclass
class FallbackResult:
    text: str
    lane: str
    requested_lane: str
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def substituted(self) -> bool:
        return self.lane != self.requested_lane

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "served_by": self.lane,
            "requested": self.requested_lane,
            "substituted": self.substituted,
            "attempts": [a.to_dict() for a in self.attempts],
        }

    def provenance_line(self) -> str:
        """One line a log or an alert can carry. Never hides a substitution."""
        if not self.substituted:
            return f"served by {self.lane} (as requested)"
        failed = ", ".join(f"{a.lane}: {a.error}" for a in self.attempts if not a.ok)
        return f"served by {self.lane} AFTER {self.requested_lane} failed — {failed}"


def build_chain(requested: str, *, allow_paid: bool = False,
                extra: Optional[list[str]] = None) -> list[str]:
    """The lanes to try, in order, starting with what the caller asked for.

    The requested lane always goes first even when it is paid: the caller named
    it, so it is not a substitution. `allow_paid` governs what we may fall back
    ONTO, not what may be asked for directly.
    """
    req = (requested or "").lower().strip()
    chain: list[str] = []
    if req and req not in NEVER_CHAIN:
        chain.append(req)
    for lane in list(extra or []) + list(FREE_CHAIN) + (list(PAID_CHAIN) if allow_paid else []):
        ln = lane.lower().strip()
        if ln in NEVER_CHAIN or ln in chain:
            continue
        chain.append(ln)
    return chain


def generate_with_fallback(
    prompt: str,
    *,
    lane: str = "grok",
    allow_paid: bool = False,
    extra_lanes: Optional[list[str]] = None,
    generate: Optional[Callable[..., Any]] = None,
    available: Optional[Callable[[str], bool]] = None,
    **kwargs: Any,
) -> FallbackResult:
    """Try `lane`, then the rest of the chain. Raise only if all of them fail.

    `generate` and `available` are injected so this is testable without a
    network; they default to llm_lane's. Every kwarg is passed through
    unchanged, so a caller using the consumption gate (`process_id=`) keeps it
    on every attempt — a fallback must not become a way around the gate.

    An availability check that returns False SKIPS a lane without spending a
    call. It is treated as a hint, not as truth: `available` reports
    authentication, and a lane that claims to be available is still tried and
    can still fail. That asymmetry is deliberate — the signal is trustworthy
    when it says "no" and was measurably wrong when it said "yes".
    """
    if generate is None or available is None:
        try:
            from scripts import llm_lane as _ll
        except ImportError:                                   # pragma: no cover
            import llm_lane as _ll                            # type: ignore
        generate = generate or _ll.generate
        available = available or _ll.available

    requested = (lane or "grok").lower().strip()
    chain = build_chain(requested, allow_paid=allow_paid, extra=extra_lanes)
    attempts: list[Attempt] = []

    for candidate in chain:
        try:
            if not available(candidate):
                attempts.append(Attempt(candidate, False, skipped_reason="reported unavailable",
                                        error="unavailable"))
                continue
        except Exception as exc:                              # noqa: BLE001
            # An availability check that itself fails must not skip the lane —
            # that would let a broken probe silence a working lane.
            attempts.append(Attempt(candidate, False,
                                    skipped_reason=f"availability probe error: {type(exc).__name__}",
                                    error=""))

        started = time.monotonic()
        try:
            out = generate(prompt, lane=candidate, **kwargs)
        except Exception as exc:                              # noqa: BLE001
            attempts.append(Attempt(candidate, False, error=f"{type(exc).__name__}: {exc}"[:200],
                                    elapsed_s=time.monotonic() - started))
            continue

        text = out[0] if isinstance(out, tuple) else out
        if not (text or "").strip():
            attempts.append(Attempt(candidate, False, error="empty response",
                                    elapsed_s=time.monotonic() - started))
            continue

        attempts.append(Attempt(candidate, True, elapsed_s=time.monotonic() - started))
        return FallbackResult(text=text, lane=candidate, requested_lane=requested,
                              attempts=attempts)

    raise AllLanesFailed([a.to_dict() for a in attempts])
