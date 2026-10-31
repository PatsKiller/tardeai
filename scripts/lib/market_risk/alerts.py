"""Market-risk phone cards and delivery intents (DSN-20261031-market-risk-engine, plan §5.10 and §4A).

``render`` turns a MarketRiskAssessment@v1 dict into the phone-length card: tier and score, the portfolio uplift
line, the top five contributors with points and ``as_of``, the "Your book" line (symbols and stop distances only),
the one change that would de-escalate, and the advisory line. ``intent_for`` decides whether a tier transition
sends at all and at what priority; ``deliver`` is the one send path, through the ``telegram_alert.send_telegram``
chokepoint (AGENTS §24.1). This module reads no market data of its own: it formats what the engine computed.
Deterministic text; an LLM may only rephrase the "why" afterwards (builder G, curation) and never a number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    from lib.market_risk.contract import TIERS, assert_no_behavior_fields
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.market_risk.contract import TIERS, assert_no_behavior_fields

ET = ZoneInfo("America/New_York")
ADVISORY = "Advisory. No order, size or stop level is implied."
ICON = {"RED": "🔴", "ORANGE": "🟠", "YELLOW": "🟡", "BLUE": "🔵", "GREEN": "🟢"}


def _rank(tier: str | None) -> int:
    t = str(tier or "NONE").upper()
    return TIERS.index(t) if t in TIERS else TIERS.index("NONE")


def _num(v: Any) -> str:
    try:
        return str(round(float(v)))
    except (TypeError, ValueError):
        return "—"


def _short_time(iso: str | None) -> str:
    if not iso:
        return "time n/a"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:16]
    return t.astimezone(ET).strftime("%m-%d %H:%M ET")


def render(a: dict[str, Any], *, max_contributors: int = 5, repeat: dict[str, Any] | None = None) -> str:
    """Phone card for one assessment. ``repeat`` (from escalation.due_repeats) adds the acknowledgment banner."""
    assert_no_behavior_fields(a)
    tier = str(a.get("tier") or "NONE").upper()
    lines: list[str] = []
    if repeat:
        lines.append(
            f"{ICON.get(tier, '')} {tier} ALERT ACTIVE — acknowledgment required "
            f"(repeat {repeat.get('repeat_number')}, {repeat.get('elapsed_min')} min since it opened)"
        )
    head = f"{ICON.get(tier, '')} MARKET RISK {tier} {_num(a.get('score'))}/100".strip()
    if a.get("confirming") is not None:
        head += f" · {a.get('confirming')} of 9 categories confirm"
    lines.append(head)
    up = a.get("uplift") or None
    if up:
        why = "; ".join(str(r) for r in (up.get("reasons") or [])) or (
            f"portfolio vulnerability {_num(up.get('vulnerability'))}"
        )
        lines.append(f"Market {_num(a.get('market_score'))} ({a.get('market_tier')}) → {tier} because {why}")
    for c in (a.get("contributors") or [])[:max_contributors]:
        pts = float(c.get("points") or 0)
        lines.append(
            f"{c.get('category')} {'+' if pts >= 0 else ''}{round(pts)} · {c.get('headline')} · {_short_time(c.get('as_of'))}"
        )
    book = a.get("portfolio") or {}
    parts = []
    for b in book.get("budget_breaches") or []:
        scope = f"{b.get('scope')} " if b.get("scope") and b.get("scope") != "book" else ""
        parts.append(f"{scope}{b.get('budget')} {_num(b.get('actual'))} vs {_num(b.get('limit'))}")
    for d in book.get("drivers") or []:
        s = str(d.get("symbol") or "")
        if d.get("stop_distance_pct") is not None:
            s += f" stop {round(float(d['stop_distance_pct']), 1)}% below"
        if d.get("reason"):
            s += f" ({d['reason']})"
        parts.append(s)
    if parts:
        lines.append("Your book: " + " · ".join(parts))
    unknown = [
        o.get("category") for o in a.get("observations") or [] if isinstance(o, dict) and o.get("state") == "UNKNOWN"
    ]
    if unknown:
        lines.append("Not measured: " + ", ".join(str(u) for u in unknown))
    if a.get("deescalates_if"):
        lines.append(f"De-escalates if: {a['deescalates_if']}")
    if tier == "RED":
        lines.append("Reply ACK RED or tap Acknowledge on Home / Risk.")
    lines.append(f"Evaluated {_short_time(a.get('as_of'))}. {ADVISORY}")
    return "\n".join(lines)


def intent_for(assessment: dict[str, Any], prior: dict[str, Any] | None, policy: dict[str, Any]) -> dict | None:
    """Transitions only. Escalation into any tier sends at that tier's priority; a drop out of ORANGE/RED sends a
    de-escalation card; anything else (same tier, small moves below YELLOW) sends nothing."""
    cfg = policy.get("alerts") or {}
    tier = str(assessment.get("tier") or "NONE").upper()
    was = str((prior or {}).get("tier") or "NONE").upper()
    if tier == was:
        return None
    if _rank(tier) > _rank(was):
        if tier == "NONE":
            return None
        key, transition = tier, f"up_from_{was.lower()}"
    else:
        if _rank(was) < _rank("ORANGE"):
            if tier == "GREEN":
                key, transition = "GREEN", f"to_green_from_{was.lower()}"
            else:
                return None
        else:
            key, transition = "deescalated", f"down_from_{was.lower()}"
    pri = (cfg.get("priority") or {}).get(key, "P2")
    dedupe = int((cfg.get("dedupe_minutes") or {}).get(key, 240))
    as_of = assessment.get("as_of")
    try:
        session_date = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    except (TypeError, ValueError):
        session_date = "unknown"
    return {
        "priority": pri,
        "dedupe_minutes": 0 if tier == "RED" else dedupe,
        "dedupe_key": f"market_risk:{tier}:{session_date}:{transition}",
        "tier": tier,
        "transition": transition,
    }


def deliver(message: str, intent: dict[str, Any], policy: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    """The one send path. Dry run returns what would be sent; a live send's failure is returned, never swallowed."""
    producer = str((policy.get("alerts") or {}).get("producer") or "market_risk_engine")
    out = {"dry_run": dry_run, "intent": intent, "chars": len(message)}
    if dry_run:
        out["sent"] = False
        return out
    from telegram_alert import send_telegram

    ok = send_telegram(
        message,
        priority=intent["priority"],
        dedupe_minutes=int(intent["dedupe_minutes"]),
        producer=producer,
        message_class="market_risk",
    )
    out["sent"] = bool(ok)
    if not ok:
        out["error"] = "send_telegram returned False"
    return out
