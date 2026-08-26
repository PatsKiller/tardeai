"""Telegram P0 card gates — suppress nonsense, never a second send.

Freeze-safe (8/21–8/27): suppression only. No new feeds, no new producers.
Authority: READ_ONLY_ADVISORY.

T1  R:R from entry/stop/target. Never emit "0.0:1". Missing leg → UNAVAILABLE
    and block ACTIONABLE promotion.
    Invalidation < price for longs (inverted for shorts) else suppress.
    Quote failure → withhold the proposal.
T2  Idempotency key (surface, symbol, decision_id). Retry edits, never a
    second sendMessage.

Counts: append JSONL via log_suppression() — metric path for 3-day report.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
RR_UNAVAILABLE = "R:R UNAVAILABLE"
QUOTE_WITHHOLD = "PRICE_UNAVAILABLE — proposal withheld"
INV_SUPPRESS = "invalidation_contradicts_price"
MAX_ADVISORY_QUOTE_AGE_HOURS = 72.0

_DEFAULT_LOG = Path(__file__).resolve().parents[2] / "data" / "cio" / "telegram_p0_suppress.jsonl"


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def infer_side(obj: dict[str, Any] | None) -> str:
    """long (default) or short. Advisory reentry/proposals are long unless marked."""
    blob = obj or {}
    for k in ("side", "direction", "position_side"):
        raw = str(blob.get(k) or "").strip().lower()
        if raw in {"short", "sell", "put"}:
            return "short"
    return "long"


def compute_rr(
    entry: Any,
    stop: Any,
    target: Any,
    *,
    side: str = "long",
) -> dict[str, Any]:
    """Arithmetic R:R. Never returns display '0.0:1'."""
    e, s, t = _f(entry), _f(stop), _f(target)
    if e is None or s is None or t is None:
        return {
            "ok": False,
            "rr": None,
            "display": RR_UNAVAILABLE,
            "reason": "missing_leg",
            "promote_actionable": False,
        }
    if side == "short":
        risk, reward = s - e, e - t
    else:
        risk, reward = e - s, t - e
    if risk <= 0 or reward <= 0:
        return {
            "ok": False,
            "rr": None,
            "display": RR_UNAVAILABLE,
            "reason": "non_positive_risk_or_reward",
            "promote_actionable": False,
        }
    rr = reward / risk
    if not math.isfinite(rr) or rr <= 0:
        return {
            "ok": False,
            "rr": None,
            "display": RR_UNAVAILABLE,
            "reason": "rr_not_positive",
            "promote_actionable": False,
        }
    shown = round(rr, 2)
    if shown <= 0:
        return {
            "ok": False,
            "rr": None,
            "display": RR_UNAVAILABLE,
            "reason": "rr_rounds_to_zero",
            "promote_actionable": False,
        }
    return {
        "ok": True,
        "rr": shown,
        "display": f"{shown}:1",
        "reason": "computed",
        "promote_actionable": True,
    }


def invalidation_ok(
    price: Any,
    invalidation: Any,
    *,
    side: str = "long",
) -> dict[str, Any]:
    """Long: invalidation < price. Short: invalidation > price. Fail closed."""
    p, inv = _f(price), _f(invalidation)
    if p is None or inv is None:
        return {"ok": False, "reason": "missing_price_or_invalidation", "suppress": False}
    if p <= 0:
        return {"ok": False, "reason": "non_positive_price", "suppress": True}
    if side == "short":
        good = inv > p
    else:
        good = inv < p
    if good:
        return {"ok": True, "reason": "ok", "suppress": False}
    return {"ok": False, "reason": INV_SUPPRESS, "suppress": True, "price": p, "invalidation": inv, "side": side}


def quote_allows_sized_proposal(packet: dict[str, Any] | None) -> dict[str, Any]:
    """No quote / not execution-eligible → withhold. Fail closed on sized cards."""
    p = packet or {}
    er = p.get("execution_readiness") if isinstance(p.get("execution_readiness"), dict) else {}
    provider = (
        p.get("quote_provider")
        or er.get("quote_provider")
        or p.get("last_price_source")
    )
    eligible = p.get("execution_eligible")
    if eligible is None:
        eligible = er.get("quote_execution_eligible")
    if eligible is False or str(eligible).lower() in {"false", "0", "no"}:
        return {"ok": False, "reason": QUOTE_WITHHOLD, "provider": provider, "eligible": False}
    if not provider:
        return {"ok": False, "reason": QUOTE_WITHHOLD, "provider": None, "eligible": eligible}
    return {"ok": True, "reason": "quote_ok", "provider": provider, "eligible": True}


def proposal_send_gate(proposal: dict[str, Any] | None) -> dict[str, Any]:
    """T1 for paper/proposal Telegram. Suppress rather than send a lie."""
    p = proposal or {}
    side = infer_side(p)
    entry = p.get("proposed_entry") if p.get("proposed_entry") not in (None, 0, 0.0) else p.get("entry")
    stop = p.get("proposed_stop") if p.get("proposed_stop") not in (None, 0, 0.0) else p.get("stop")
    target = (
        p.get("proposed_target1")
        if p.get("proposed_target1") not in (None, 0, 0.0)
        else (p.get("target") or p.get("proposed_target"))
    )
    rr = compute_rr(entry, stop, target, side=side)
    q = quote_allows_sized_proposal(p)
    suppress: list[str] = []
    if not q["ok"]:
        suppress.append("quote_fail")
    # Quote fail withholds the whole proposal. Missing R:R still may send, but
    # never as ACTIONABLE and never as the token "0.0:1".
    send = "quote_fail" not in suppress
    return {
        "send": send,
        "rr": rr,
        "quote": q,
        "suppress": suppress,
        "reason": ",".join(suppress) if suppress else "ok",
        "promote_actionable": bool(rr.get("promote_actionable") and q.get("ok")),
    }


def intelligence_card_gate(obj: dict[str, Any] | None) -> dict[str, Any]:
    """Fail closed on contradictory or incomplete financial-looking reentry cards."""
    o = obj or {}
    tech = o.get("technical") if isinstance(o.get("technical"), dict) else {}
    change = o.get("change") if isinstance(o.get("change"), dict) else {}
    is_reentry = o.get("action_class") == "REENTRY_WATCH" or "reentry" in str(change.get("kind") or "")
    failures: list[str] = []
    conflicts = tech.get("data_conflicts") if isinstance(tech.get("data_conflicts"), list) else []
    if conflicts:
        failures.append("DATA_CONFLICT")

    zone: dict[str, Any] = {"ok": True, "reason": "not_reentry"}
    freshness: dict[str, Any] = {"ok": True, "reason": "not_reentry"}
    if is_reentry:
        price = _f(tech.get("price"))
        low = _f(tech.get("support_or_zone_low"))
        high = _f(tech.get("resistance_or_zone_high"))
        zone_ok = bool(price is not None and low is not None and high is not None and low <= high)
        zone = {"ok": zone_ok, "price": price, "low": low, "high": high,
                "reason": "ok" if zone_ok else "ZONE_DATA_UNAVAILABLE_OR_INVALID"}
        if not zone_ok:
            failures.append(zone["reason"])
        source = str(tech.get("price_source") or "").strip()
        as_of = tech.get("price_as_of")
        age_h = None
        try:
            explicit_age = tech.get("price_age_h")
            if explicit_age is not None:
                age_h = float(explicit_age)
        except (TypeError, ValueError):
            age_h = None
        try:
            if age_h is None:
                parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0
        except Exception:
            pass
        fresh_ok = bool(source and age_h is not None and -0.25 <= age_h <= MAX_ADVISORY_QUOTE_AGE_HOURS)
        freshness = {"ok": fresh_ok, "source": source or None, "as_of": as_of,
                     "age_hours": round(age_h, 2) if age_h is not None else None,
                     "reason": "ok" if fresh_ok else "QUOTE_SOURCE_STALE_OR_UNAVAILABLE"}
        if not fresh_ok:
            failures.append(freshness["reason"])
        state = str(tech.get("status") or change.get("to") or "").upper()
        if state == "NEAR" and zone_ok:
            if price < low:
                computed_distance = (price - low) / low * 100.0
            elif price > high:
                computed_distance = (price - high) / high * 100.0
            else:
                computed_distance = 0.0
            threshold = _f(tech.get("near_threshold_pct")) or 3.0
            if abs(computed_distance) > threshold:
                failures.append("NEAR_THRESHOLD_EXCEEDED")
            supplied = tech.get("distance_pct")
            if supplied is not None:
                try:
                    if abs(float(supplied) - computed_distance) > 0.15:
                        failures.append("ZONE_DISTANCE_CONFLICT")
                except (TypeError, ValueError):
                    failures.append("ZONE_DISTANCE_CONFLICT")
    side = infer_side({**o, **tech})
    inv = invalidation_ok(tech.get("price"), tech.get("stop_invalidation"), side=side)
    if is_reentry and not inv.get("ok"):
        failures.append(str(inv.get("reason") or "INVALIDATION_UNAVAILABLE"))
    elif inv.get("suppress"):
        failures.append(str(inv.get("reason") or INV_SUPPRESS))
    failures = list(dict.fromkeys(failures))
    send = not failures
    return {
        "send": send,
        "invalidation": inv,
        "zone": zone,
        "freshness": freshness,
        "failures": failures,
        "reason": ",".join(failures) if failures else "ok",
        "symbol": o.get("symbol"),
    }


def idempotency_key(surface: str, symbol: Any, decision_id: Any) -> str:
    s = str(symbol or "").strip().upper() or "_"
    d = str(decision_id or "").strip() or "_"
    surf = str(surface or "unknown").strip() or "unknown"
    return f"{surf}:{s}:{d}"


def log_suppression(
    rule: str,
    *,
    symbol: Any = None,
    decision_id: Any = None,
    reason: str = "",
    extra: dict | None = None,
    path: Path | None = None,
) -> None:
    dest = path or _DEFAULT_LOG
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "rule": rule,
            "symbol": None if symbol is None else str(symbol).upper(),
            "decision_id": decision_id,
            "reason": reason,
            "authority": AUTHORITY,
        }
        if extra:
            rec["extra"] = extra
        with dest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        pass
