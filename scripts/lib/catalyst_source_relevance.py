"""Is a search result evidence of a catalyst for this symbol, today? (LQ-20261107-131)

2026-11-07 audit of the live 2026-11-06 run: the researcher took ``all_sources[0]`` as the catalyst and set
``confidence = min(0.7, 0.3 + 0.1 * len(all_sources))``, so the catalyst attached to a symbol was whichever page a
search engine happened to rank first, and confidence grew with the number of pages returned about anything at all.
Measured on that day's 38 sources: CIIT was "news_momentum high 0.6" on a 2020 Wikinews page, a bank login page and
a certification page; VSA on a car warning-light article; DFH "high 0.6" on a Forbes page 298 days old and a stock
chart. All three are ticker STRINGS somewhere on a page, not stories about the issuer.

Three questions, asked of every result before it can become evidence:

* IDENTITY — does the page's own text name the ticker as a whole word, or the company by name? The read-side
  matcher (:func:`lib.hermes_scalp_catalyst_record.verify_identity`) is reused, never re-implemented, so the writer
  refuses exactly what the readers would demote. A ticker that appears only in the URL path is a site section
  ("…/segg/"), not a story.
* RECENCY — a dated page older than :data:`FRESH_DAYS` is history, not a current catalyst. An undated page is weak
  evidence and is accepted only when it names the COMPANY: a page carrying just the ticker is the search artefact
  above (a car light, a time zone, a compensation disclosure).
* SHAPE — a quote/chart page is a market-data surface, never a story.

Pure: no I/O, no network, no clock beyond the ``now`` the caller passes. Stdlib + the read-side matcher only.
READ_ONLY_ADVISORY.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import unquote, urlparse

from lib.hermes_scalp_catalyst_record import VERIFIED, verify_identity

#: A dated page older than this many days is not a *current* catalyst (measured: the stale pages in the audit were
#: 129, 245, 298 and 688 days old; the legitimate ones 0-8 — the line is not near either cluster).
FRESH_DAYS = 14

#: URL path segments that mean "market data", never "story" (a chart, a quote, a ticker overview page).
_MARKET_DATA_SEGMENTS = frozenset({"stockchart", "stockcharts", "chart", "charts", "quote", "quotes", "overview",
                                   "markets", "market-data"})
#: …and the ones that only mean it when the symbol itself sits in the path ("/investing/stock/dfh", "/ticker/ELPW").
_MARKET_DATA_PARENT = frozenset({"investing", "stock", "ticker", "quote", "symbol"})

#: Basis of an evidence set, strongest first.
FRESH = "fresh"
COMPANY = "company"
NONE = "none"

#: Why a source was refused (the values the tests and the DONE note quote).
UNRELATED = "unrelated"
URL_ONLY = "ticker only in the URL"
MARKET_DATA = "quote/chart page"
UNDATED_TICKER = "undated, ticker only"


def publish_age_days(published: Any, *, now: Optional[datetime] = None) -> Optional[int]:
    """Age in whole days of an ISO-8601 or RFC-2822 publish stamp; ``None`` when absent or unparseable."""
    text = str(published or "").strip()
    if not text:
        return None
    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((_utc(now) - dt).days, 0)


def _utc(moment: Optional[datetime] = None) -> datetime:
    """UTC now (or ``moment``); a naive stamp is read as UTC so a subtraction never mixes naive and aware."""
    moment = moment or datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _market_data_page(url: Any, symbol: str = "") -> bool:
    """A quote, chart or overview page — a number, not a story."""
    try:
        path = unquote(urlparse(str(url or "")).path).lower()
    except ValueError:
        return False
    segs = [s for s in path.split("/") if s]
    if any(seg in _MARKET_DATA_SEGMENTS for seg in segs):
        return True
    return bool(symbol) and symbol.lower() in segs and any(seg in _MARKET_DATA_PARENT for seg in segs)


def _identity(symbol: str, source: Mapping[str, Any], company_names: Iterable[str]) -> dict[str, Any]:
    """The read-side verdict for ONE search result (its title as the headline, so ``where`` names the field)."""
    return verify_identity(
        symbol,
        {"catalyst_summary": str(source.get("title") or ""), "sources": [source]},
        company_names,
    )


def select_evidence(symbol: str, sources: Iterable[Any], company_names: Iterable[str] = (), *,
                    now: Optional[datetime] = None, fresh_days: int = FRESH_DAYS) -> dict[str, Any]:
    """Rank a run's search results into catalyst evidence. Pure.

    Returns ``{"basis", "best", "evidence", "rejected", "confidence"}``:

    * ``evidence`` — entries ``{"source", "age_days", "where", "matched"}``, freshest first then undated;
    * ``best`` — ``evidence[0]`` when the set can carry a catalyst, else ``None``;
    * ``confidence`` — 0.3 + 0.1 per FRESH source (cap 0.7); 0.3 when only undated company-named pages; ``None``
      when nothing qualifies (the caller's floor is its own);
    * ``basis`` — ``fresh`` / ``company`` / ``none``.
    """
    names = list(company_names or ())
    now = _utc(now)
    fresh: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []          # undated, but they name the company itself
    rejected: list[dict[str, Any]] = []

    def refuse(source: Mapping[str, Any], why: str) -> None:
        rejected.append({"title": str(source.get("title") or "")[:200], "url": str(source.get("url") or ""),
                         "why": why})

    for source in sources or []:
        if not isinstance(source, Mapping):
            continue
        if source.get("error"):
            refuse(source, "error row")
            continue
        verdict = _identity(symbol, source, names)
        if verdict.get("status") != VERIFIED:
            refuse(source, UNRELATED)
            continue
        if verdict.get("evidence") == "source URL":
            refuse(source, URL_ONLY)
            continue
        if _market_data_page(source.get("url"), symbol):
            refuse(source, MARKET_DATA)
            continue
        age = publish_age_days(source.get("published") or source.get("publishedDate"), now=now)
        if age is not None and age > fresh_days:
            refuse(source, f"stale ({age}d old)")
            continue
        entry = {"source": source, "age_days": age, "where": verdict.get("evidence"),
                 "matched": verdict.get("matched")}
        if age is not None:
            fresh.append(entry)
        elif entry["matched"] == "company":
            weak.append(entry)
        else:
            refuse(source, UNDATED_TICKER)   # an undated page that carries the ticker and nothing else

    fresh.sort(key=lambda e: e["age_days"])
    evidence = fresh + weak
    if fresh:
        return {"basis": FRESH, "best": fresh[0], "evidence": evidence, "rejected": rejected,
                "confidence": min(0.7, 0.3 + 0.1 * len(fresh))}
    if weak:
        return {"basis": COMPANY, "best": weak[0], "evidence": evidence, "rejected": rejected,
                "confidence": 0.3}
    return {"basis": NONE, "best": None, "evidence": [], "rejected": rejected, "confidence": None}


def rejected_summary(decision: Mapping[str, Any], limit: int = 3) -> list[dict[str, str]]:
    """The refusal rows a record carries (bounded: a record is read by everyone downstream)."""
    return [{"url": str(r.get("url") or "")[:300], "why": str(r.get("why") or "")}
            for r in (decision.get("rejected") or [])[:limit]]
