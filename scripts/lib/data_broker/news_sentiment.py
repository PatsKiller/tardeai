"""Data Broker projection — per-ticker news sentiment from the Alpha Vantage owner.

Proposed registry domain ``news_sentiment`` (config/policy_proposals/
data_source_authority_alpha_vantage_scope_20261010.json; operator grant pending). The single
writer is scripts/alpha_vantage_owner.py: 14 windowed NEWS_SENTIMENT pulls a day (no ticker
filter — a multi-ticker query is an AND), rolled up per ticker over 72 h into
data/runtime/alpha_vantage/news_sentiment_latest.json. This module only reads that file: zero
provider calls, so a scalp list or a catalyst lane can ask about any number of tickers without
spending any of the 25 daily requests.

Measured gap it fills (read-only query 2026-10-10): 0 of 7,492 news_articles rows from the last
3 days carry a sentiment_score.

Freshness: 3 h inside the 06:00-21:00 ET pull window, 13 h outside it. A missing index is
``gap.kind == no_coverage`` (declared ``say_so``); a ticker no article mentioned is ``None``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from lib.data_broker.envelope import envelope

DOMAIN = "news_sentiment"
STALE_AFTER_HOURS = 3.0
STALE_AFTER_HOURS_CLOSED = 13.0
NO_COVERAGE = "say_so"
WRITER = "scripts/alpha_vantage_owner.py"
_ET = ZoneInfo("America/New_York")


def _path(base: Path | None) -> Path:
    if base is not None:
        return Path(base) / "news_sentiment_latest.json"
    from lib.alpha_vantage_owner import state_dir
    return state_dir() / "news_sentiment_latest.json"


def _load(base: Path | None) -> dict[str, Any] | None:
    try:
        return json.loads(_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _window(now: datetime) -> float:
    h = now.astimezone(_ET).hour
    return STALE_AFTER_HOURS if 6 <= h < 21 else STALE_AFTER_HOURS_CLOSED


def _env(doc: dict[str, Any] | None, now: datetime | None) -> dict[str, Any]:
    ref = now or datetime.now(timezone.utc)
    env = envelope(DOMAIN, (doc or {}).get("as_of"), now=ref, registry={}, stale_after_hours=_window(ref),
                   source={"file": "runtime/alpha_vantage/news_sentiment_latest.json", "writer": WRITER,
                           "projection": DOMAIN, "provider": "alpha_vantage",
                           "registry": "PROPOSED (operator grant pending)"})
    if env.get("gap"):
        env["gap"]["declared_behaviour"] = NO_COVERAGE
    if doc:
        env["last_pull"] = doc.get("last_pull")
    return env


def get_sentiment(symbols: Iterable[str], *, base: Path | None = None,
                  now: datetime | None = None) -> dict[str, Any]:
    """{symbols: {SYM: {articles, articles_24h, weighted_score, label, latest_published_at, top} | None}, envelope}."""
    doc = _load(base)
    by = (doc or {}).get("by_ticker") or {}
    out: dict[str, Any] = {"symbols": {str(s).upper(): by.get(str(s).upper()) for s in symbols},
                           "window_hours": (doc or {}).get("window_hours"),
                           "min_relevance": (doc or {}).get("min_relevance")}
    out.update(_env(doc, now))
    return out


def get_articles(symbol: str, *, lookback_hours: float = 72.0, min_relevance: float = 0.3,
                 base: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Articles mentioning ``symbol`` (relevance >= min_relevance), newest first, with that ticker's score."""
    doc = _load(base)
    sym = str(symbol).upper()
    ref = now or datetime.now(timezone.utc)
    cut = ref - timedelta(hours=lookback_hours)
    rows = []
    for a in (doc or {}).get("articles") or []:
        t = next((t for t in a.get("tickers") or [] if t.get("ticker") == sym), None)
        if not t or (t.get("relevance") or 0) < min_relevance:
            continue
        try:
            pub = datetime.fromisoformat(a.get("published_at") or "")
        except ValueError:
            continue
        if pub < cut:
            continue
        rows.append({"title": a.get("title"), "url": a.get("url"), "source": a.get("source"),
                     "published_at": a.get("published_at"), "ticker_score": t.get("score"),
                     "ticker_label": t.get("label"), "relevance": t.get("relevance"),
                     "overall_score": a.get("overall_score"), "overall_label": a.get("overall_label")})
    rows.sort(key=lambda r: r["published_at"] or "", reverse=True)
    out: dict[str, Any] = {"symbol": sym, "articles": rows}
    out.update(_env(doc, ref))
    return out
