"""Industry-momentum close semantics: confirm once, notify once.

Confirmation uses prior *sessions* (as_of < today). Replaying --close on the
same session cannot re-confirm just because today's row is already persisted.

Notification uses alert_condition_state so the same from→to does not page again
until the transition reverses.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from alert_condition_state import observe


def _affiliation(oscillator_id: str, **kw):
    """Fail-soft stamp. Labelling must never break the notification path."""
    try:
        from oscillator_registry import try_affiliation_for
        return try_affiliation_for(oscillator_id, **kw)
    except Exception:
        return None


def semantic_uid(industry: str, from_state: str, to_state: str, session: str) -> str:
    return f"industry_momentum:{industry}:{from_state}:{to_state}:{session}"


def condition_key(industry: str) -> str:
    return f"industry_momentum:{industry}"


def is_confirmed(prior_excluding_today: list[str], current: str | None, debounce_days: int) -> bool:
    """2nd consecutive close in a new state = confirmed (debounce_days=2)."""
    if not current or debounce_days < 1:
        return False
    if len(prior_excluding_today) < debounce_days:
        return False
    return prior_excluding_today[0] == current and prior_excluding_today[-1] != current


def build_alerts(
    confirmed: Iterable[dict[str, Any]],
    *,
    max_alerts: int = 3,
) -> list[dict[str, Any]]:
    alerts = []
    for c in confirmed:
        if not (c.get("held") or c.get("watched")):
            continue
        who = ("holding " + "/".join((c.get("held") or [])[:4])) if c.get("held") else \
              ("watching " + "/".join((c.get("watched") or [])[:4]))
        rel = c.get("rel1w")
        rel_s = f"{rel:+.1f}" if rel is not None else "?"
        alerts.append({
            **c,
            "oscillator_id": "industry_momentum_quadrant",
            "oscillator_affiliation": _affiliation(
                "industry_momentum_quadrant", reading=rel, state=c.get("to"),
                prior_state=c.get("from")),
            "line": (
                f"⚠ {c['industry']} ({c.get('sector')}) {c.get('from')}→{c.get('to')} "
                f"— rel1w {rel_s} · {who}"
            ),
        })
        if len(alerts) >= max_alerts:
            break
    return alerts


def decide_notifications(
    alerts: Iterable[dict[str, Any]],
    *,
    session: str,
    state_path=None,
) -> dict[str, Any]:
    """Return {send, suppressed, observations} for a close run."""
    send: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for a in alerts:
        industry = a.get("industry") or ""
        frm = a.get("from") or ""
        to = a.get("to") or ""
        obs = observe(
            condition_key(industry),
            f"{frm}->{to}",
            alertable=True,
            path=state_path,
            extra={"session": session, "uid": semantic_uid(industry, frm, to, session)},
        )
        observations.append(obs)
        if obs["notify"]:
            send.append(a)
        else:
            suppressed.append({**a, "suppress_reason": obs["action"]})
    return {"send": send, "suppressed": suppressed, "observations": observations}


def emit_telegram(
    decided: dict[str, Any],
    send_fn: Callable[..., Any] | None,
    *,
    title: str = "INDUSTRY MOMENTUM",
) -> int:
    """Route through the canonical sender. Never bypass_router.

    Each line is prefixed with its oscillator's operator-facing display name
    (from the registry) so the operator can tell WHICH oscillator spoke — a
    sector RS transition and a style spread and an industry quadrant all flow
    through here, and before the affiliation they were indistinguishable.
    """
    lines = []
    for a in decided.get("send") or []:
        line = a.get("line")
        if not line:
            continue
        aff = a.get("oscillator_affiliation") or {}
        name = aff.get("display_name")
        if name:
            lines.append(f"{name.upper()}: {line}")
        else:
            lines.append(line)
    if not lines or send_fn is None:
        return 0
    send_fn(title + "\n" + "\n".join(lines))
    return len(lines)


def sector_condition_key(sector: str) -> str:
    return f"sector_momentum:{sector}"


def sector_semantic_uid(sector: str, from_state: str, to_state: str, session: str) -> str:
    return f"sector_momentum:{sector}:{from_state}:{to_state}:{session}"


def decide_sector_notifications(
    alerts: Iterable[dict[str, Any]],
    *,
    session: str,
    state_path=None,
) -> dict[str, Any]:
    """Same transition state machine as industry. Never notify on replay."""
    send: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for a in alerts:
        sector = str(a.get("sector") or a.get("etf") or "")
        frm = a.get("from") or ""
        to = a.get("to") or ""
        obs = observe(
            sector_condition_key(sector),
            f"{frm}->{to}",
            alertable=True,
            path=state_path,
            extra={"session": session, "uid": sector_semantic_uid(sector, frm, to, session)},
        )
        observations.append(obs)
        if obs["notify"]:
            send.append(a)
        else:
            suppressed.append({**a, "suppress_reason": obs["action"]})
    return {"send": send, "suppressed": suppressed, "observations": observations}
