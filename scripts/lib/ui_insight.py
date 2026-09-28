"""Server-supplied insight lines for the Command Center (PR3, 2026-09-27).

Why: the redesign puts a takeaway at the top of every card ("insight first, data second").
AGENTS §13 forbids frontend business logic, so the sentence and its tone are produced HERE,
from decisions the platform has already made, and the frontend only renders them.

What: ``build_insight(kind, payload)`` returns

    {"schema": "UiInsight@v1", "headline": str, "tone": success|warning|danger|info|ai|neutral,
     "drivers": [str, ...], "source": "rule"|"llm", "as_of": iso|None, "provenance": str|None,
     "decision": {...}|None}

It never sizes, orders, or invents a verdict: every headline is copied or assembled from
fields that already exist on the payload (plain_english, committee_memo, cio_decision,
thesis stance, flags, verdict), and the tone follows the fixed mapping in TONE_OF. When
nothing on the payload supports a takeaway the insight says so (tone neutral) rather than
guessing. READ_ONLY_ADVISORY; MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = "UiInsight@v1"
TONES = ("success", "warning", "danger", "info", "ai", "neutral")

# The single vocabulary -> tone mapping (mirrors designTokens.toneFromVerdict).
TONE_OF = {
    "APPROVE": "success", "READY": "success", "GO": "success", "BUY": "success", "STRONG_BUY": "success",
    "MONITOR_ONLY": "warning", "WAIT": "warning", "WATCH": "warning", "HOLD": "warning", "MORE_RESEARCH": "warning",
    "REJECT": "danger", "BLOCKED": "danger", "FIX": "danger", "AVOID": "danger", "NO_TRADE": "danger", "SELL": "danger",
    "INFO": "info",
}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def tone_for(label: Any, default: str = "neutral") -> str:
    s = str(label or "").strip().upper().replace(" ", "_")
    return TONE_OF.get(s, default)


def _insight(headline: str, tone: str, *, drivers: Optional[list[str]] = None, source: str = "rule",
             as_of: Optional[str] = None, provenance: Optional[str] = None, decision: Optional[dict] = None) -> dict[str, Any]:
    if tone not in TONES:
        tone = "neutral"
    return {"schema": SCHEMA, "headline": str(headline or "").strip()[:280], "tone": tone,
            "drivers": [str(d).strip()[:200] for d in (drivers or []) if str(d).strip()][:4],
            "source": source, "as_of": as_of or _now_iso(), "provenance": provenance, "decision": decision}


def options_insight(p: dict[str, Any]) -> dict[str, Any]:
    """Takeaway for an options proposal card, from what the desk already decided.

    Precedence: a CIO decision (LLM) with its reasoning; else the truth flags (approvable /
    not, with the named blocker); else the plain-English objective. Drivers come from the
    CIO's concerns, the block reasons and the economics caveat, in that order."""
    dec = p.get("cio_decision") or {}
    review = dec.get("review") or {}
    memo = p.get("committee_memo") or {}
    pe = p.get("plain_english") or {}
    econ = p.get("economics") or {}
    flags = p.get("flags") or []
    not_ok = next((f for f in flags if isinstance(f, dict) and f.get("key") == "NOT_APPROVABLE"), None)
    blocks = list(((p.get("enterprise") or {}).get("blocks") or [])) + [
        str((b or {}).get("reason") or b) for b in (p.get("thesis_blocks") or [])]
    drivers: list[str] = []
    if review.get("concerns"):
        drivers += [str(c) for c in review["concerns"][:2]]
    if econ.get("ev_caveat"):
        drivers.append(f"Expected P/L: {econ['ev_caveat']}")
    drivers += [str(b) for b in blocks[:2] if b]      # _insight() keeps the first four
    sym = str(p.get("symbol") or "").upper()
    if dec.get("outcome"):
        outcome = str(dec["outcome"]).upper()
        head = str(review.get("reasoning") or "").strip()
        if head:
            head = head.split(". ")[0].rstrip(".") + "."
        else:
            head = f"CIO decision for {sym}: {outcome.replace('_', ' ').lower()}."
        return _insight(head, tone_for(outcome, "warning"), drivers=drivers, source="llm", as_of=dec.get("at"),
                        provenance=f"CIO review {dec.get('decision_guid') or ''}".strip(),
                        decision={"outcome": outcome, "confidence": dec.get("confidence"), "decision_id": dec.get("decision_guid")})
    if not_ok:
        why = str(not_ok.get("label") or "").replace("Not approvable: ", "")
        return _insight(f"{sym}: not approvable — {why}." if why else f"{sym}: not approvable.", "danger" if "reject" in why.lower() else "warning",
                        drivers=drivers, source="rule", as_of=p.get("generated_at"), provenance="desk truth flags")
    if p.get("approvable"):
        return _insight(f"{sym}: {pe.get('objective') or memo.get('classification_label') or 'approvable idea'}", "success",
                        drivers=drivers, source="rule", as_of=p.get("generated_at"), provenance="desk truth flags")
    return _insight(f"{sym}: {pe.get('objective') or 'idea under review'}", "neutral", drivers=drivers, source="rule",
                    as_of=p.get("generated_at"), provenance="plain_english")


