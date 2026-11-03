"""Approved Home v007 additive stored-data context; no decisions or side effects.

Pure projection over existing read models. Missing or unclocked data stays unknown.
Prices/analysis references are observations, never orders or new stop levels.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
import hashlib
import json
from typing import Any

from scripts.lib.market_risk.contract import CATEGORIES
from scripts.lib.market_risk import sessions

SCHEMA = "HomeMarketRiskContext@v1"
INVERSE_DISPLAY_SYMBOLS = ("SH", "PSQ", "DOG", "RWM")


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
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


def expected_regular_session_date(now: datetime) -> str:
    """Canonical calendar target, independent of reader availability or cache claims."""
    local = now.astimezone(sessions.ET)
    if sessions.is_trading_day(local.date()) and local.time() >= sessions.REGULAR_OPEN:
        return local.date().isoformat()
    return sessions.last_closed_session(now).isoformat()


def active_extended_start(now: datetime) -> datetime | None:
    local = now.astimezone(sessions.ET)
    label = sessions.session_label(now)
    if label == "premarket":
        return datetime.combine(local.date(), sessions.PREMARKET_START, sessions.ET)
    if label == "afterhours":
        return datetime.combine(local.date(), sessions.close_time(local.date()), sessions.ET)
    if label == "overnight":
        day = local.date() if local.time() >= sessions.OVERNIGHT_START else local.date() - timedelta(days=1)
        return datetime.combine(day, sessions.OVERNIGHT_START, sessions.ET)
    return None


def budget_source_binding(row: dict, projection: dict) -> dict:
    """An exact observation binding for the existing operator decision route."""
    payload = {key: row.get(key) for key in ("scope_id", "budget", "actual", "limit", "unit")}
    payload["source_mode"] = projection.get("mode") or "live"
    payload["breached"] = row.get("breached", True)
    payload.update(actual=number(row.get("actual")), limit=number(row.get("limit")))
    payload["as_of"] = projection.get("as_of")
    return {
        "as_of": projection.get("as_of"),
        "sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest(),
    }


def with_budget_presentation(
    context: dict, projection: dict, *, decision_rows: list | None = None, store_approved: bool = False, now: datetime
) -> dict:
    """Attach presentation history without changing measurements or breach truth.

    Pure: None means the ledger could not be read; [] is a verified empty read.
    The owner measurement binding is distinct from the operator POST envelope.
    """
    from scripts.lib import operator_approvals as approvals

    budgets, current = [], []
    observed = stamp(projection.get("as_of"))
    source_valid = (
        projection.get("state") == "evaluated"
        and projection.get("stale", False) is False
        and projection.get("mode") in (None, "live", "shadow")
        and observed is not None
        and observed <= now
    )
    complete = decision_rows is not None and source_valid
    for source in context.get("budgets") or []:
        row = {
            **source,
            "source_mode": projection.get("mode") or "live",
            "source_status": projection.get("state") if source_valid else "UNAVAILABLE",
            "stale": projection.get("stale", False),
        }
        row["source_binding"] = budget_source_binding(row, projection)
        valid = False
        try:
            if row.get("presentation_source_valid", True) is not True:
                raise approvals.Refused("BUDGET_SOURCE_UNAVAILABLE", 503)
            normalized = approvals._budget_current(row, row.get("scope_id"), row.get("budget"), now)
            row["presentation_binding"] = normalized["source_binding"]
            current.append(row)
            valid = True
        except approvals.Refused:
            row["presentation_binding"] = None
            complete = False
        available = valid and decision_rows is not None and store_approved is True and row.get("breached") is True
        row["operator_decision"] = {
            "state": "available" if available else "unavailable",
            "requires_operator": True,
            "subtype": approvals.BUDGET_PRESENTATION_SUBTYPE,
            "action": "intentional_until",
            "route": "/api/v2/governance/budget-presentation/decide" if available else "/ops/approvals",
            "basis_route": "/api/v2/governance/budget-presentation",
            "reason": "Presentation acknowledgment only; the measured breach remains visible."
            if available
            else "A current canonical measurement and an approved readable decision store are required.",
        }
        if not available:
            row["operator_decision"]["remediation"] = {
                "key": "HOMEV007:budget_presentation_decision",
                "action": "Restore the current measurement and the registered read-only decision store.",
            }
        budgets.append(row)
    try:
        readback = approvals.budget_presentation_decisions(decision_rows or [], current, now)
        readback["complete"] = complete
    except approvals.Refused:
        readback = approvals.budget_presentation_decisions(decision_rows or [], None, now)
        for row in budgets:
            row["operator_decision"]["state"] = "unavailable"
            row["operator_decision"]["route"] = "/ops/approvals"
    by_key = {(item["scope_id"], item["budget"]): item for item in readback["items"]}
    for row in budgets:
        row["budget_presentation_decision"] = by_key.get((row.get("scope_id"), row.get("budget")))
    return {**context, "budgets": budgets, "budget_presentation_decisions": readback}


def previous_session_date(session_date: Any) -> str | None:
    try:
        day = date.fromisoformat(str(session_date)) - timedelta(days=1)
    except ValueError:
        return None
    for _ in range(15):
        if sessions.is_trading_day(day):
            return day.isoformat()
        day -= timedelta(days=1)
    return None


def next_declared_evaluation(registry: dict, *, now: datetime) -> str | None:
    """Existing DST-safe schedule reader; a declaration is not an execution promise."""
    from scripts.lib.cron_outage_watchdog import schedules
    from scripts.lib.cron_schedule import fires_between

    matches = [
        row
        for row in registry.get("lanes", [])
        if isinstance(row, dict) and row.get("lane_id") == "market-risk-evaluate" and row.get("state") == "ACTIVE"
    ]
    if len(matches) != 1:
        return None
    expressions, zone, issue = schedules(matches[0])
    if issue:
        return None
    upcoming = [
        fire.at for expression in expressions for fire in fires_between(expression, now, now + timedelta(days=2), zone)
    ]
    return iso(min(upcoming)) if upcoming else None


def collect(
    projection: dict,
    joined: dict,
    *,
    reader: Any,
    now: datetime,
    registry: dict | None = None,
    read_rows: Any = None,
    cio_stances: dict | None = None,
) -> dict:
    """Read only through existing canonical readers. No provider/bridge/broker calls."""
    symbols = symbols_for(projection, joined)
    quotes, bars, news, events, errors = [], [], {}, {}, []

    def failed(source: str, exc: Exception) -> None:
        connection = getattr(reader, "_conn", None)
        if connection is not None:
            try:
                connection.rollback()
            except Exception as rollback_error:  # noqa: BLE001 — retain both typed failures
                errors.append(
                    {
                        "source": source + ".transaction_rollback",
                        "reason": type(rollback_error).__name__,
                        "remediation": {
                            "key": "HOMEV007:read_transaction",
                            "action": "Restore the read-only source connection; no retry or mutation was attempted.",
                        },
                    }
                )
        errors.append(
            {
                "source": source,
                "reason": type(exc).__name__,
                "remediation": {"key": "HOMEV007:" + source, "action": "Restore or instrument this canonical source."},
            }
        )

    try:
        method = getattr(reader, "regular_session_quotes", None)
        if method is None:
            raise RuntimeError("canonical regular observation hotfix not installed")
        quotes.extend(
            {**row, "symbol": symbol, "observed_at": iso(now)}
            for symbol, row in method(symbols, end=now).items()
            if isinstance(row, dict)
        )
    except Exception as exc:  # noqa: BLE001 — source gap, never a substitute old close
        failed("regular_session_quotes", exc)
    try:
        quotes.extend(reader.extended_quotes(symbols, start=now - timedelta(days=4), end=now) or [])
        if getattr(reader, "extended_quotes_error", None):
            failed("market_quotes_extended", RuntimeError("canonical extended source unavailable"))
    except Exception as exc:  # noqa: BLE001
        failed("market_quotes_extended", exc)
    try:
        bars = reader.daily_bars(symbols, sessions=80, end=now) or []
    except Exception as exc:  # noqa: BLE001
        failed("daily_bars", exc)
    if read_rows is not None:
        try:
            regular = [row for row in quotes if row.get("session") == "regular" and stamp(row.get("as_of"))]
            if regular:
                rows = read_rows(
                    "SELECT upper(symbol) AS symbol, price, prev_close, volume, fetched_at "
                    "FROM market_quotes WHERE source = %s AND (upper(symbol), fetched_at) IN "
                    "(SELECT unnest(%s::text[]), unnest(%s::timestamptz[])) LIMIT 80",
                    ["alpaca", [row["symbol"] for row in regular], [row["as_of"] for row in regular]],
                )
                for quote in regular:
                    matches = [
                        row
                        for row in rows
                        if str(row.get("symbol") or "").upper() == quote["symbol"]
                        and stamp(row.get("fetched_at")) == stamp(quote["as_of"])
                        and number(row.get("price")) == number(quote.get("price"))
                    ]
                    if len(matches) == 1:
                        quote.update({key: matches[0].get(key) for key in ("prev_close", "volume")})
        except Exception as exc:  # noqa: BLE001 — never use a different snapshot's volume
            failed("market_quotes_exact_observation_fields", exc)
        try:
            from scripts.news_symbol_guard import headline_matches_symbol

            rows = read_rows(
                "SELECT upper(symbol) AS symbol, title, summary, source, source_url, published_at "
                "FROM news_articles WHERE upper(symbol) = ANY(%s) AND published_at >= %s "
                "AND published_at <= %s AND COALESCE(is_duplicate, false) = false "
                "ORDER BY published_at DESC LIMIT 400",
                [symbols, now - timedelta(hours=72), now],
            )
            news = {symbol: {"rows": [], "as_of": iso(now)} for symbol in symbols}
            for row in rows:
                symbol = str(row.get("symbol") or "").upper()
                at = stamp(row.get("published_at"))
                if symbol not in news or at is None or not now - timedelta(hours=72) <= at <= now:
                    continue
                guarded, _ = headline_matches_symbol(symbol, row.get("title") or "", row.get("summary") or "")
                if guarded and len(news[symbol]["rows"]) < 2:
                    news[symbol]["rows"].append(
                        {
                            "title": row.get("title"),
                            "source": row.get("source"),
                            "url": row.get("source_url"),
                            "published_at": iso(at),
                            "guarded": True,
                        }
                    )
        except Exception as exc:  # noqa: BLE001 — missing guard is fail closed
            news = {}
            failed("guarded_symbol_headlines", exc)
        try:
            rows = read_rows(
                "SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol, next_earnings_date, updated_at "
                "FROM symbol_profiles WHERE upper(symbol) = ANY(%s) "
                "ORDER BY upper(symbol), updated_at DESC NULLS LAST",
                [symbols],
            )
            for row in rows:
                symbol = str(row.get("symbol") or "").upper()
                upcoming = str(row.get("next_earnings_date") or "")[:10]
                events[symbol] = {
                    "value": {"kind": "earnings", "date": upcoming}
                    if upcoming >= now.date().isoformat()
                    else {"kind": "none_reported"},
                    "as_of": row.get("updated_at"),
                }
        except Exception as exc:  # noqa: BLE001
            failed("canonical_symbol_calendar", exc)
    result = build(
        projection,
        joined,
        quotes=quotes,
        daily_bars=bars,
        headlines=news,
        events=events,
        cio_stances=cio_stances,
        next_evaluation_at=next_declared_evaluation(registry or {}, now=now),
        now=now,
    )
    result["read_errors"] = errors
    return result


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
    cio_stances: dict | None = None,
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
        candidates = [*(quotes or []), *([current] if current else [])]
        expected_date = expected_regular_session_date(now)
        extended_start = active_extended_start(now)

        def applicable(row: dict) -> bool:
            if row.get("session") in ("regular", "regular_close"):
                at = stamp(row.get("as_of"))
                if row.get("session_date") != expected_date or at is None:
                    return False
                day = date.fromisoformat(expected_date)
                # The stored observation clock must independently belong to the
                # claimed NYSE session, including its fractional closing minute.
                # This does not turn the ledger clock into a provider event time.
                opening = datetime.combine(day, sessions.REGULAR_OPEN, sessions.ET)
                closing = datetime.combine(day, sessions.close_time(day), sessions.ET) + timedelta(minutes=1)
                return opening <= at < closing
            at = stamp(row.get("as_of"))
            return (
                extended_start is not None
                and row.get("session") == sessions.session_label(now)
                and at is not None
                and extended_start <= at <= now
            )

        rows = [
            row
            for row in candidates
            if isinstance(row, dict)
            and applicable(row)
            and str(row.get("symbol") or (symbol if row is current else "")).upper() == symbol
            and row.get("session_date")
            and row.get("session")
            and number(row.get("price")) is not None
            and number(row.get("price")) > 0
            and stamp(row.get("as_of")) is not None
            and stamp(row["as_of"]) <= now
        ]
        unavailable = [
            row
            for row in (quotes or [])
            if isinstance(row, dict)
            and str(row.get("symbol") or "").upper() == symbol
            and row.get("status") == "unavailable"
        ]
        absent = {
            "reason": "No accepted canonical quote for the calendar-selected session",
            "source": "canonical_stored_quote",
        }
        quote = max(rows, key=lambda row: stamp(row["as_of"]), default=unavailable[0] if unavailable else absent)
        price = number(quote.get("price"))
        bars = [row for row in (daily_bars or []) if str(row.get("symbol") or "").upper() == symbol]
        bars = sorted(bars, key=lambda row: str(row.get("date") or ""))
        prior_session = previous_session_date(quote.get("session_date"))
        prior = [row for row in bars if not row.get("provisional") and row.get("date") == prior_session]
        previous = number(prior[-1].get("close")) if len(prior) == 1 else None
        if previous is None and quote.get("session") in ("regular", "regular_close"):
            previous = number(quote.get("prev_close"))
        source = str(quote.get("source") or "canonical_stored_quote")
        qclock = quote.get("as_of")
        quote_reason = quote.get("reason")
        if quote.get("status") not in (None, "available"):
            quote_reason = quote_reason or "Canonical quote status is unavailable"
        quote_fact = fact(price, as_of=qclock, source=source, now=now, reason=quote_reason)
        accepted = quote_fact["state"] == "measured"
        price = number(quote_fact["value"]) if accepted else None
        rejected_reason = None if accepted else quote_fact["reason"]
        quote_fact.update(
            session=quote.get("session"),
            session_date=quote.get("session_date"),
            clock_basis="stored source observation",
            expected_session_date=expected_date,
            basis=quote.get("basis"),
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
            key: {
                **distance(price, stages.get(key)),
                "state": "measured" if price is not None and number(stages.get(key)) else "unknown",
                "price_as_of": qclock,
                "reference_as_of": card.get("as_of") or projection.get("as_of"),
                "remediation": None
                if price is not None and number(stages.get(key))
                else {
                    "key": "HOMEV007:analysis_reference:" + key,
                    "action": "Refresh the canonical observation or recorded analysis reference; never invent a level.",
                },
            }
            for key in ("invalidation_level", "sma10", "sma20", "anchored_vwap")
        }
        stance = stances.get(symbol) if isinstance(stances.get(symbol), dict) else card
        stance_clock = stance.get("as_of") or projection.get("as_of")
        cio = {
            key: stance.get(key)
            for key in ("stance", "conviction", "reason", "reasons", "headline")
            if stance.get(key) is not None
        }
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
        volume = number(quote.get("volume")) if accepted else None
        ratio = volume / average if volume is not None and volume >= 0 and average and average > 0 else None
        canonical_cio = (cio_stances or {}).get(symbol)
        canonical_cio = canonical_cio if isinstance(canonical_cio, dict) else {}
        cio_source = "cio_prospect:" + str((canonical_cio.get("source") or {}).get("kind") or "unavailable")
        cio_clock = canonical_cio.get("inputs_as_of") or canonical_cio.get("as_of")
        cio_value = {
            key: canonical_cio.get(key)
            for key in ("stance", "conviction", "stale", "identity_status", "as_of", "inputs_as_of")
        }
        cio_reason = (canonical_cio.get("gap") or {}).get("reason")
        if canonical_cio.get("identity_status") != "CONFIRMED":
            cio_reason = "Canonical CIO identity is unresolved; no ticker-based stance substitution"
        news = (headlines or {}).get(symbol)
        event = (events or {}).get(symbol)
        per_symbol[symbol] = {
            "quote": quote_fact,
            "day_change": {
                **fact(day, as_of=qclock, source=source + "+previous_session_close", now=now, reason=rejected_reason),
                "reference_session_date": prior_session,
                "basis": "previous completed NYSE session close",
            },
            "since_exit": fact(
                since, as_of=qclock, source="reentry_watch.exit_price+" + source, now=now, reason=rejected_reason
            ),
            "analysis_references": fact(
                references if stages and accepted else None,
                as_of=card.get("as_of") or projection.get("as_of"),
                source="reentry_watch.stages",
                now=now,
                reason=rejected_reason,
            ),
            "cio": fact(
                cio_value if canonical_cio.get("stance") is not None else None,
                as_of=cio_clock,
                source=cio_source,
                now=now,
                reason=cio_reason,
            ),
            "cio_reason": fact(
                None,
                as_of=cio_clock,
                source="cio_truth.rationale",
                now=now,
                reason="The registered CIO stance projection does not carry a current stance rationale",
            ),
            "market_risk_stance": fact(
                cio or None, as_of=stance_clock, source="market_risk.positions/reentry_watch", now=now
            ),
            "conviction": fact(
                number(canonical_cio.get("conviction")), as_of=cio_clock, source=cio_source, now=now, reason=cio_reason
            ),
            "volume_vs_20d": fact(
                {
                    "volume": volume,
                    "average_volume_20d": average,
                    "ratio": round(ratio, 4),
                    "session_date": quote.get("session_date"),
                    "sample_sessions": 20,
                    "average_start_date": completed[-20].get("date"),
                    "average_end_date": completed[-1].get("date"),
                    "basis": "observed session volume versus twenty prior completed-session volumes; not time-adjusted",
                }
                if ratio is not None
                else None,
                as_of=qclock,
                source="canonical_quote+daily_bars.volume",
                now=now,
                reason=rejected_reason,
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
        if not card:
            for field in ("since_exit", "analysis_references", "volume_vs_20d"):
                per_symbol[symbol][field] = {
                    "value": None,
                    "state": "not_applicable",
                    "as_of": None,
                    "source": "reentry_watch",
                    "reason": "Symbol is not on the exited-symbol watch",
                }
        held_symbols = {
            str(row.get("symbol") or "").upper() for row in (joined.get("book_exposure") or {}).get("rows") or []
        }
        if symbol in INVERSE_DISPLAY_SYMBOLS and symbol not in held_symbols and not card:
            for field in ("cio", "cio_reason", "conviction", "market_risk_stance"):
                per_symbol[symbol][field] = {
                    "value": None,
                    "state": "not_applicable",
                    "as_of": None,
                    "source": "inverse_quote_display",
                    "reason": "Quote comparison only; no CIO stance implied",
                }
    categories = {
        str(row.get("category") or ""): row for row in projection.get("categories") or [] if isinstance(row, dict)
    }
    chips = []
    for category in CATEGORIES:
        row = categories.get(category, {})
        chip = fact(
            row or None,
            as_of=row.get("as_of"),
            source="market_risk.category." + category,
            now=now,
            reason=(row.get("detail") or "category not measured") if row.get("state") == "UNKNOWN" else None,
        )
        chip.update(
            category=category,
            chip=(
                {"CALM": "OK", "WARN": "WARN", "STRESS": "STRESS"}.get(row.get("state"), "not_measured")
                if chip["state"] == "measured"
                else "not_measured"
            ),
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
        as_of=hedge.get("momentum_as_of"),
        source="defense_hedge_existing_thresholds",
        now=now,
    )
    largest = hedge.get("largest_weakening") or {}
    current_exposure = number(largest.get("pct_invested"))
    exposure_threshold = number(thresholds.get("trigger_book_pct"))
    exposure_progress = fact(
        {
            "current": current_exposure,
            "threshold": exposure_threshold,
            "ratio": current_exposure / exposure_threshold,
            "group": largest.get("label"),
            "basis": "same sector_momentum.book_pct compared by existing Defense trigger",
        }
        if current_exposure is not None and exposure_threshold and exposure_threshold > 0
        else None,
        as_of=hedge.get("momentum_as_of"),
        source="sector_momentum_existing_exposure_trigger",
        now=now,
    )
    budgets = []
    for row in joined.get("budgets_detail") or []:
        actual, limit = number(row.get("actual")), number(row.get("limit"))
        label = str(row.get("budget") or "budget").replace("_", " ")
        budgets.append(
            {
                **row,
                "actual": actual,
                "limit": limit,
                "presentation_source_valid": (
                    type(row.get("actual")) in (int, float)
                    and type(row.get("limit")) in (int, float)
                    and actual is not None
                    and limit is not None
                ),
                "source_binding": budget_source_binding(row, projection),
                "plain_breach": (
                    f"{label} is above its recorded limit"
                    if actual > limit
                    else f"{label} is within its recorded limit"
                )
                if actual is not None and limit is not None
                else "Budget measurement unavailable",
                "clears_when": f"{label} is at or below {limit:g}{row.get('unit') or '%'}"
                if limit is not None
                else "Clear condition unavailable until the existing budget limit is recorded",
                "operator_decision": {
                    "state": "unavailable",
                    "requires_operator": True,
                    "route": "/ops/approvals",
                    "reason": "Budget-intent decision subtype must be verified on the existing authorized approval route before a write is offered",
                    "remediation": {
                        "key": "HOMEV007:budget_presentation_decision",
                        "action": "Wire the reviewed operator-only presentation-decision subtype; never suppress underlying breach truth.",
                    },
                },
            }
        )
    positions = []
    stored_stops = joined.get("observed_stops")
    for row in (joined.get("book_exposure") or {}).get("rows") or []:
        symbol = str(row.get("symbol") or "").upper()
        observation = (per_symbol.get(symbol) or {}).get("quote") or {}
        price = number(observation.get("value"))
        matches = [
            stop
            for stop in stored_stops or []
            if stop.get("symbol") == symbol and stop.get("account_label") == row.get("account_label")
        ]
        stop = max(
            matches, key=lambda stop: stamp(stop.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc), default={}
        )
        level = number(stop.get("price"))
        value = (
            {
                "stored_price": level,
                "distance_price": round(price - level, 4),
                "distance_pct_of_price": round((price - level) / price * 100, 4),
                "status": stop.get("status"),
                "note": "Stored stop observation; no new stop is recommended",
            }
            if price and level and level > 0
            else None
        )
        stop_fact = fact(value, as_of=stop.get("as_of"), source=str(stop.get("source") or "last_known_stops"), now=now)
        if stored_stops is not None and not matches:
            stop_fact = fact(
                {"status": "not_recorded", "note": "No stored stop observed"},
                as_of=iso(now),
                source="last_known_stops_query",
                now=now,
            )
        positions.append(
            {
                "symbol": symbol,
                "account_label": row.get("account_label"),
                "stop": stop_fact,
                "quote": observation,
                "day_change": (per_symbol.get(symbol) or {}).get("day_change"),
                "account_pct_basis": "position market value / same account total",
                "pct_account": row.get("pct_account"),
            }
        )
    gaps = [
        {"symbol": symbol, "field": key, "reason": value["reason"], "remediation": value["remediation"]}
        for symbol, row in per_symbol.items()
        for key, value in row.items()
        if isinstance(value, dict) and value.get("state") == "unknown"
    ]
    return {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "symbols": per_symbol,
        "positions": positions,
        "gaps": gaps,
        "risk": {
            "as_of": projection.get("as_of"),
            "source": "market_risk_latest/history",
            "history": history,
            "score_change": change,
            "categories": chips,
            "category_changes": fact(
                None,
                as_of=projection.get("as_of"),
                source="market_risk_category_history",
                now=now,
                reason="Stored score history does not retain earlier category observations",
            ),
            "next_evaluation": {
                **fact(next_evaluation_at, as_of=now.isoformat(), source="market_risk_evaluation_schedule", now=now),
                "basis": "registry declaration, not proof of installation or execution",
            },
        },
        "hedge": {
            "lagging_progress": progress,
            "exposure_progress": exposure_progress,
            "inverse_moves": {symbol: per_symbol.get(symbol) for symbol in INVERSE_DISPLAY_SYMBOLS},
        },
        "budgets": budgets,
        "advisory_only": True,
    }
