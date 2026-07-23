"""Deterministic Re-Entry rotation-back composite monitor.

Reads operator-confirmed Rotation Links and armed monitor definitions from the
server-side ui_prefs store. Every scheduled pass recomputes all six mandatory
gates from primary database evidence. A missing input is UNAVAILABLE, never PASS.

Advisory only: this module writes notification evidence to ``alert_events`` through
its caller. It never creates a proposal, broker order, approval, or 2FA request.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Callable

ROTATION_PREF_KEY = "portfolio.reentry.rotation-links.v1"
ALERT_PREF_KEY = "portfolio.reentry.composite-alerts.v1"

PASS = "PASS"
WAIT = "WAIT"
BLOCK = "BLOCK"
UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Gate:
    key: str
    state: str
    current: Any
    threshold: Any
    reason: str
    as_of: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "state": self.state,
            "current": self.current,
            "threshold": self.threshold,
            "reason": self.reason,
            "as_of": self.as_of,
        }


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _pref(ex: Callable[..., Any], key: str) -> dict[str, Any]:
    row = ex("SELECT value FROM ui_prefs WHERE key=%s", (key,), fetch="one") or {}
    return _dict(row.get("value"))


def _f(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _closes(ex: Callable[..., Any], symbol: str, days: int = 320) -> list[tuple[dt.date, float]]:
    rows = ex(
        """SELECT price_date, close_price FROM ticker_prices
           WHERE upper(symbol)=%s AND price_date > CURRENT_DATE - %s
             AND close_price IS NOT NULL
           ORDER BY price_date""",
        (symbol.upper(), days),
        fetch="all",
    ) or []
    # Repricers can write more than one row per session. Keep the last close per date.
    by_date: dict[dt.date, float] = {}
    for row in rows:
        date_value = row.get("price_date")
        close = _f(row.get("close_price"))
        if date_value is None or close is None or close <= 0:
            continue
        if isinstance(date_value, dt.datetime):
            date_value = date_value.date()
        elif not isinstance(date_value, dt.date):
            try:
                date_value = dt.date.fromisoformat(str(date_value)[:10])
            except Exception:
                continue
        by_date[date_value] = close
    return sorted(by_date.items())


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ret(series: list[tuple[dt.date, float]], sessions: int) -> float | None:
    if len(series) <= sessions:
        return None
    start = series[-sessions - 1][1]
    end = series[-1][1]
    return (end - start) / start * 100 if start else None


def _price_metrics(ex: Callable[..., Any], symbol: str) -> dict[str, Any]:
    series = _closes(ex, symbol)
    if not series:
        return {
            "symbol": symbol,
            "price": None,
            "as_of": None,
            "ma20": None,
            "ma50": None,
            "ma200": None,
            "ret20": None,
            "trend": UNAVAILABLE,
        }
    closes = [value for _, value in series]
    price = closes[-1]
    ma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    ma50 = _mean(closes[-50:]) if len(closes) >= 50 else None
    ma200 = _mean(closes[-200:]) if len(closes) >= 200 else None
    recent5 = _ret(series, 5)
    prior5 = None
    if len(series) >= 11:
        start, end = series[-11][1], series[-6][1]
        prior5 = (end - start) / start * 100 if start else None
    trend = UNAVAILABLE
    if ma20 is not None and ma50 is not None and recent5 is not None:
        improving = prior5 is None or recent5 > prior5
        if price > ma20 > ma50:
            trend = "IMPROVING" if improving else "CONSTRUCTIVE"
        elif price < ma20 < ma50:
            trend = "DETERIORATING"
        elif price > ma20 and improving:
            trend = "IMPROVING"
        else:
            trend = "MIXED"
    return {
        "symbol": symbol,
        "price": round(price, 4),
        "as_of": series[-1][0].isoformat(),
        "ma20": round(ma20, 4) if ma20 is not None else None,
        "ma50": round(ma50, 4) if ma50 is not None else None,
        "ma200": round(ma200, 4) if ma200 is not None else None,
        "ret20": round(_ret(series, 20), 4) if _ret(series, 20) is not None else None,
        "trend": trend,
    }


def _rsi(ex: Callable[..., Any], symbol: str) -> tuple[float | None, str | None]:
    row = ex(
        """SELECT rsi, first_seen_at FROM watchlist_items
           WHERE upper(symbol)=%s AND rsi IS NOT NULL
           ORDER BY first_seen_at DESC LIMIT 1""",
        (symbol.upper(),),
        fetch="one",
    ) or {}
    value = _f(row.get("rsi"))
    stamp = row.get("first_seen_at")
    return value, str(stamp) if stamp else None


def _entry_zone(ex: Callable[..., Any], symbol: str) -> dict[str, Any]:
    row = ex(
        """SELECT entry_zone_low, entry_zone_high, created_at, urgency, confidence
           FROM watchlist_entry_plans
           WHERE upper(symbol)=%s
             AND entry_zone_low IS NOT NULL AND entry_zone_high IS NOT NULL
           ORDER BY created_at DESC LIMIT 1""",
        (symbol.upper(),),
        fetch="one",
    ) or {}
    low, high = _f(row.get("entry_zone_low")), _f(row.get("entry_zone_high"))
    if low is not None and high is not None and low > high:
        low, high = high, low
    return {
        "low": low,
        "high": high,
        "as_of": str(row.get("created_at")) if row.get("created_at") else None,
        "urgency": row.get("urgency"),
        "confidence": _f(row.get("confidence")),
    }


def _regime() -> dict[str, Any]:
    try:
        from holding_family import current_regime
        return current_regime() or {}
    except Exception:
        return {"posture": None, "label": None, "stale": True}


def compute_rotation_gates(ex: Callable[..., Any], link: dict[str, Any]) -> dict[str, Any]:
    source = str(link.get("sourceSymbol") or "").upper().strip()
    destination = str(link.get("destinationSymbol") or "").upper().strip()
    source_metrics = _price_metrics(ex, source) if source else {}
    destination_metrics = _price_metrics(ex, destination) if destination else {}
    regime = _regime()
    gates: list[Gate] = []

    posture = str(regime.get("posture") or "").lower()
    label = regime.get("label")
    if not posture or regime.get("stale"):
        gates.append(Gate("regime", UNAVAILABLE, label, "risk_on / constructive",
                          "The market-regime snapshot is missing or stale.", regime.get("generated_at")))
    elif posture == "risk_on":
        gates.append(Gate("regime", PASS, label or posture, "risk_on / constructive",
                          "The current regime is constructive.", regime.get("generated_at")))
    else:
        gates.append(Gate("regime", WAIT, label or posture, "risk_on / constructive",
                          "The current regime is not yet constructive.", regime.get("generated_at")))

    trend = source_metrics.get("trend")
    if trend in (None, UNAVAILABLE):
        gates.append(Gate("trend", UNAVAILABLE, trend, "IMPROVING or CONSTRUCTIVE",
                          "Closed-session trend evidence is unavailable.", source_metrics.get("as_of")))
    elif trend in ("IMPROVING", "CONSTRUCTIVE"):
        gates.append(Gate("trend", PASS, trend, "IMPROVING or CONSTRUCTIVE",
                          "Source price structure is constructive.", source_metrics.get("as_of")))
    else:
        gates.append(Gate("trend", WAIT, trend, "IMPROVING or CONSTRUCTIVE",
                          "Source price structure has not improved enough.", source_metrics.get("as_of")))

    source_ret = _f(source_metrics.get("ret20"))
    destination_ret = _f(destination_metrics.get("ret20"))
    threshold = _f(link.get("rsThresholdPct"))
    threshold = 0.0 if threshold is None else threshold
    spread = source_ret - destination_ret if source_ret is not None and destination_ret is not None else None
    rs_as_of = source_metrics.get("as_of") if source_metrics.get("as_of") == destination_metrics.get("as_of") else None
    if spread is None:
        gates.append(Gate("relative_strength", UNAVAILABLE, None, threshold,
                          "Both source and destination need aligned 20-session returns.", rs_as_of))
    elif spread >= threshold:
        gates.append(Gate("relative_strength", PASS, round(spread, 3), threshold,
                          "Source relative strength has reclaimed the configured spread.", rs_as_of))
    else:
        gates.append(Gate("relative_strength", WAIT, round(spread, 3), threshold,
                          "Source still trails the relative-strength threshold.", rs_as_of))

    zone = _entry_zone(ex, source) if source else {}
    price = _f(source_metrics.get("price"))
    low, high = _f(zone.get("low")), _f(zone.get("high"))
    if price is None or low is None or high is None:
        gates.append(Gate("entry_zone", UNAVAILABLE, price, {"low": low, "high": high},
                          "A current closed price and a persisted validated entry zone are required.",
                          zone.get("as_of") or source_metrics.get("as_of")))
    elif low <= price <= high:
        gates.append(Gate("entry_zone", PASS, price, {"low": low, "high": high},
                          "Source closed inside the validated re-entry zone.", source_metrics.get("as_of")))
    else:
        gates.append(Gate("entry_zone", WAIT, price, {"low": low, "high": high},
                          "Source closed outside the validated re-entry zone.", source_metrics.get("as_of")))

    rsi, rsi_as_of = _rsi(ex, source) if source else (None, None)
    if rsi is None:
        gates.append(Gate("rsi", UNAVAILABLE, None, "40 <= RSI < 70",
                          "Current RSI evidence is unavailable.", rsi_as_of))
    elif 40 <= rsi < 70:
        gates.append(Gate("rsi", PASS, round(rsi, 2), "40 <= RSI < 70",
                          "RSI is constructive without being overbought.", rsi_as_of))
    else:
        gates.append(Gate("rsi", WAIT, round(rsi, 2), "40 <= RSI < 70",
                          "RSI is either not constructive or already overbought.", rsi_as_of))

    constraints = {
        "tax_wash_clear": bool(link.get("taxClear")),
        "account_clear": bool(link.get("accountClear")),
        "settlement_clear": bool(link.get("settlementClear")),
    }
    if all(constraints.values()):
        gates.append(Gate("constraints", PASS, constraints, "all true",
                          "Operator-confirmed tax/wash, account, and settlement constraints are clear.",
                          str(link.get("updatedAt") or "") or None))
    else:
        gates.append(Gate("constraints", BLOCK, constraints, "all true",
                          "At least one required operator-confirmed constraint is not clear.",
                          str(link.get("updatedAt") or "") or None))

    return {
        "source": source,
        "destination": destination,
        "source_metrics": source_metrics,
        "destination_metrics": destination_metrics,
        "gates": [gate.as_dict() for gate in gates],
        "all_pass": len(gates) == 6 and all(gate.state == PASS for gate in gates),
        "has_unavailable": any(gate.state == UNAVAILABLE for gate in gates),
        "has_block": any(gate.state == BLOCK for gate in gates),
    }


def evaluate_armed_rotation_alerts(ex: Callable[..., Any], today: str | None = None) -> dict[str, Any]:
    """Evaluate armed composite monitors and persist deduplicated alert evidence.

    The caller remains responsible for batching/sending Telegram, so these alerts
    share the existing Watch daily cap and one-message-per-pass behavior.
    """
    today = today or dt.date.today().isoformat()
    rotations = _pref(ex, ROTATION_PREF_KEY)
    alert_defs = _pref(ex, ALERT_PREF_KEY)
    lines: list[str] = []
    fired: list[str] = []
    evaluations: dict[str, Any] = {}
    for link_id, definition in alert_defs.items():
        if not isinstance(definition, dict) or not definition.get("armed"):
            continue
        link = rotations.get(link_id)
        if not isinstance(link, dict):
            evaluations[link_id] = {"error": "rotation_link_missing", "all_pass": False}
            continue
        if not link.get("confirmed"):
            evaluations[link_id] = {"error": "capital_lineage_not_confirmed", "all_pass": False}
            continue
        result = compute_rotation_gates(ex, link)
        evaluations[link_id] = result
        if not result["all_pass"]:
            continue
        uid = f"reentry_rotation:{link_id}:{today}"
        if ex("SELECT 1 FROM alert_events WHERE alert_uid=%s LIMIT 1", (uid,), fetch="one"):
            continue
        source, destination = result["source"], result["destination"]
        line = (
            f"🔄 {source} → {destination} return-to-growth review · 6/6 gates PASS · "
            "open Portfolio → Re-Entry (advisory only)"
        )
        ex(
            """INSERT INTO alert_events
               (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
               VALUES (%s,'watch_alert',%s,'info','watch_alerts_eval',%s,NOW())
               ON CONFLICT (alert_uid) DO NOTHING""",
            (uid, source or None, line),
            fetch=None,
        )
        lines.append(line)
        fired.append(link_id)
    return {"lines": lines, "fired": fired, "evaluations": evaluations}
