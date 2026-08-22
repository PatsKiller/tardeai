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
    """T1 for CIO IIC / reentry cards. Inverted invalidation → suppress."""
    o = obj or {}
    tech = o.get("technical") if isinstance(o.get("technical"), dict) else {}
    side = infer_side({**o, **tech})
    inv = invalidation_ok(tech.get("price"), tech.get("stop_invalidation"), side=side)
    send = not inv.get("suppress")
    return {
        "send": send,
        "invalidation": inv,
        "reason": inv.get("reason") if not send else "ok",
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
