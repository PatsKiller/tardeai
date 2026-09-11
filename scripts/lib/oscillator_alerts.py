#!/usr/bin/env python3
"""Confluence-flip alerting: the one symbol-scope oscillator that may alert.

Operator decision (2026-09-11): a single oscillator never alerts. A
``confluence_flip`` fires only when ``analyze_confluence_v2.state`` enters a
directional STRONG state, which by construction requires ``STRONG_MIN_FAMILIES
>= 3`` independent families — so the alert is a genuine multi-oscillator
agreement, not an RSI wiggle.

Routed DIGEST (never IMMEDIATE, never ``CRITICAL_IMMEDIATE_TYPES``) via
``operator_alert_policy_v2.route_event``. Deduped through the same
``alert_condition_state`` mechanism as sector transitions, so the same
``from->to`` does not page again until it leaves the state and re-enters.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

STRONG_STATES = frozenset({"BULLISH_STRONG", "BEARISH_STRONG"})

# A flip out of STRONG is not a flip; only ENTRY into STRONG is news, and only
# that entry requires 3 families. This keeps the alert volume bounded by how
# often a name actually firms into a strong multi-family agreement.
_DIRECTIONAL_BOUNDARY = frozenset({"BULLISH_STRONG", "BEARISH_STRONG",
                                   "BULLISH_CONDITIONAL", "BEARISH_CONDITIONAL",
                                   "MIXED", "NEUTRAL"})


def is_directional_flip(prior_state: str | None, new_state: str | None) -> bool:
    """True only when a symbol ENTERS a STRONG state from something else.

    ``None`` prior (a first-ever reading) is not a flip — there is no prior to
    have flipped away from, and alerting on every first computation would flood
    the channel on day one.
    """
    if not new_state or new_state not in STRONG_STATES:
        return False
    if prior_state is None:
        return False
    return prior_state != new_state


def flip_badge(prior_state: str | None, new_state: str) -> str:
    """A stable, human-readable transition label for the dedupe key and line."""
    return f"{prior_state or 'NONE'}->{new_state}"


def detect_confluence_flips(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure: given per-symbol prior/new states, return the directional flips.

    Each record is ``{"symbol", "prior_state", "new_state", "affiliation"}``.
    The affiliation is carried through so the alert line names the oscillator
    and its contributing momentum oscillators.
    """
    flips: list[dict[str, Any]] = []
    for r in records:
        prior = r.get("prior_state")
        new = r.get("new_state")
        if not is_directional_flip(prior, new):
            continue
        flips.append({
            "symbol": str(r.get("symbol") or ""),
            "from": prior,
            "to": new,
            "transition": flip_badge(prior, new),
            "oscillator_affiliation": r.get("affiliation"),
        })
    return flips


def confluence_condition_key(symbol: str) -> str:
    return f"confluence:{symbol}"


def notify_confluence_flips(
    flips: Iterable[dict[str, Any]],
    *,
    send_fn: Callable[[str], Any] | None = None,
    session: str | None = None,
    state_path: str | None = None,
    max_per_day: int = 5,
) -> dict[str, Any]:
    """Dedupe and send confluence flips through the governed router.

    ``send_fn`` is ``telegram_alert.send_telegram``; it already applies the
    router (``should_send_telegram``) internally, so a suppressed flip is not
    double-counted here. Returns counts so a caller can record the outcome.

    Never bypasses the router. A single flip fires at most once per state
    change; a repeat of the same ``from->to`` is suppressed until reversal.
    """
    from alert_condition_state import observe

    sent: list[str] = []
    suppressed: list[dict[str, Any]] = []
    remaining = max_per_day
    for f in list(flips):
        if remaining <= 0:
            # A cap that silently drops the excess is a failure swallow (§9.1).
            # Record the over-cap flips so the count is visible, not lost.
            suppressed.append({**f, "suppress_reason": "daily_cap"})
            continue
        symbol = f.get("symbol") or ""
        obs = observe(
            confluence_condition_key(symbol),
            f["transition"],
            alertable=True,
            path=state_path,
            extra={"session": session} if session else {},
        )
        if not obs.get("notify"):
            suppressed.append({**f, "suppress_reason": obs.get("action")})
            continue
        if send_fn is None:
            continue
        aff = f.get("oscillator_affiliation") or {}
        name = aff.get("display_name") or "Indicator Confluence"
        contributors = aff.get("contributing_oscillators") or []
        contrib = f" ({', '.join(contributors)})" if contributors else ""
        line = (
            f"🔄 {name.upper()}: {symbol} {f['from']}→{f['to']}{contrib}\n"
            f"Multiple independent oscillator families now agree — advisory context, no action."
        )
        try:
            send_fn(line)
            sent.append(symbol)
            remaining -= 1
        except Exception:
            suppressed.append({**f, "suppress_reason": "send_error"})
    return {"sent": sent, "suppressed": suppressed}
