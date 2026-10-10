"""Canonical catalyst read helper — single verification model for catalyst_record.

Authority: catalyst_events.confidence >= 0.3 ⇒ verified (matches scoring.validate_catalyst_relevance).
"""
from __future__ import annotations

from typing import Any


def _confidence(row: dict[str, Any]) -> float | None:
    for key in ("confidence", "impact_score"):
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def normalize_catalyst_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a catalyst_events (or compatible) row to the broker schema."""
    if not row:
        return None
    conf = _confidence(row)
    verified = row.get("verified")
    if verified is None and conf is not None:
        verified = conf >= 0.3
    return {
        "symbol": row.get("symbol"),
        "headline": row.get("headline") or row.get("title"),
        "catalyst_type": row.get("catalyst_type"),
        "verified": bool(verified),
        "confidence": conf,
        "severity": row.get("severity"),
        "impact_score": row.get("impact_score"),
        "source_url": row.get("source_url"),
        "at": row.get("published_at") or row.get("created_at") or row.get("ts"),
    }


def get_catalyst_record(db_query, symbol: str, *, days: int = 45) -> dict[str, Any] | None:
    """Fetch the latest catalyst_events row for symbol via injected _db_query callable."""
    sym = (symbol or "").upper()
    if not sym:
        return None
    row = db_query(
        f"""
        SELECT symbol, catalyst_type, headline, severity, impact_score, confidence,
               source_url, COALESCE(published_at, created_at) AS at
        FROM catalyst_events
        WHERE upper(symbol) = upper(%s) AND catalyst_type <> 'other'
          AND COALESCE(published_at, created_at) > now() - make_interval(days => %s)
          AND {not_news_sql("headline")}
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT 1
        """,
        (sym, days),
        fetch="one",
    )
    return normalize_catalyst_row(row)


def _db_query(sql, params=None, fetch="all"):
    """Injected-callable shape the module's functions expect."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def _jsonable(value: Any) -> Any:
    """Postgres hands back Decimal and datetime; the snapshot content-hashes
    every domain payload with json.dumps, which raises on both. A collector that
    returns them takes the whole snapshot down, not just its own domain."""
    from datetime import date, datetime as _dt
    from decimal import Decimal
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def get_catalysts(days: int = 7) -> dict[str, Any]:
    """Domain collector for `catalysts`, resolved by the snapshot by name.

    `get_catalyst_record(db_query, symbol)` exists but requires arguments the
    snapshot never passes, so calling it raised TypeError and the domain
    reported unavailable -- while 133,659 catalyst rows sat in the table, 646 of
    them from the last 24 hours. The per-symbol function is untouched; this is
    the domain-level view it never had.

    `as_of` is the newest event's own timestamp, never `now()`: stamping the
    read time would report the domain fresh on a feed that had stopped.
    """
    rows = _db_query(
        """SELECT symbol, catalyst_type, headline, severity, impact_score, confidence,
                  COALESCE(published_at, created_at) AS at
           FROM catalyst_events
           WHERE catalyst_type <> 'other'
             AND COALESCE(published_at, created_at) > now() - make_interval(days => %s)
           ORDER BY COALESCE(published_at, created_at) DESC
           LIMIT 500""",
        (int(days),),
    ) or []

    normalized = [c for c in (normalize_catalyst_row(r) for r in rows) if c]
    if not normalized:
        return {"state": "DATA_UNAVAILABLE", "as_of": "", "catalysts": [],
                "gap_reason": "no_catalyst_events_in_window"}

    newest = max((r.get("at") for r in rows if r.get("at")), default=None)
    return {
        "state": "AVAILABLE",
        "as_of": newest.isoformat() if hasattr(newest, "isoformat") else str(newest or ""),
        "catalyst_count": len(normalized),
        "symbols_covered": sorted({str(r.get("symbol")).upper() for r in rows if r.get("symbol")}),
        "catalysts": _jsonable(normalized[:100]),
    }