def thesis_insight(t: dict[str, Any]) -> dict[str, Any]:
    """Takeaway from a symbol thesis record (stance + state + summary), for watchlist and CIO cards."""
    sym = str(t.get("symbol") or "").upper()
    stance = str(t.get("thesis_stance") or "").strip()
    state = str(t.get("thesis_state") or "").upper()
    summary = str(t.get("thesis_summary") or "").strip()
    head = summary.split(". ")[0].rstrip(".") + "." if summary else (f"{sym}: no stated thesis stance yet." if not stance else f"{sym}: stance {stance}.")
    tone = tone_for(stance, "neutral") if stance else "neutral"
    if state in ("THIN", "INSUFFICIENT_DATA") and tone == "success":
        tone = "warning"
    drivers = [g for g in (t.get("research_gaps") or [])[:2]]
    if state:
        drivers.append(f"thesis {state.lower()}" + (f", grade {t.get('substantiveness_grade')}" if t.get("substantiveness_grade") else ""))
    return _insight(head, tone, drivers=drivers, source="llm" if summary else "rule", as_of=t.get("last_reviewed"),
                    provenance=t.get("symbol_thesis_version"))


def verdict_insight(row: dict[str, Any], *, kind: str = "row") -> dict[str, Any]:
    """Generic: a server verdict / recommendation / stance field plus an optional why line."""
    sym = str(row.get("symbol") or "").upper()
    label = row.get("verdict") or row.get("recommendation") or row.get("stance") or row.get("state") or ""
    why = row.get("why") or row.get("reason") or row.get("summary") or ""
    head = f"{sym}: {str(label).replace('_', ' ')}" if label else f"{sym}: no verdict on file"
    if why:
        head += f" — {str(why).split('. ')[0].rstrip('.')}."
    return _insight(head, tone_for(label, "neutral"), source="rule", as_of=row.get("as_of") or row.get("updated_at"),
                    provenance=row.get("source") or kind)


def build_insight(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch by card kind. Unknown kinds get an honest neutral insight, never a guess."""
    try:
        if kind == "options_proposal":
            return options_insight(payload or {})
        if kind == "symbol_thesis":
            return thesis_insight(payload or {})
        if kind in ("watch", "position", "holding", "row"):
            return verdict_insight(payload or {}, kind=kind)
    except Exception as exc:  # noqa: BLE001 -- a takeaway that cannot be formed says so
        return _insight(f"No takeaway available ({type(exc).__name__}).", "neutral", source="rule", provenance="ui_insight")
    return _insight("No takeaway available for this card.", "neutral", source="rule", provenance="ui_insight")
