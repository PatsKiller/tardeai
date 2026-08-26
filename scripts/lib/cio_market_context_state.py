"""Deterministic MarketContextState@v1 from governed structured sources."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


SCHEMA = "MarketContextState@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FRED_MAX_AGE_DAYS = 7
FRED_MAX_AGE_DAYS_BY_SERIES = {"CPIAUCSL": 62, "UNRATE": 62, "MORTGAGE30US": 14}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _field(value: Any, *, source: str, as_of: Any, state: str = "VERIFIED") -> dict[str, Any]:
    if value is None or value == "" or str(value).strip().upper() in {"UNKNOWN", "UNAVAILABLE", "DATA_UNAVAILABLE"}:
        return {"state": "UNAVAILABLE", "value": None, "source": source, "as_of": _plain(as_of)}
    return {"state": state, "value": _plain(value), "source": source, "as_of": _plain(as_of)}


def _fred_field(row: dict[str, Any] | None, *, evaluated_at: datetime) -> dict[str, Any]:
    if not row:
        return _field(None, source="FRED", as_of=None)
    observed = _parse_datetime(row.get("observation_date"))
    age_days = (evaluated_at - observed.astimezone(timezone.utc)).total_seconds() / 86400 if observed else None
    max_age = FRED_MAX_AGE_DAYS_BY_SERIES.get(str(row.get("series_id")), FRED_MAX_AGE_DAYS)
    state = "STALE" if age_days is None or age_days > max_age else "VERIFIED"
    result = _field(row.get("value"), source="FRED", as_of=row.get("observation_date"), state=state)
    result.update({"series_id": row.get("series_id"), "fetched_at": _plain(row.get("fetched_at")), "age_days": round(age_days, 2) if age_days is not None else None, "max_age_days": max_age})
    return result


def build_market_context_state(
    *,
    regime_snapshot: dict[str, Any] | None,
    fred_rows: list[dict[str, Any]] | None = None,
    valuation: dict[str, Any] | None = None,
    macro_calendar: list[dict[str, Any]] | None = None,
    portfolio_earnings_calendar: list[dict[str, Any]] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = evaluated_at or datetime.now(timezone.utc)
    regime = regime_snapshot or {}
    regime_as_of = regime.get("generated_at")
    regime_state = "STALE" if regime.get("stale_data") else "VERIFIED"
    fred = {str(row.get("series_id")): row for row in (fred_rows or []) if isinstance(row, dict)}

    fields = {
        "regime": _field(regime.get("regime_label"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "trend": _field(regime.get("trend_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "breadth": _field(regime.get("breadth_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "volatility": _field(regime.get("volatility_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "liquidity": _field(regime.get("liquidity_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "sector_leadership": _field(regime.get("leadership_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "risk_appetite": _field(regime.get("risk_appetite_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state),
        "style_factor_leadership": _field(None, source="market_regime_indicators", as_of=regime_as_of),
        "fed_funds_rate_pct": _fred_field(fred.get("DFF"), evaluated_at=now),
        "ten_two_spread_pct": _fred_field(fred.get("T10Y2Y"), evaluated_at=now),
        "credit_spread_pct": _fred_field(fred.get("BAA10Y"), evaluated_at=now),
        "cpi_index": _fred_field(fred.get("CPIAUCSL"), evaluated_at=now),
        "unemployment_rate_pct": _fred_field(fred.get("UNRATE"), evaluated_at=now),
        "vix_close": _fred_field(fred.get("VIXCLS"), evaluated_at=now),
        "valuation": _field((valuation or {}).get("value"), source=(valuation or {}).get("source") or "valuation_state", as_of=(valuation or {}).get("as_of")),
        "earnings_regime": _field(None, source="earnings_state", as_of=None),
    }
    macro_events = list(macro_calendar or [])
    earnings_events = list(portfolio_earnings_calendar or [])
    fields["macro_calendar"] = _field(
        macro_events if macro_events else None,
        source="economic_calendar",
        as_of=now if macro_events else None,
    )
    fields["portfolio_earnings_calendar"] = _field(
        earnings_events if earnings_events else None,
        source="portfolio_earnings_calendar",
        as_of=now if earnings_events else None,
    )

    unavailable = sorted(name for name, field in fields.items() if field["state"] == "UNAVAILABLE")
    stale = sorted(name for name, field in fields.items() if field["state"] == "STALE")
    required = {"regime", "trend", "breadth", "volatility", "fed_funds_rate_pct", "ten_two_spread_pct", "vix_close"}
    if set(stale) & required:
        quality = "STALE"
    elif unavailable and required.intersection(unavailable):
        quality = "UNAVAILABLE"
    elif unavailable:
        quality = "PARTIAL"
    else:
        quality = "VERIFIED"

    payload = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "generated_at": now.isoformat(),
        "truth_quality": quality,
        "fields": fields,
        "unavailable_fields": unavailable,
        "stale_fields": stale,
        "regime_score": _plain(regime.get("regime_score")),
        "confidence": _plain(regime.get("confidence")),
        "missing_data": regime.get("missing_data") or [],
        "llm_generated_state": False,
    }
    payload["version"] = "market_context_" + hashlib.sha256(
        json.dumps({"fields": fields, "quality": quality}, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return payload


def connect_trade_ai_readonly():
    """Open a read-only PostgreSQL connection from the existing runtime environment."""
    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def load_market_context_inputs(conn) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    import psycopg2.extras

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT snapshot_id, generated_at, market_session, regime_label, regime_score,
               confidence, volatility_state, trend_state, breadth_state, liquidity_state,
               leadership_state, risk_appetite_state, macro_state, data_freshness_state,
               stale_data, missing_data, inputs
        FROM market_regime_snapshots ORDER BY generated_at DESC LIMIT 1
    """)
    regime_row = cur.fetchone()
    cur.execute("""
        SELECT DISTINCT ON (series_id) series_id, series_name, value,
               observation_date, fetched_at
        FROM fred_economic_series ORDER BY series_id, observation_date DESC
    """)
    fred_rows = cur.fetchall()
    return (dict(regime_row) if regime_row else None, [dict(row) for row in fred_rows])
