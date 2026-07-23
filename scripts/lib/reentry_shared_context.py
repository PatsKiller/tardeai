"""Shared Re-Entry / Watch / Journal symbol context.

This module creates a read-only cross-surface cache from evidence that already
exists in Trade AI.  It deliberately separates operator-saved classification
from deterministic auto-tags.  Missing evidence stays unavailable; no trading
or approval path is reachable.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Callable

CACHE_KEY = "portfolio.shared-symbol-context.v1"
EXIT_CACHE_KEY = "portfolio.reentry.exit-universe.v1"
MANDATE_KEY = "portfolio.reentry.mandates.v4"
EVENT_KEY = "portfolio.reentry.event-classifications.v1"
DISPOSITION_KEY = "portfolio.reentry.dispositions.v1"
RESISTANCE_KEY = "portfolio.reentry.resistance.v1"

MAG7 = {"AAPL", "AMZN", "GOOGL", "GOOG", "META", "MSFT", "NVDA", "TSLA"}


def _pref(ex: Callable[..., Any], key: str) -> dict[str, Any]:
    row = ex("SELECT value FROM ui_prefs WHERE key=%s", (key,), fetch="one") or {}
    value = row.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = None
    return value if isinstance(value, dict) else {}


def _text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        result = str(value).strip()
        if result:
            return result
    return ""


def _float(*values: Any) -> float | None:
    for value in values:
        try:
            number = float(value)
            if number == number:
                return number
        except (TypeError, ValueError):
            pass
    return None


def _path(value: Any, dotted: str) -> Any:
    result = value
    for part in dotted.split("."):
        if not isinstance(result, dict):
            return None
        result = result.get(part)
    return result


def _first(row: dict[str, Any], paths: tuple[str, ...]) -> Any:
    for path in paths:
        value = _path(row, path)
        if value not in (None, "", [], {}):
            return value
    return None


def infer_event(row: dict[str, Any]) -> tuple[str, str]:
    evidence = " ".join(
        _text(row.get(key))
        for key in ("action", "description", "event_status", "completion_status", "operator_status")
    )
    if re.search(r"\b(stop(?:ped)?|stop[- ]loss|trailing stop|protective stop)\b", evidence, re.I):
        return "stopped_out", _text(row.get("description"), "Broker record indicates a stop execution.")
    if re.search(r"\b(partial|trim|reduce|scaled? out)\b", evidence, re.I):
        return "partial_trim", _text(row.get("description"), "Broker record indicates a partial reduction.")
    if re.search(r"\b(assign(?:ed|ment)|expire(?:d|ation))\b", evidence, re.I):
        return "assignment_expiration", _text(row.get("description"), "Option assignment or expiration event.")
    if re.search(r"\b(day[ -]?trade|intraday|scalp|round trip)\b", evidence, re.I):
        return "momentum_scalp", _text(row.get("description"), "Detected short-duration tactical trade.")
    if re.search(r"\b(sell|sold|closed|exit)\b", evidence, re.I):
        return "discretionary_sale", _text(row.get("description"), "Broker record indicates a discretionary sale.")
    return "other", _text(row.get("description"), "Exit reason is not explicit in the source record.")


def _classified(mandate: dict[str, Any], event: dict[str, Any], disposition: dict[str, Any]) -> bool:
    flags = mandate.get("flags") if isinstance(mandate.get("flags"), dict) else {}
    return bool(
        mandate.get("updatedAt")
        or event.get("updatedAt")
        or disposition.get("updatedAt")
        or mandate.get("mandate") not in (None, "", "unclassified")
        or any(bool(value) for value in flags.values())
        or mandate.get("targetAccount")
        or mandate.get("targetWeightPct") is not None
        or mandate.get("thesis")
    )


def _date(value: Any) -> dt.date | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _resistance_context(resistance: dict[str, Any]) -> dict[str, Any]:
    if not resistance:
        return {
            "state": "UNAVAILABLE",
            "resistance": None,
            "distance_pct": None,
            "hold_days": None,
            "reason": "No closed-session resistance evidence is cached for this symbol.",
            "as_of": None,
        }
    return {
        "state": _text(resistance.get("state"), "UNAVAILABLE").upper(),
        "resistance": _float(resistance.get("resistance")),
        "distance_pct": _float(resistance.get("distance_pct")),
        "hold_days": resistance.get("hold_days"),
        "reason": _text(resistance.get("reason"), resistance.get("method"), "Closed-session resistance cache."),
        "as_of": resistance.get("as_of"),
    }


def refresh_shared_symbol_context(
    ex: Callable[..., Any],
    *,
    exit_payload: dict[str, Any] | None = None,
    resistance_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_payload = exit_payload or _pref(ex, EXIT_CACHE_KEY)
    resistance_payload = resistance_payload or _pref(ex, RESISTANCE_KEY)
    mandates = _pref(ex, MANDATE_KEY)
    events = _pref(ex, EVENT_KEY)
    dispositions = _pref(ex, DISPOSITION_KEY)

    watch_rows = ex(
        """SELECT * FROM watchlist_items
           WHERE symbol IS NOT NULL
           ORDER BY first_seen_at DESC NULLS LAST
           LIMIT 10000""",
        fetch="all",
    ) or []
    watch_by_symbol: dict[str, dict[str, Any]] = {}
    for row in watch_rows:
        symbol = _text(row.get("symbol")).upper()
        if symbol and symbol not in watch_by_symbol:
            watch_by_symbol[symbol] = row

    exits_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in exit_payload.get("rows") or []:
        symbol = _text(row.get("symbol")).upper()
        if symbol:
            exits_by_symbol.setdefault(symbol, []).append(row)

    resistance_map = resistance_payload.get("symbols") if isinstance(resistance_payload.get("symbols"), dict) else {}
    symbols = sorted(set(exits_by_symbol) | set(mandates) | set(watch_by_symbol) | set(resistance_map))
    today = dt.date.today()
    output: dict[str, Any] = {}

    for symbol in symbols:
        exit_rows = sorted(
            exits_by_symbol.get(symbol, []),
            key=lambda row: f"{row.get('trade_date') or ''}T{row.get('trade_time') or ''}",
            reverse=True,
        )
        latest_exit = exit_rows[0] if exit_rows else {}
        event_key = _text(latest_exit.get("event_key"))
        saved_event = events.get(event_key) if isinstance(events.get(event_key), dict) else {}
        disposition = dispositions.get(event_key) if isinstance(dispositions.get(event_key), dict) else {}
        mandate = mandates.get(symbol) if isinstance(mandates.get(symbol), dict) else {}
        auto_type, auto_reason = infer_event(latest_exit)
        event_type = _text(saved_event.get("eventType"), auto_type)
        reason = _text(saved_event.get("reason"), auto_reason)
        watch = watch_by_symbol.get(symbol, {})
        packet = watch.get("decision_packet") if isinstance(watch.get("decision_packet"), dict) else {}
        resistance = _resistance_context(resistance_map.get(symbol) if isinstance(resistance_map, dict) else {})

        rec = _text(
            watch.get("synthesis_recommendation"),
            watch.get("latest_recommendation"),
            _first(packet, ("primary_action.state", "action.state", "state")),
        ).replace("_", " ").upper()
        sector = _text(watch.get("profile_sector"), watch.get("sector"))
        trend = _text(
            watch.get("trend_direction"),
            watch.get("trend_state"),
            _first(packet, ("technical.trend", "technicals.trend", "current_mechanics.trend")),
        ).replace("_", " ").upper()
        rsi = _float(watch.get("rsi"), watch.get("rsi_14"), _first(packet, ("technical.rsi", "technicals.rsi")))
        catalyst = _text(watch.get("catalyst_headline"), watch.get("top_catalyst"))
        catalyst_at = _text(watch.get("catalyst_at"), watch.get("catalyst_date"))
        earnings = _date(_first(watch, ("earnings_date", "next_earnings_date", "profile_earnings_date")))
        regime = _text(
            watch.get("market_regime"),
            watch.get("risk_regime"),
            _first(packet, ("market.regime", "risk.regime", "context.regime", "action_policy.regime")),
        ).replace("_", " ").upper()
        narrative = _text(watch.get("synthesis_narrative_snip"), watch.get("latest_reasoning"))

        annotations: list[dict[str, Any]] = []
        annotations.append({"kind": "exit", "label": event_type.replace("_", " ").upper(), "detail": reason, "source": _text(latest_exit.get("import_source"), "broker/journal")})
        if rec:
            annotations.append({"kind": "watch", "label": f"WATCH {rec}", "detail": narrative or "Current Watch recommendation.", "source": "watchlist_items"})
        if sector:
            annotations.append({"kind": "sector", "label": sector.upper(), "detail": "Sector metadata from Watch.", "source": "watchlist_items"})
        if regime:
            annotations.append({"kind": "regime", "label": f"REGIME {regime}", "detail": "Market/risk regime attached to the latest Watch evidence.", "source": "watch decision packet"})
        if earnings and abs((earnings - today).days) <= 7:
            label = "MAG7 EARNINGS WINDOW" if symbol in MAG7 else "EARNINGS WINDOW"
            annotations.append({"kind": "earnings", "label": label, "detail": f"Reported earnings date {earnings.isoformat()} is within seven calendar days.", "source": "watchlist_items"})
        if catalyst:
            annotations.append({"kind": "catalyst", "label": "CATALYST", "detail": catalyst, "source": catalyst_at or "watchlist_items"})
        if rsi is not None or trend:
            technical = []
            if rsi is not None:
                technical.append(f"RSI {rsi:.1f}")
            if trend:
                technical.append(f"trend {trend}")
            annotations.append({"kind": "technical", "label": "TECHNICAL", "detail": " · ".join(technical), "source": _text(watch.get("last_enriched_at"), "watchlist_items")})
        if resistance.get("state") != "UNAVAILABLE":
            annotations.append({"kind": "resistance", "label": f"RESISTANCE {resistance['state']}", "detail": resistance.get("reason"), "source": resistance.get("as_of") or "closed-session cache"})

        flags = mandate.get("flags") if isinstance(mandate.get("flags"), dict) else {}
        manually_classified = _classified(mandate, saved_event, disposition)
        auto_tagged = bool(exit_rows or rec or sector or regime or catalyst or rsi is not None or resistance.get("state") != "UNAVAILABLE")
        status = "CLASSIFIED" if manually_classified else "AUTO_TAGGED" if auto_tagged else "UNCLASSIFIED"
        journal_annotation = " | ".join(
            _text(item.get("label")) + (f": {_text(item.get('detail'))}" if _text(item.get("detail")) else "")
            for item in annotations[:6]
        )

        output[symbol] = {
            "symbol": symbol,
            "classification_status": status,
            "classified": manually_classified,
            "auto_tagged": auto_tagged,
            "mandate": mandate,
            "latest_event": {
                "event_key": event_key or None,
                "event_type": event_type,
                "reason": reason,
                "notes": _text(saved_event.get("notes")),
                "trade_date": latest_exit.get("trade_date"),
                "account": latest_exit.get("account"),
                "source": _text(latest_exit.get("import_source"), "unknown"),
                "manual": bool(saved_event.get("updatedAt")),
            },
            "queue": {
                "state": _text(disposition.get("state"), "review"),
                "reason": _text(disposition.get("reason")),
            },
            "watch": {
                "recommendation": rec or None,
                "sector": sector or None,
                "regime": regime or None,
                "trend": trend or None,
                "rsi": rsi,
                "catalyst": catalyst or None,
                "catalyst_at": catalyst_at or None,
                "earnings_date": earnings.isoformat() if earnings else None,
                "narrative": narrative or None,
                "as_of": _text(watch.get("last_enriched_at"), watch.get("updated_at")) or None,
            },
            "resistance": resistance,
            "annotations": annotations,
            "journal_annotation": journal_annotation,
        }

    payload = {
        "version": "shared_symbol_context_v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "symbol_count": len(output),
        "symbols": output,
    }
    ex(
        """INSERT INTO ui_prefs (key, value, updated_at)
           VALUES (%s,%s::jsonb,NOW())
           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
        (CACHE_KEY, json.dumps(payload)),
        fetch=None,
    )
    return payload
