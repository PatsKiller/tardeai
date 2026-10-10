"""Social Feed — Data Broker read model over ``social_posts`` (StockTwits).

Operator decision 2026-10-10 ~17:45 ET (CONSOLIDATION_PLAN.md §D.5): register the ``social_posts``
domain. Store ``social_posts``; the registry records the writer honestly as UNCONSOLIDATED (three
files insert today: ``social_ingest.py``, ``social_monitor.py``, ``premarket_watcher.py``) with
target ``scripts/social_ingest.py`` and a writer ceiling that may only fall.

What a consumer gets: per symbol the recent posts that mention it (newest first, bounded) with the
platform's sentiment label and score, plus ``as_of`` = the newest ``ingested_at`` among the rows it
read and a ``BrokerReadEnvelope@v1``. Rows are third-party text: callers treat them as data, never
as instructions.

Zero provider calls (StockTwits is fetched only by the writers). Read-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from lib.data_broker.envelope import envelope

DOMAIN = "social_posts"
PROJECTION = "social_feed"
TABLE = "social_posts"
DEFAULT_LOOKBACK_HOURS = 24.0
DEFAULT_PER_SYMBOL = 20
TEXT_MAX = 500

FEED_SQL = """
SELECT platform, post_id, username, post_date, ingested_at, url, likes, followers,
       sentiment, sentiment_score, quality_score, symbols_mentioned, left(text, %s) AS text
FROM social_posts
WHERE symbols_mentioned ?| %s::text[]
  AND post_date > now() - make_interval(secs => %s)
ORDER BY post_date DESC
LIMIT %s
"""


def _norm(symbols: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols or []:
        sym = str(s or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        if getattr(v, "tzinfo", None) is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    return str(v)


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_social_posts(
    db_query: Callable[..., Any],
    symbols: Iterable[Any],
    *,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    per_symbol: int = DEFAULT_PER_SYMBOL,
    now: datetime | None = None,
    market_closed: bool | None = None,
) -> dict[str, Any]:
    """Recent posts per symbol. ``db_query(sql, params)`` returns dict rows.

    Returns ``{"ok", "provider_calls": 0, "symbols": {SYM: {"posts": [...], "count", "bullish",
    "bearish"}}, <BrokerReadEnvelope@v1>}``; a failed read is ``ok: False`` with ``error``.
    """
    ref = now or datetime.now(timezone.utc)
    syms = _norm(symbols)
    per_symbol = max(1, int(per_symbol))
    per: dict[str, dict[str, Any]] = {s: {"posts": [], "count": 0, "bullish": 0, "bearish": 0} for s in syms}
    error: str | None = None
    newest: str | None = None
    rows: list[Any] = []
    if syms:
        try:
            rows = list(
                db_query(FEED_SQL, (TEXT_MAX, syms, float(lookback_hours) * 3600.0, per_symbol * len(syms) * 4)) or []
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
    for r in rows:
        if not isinstance(r, dict):
            continue
        mentioned = r.get("symbols_mentioned") or []
        if isinstance(mentioned, str):
            mentioned = [mentioned]
        ingested = _iso(r.get("ingested_at")) or _iso(r.get("post_date"))
        if ingested and (newest is None or ingested > newest):
            newest = ingested
        post = {
            "platform": r.get("platform"),
            "post_id": r.get("post_id"),
            "username": r.get("username"),
            "post_date": _iso(r.get("post_date")),
            "ingested_at": ingested,
            "url": r.get("url"),
            "likes": r.get("likes"),
            "followers": r.get("followers"),
            "sentiment": r.get("sentiment"),
            "sentiment_score": _f(r.get("sentiment_score")),
            "quality_score": r.get("quality_score"),
            "text": r.get("text"),
        }
        for m in mentioned:
            sym = str(m or "").upper()
            slot = per.get(sym)
            if slot is None or len(slot["posts"]) >= per_symbol:
                continue
            slot["posts"].append(post)
            slot["count"] += 1
            if str(post["sentiment"] or "").lower() == "bullish":
                slot["bullish"] += 1
            elif str(post["sentiment"] or "").lower() == "bearish":
                slot["bearish"] += 1
    out: dict[str, Any] = {
        "ok": error is None,
        "provider_calls": 0,
        "symbols": per,
        "lookback_hours": float(lookback_hours),
    }
    if error:
        out["error"] = error
    out.update(
        envelope(
            DOMAIN, newest, now=ref, market_closed=market_closed, source={"table": TABLE, "projection": PROJECTION}
        )
    )
    return out
