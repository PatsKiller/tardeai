"""Canonical Watch quote selection — single CASE boundary for price + identity.

Mirrors api_v2 watchlist items overlay (lateral market_quotes + enrichment CASE).
All fields in the returned artifact describe the SAME winning record.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Display freshness thresholds (minutes) by session of observation
_RTH_CURRENT_MAX = 90          # 15m quote cadence + slack
_PREMARKET_CURRENT_MAX = 120
_AFTERHOURS_CURRENT_MAX = 240  # through evening session
_WEEKEND_HOLD_MAX = 60 * 48    # Fri print held over weekend


def _as_aware(dt: datetime | str | None) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        # Treat naive as America/New_York (host session)
        return dt.replace(tzinfo=ET)
    return dt


def market_session_for(observed_at: datetime | str | None) -> str | None:
    """US equity session of the observation instant (not 'now')."""
    dt = _as_aware(observed_at)
    if not dt:
        return None
    local = dt.astimezone(ET)
    t = local.timetz().replace(tzinfo=None)
    # weekday 0=Mon .. 6=Sun
    if local.weekday() >= 5:
        return "closed"
    if time(9, 30) <= t < time(16, 0):
        return "regular"
    if time(4, 0) <= t < time(9, 30):
        return "premarket"
    if time(16, 0) <= t < time(20, 0):
        return "afterhours"
    return "closed"


def derive_freshness(
    observed_at: datetime | str | None,
    *,
    now: datetime | None = None,
    future_slop_minutes: int = 5,
) -> tuple[str, str | None]:
    """Return (freshness_state, market_session).

    A timestamp alone does not prove CURRENT — age + session matter.
    """
    dt = _as_aware(observed_at)
    if not dt:
        return "DATA_UNAVAILABLE", None
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    # Future-dated rejection
    if dt > ref + timedelta(minutes=future_slop_minutes):
        return "DATA_UNAVAILABLE", market_session_for(dt)

    session = market_session_for(dt)
    age_min = max(0.0, (ref - dt).total_seconds() / 60.0)

    if session == "regular":
        if age_min <= _RTH_CURRENT_MAX:
            return "CURRENT", session
        return "STALE", session
    if session == "premarket":
        if age_min <= _PREMARKET_CURRENT_MAX:
            return "PREMARKET_CURRENT", session
        return "STALE", session
    if session == "afterhours":
        if age_min <= _AFTERHOURS_CURRENT_MAX:
            return "AFTER_HOURS_CURRENT", session
        return "STALE", session
    # closed / weekend: Friday RTH or AH print held
    if age_min <= _WEEKEND_HOLD_MAX:
        # Label by observation session if afterhours/regular
        if market_session_for(dt) in ("regular", "afterhours"):
            return "AFTER_HOURS_CURRENT", session or "closed"
        return "STALE", session or "closed"
    return "STALE", session or "closed"


def compose_quote_artifact(
    *,
    symbol: str,
    mq_id: int | None,
    mq_price: float | None,
    mq_fetched_at: datetime | str | None,
    mq_source: str | None,
    mq_day_change_pct: float | None,
    wi_id: int | None,
    wi_price: float | None,
    wi_last_enriched_at: datetime | str | None,
    wi_change_pct: float | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply the single CASE boundary: market_quotes wins only when newer + complete.

    When market_quotes wins → identity is mq.*
    When enrichment wins → identity is watchlist_items.*; mq.id MUST NOT appear.
    """
    empty = {
        "symbol": symbol.upper(),
        "last": None,
        "day_change_pct": None,
        "price_as_of": None,
        "observed_at": None,
        "price_source": None,
        "quote_id": None,
        "source_record_id": None,
        "market_session": None,
        "freshness_state": "DATA_UNAVAILABLE",
        "market_state": "DATA_UNAVAILABLE",
        "missing": ["canonical_market_quote"],
        "winning_branch": None,
    }
    mq_ts = _as_aware(mq_fetched_at)
    wi_ts = _as_aware(wi_last_enriched_at)
    mq_ok = mq_price is not None and mq_ts is not None
    wi_ok = wi_price is not None and wi_ts is not None

    mq_wins = False
    if mq_ok:
        if wi_ts is None:
            mq_wins = True
        elif mq_ts > wi_ts:
            mq_wins = True

    if mq_wins:
        asof = mq_ts
        last = float(mq_price)
        # Watchlist list uses w.change_pct for display when a row exists; keep that
        # for cross-surface price_change coherence when enrichment row present.
        chg = float(wi_change_pct) if wi_change_pct is not None else (
            float(mq_day_change_pct) if mq_day_change_pct is not None else None
        )
        fresh, session = derive_freshness(asof, now=now)
        if fresh == "DATA_UNAVAILABLE":
            return empty
        return {
            "symbol": symbol.upper(),
            "last": last,
            "day_change_pct": chg,
            "price_as_of": asof.isoformat(),
            "observed_at": asof.isoformat(),
            "price_source": "market_quotes",
            "quote_id": int(mq_id) if mq_id is not None else None,
            "source_record_id": f"market_quotes:{int(mq_id)}" if mq_id is not None else None,
            "market_session": session,
            "freshness_state": fresh,
            "market_state": "OK" if fresh != "STALE" else "STALE",
            "missing": [],
            "winning_branch": "market_quotes",
            "mq_source": mq_source,
        }

    if wi_ok:
        asof = wi_ts
        last = float(wi_price)
        chg = float(wi_change_pct) if wi_change_pct is not None else None
        fresh, session = derive_freshness(asof, now=now)
        if fresh == "DATA_UNAVAILABLE":
            return empty
        return {
            "symbol": symbol.upper(),
            "last": last,
            "day_change_pct": chg,
            "price_as_of": asof.isoformat(),
            "observed_at": asof.isoformat(),
            "price_source": "enrichment",
            "quote_id": f"enrichment:{int(wi_id)}" if wi_id is not None else None,
            "source_record_id": f"watchlist_items:{int(wi_id)}" if wi_id is not None else None,
            "market_session": session,
            "freshness_state": fresh,
            "market_state": "OK" if fresh != "STALE" else "STALE",
            "missing": [],
            "winning_branch": "enrichment",
            # Explicitly no market_quotes identity when enrichment wins
            "mq_id_unused": int(mq_id) if mq_id is not None else None,
        }

    return empty


