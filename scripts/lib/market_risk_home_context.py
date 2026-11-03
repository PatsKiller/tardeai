"""Approved Home v007 additive stored-data context; no decisions or side effects.

Pure projection over existing read models. Missing or unclocked data stays unknown.
Prices/analysis references are observations, never orders or new stop levels.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from scripts.lib.market_risk.contract import CATEGORIES

SCHEMA = "HomeMarketRiskContext@v1"
INVERSE_DISPLAY_SYMBOLS = ("SH", "PSQ", "DOG", "RWM")


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def stamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fact(value: Any, *, as_of: Any, source: str, now: datetime, reason: str | None = None) -> dict:
    clock = stamp(as_of)
    valid_clock = clock is not None and clock <= now
    known = value is not None and valid_clock and not reason
    why = reason or ("source clock unavailable or in the future" if not valid_clock else "source value unavailable")
    return {
        "value": value if known else None,
        "state": "measured" if known else "unknown",
        "as_of": iso(clock) if valid_clock else None,
        "source": source,
        "age_seconds": round((now - clock).total_seconds()) if valid_clock else None,
        "reason": None if known else why,
        "remediation": None
        if known
        else {
            "key": "HOMEV007:" + source,
            "action": "Refresh or instrument the named canonical source; do not substitute a sample value.",
        },
    }


def distance(current: float | None, reference: Any) -> dict:
    level = number(reference)
    if current is None or level is None or level <= 0:
        return {"reference_price": level, "distance_price": None, "distance_pct": None}
    return {
        "reference_price": level,
        "distance_price": round(current - level, 4),
        "distance_pct": round((current / level - 1) * 100, 4),
    }


def symbols_for(projection: dict, joined: dict) -> list[str]:
    rows = (joined.get("book_exposure") or {}).get("rows") or []
    symbols = {str(row.get("symbol") or "").upper() for row in rows if isinstance(row, dict)}
    symbols.update(
        str(symbol).upper() for symbol in (projection.get("reentry_watch") or {}) if not str(symbol).startswith("_")
    )
    symbols.update(INVERSE_DISPLAY_SYMBOLS)
    return sorted(symbol for symbol in symbols if symbol and symbol.replace(".", "").replace("-", "").isalnum())[:80]


def build(
    projection: dict,
    joined: dict,
    *,
    quotes: list[dict] | None = None,
    daily_bars: list[dict] | None = None,
    headlines: dict | None = None,
    events: dict | None = None,
    next_evaluation_at: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Home context requires an aware observation clock")
    now = now.astimezone(timezone.utc)
    reentry = projection.get("reentry_watch") or {}
    stances = projection.get("positions") or {}
    per_symbol = {}
    for symbol in symbols_for(projection, joined):
        card = reentry.get(symbol) if isinstance(reentry.get(symbol), dict) else {}
        current = card.get("current_quote") if isinstance(card.get("current_quote"), dict) else {}
        rows = [
            row
            for row in [*(quotes or []), *([current] if current else [])]
            if str(row.get("symbol") or (symbol if row is current else "")).upper() == symbol
            and stamp(row.get("as_of")) is not None
            and stamp(row["as_of"]) <= now
        ]
        quote = max(rows, key=lambda row: stamp(row["as_of"]), default={})
        price = number(quote.get("price"))
        previous = number(quote.get("prev_close"))
        source = str(quote.get("source") or "canonical_stored_quote")
        qclock = quote.get("as_of")
        quote_fact = fact(price, as_of=qclock, source=source, now=now)
        quote_fact.update(
            session=quote.get("session"),
            session_date=quote.get("session_date"),
            clock_basis="stored source observation",
        )
        day = (
            {"price": round(price - previous, 4), "pct": round((price / previous - 1) * 100, 4)}
            if price is not None and previous and previous > 0
            else None
        )
        stages = card.get("stages") if isinstance(card.get("stages"), dict) else {}
        exit_price = number(card.get("exit_price"))
        since = distance(price, exit_price) if exit_price and exit_price > 0 else None
        references = {
            key: distance(price, stages.get(key)) for key in ("invalidation_level", "sma10", "sma20", "anchored_vwap")
        }
        stance = stances.get(symbol) if isinstance(stances.get(symbol), dict) else card
        stance_clock = stance.get("as_of") or projection.get("as_of")
        cio = {
            key: stance.get(key)
            for key in ("stance", "conviction", "reason", "reasons", "headline")
            if stance.get(key) is not None
        }
        bars = [row for row in (daily_bars or []) if str(row.get("symbol") or "").upper() == symbol]
        bars = sorted(bars, key=lambda row: str(row.get("date") or ""))
        completed = [
            row
            for row in bars
            if not row.get("provisional")
            and quote.get("session_date")
            and str(row.get("date") or "") < str(quote["session_date"])
        ]
        volumes = [number(row.get("volume")) for row in completed[-20:]]
        average = (
            sum(volumes) / 20
            if len(volumes) == 20 and all(value is not None and value >= 0 for value in volumes)
            else None
        )
        volume = number(quote.get("volume"))
        ratio = volume / average if volume is not None and volume >= 0 and average and average > 0 else None
        news = (headlines or {}).get(symbol)
        event = (events or {}).get(symbol)
        per_symbol[symbol] = {
            "quote": quote_fact,
            "day_change": fact(day, as_of=qclock, source=source, now=now),
            "since_exit": fact(since, as_of=qclock, source="reentry_watch.exit_price+" + source, now=now),
            "analysis_references": fact(
                references if stages else None,
                as_of=card.get("as_of") or projection.get("as_of"),
                source="reentry_watch.stages",
                now=now,
            ),
            "cio": fact(cio or None, as_of=stance_clock, source="market_risk.positions/reentry_watch", now=now),
            "volume_vs_20d": fact(
                {"volume": volume, "average_volume_20d": average, "ratio": round(ratio, 4)}
                if ratio is not None
                else None,
                as_of=qclock,
                source="canonical_quote+daily_bars.volume",
                now=now,
            ),
            "headlines": fact(
                news.get("rows") if isinstance(news, dict) else None,
                as_of=news.get("as_of") if isinstance(news, dict) else None,
                source="guarded_symbol_headlines",
                now=now,
            ),
            "next_event": fact(
                event.get("value") if isinstance(event, dict) else None,
                as_of=event.get("as_of") if isinstance(event, dict) else None,
                source="canonical_symbol_calendar",
                now=now,
            ),
            "since_exit_history": [
                {"date": row.get("date"), "close": number(row.get("close")), "source": row.get("source")}
                for row in bars
                if card.get("exit_date") and str(row.get("date") or "") >= str(card["exit_date"])
            ][-60:],
        }
    categories = {
        str(row.get("category") or ""): row for row in projection.get("categories") or [] if isinstance(row, dict)
    }
    chips = []
    for category in CATEGORIES:
        row = categories.get(category, {})
        chip = {
            "category": category,
            "chip": {"CALM": "OK", "WARN": "WARN", "STRESS": "STRESS"}.get(row.get("state"), "not_measured"),
        }
        chip.update(
            fact(
                row or None,
                as_of=row.get("as_of"),
                source="market_risk.category." + category,
                now=now,
                reason=(row.get("detail") or "category not measured") if row.get("state") == "UNKNOWN" else None,
            )
        )
        chips.append(chip)
    history = [
        row
        for row in projection.get("history") or []
        if isinstance(row, dict) and stamp(row.get("as_of")) and stamp(row["as_of"]) <= now
    ]
    if (
        stamp(projection.get("as_of"))
        and stamp(projection["as_of"]) <= now
        and number(projection.get("score")) is not None
    ):
        history = [row for row in history if row["as_of"] != projection["as_of"]]
        history.append({key: projection.get(key) for key in ("as_of", "score", "tier")})
    history = sorted(history, key=lambda row: stamp(row["as_of"]))[-30:]
    change = None
    if (
        len(history) > 1
        and number(history[-1].get("score")) is not None
        and number(history[-2].get("score")) is not None
    ):
        change = round(float(history[-1]["score"]) - float(history[-2]["score"]), 4)
    hedge = joined.get("hedge") or {}
    thresholds = hedge.get("thresholds") or {}
    lagging = number(hedge.get("lagging_count"))
    trigger = number(thresholds.get("index_trigger_lagging_sectors"))
    progress = fact(
        {"current": lagging, "threshold": trigger, "unit": "sectors", "ratio": lagging / trigger}
        if lagging is not None and trigger and trigger > 0
        else None,
        as_of=hedge.get("as_of"),
        source="defense_hedge_existing_thresholds",
        now=now,
    )
    budgets = []
    for row in joined.get("budgets_detail") or []:
        actual, limit = number(row.get("actual")), number(row.get("limit"))
        label = str(row.get("budget") or "budget").replace("_", " ")
        budgets.append(
            {
                **row,
                "plain_breach": f"{label} is above its recorded limit"
                if actual is not None and limit is not None and actual > limit
                else "Budget measurement unavailable",
                "clears_when": f"{label} is at or below {limit:g}{row.get('unit') or '%'}"
                if limit is not None
                else "Clear condition unavailable until the existing budget limit is recorded",
                "operator_decision": {
                    "state": "unavailable",
                    "requires_operator": True,
                    "route": "/ops/approvals",
                    "reason": "Budget-intent decision subtype must be verified on the existing authorized approval route before a write is offered",
                },
            }
        )
    return {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "symbols": per_symbol,
        "risk": {
            "as_of": projection.get("as_of"),
            "source": "market_risk_latest/history",
            "history": history,
            "score_change": change,
            "categories": chips,
            "next_evaluation": fact(
                next_evaluation_at, as_of=now.isoformat(), source="market_risk_evaluation_schedule", now=now
            ),
        },
        "hedge": {
            "lagging_progress": progress,
            "inverse_moves": {symbol: per_symbol.get(symbol) for symbol in INVERSE_DISPLAY_SYMBOLS},
        },
        "budgets": budgets,
        "advisory_only": True,
    }