def get_latest_news(db_query, symbols: list[str], *, hours: int = 72) -> dict[str, dict[str, Any]]:
    """{SYMBOL: {title, source, url, published_at, sentiment}} — the newest non-duplicate article per symbol
    (news_articles, registry domain catalyst_news; advice digests, operator 2026-10-08). Read-only."""
    syms = sorted({(s or "").upper() for s in symbols if s})
    if not syms:
        return {}
    rows = db_query(
        f"""
        SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol, title, source, source_url, published_at, sentiment
        FROM news_articles
        WHERE upper(symbol) = ANY(%s) AND published_at > now() - make_interval(hours => %s)
          AND NOT COALESCE(is_duplicate, false) AND title IS NOT NULL AND {not_news_sql()}
        ORDER BY upper(symbol), published_at DESC
        """,
        (syms, int(hours)),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        at = r.get("published_at")
        out[str(r["symbol"])] = {"title": r.get("title"), "source": r.get("source"), "url": r.get("source_url"),
                                 "published_at": at.isoformat() if hasattr(at, "isoformat") else at,
                                 "sentiment": r.get("sentiment")}
    return out


# Quote pages and option-contract listings that the RSS feeds return as "news" (operator 2026-10-09: the BRCC view
# listed "BRCC Oct 2026 8.000 call (BRCC261016C00008000) stock price, news, quote and history"). 594 of 4,908 articles
# in the 7 days to 2026-10-09 matched. They are not news and are left out wherever news is read.
NOT_NEWS_PATTERNS = (
    r"\d+\.\d{3} (call|put) \(",                         # option-contract listing pages
    r"stock price, news, quote|stock historical prices",   # quote pages
    r"\(.+\) stock forecasts?( & analyst predictions)? -",  # forecast listing pages
    r"latest stock price, analysis, news",
)


def not_news_sql(col: str = "title") -> str:
    """SQL predicate that keeps real headlines: `col !~* p` for every NOT_NEWS_PATTERNS entry (no parameters)."""
    return " AND ".join(f"COALESCE({col}, '') !~* '{p}'" for p in NOT_NEWS_PATTERNS)


def title_key(title: Any) -> str:
    """Comparable headline: lower-case, whitespace-collapsed, trailing " - Publisher" dropped (feeds append it)."""
    t = " ".join(str(title or "").lower().split())
    head, sep, tail = t.rpartition(" - ")
    if sep and head and len(tail) <= 40:
        t = head
    return t[:120]


def get_symbol_news(db_query, symbol: str, *, days: int = 45, limit: int = 6) -> list[dict[str, Any]]:
    """Newest non-duplicate articles for one symbol (news_articles, registry domain catalyst_news), for the opportunity
    modal (operator 2026-10-08). Same-title rows from different feeds collapse to the newest. Read-only."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    rows = db_query(
        f"""
        SELECT title, source, source_url, published_at, sentiment
        FROM news_articles
        WHERE upper(symbol) = %s AND published_at > now() - make_interval(days => %s)
          AND NOT COALESCE(is_duplicate, false) AND title IS NOT NULL AND {not_news_sql()}
        ORDER BY published_at DESC
        LIMIT %s
        """,
        (sym, int(days), int(limit) * 3),
    ) or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        key = title_key(r.get("title"))
        if not key or key in seen:
            continue
        seen.add(key)
        at = r.get("published_at")
        out.append({"title": r.get("title"), "source": r.get("source"), "url": r.get("source_url"),
                    "published_at": at.isoformat() if hasattr(at, "isoformat") else at,
                    "sentiment": r.get("sentiment")})
        if len(out) >= int(limit):
            break
    return out


def get_news_bulk(db_query, symbols: list[str], *, hours: int = 72, per_symbol: int = 6) -> dict[str, list[dict[str, Any]]]:
    """{SYMBOL: [articles newest first]} for many symbols in one query (news_articles, registry domain catalyst_news),
    for the 5-min scalp lane's catalyst read (2026-10-09). Same-title rows collapse per symbol. Read-only."""
    syms = sorted({(s or "").upper().strip() for s in symbols if s and str(s).strip()})
    if not syms:
        return {}
    rows = db_query(
        f"""
        SELECT upper(symbol) AS symbol, title, source, source_url, published_at
        FROM news_articles
        WHERE upper(symbol) = ANY(%s) AND published_at > now() - make_interval(hours => %s)
          AND NOT COALESCE(is_duplicate, false) AND title IS NOT NULL AND {not_news_sql()}
        ORDER BY upper(symbol), published_at DESC
        """,
        (syms, int(hours)),
    ) or []
    out: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, set[str]] = {}
    for r in rows:
        sym = str(r.get("symbol") or "")
        key = title_key(r.get("title"))
        if not sym or not key or key in seen.setdefault(sym, set()) or len(out.get(sym, [])) >= int(per_symbol):
            continue
        seen[sym].add(key)
        at = r.get("published_at")
        out.setdefault(sym, []).append({"title": r.get("title"), "source": r.get("source"), "url": r.get("source_url"),
                                        "published_at": at.isoformat() if hasattr(at, "isoformat") else at})
    return out


def get_symbol_catalysts(db_query, symbol: str, *, days: int = 90, limit: int = 5) -> list[dict[str, Any]]:
    """Typed catalysts for one symbol, newest first (catalyst_events; 'other' is untyped news and is excluded), each
    normalized with the verified flag (confidence >= 0.3). For the opportunity modal (operator 2026-10-08). Read-only."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    rows = db_query(
        f"""
        SELECT symbol, catalyst_type, headline, severity, impact_score, confidence, source_url,
               COALESCE(published_at, created_at) AS at
        FROM catalyst_events
        WHERE upper(symbol) = %s AND catalyst_type <> 'other'
          AND COALESCE(published_at, created_at) > now() - make_interval(days => %s)
          AND {not_news_sql("headline")}
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT %s
        """,
        (sym, int(days), int(limit) * 3),
    ) or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        n = normalize_catalyst_row(r) or {}
        key = title_key(n.get("headline"))
        if not key or key in seen:
            continue
        seen.add(key)
        at = r.get("at") or n.get("at")
        n["at"] = at.isoformat() if hasattr(at, "isoformat") else at
        out.append(_jsonable(n))
        if len(out) >= int(limit):
            break
    return out