def batch_canonical_quotes(symbols: list[str], *, now: datetime | None = None) -> dict[str, dict]:
    """Batch-load raw rows and compose CASE-bound quote artifacts."""
    from db_adapter import _get_conn

    out: dict[str, dict] = {}
    empty_base = compose_quote_artifact(
        symbol="?",
        mq_id=None, mq_price=None, mq_fetched_at=None, mq_source=None, mq_day_change_pct=None,
        wi_id=None, wi_price=None, wi_last_enriched_at=None, wi_change_pct=None,
        now=now,
    )
    syms = [s.upper() for s in symbols]
    for s in syms:
        out[s] = {**empty_base, "symbol": s}

    if not syms:
        return out

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (upper(w.symbol))
               upper(w.symbol) AS symbol,
               w.id AS wi_id,
               w.price AS wi_price,
               w.last_enriched_at AS wi_last_enriched_at,
               w.change_pct AS wi_change_pct,
               mq.id AS mq_id,
               mq.price AS mq_price,
               mq.fetched_at AS mq_fetched_at,
               mq.source AS mq_source,
               mq.day_change_pct AS mq_day_change_pct
          FROM watchlist_items w
          LEFT JOIN LATERAL (
                SELECT t.id, t.price, t.fetched_at, t.source, t.day_change_pct
                  FROM market_quotes t
                 WHERE t.symbol = w.symbol
                   AND t.price IS NOT NULL
                   AND t.fetched_at IS NOT NULL
                   AND t.fetched_at <= (NOW() AT TIME ZONE 'UTC' + INTERVAL '5 minutes')
                 ORDER BY t.fetched_at DESC, t.id DESC
                 LIMIT 1
          ) mq ON true
         WHERE upper(w.symbol) = ANY(%s)
         ORDER BY upper(w.symbol), w.updated_at DESC NULLS LAST
        """,
        (syms,),
    )
    for row in cur.fetchall() or []:
        if hasattr(row, "keys"):
            art = compose_quote_artifact(
                symbol=row["symbol"],
                mq_id=row.get("mq_id"),
                mq_price=float(row["mq_price"]) if row.get("mq_price") is not None else None,
                mq_fetched_at=row.get("mq_fetched_at"),
                mq_source=row.get("mq_source"),
                mq_day_change_pct=float(row["mq_day_change_pct"]) if row.get("mq_day_change_pct") is not None else None,
                wi_id=row.get("wi_id"),
                wi_price=float(row["wi_price"]) if row.get("wi_price") is not None else None,
                wi_last_enriched_at=row.get("wi_last_enriched_at"),
                wi_change_pct=float(row["wi_change_pct"]) if row.get("wi_change_pct") is not None else None,
                now=now,
            )
        else:
            # tuple order matches SELECT
            (symbol, wi_id, wi_price, wi_le, wi_chg, mq_id, mq_price, mq_ft, mq_src, mq_chg) = row
            art = compose_quote_artifact(
                symbol=symbol,
                mq_id=mq_id,
                mq_price=float(mq_price) if mq_price is not None else None,
                mq_fetched_at=mq_ft,
                mq_source=mq_src,
                mq_day_change_pct=float(mq_chg) if mq_chg is not None else None,
                wi_id=wi_id,
                wi_price=float(wi_price) if wi_price is not None else None,
                wi_last_enriched_at=wi_le,
                wi_change_pct=float(wi_chg) if wi_chg is not None else None,
                now=now,
            )
        out[art["symbol"]] = art

    # Pure market_quotes for symbols not on watchlist
    still = [s for s in syms if out[s].get("last") is None]
    if still:
        cur.execute(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, id, source, price, day_change_pct, fetched_at
              FROM market_quotes
             WHERE symbol = ANY(%s)
               AND price IS NOT NULL
               AND fetched_at IS NOT NULL
               AND fetched_at <= (NOW() AT TIME ZONE 'UTC' + INTERVAL '5 minutes')
             ORDER BY symbol, fetched_at DESC, id DESC
            """,
            (still,),
        )
        for row in cur.fetchall() or []:
            if hasattr(row, "keys"):
                art = compose_quote_artifact(
                    symbol=str(row["symbol"]).upper(),
                    mq_id=row["id"],
                    mq_price=float(row["price"]),
                    mq_fetched_at=row["fetched_at"],
                    mq_source=row.get("source"),
                    mq_day_change_pct=float(row["day_change_pct"]) if row.get("day_change_pct") is not None else None,
                    wi_id=None, wi_price=None, wi_last_enriched_at=None, wi_change_pct=None,
                    now=now,
                )
            else:
                art = compose_quote_artifact(
                    symbol=str(row[0]).upper(),
                    mq_id=row[1],
                    mq_price=float(row[3]),
                    mq_fetched_at=row[5],
                    mq_source=row[2],
                    mq_day_change_pct=float(row[4]) if row[4] is not None else None,
                    wi_id=None, wi_price=None, wi_last_enriched_at=None, wi_change_pct=None,
                    now=now,
                )
            out[art["symbol"]] = art
    return out
