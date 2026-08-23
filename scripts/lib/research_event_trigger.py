"""Deterministic material-research trigger planner with dwell and dedupe."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ResearchTriggerPlan@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MATERIAL_MEMBERSHIPS = frozenset({"HELD", "REENTRY", "WATCH", "PROPOSAL", "T0-HOLD", "T0-PROP", "T1-WATCH"})
EVENT_TYPES = frozenset({
    "EARNINGS", "GUIDANCE", "SEC", "FDA", "REGULATORY", "M_AND_A",
    "ANALYST_REVISION", "TARGET_REVISION", "SECTOR_DIVERGENCE",
    "MARKET_REGIME_SHIFT", "REENTRY_TRANSITION", "OPPORTUNITY_TRANSITION",
    "FINANCIAL_SENSES_CONFLICT", "OPERATOR_NEED_DATA", "THESIS_REVIEW_DUE",
    "INVALIDATION_TRIGGER", "ATR_MOVE", "RVOL_SHOCK",
})


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        out = value
    elif value:
        try:
            out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return (out if out.tzinfo else out.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _prior_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def plan_research_trigger(
    *,
    symbol: str,
    memberships: list[str],
    due: bool,
    changed: bool,
    stale: bool,
    current_market: dict[str, Any] | None = None,
    previous_market: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    state_transitions: list[str] | None = None,
    operator_need_data: bool = False,
    financial_senses_conflict: bool = False,
    thesis_review_due: bool = False,
    invalidation_triggered: bool = False,
    now: datetime | None = None,
    ledger_path: Path | None = None,
    dwell_hours: float = 6.0,
    persist: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sym = symbol.upper()
    material = bool(set(str(x).upper() for x in memberships) & MATERIAL_MEMBERSHIPS)
    current_market = current_market or {}
    previous_market = previous_market or {}
    reasons: list[dict[str, Any]] = []

    try:
        price = float(current_market.get("price"))
        prior_price = float(previous_market.get("price"))
        atr = float(current_market.get("atr") or previous_market.get("atr"))
        if atr > 0 and abs(price - prior_price) >= atr:
            reasons.append({"type": "ATR_MOVE", "magnitude_atr": round(abs(price - prior_price) / atr, 4)})
    except (TypeError, ValueError):
        pass
    try:
        rvol = float(current_market.get("rvol"))
        if rvol >= 2.0:
            reasons.append({"type": "RVOL_SHOCK", "rvol": rvol})
    except (TypeError, ValueError):
        pass
    for event in events or []:
        event_type = str(event.get("type") or event.get("catalyst_type") or "").upper().replace("&", "AND").replace(" ", "_")
        severity = str(event.get("severity") or "MEDIUM").upper()
        if event_type in EVENT_TYPES and severity in {"MEDIUM", "HIGH", "CRITICAL"}:
            reasons.append({"type": event_type, "event_id": event.get("event_id") or event.get("id"), "severity": severity})
    for transition in state_transitions or []:
        event_type = str(transition).upper()
        if event_type in EVENT_TYPES:
            reasons.append({"type": event_type})
    for flag, event_type in (
        (operator_need_data, "OPERATOR_NEED_DATA"),
        (financial_senses_conflict, "FINANCIAL_SENSES_CONFLICT"),
        (thesis_review_due, "THESIS_REVIEW_DUE"),
        (invalidation_triggered, "INVALIDATION_TRIGGER"),
    ):
        if flag:
            reasons.append({"type": event_type})

    reasons = [dict(item) for item in {json.dumps(item, sort_keys=True): item for item in reasons}.values()]
    fingerprint = _digest({"symbol": sym, "reasons": reasons})
    duplicate = in_dwell = False
    if ledger_path:
        prior = [row for row in _prior_rows(ledger_path) if row.get("symbol") == sym and row.get("triggered")]
        if prior:
            last = prior[-1]
            last_at = _utc(last.get("as_of"))
            duplicate = last.get("fingerprint") == fingerprint
            in_dwell = bool(last_at and now - last_at < timedelta(hours=dwell_hours))

    trigger_present = bool(reasons)
    eligible = material and due and (changed or stale or trigger_present)
    suppressed = eligible and duplicate and in_dwell
    row = {
        "schema": SCHEMA,
        "symbol": sym,
        "memberships": sorted(set(str(x).upper() for x in memberships)),
        "due": bool(due),
        "changed": bool(changed),
        "stale": bool(stale),
        "trigger_reasons": reasons,
        "fingerprint": fingerprint,
        "triggered": bool(eligible and not suppressed),
        "suppressed": bool(suppressed),
        "suppression_reason": "DWELL_DUPLICATE" if suppressed else None,
        "dwell_hours": dwell_hours,
        "as_of": now.replace(microsecond=0).isoformat(),
        "authority": AUTHORITY,
        "financial_action": False,
    }
    if persist and ledger_path:
        _append(ledger_path, row)
    return row
