"""Injected read-only core of the registered catalyst_record projection.

The public catalyst_record facade re-exports these exact implementations. No default
DB adapter, broker/provider import, credential read or connection is available here.
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
        # Preserve the legacy decision input, but do not present a confidence
        # threshold as independently verified publication evidence.
        "verification_basis": "EXPLICIT_SOURCE_FLAG"
        if row.get("verified") is not None
        else "LEGACY_CONFIDENCE_THRESHOLD",
        "factual_verification_status": "VERIFIED"
        if row.get("verified") is True
        and row.get("verification_method") in {"PRIMARY_PUBLICATION", "PUBLICATION_MATCH", "SOURCE_CORROBORATION"}
        and row.get("source_url")
        else "UNVERIFIED"
        if row.get("verified") is False
        else "UNKNOWN",
        "verification_method": row.get("verification_method"),
        "relevance": row.get("relevance"),
        "model_confidence": conf,
        "published_at": row.get("published_at"),
        "observed_at": row.get("observed_at"),
        "source_ref": row.get("source_ref"),
        "severity": row.get("severity"),
        "impact_score": row.get("impact_score"),
        "source_url": row.get("source_url"),
        "at": row.get("published_at") or row.get("created_at") or row.get("ts"),
    }


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


NOT_NEWS_PATTERNS = (
    r"\d+\.\d{3} (call|put) \(",  # option-contract listing pages
    r"stock price, news, quote|stock historical prices",  # quote pages
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


def get_catalyst_records_bulk(db_query, *, days: int = 30, per_symbol: int = 3) -> dict[str, list[dict[str, Any]]]:
    """{SYMBOL: [typed catalysts newest first]} for every symbol with a typed catalyst in the window, in ONE query.

    For the CIO prospect builder (silo audit 2026-10-23, operator: "anything for the security, the CIO agent needs to
    have it in memory"): the same normalization and verified rule as ``get_symbol_catalysts`` (``catalyst_type``
    'other' is untyped news and is excluded; quote pages are not news), plus the row ``id`` and ``subject_guid`` so
    the prospect can name the event and check its identity, and ``source`` (the producing feed). Read-only."""
    rows = (
        db_query(
            f"""
        SELECT id, symbol, subject_guid, catalyst_type, headline, severity, impact_score, confidence, source,
               source_url, at
        FROM (
            SELECT id, upper(symbol) AS symbol, subject_guid::text AS subject_guid, catalyst_type, headline, severity,
                   impact_score, confidence, source, source_url, COALESCE(published_at, created_at) AS at,
                   row_number() OVER (PARTITION BY upper(symbol)
                                      ORDER BY COALESCE(published_at, created_at) DESC, id DESC) AS rn
            FROM catalyst_events
            WHERE catalyst_type <> 'other'
              AND COALESCE(published_at, created_at) > now() - make_interval(days => %s)
              AND {not_news_sql("headline")}
        ) t
        WHERE rn <= %s
        ORDER BY symbol, at DESC, id DESC
        """,
            (int(days), int(per_symbol) * 3),
        )
        or []
    )
    out: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, set[str]] = {}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        key = title_key(r.get("headline"))
        if not sym or not key or key in seen.setdefault(sym, set()) or len(out.get(sym, [])) >= int(per_symbol):
            continue
        seen[sym].add(key)
        n = normalize_catalyst_row(r) or {}
        at = r.get("at") or n.get("at")
        n["at"] = at.isoformat() if hasattr(at, "isoformat") else at
        n.update({"id": r.get("id"), "subject_guid": r.get("subject_guid"), "source": r.get("source")})
        out.setdefault(sym, []).append(_jsonable(n))
    return out
