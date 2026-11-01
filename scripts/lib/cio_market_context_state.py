"""Deterministic MarketContextState@v1 from governed structured sources."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from decimal import Decimal
from typing import Any


SCHEMA = "MarketContextState@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FRED_MAX_AGE_DAYS = 7
FRED_MAX_AGE_DAYS_BY_SERIES = {"CPIAUCSL": 62, "UNRATE": 62, "MORTGAGE30US": 14}


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    result.update(
        {
            "series_id": row.get("series_id"),
            "fetched_at": _plain(row.get("fetched_at")),
            "age_days": round(age_days, 2) if age_days is not None else None,
            "max_age_days": max_age,
        }
    )
    return result


def _market_risk_field(mr: dict[str, Any] | None) -> dict[str, Any]:
    """One market-context field from the market-risk projection (scripts/lib/market_risk_projection.build)."""
    if not isinstance(mr, dict) or mr.get("state") in (None, "not_evaluated"):
        # Always a value: _field() reads a None value as UNAVAILABLE, and "not evaluated" is a different fact.
        value: dict[str, Any] = {"tier": "NOT_EVALUATED", "reason": "no market-risk projection", "options_flow": None}
        if isinstance(mr, dict):
            flow = (mr.get("sources") or {}).get("options_flow") or {}
            findings = [
                f for f in (flow.get("findings") or []) if isinstance(f, dict) and f.get("state") in ("WARN", "STRESS")
            ]
            value = {
                "tier": "NOT_EVALUATED",
                "reason": mr.get("reason"),
                "options_flow": [
                    {
                        "symbol": f.get("symbol"),
                        "state": f.get("state"),
                        "pc_vol_ratio": f.get("pc_vol_ratio"),
                        "pc_oi_ratio": f.get("pc_oi_ratio"),
                    }
                    for f in findings
                ]
                or None,
            }
        return _field(
            value,
            source="market_risk_projection",
            as_of=(mr or {}).get("generated_at") if isinstance(mr, dict) else None,
            state="NOT_EVALUATED",
        )
    contributors = [
        {"name": c.get("name"), "points": c.get("points"), "detail": c.get("detail")}
        for c in (mr.get("contributors") or [])[:5]
        if isinstance(c, dict)
    ]
    value = {
        "tier": mr.get("tier"),
        "score": mr.get("score"),
        "confirming": mr.get("confirming"),
        "contributors": contributors,
        "deescalates_if": mr.get("deescalates_if"),
        "uplift": mr.get("uplift"),
        "episode": {k: (mr.get("episode") or {}).get(k) for k in ("id", "tier", "opened_at", "acknowledged_at")}
        if mr.get("episode")
        else None,
        "book_vulnerability": (
            (mr.get("book") or {}).get("vulnerability") if isinstance(mr.get("book"), dict) else None
        ),
        "probabilities": mr.get("probabilities"),
        "mode": mr.get("mode"),  # live | shadow (shadow: evaluated, no alert sent)
    }
    return _field(
        value, source="market_risk_projection", as_of=mr.get("as_of"), state="STALE" if mr.get("stale") else "VERIFIED"
    )


def load_market_risk_projection(project_root: Path | None = None) -> dict[str, Any] | None:
    """Read the engine snapshot and the hedging radar from the served runtime dir and build the projection.
    Returns None when neither file can be read (the caller then records NOT_EVALUATED)."""
    import json as _json

    root = project_root or PROJECT_ROOT

    def _load(rel: str):
        try:
            return _json.loads((root / rel).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a missing or torn file is "not evaluated", never a crash of the CIO
            return None

    try:
        from lib.market_risk_projection import build, load_snapshot
    except ImportError:  # pragma: no cover - imported as scripts.lib
        from scripts.lib.market_risk_projection import build, load_snapshot

    # live when present; torn live -> not_evaluated with the reason; absent -> the labelled shadow assessment
    snap = load_snapshot(_load, lambda rel: (root / rel).exists())
    radar = _load("data/runtime/hedging_radar_latest.json")
    if snap is None and radar is None:
        return None
    return build(snap, radar)


def _market_risk_summary(field: dict[str, Any]) -> dict[str, Any]:
    v = field.get("value") if isinstance(field.get("value"), dict) else {}
    tier = v.get("tier") or "NOT_EVALUATED"
    top = (v.get("contributors") or [None])[0] if v.get("contributors") else None
    why = (
        f"{top['name']}" + (f" · {top['detail']}" if top and top.get("detail") else "")
        if top
        else (v.get("reason") or "")
    )
    mode = v.get("mode") if v.get("mode") in ("live", "shadow") else None
    line = (
        f"Market risk: {tier}"
        + (f" {round(v['score'])}/100" if isinstance(v.get("score"), (int, float)) else "")
        # a shadow tier was evaluated but nobody was alerted on it; the CIO must not say "the engine warned you"
        + (" (SHADOW, not alerting)" if mode == "shadow" else "")
        + (f" — {why}" if why else "")
    )
    return {
        "tier": tier,
        "score": v.get("score"),
        "state": field.get("state"),
        "as_of": field.get("as_of"),
        "mode": mode,
        "line": line,
    }


def build_market_context_state(
    *,
    regime_snapshot: dict[str, Any] | None,
    fred_rows: list[dict[str, Any]] | None = None,
    valuation: dict[str, Any] | None = None,
    macro_calendar: list[dict[str, Any]] | None = None,
    portfolio_earnings_calendar: list[dict[str, Any]] | None = None,
    evaluated_at: datetime | None = None,
    market_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = evaluated_at or datetime.now(timezone.utc)
    regime = regime_snapshot or {}
    regime_as_of = regime.get("generated_at")
    regime_state = "STALE" if regime.get("stale_data") else "VERIFIED"
    fred = {str(row.get("series_id")): row for row in (fred_rows or []) if isinstance(row, dict)}

    fields = {
        "regime": _field(
            regime.get("regime_label"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "trend": _field(
            regime.get("trend_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "breadth": _field(
            regime.get("breadth_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "volatility": _field(
            regime.get("volatility_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "liquidity": _field(
            regime.get("liquidity_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "sector_leadership": _field(
            regime.get("leadership_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "risk_appetite": _field(
            regime.get("risk_appetite_state"), source="market_regime_snapshots", as_of=regime_as_of, state=regime_state
        ),
        "style_factor_leadership": _field(None, source="market_regime_indicators", as_of=regime_as_of),
        "fed_funds_rate_pct": _fred_field(fred.get("DFF"), evaluated_at=now),
        "ten_two_spread_pct": _fred_field(fred.get("T10Y2Y"), evaluated_at=now),
        "credit_spread_pct": _fred_field(fred.get("BAA10Y"), evaluated_at=now),
        "cpi_index": _fred_field(fred.get("CPIAUCSL"), evaluated_at=now),
        "unemployment_rate_pct": _fred_field(fred.get("UNRATE"), evaluated_at=now),
        "vix_close": _fred_field(fred.get("VIXCLS"), evaluated_at=now),
        "valuation": _field(
            (valuation or {}).get("value"),
            source=(valuation or {}).get("source") or "valuation_state",
            as_of=(valuation or {}).get("as_of"),
        ),
        "earnings_regime": _field(None, source="earnings_state", as_of=None),
        # Market Risk Engine (operator 2026-10-31: "The CIO agent needs to know about everything, including this market
        # information"). The projection's tier/score/contributors, provenance D. NOT_EVALUATED until the engine is live
        # (DSN-20261031-market-risk-engine P2-T1) — a distinct state, never UNAVAILABLE, so it cannot be mistaken for an
        # outage of a source that exists, and never a tier the engine did not compute.
        "market_risk": _market_risk_field(market_risk),
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
        # Top-level summary for CIO prompts and the morning brief (the field above is the record of truth).
        "market_risk": _market_risk_summary(fields["market_risk"]),
    }
    payload["version"] = (
        "market_context_"
        + hashlib.sha256(
            json.dumps({"fields": fields, "quality": quality}, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
    )
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
