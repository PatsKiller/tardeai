"""catalyst_enrichment.py — Multi-source catalyst enrichment for each ticker.

Sources (in priority order for dedup):
  1. Finnhub company news
  2. NewsAPI everything endpoint
  3. Polygon ticker news
  4. FMP (Financial Modeling Prep) stock news
  5. Alpha Vantage news sentiment
  6. Finviz News API  (news_export.ashx — token auth, NEW)
  7. Yahoo Finance    (RSS + JSON fallback, no key, NEW)

Rules:
  - Lookback: max 72 hours; preferred window 30 min – 12 hours
  - News is ranked by recency (most recent first)
  - Material events only: FDA, earnings, M&A, material 8-K, short squeeze
  - Noise filter: marketing emails, generic press, wire spam rejected
  - Duplicate headlines deduplicated by 10-word title fingerprint
"""
from __future__ import annotations
import hashlib, os, time, re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

# ── Constants ────────────────────────────────────────────────────────────────

LOOKBACK_MAX_HOURS = 72
PREFERRED_MAX_HOURS = 12

# Keywords that disqualify an article as noise
NOISE_KEYWORDS = [
    "newsletter", "subscribe", "sign up", "unsubscribe", "weekly digest",
    "marketing", "investor relations presentation", "conference invitation",
    "webinar registration", "sponsored", "advertorial", "press release service",
    "globe newswire general", "businesswire general",
]

# Keywords that classify a catalyst as high_impact
HIGH_IMPACT_KEYWORDS = [
    "fda approval", "fda approved", "fda approv", "pdufa", "nda approval",
    "bla approval", "clinical trial results", "phase 3 results", "phase 2 results",
    "breakthrough therapy", "fast track designation",
    "earnings beat", "earnings per share beat", "raised guidance", "revenue beat",
    "above consensus", "exceeded expectations",
    "acquisition", "merger", "buyout", "takeover", "letter of intent", "loi",
    "going private", "going-private",
    "material definitive agreement", "8-k material", "material event",
    "restatement", "sec investigation", "doj investigation", "subpoena",
    "short squeeze", "heavily shorted", "short interest",
]

# Keywords that classify a catalyst as medium_impact
MEDIUM_IMPACT_KEYWORDS = [
    "upgrade", "price target raised", "outperform", "overweight", "buy rating",
    "partnership", "licensing agreement", "supply agreement", "contract award",
    "new product launch", "fda clearance", "510k clearance",
    "secondary offering", "atm offering", "shelf registration s-3",
    "executive order", "national security", "government funding", "federal funding",
    "department of commerce", "commerce department", "dod contract", "defense contract",
    "chips act", "us government", "u.s. government", "government investment",
    "national quantum", "quantum initiative",
]


# ── Utilities ────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _cutoff_utc(hours: int) -> datetime:
    return _now_utc() - timedelta(hours=hours)

def _fingerprint(title: str, symbol: str = "", day: str = "") -> str:
    """De-collision (2026-06-11): the 10-word MD5 collapsed DISTINCT catalysts ("FDA approves drug X" vs
    "...drug Y" share prefixes). Symbol+day now salt the print so only true same-story dupes collapse."""
    title = f"{symbol}|{day}|{title}"
    return __fingerprint_inner(title)


def __fingerprint_inner(title: str) -> str:
    words = title.lower().split()[:10]
    return hashlib.md5(" ".join(words).encode()).hexdigest()

def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:26], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

def _hours_old(dt: Optional[datetime]) -> float:
    if dt is None:
        return 9999.0
    delta = _now_utc() - dt
    return delta.total_seconds() / 3600

def _is_noise(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in NOISE_KEYWORDS)


# Generic multi-stock / roundup patterns that are never ticker-specific catalysts
_GENERIC_ROUNDUP_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\d+\s+\w+\s+stocks?\s+moving",        # "12 Industrials Stocks Moving..."
        r"top gainers and losers",
        r"after.hours?\s+session",
        r"pre.?market\s+movers",
        r"biggest\s+movers",
        r"most\s+active\s+stocks",
        r"stocks?\s+experiencing",
        r"unusual\s+volume\s+in\s+today",         # "These stocks have an unusual volume..."
        r"these\s+stocks\s+have\s+an?\s+unusual",
        r"top\s+(?:midday|morning|afternoon)\s+(?:gainers|losers)",
        r"curious\s+about\s+the\s+stocks",
        r"stocks?\s+that\s+are\s+showing\s+activity",
        r"discover\s+the\s+top\s+movers",
        r"market\s+wrap",
        r"morning\s+bell",
        r"weekly\s+roundup",
        r"here.s how much \$\d+",                 # "Here's How Much $100 Invested..."
        r"invested.*\d+\s+years?\s+ago",
    ]
]


def _is_generic_roundup(title: str) -> bool:
    """Detect generic multi-stock / roundup articles that aren't real catalysts."""
    return any(pat.search(title) for pat in _GENERIC_ROUNDUP_PATTERNS)

def _classify_impact(title: str, summary: str = "") -> str:
    text = (title + " " + summary).lower()
    if any(kw in text for kw in HIGH_IMPACT_KEYWORDS):
        return "high_impact"
    if any(kw in text for kw in MEDIUM_IMPACT_KEYWORDS):
        return "medium_impact"
    if any(c.isupper() for c in title[10:]) or len(title.split()) > 4:
        return "low_impact"
    return "noise"

def _recency_tier(hours: float) -> str:
    if hours <= 2:
        return "under_2h"
    if hours <= 12:
        return "h2_to_12h"
    if hours <= 72:
        return "h12_to_72h"
    return "over_72h"

def _recency_multiplier(tier: str) -> float:
    return {"under_2h": 1.5, "h2_to_12h": 1.2, "h12_to_72h": 1.0, "over_72h": 0.0}.get(tier, 0.0)


# ── Per-API fetchers ─────────────────────────────────────────────────────────

def _fetch_finnhub(symbol: str, from_dt: datetime, to_dt: datetime) -> List[Dict]:
    try:
        from api_budget import spend as _ab_spend
        if not _ab_spend("finnhub"):
            return []
    except Exception:
        pass
    key = _env("FINNHUB_API_KEY")
    if not key:
        return []
    try:
        from datetime import timezone
        url = "https://finnhub.io/api/v1/company-news"
        # Finnhub requires YYYY-MM-DD format in Eastern or UTC
        _from = from_dt.astimezone(timezone.utc).strftime("%Y-%m-%d") if from_dt.tzinfo else from_dt.strftime("%Y-%m-%d")
        _to   = to_dt.astimezone(timezone.utc).strftime("%Y-%m-%d")   if to_dt.tzinfo   else to_dt.strftime("%Y-%m-%d")
        params = {
            "symbol": symbol,
            "from":   _from,
            "to":     _to,
            "token":  key,
        }
        resp = requests.get(url, params=params, timeout=(5, 8))
        if resp.status_code == 422:
            return []   # Unprocessable — skip silently
        resp.raise_for_status()
        items = resp.json() or []
        results = []
        for item in items:
            dt = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
            results.append({
                "title": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "source": item.get("source", "Finnhub"),
                "published_at": dt.isoformat(),
                "provider": "finnhub",
            })
        return results
    except Exception:
        return []

def _fetch_newsapi(symbol: str, company: str, from_dt: datetime) -> List[Dict]:
    try:
        from api_budget import spend as _ab_spend
        if not _ab_spend("newsapi"):
            return []
    except Exception:
        pass
    key = _env("NEWSAPI_KEY")
    if not key:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        query = f"{symbol} stock" if not company else f"{symbol} OR \"{company}\""
        params = {
            "q": query,
            "from": from_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 20,
            "apiKey": key,
        }
        resp = requests.get(url, params=params, timeout=(5, 8))
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        results = []
        for a in articles:
            results.append({
                "title": a.get("title", ""),
                "summary": a.get("description", ""),
                "url": a.get("url", ""),
                "source": a.get("source", {}).get("name", "NewsAPI"),
                "published_at": a.get("publishedAt", ""),
                "provider": "newsapi",
            })
        return results
    except Exception:
        return []

def _fetch_polygon(symbol: str, from_dt: datetime) -> List[Dict]:
    try:
        from api_budget import spend as _ab_spend
        if not _ab_spend("polygon"):
            return []
    except Exception:
        pass
    key = _env("POLYGON_API_KEY")
    if not key:
        return []
    try:
        url = "https://api.polygon.io/v2/reference/news"
        params = {
            "ticker": symbol,
            "published_utc.gte": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "order": "desc",
            "limit": 20,
            "apiKey": key,
        }
        resp = requests.get(url, params=params, timeout=(5, 8))
        resp.raise_for_status()
        items = resp.json().get("results", [])
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "summary": item.get("description", ""),
                "url": item.get("article_url", ""),
                "source": (item.get("publisher") or {}).get("name", "Polygon"),
                "published_at": item.get("published_utc", ""),
                "provider": "polygon",
            })
        return results
    except Exception:
        return []

def _fetch_fmp(symbol: str, limit: int = 20) -> List[Dict]:
    try:
        from api_budget import spend as _ab_spend
        if not _ab_spend("fmp"):
            return []
    except Exception:
        pass
    key = _env("FMP_API_KEY")
    if not key:
        return []
    try:
        # Try v3 stable endpoint first, fall back silently on 403
        url = "https://financialmodelingprep.com/stable/stock-news"
        params = {"tickers": symbol, "limit": limit, "apikey": key}
        resp = requests.get(url, params=params, timeout=(5, 8))
        if resp.status_code == 403:
            # v3 stock_news requires higher plan — try v4 general search
            url2 = "https://financialmodelingprep.com/api/v4/general_news"
            params2 = {"page": 0, "apikey": key}
            try:
                resp = requests.get(url2, params=params2, timeout=(5, 8))
                if not resp.ok:
                    return []
                # Filter for this symbol
                all_news = resp.json() or []
                sym_upper = symbol.upper()
                filtered = [n for n in all_news
                           if sym_upper in (n.get("symbol","") or "").upper()
                           or sym_upper in (n.get("title","") or "").upper()]
                return [{
                    "provider": "fmp",
                    "title": n.get("title",""),
                    "summary": n.get("text",""),
                    "published_at": n.get("publishedDate",""),
                    "url": n.get("url",""),
                } for n in filtered[:limit]]
            except Exception:
                return []
        resp.raise_for_status()
        items = resp.json() or []
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "summary": item.get("text", ""),
                "url": item.get("url", ""),
                "source": item.get("site", "FMP"),
                "published_at": item.get("publishedDate", ""),
                "provider": "fmp",
            })
        return results
    except Exception:
        return []

def _fetch_alpha_vantage(symbol: str) -> List[Dict]:
    try:
        from api_budget import spend as _ab_spend
        if not _ab_spend("alphavantage"):
            return []
    except Exception:
        pass
    # Alpha Vantage free tier = 5 calls/min, 100/day — disabled for bulk catalyst runs
    # Enable only for single-ticker deep dives: ENABLE_ALPHA_VANTAGE_CATALYST=true in .env
    if _env("ENABLE_ALPHA_VANTAGE_CATALYST", "false").lower() != "true":
        return []
    key = _env("ALPHA_VANTAGE_API_KEY")
    if not key:
        return []
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "sort": "LATEST",
            "limit": 20,
            "apikey": key,
        }
        resp = requests.get(url, params=params, timeout=(5, 8))
        resp.raise_for_status()
        items = resp.json().get("feed", [])
        results = []
        for item in items:
            raw_time = item.get("time_published", "")
            try:
                dt = datetime.strptime(raw_time, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                published_at = dt.isoformat()
            except ValueError:
                published_at = ""
            results.append({
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "source": item.get("source", "Alpha Vantage"),
                "published_at": published_at,
                "provider": "alpha_vantage",
                "sentiment_score": item.get("overall_sentiment_score", 0),
                "sentiment_label": item.get("overall_sentiment_label", "Neutral"),
            })
        return results
    except Exception:
        return []


# ── Source 6: Finviz News API (token-based, replaces old regex scraper) ──────

def _fetch_finviz_news(symbol: str) -> List[Dict]:
    """
    Fetch Finviz ticker news via news_export.ashx API endpoint.
    Uses FINVIZ_API_TOKEN (never expires). Falls back to cookie-based
    quote page scrape if token is absent.
    """
    token = _env("FINVIZ_API_TOKEN")

    # ── Method A: Token API (preferred) ──────────────────────────────────────
    if token and _env("FINVIZ_NEWS_ENABLED", "true").lower() == "true":
        try:
            url = f"https://elite.finviz.com/news_export.ashx?t={symbol}&auth={token}"
            headers = {
                "User-Agent": _env("FINVIZ_USER_AGENT", "Mozilla/5.0"),
                "Accept": "*/*",
            }
            resp = finviz_get(url, headers=headers, timeout=(5, 10), raise_on_429=False)
            if resp.status_code == 200:
                data = []
                content_type = resp.headers.get("content-type", "")

                # Handle CSV response (Finviz returns CSV with columns: Title,Source,Date,Url,Category)
                if "csv" in content_type or resp.text.startswith('"Title"'):
                    import csv, io
                    reader = csv.DictReader(io.StringIO(resp.text))
                    for row in reader:
                        data.append({
                            "title": row.get("Title", "").strip(),
                            "source": row.get("Source", "Finviz"),
                            "date": row.get("Date", ""),
                            "url": row.get("Url", ""),
                            "category": row.get("Category", ""),
                        })
                else:
                    # Try JSON fallback
                    try:
                        data = resp.json()
                        if not isinstance(data, list):
                            data = data.get("news", data.get("articles", []))
                    except Exception:
                        data = []

                results = []
                sym_lower = symbol.lower()
                company_lower = (_env("_FINVIZ_COMPANY") or "").lower()  # not available here
                for item in (data or []):
                    headline = (item.get("headline") or item.get("title") or "").strip()
                    if not headline:
                        continue
                    # Finviz news_export returns market-wide news regardless of ?t= param.
                    # Only keep articles that actually mention the ticker symbol.
                    hl_lower = headline.lower()
                    if sym_lower not in hl_lower:
                        continue
                    date_str = item.get("date") or item.get("datetime") or ""
                    pub_ts = 0
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%b-%d-%y %I:%M%p", "%b-%d-%Y %I:%M%p"):
                        try:
                            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                            pub_ts = int(dt.timestamp())
                            break
                        except ValueError:
                            continue
                    pub_iso = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat() if pub_ts else ""
                    results.append({
                        "title": headline,
                        "summary": "",
                        "url": item.get("url") or item.get("link") or "",
                        "source": item.get("source") or "Finviz",
                        "published_at": pub_iso,
                        "provider": "finviz_news",
                    })
                if results:
                    return results[:10]
        except Exception:
            pass

    # ── Method B: Cookie scrape fallback (legacy) ─────────────────────────────
    cookie = _env("FINVIZ_COOKIE")
    if not cookie:
        return []
    try:
        url = f"https://elite.finviz.com/quote.ashx?t={symbol}&p=d"
        headers = {
            "User-Agent": _env("FINVIZ_USER_AGENT", "Mozilla/5.0"),
            "Cookie": cookie,
            "Accept": "text/html,*/*",
        }
        resp = finviz_get(url, headers=headers, timeout=(5, 10), raise_on_429=False)
        if resp.status_code != 200:
            return []
        html = resp.text
        pattern = re.compile(
            r'class="news-date-cell[^"]*"[^>]*>([^<]+)</td>.*?'
            r'href="([^"]+)"[^>]*>([^<]+)</a>.*?'
            r'(?:finviz\.com|news-source)[^>]*>([^<]+)<',
            re.DOTALL
        )
        items = []
        for m in pattern.finditer(html):
            date_str, link, title, source = m.groups()
            title = title.strip()[:200]
            if not title:
                continue
            items.append({
                "title": title,
                "summary": "",
                "url": link.strip(),
                "source": source.strip() or "Finviz",
                "published_at": "",
                "provider": "finviz_cookie",
            })
            if len(items) >= 8:
                break
        return items
    except Exception:
        return []


# ── Source 7: Yahoo Finance (RSS + JSON, no key needed) ───────────────────────

def _fetch_yahoo_news(symbol: str) -> List[Dict]:
    """
    Fetch Yahoo Finance news for a ticker.
    Strategy A: /v1/finance/search JSON (fast, ~8 items)
    Strategy B: RSS feed fallback (broader history)
    No API key required.
    """
    if _env("YAHOO_NEWS_ENABLED", "true").lower() != "true":
        return []

    results: List[Dict] = []

    # ── Strategy A: JSON search ───────────────────────────────────────────────
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": symbol, "newsCount": 10, "quotesCount": 0}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com/",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=(5, 8))
        if resp.status_code == 200:
            for item in resp.json().get("news", []):
                headline = (item.get("title") or "").strip()
                if not headline:
                    continue
                pub_ts = item.get("providerPublishTime", 0)
                pub_iso = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat() if pub_ts else ""
                results.append({
                    "title": headline,
                    "summary": "",
                    "url": item.get("link", ""),
                    "source": "Yahoo Finance",
                    "published_at": pub_iso,
                    "provider": "yahoo_finance",
                })
    except Exception:
        pass

    # ── Strategy B: RSS fallback ──────────────────────────────────────────────
    if not results:
        try:
            import xml.etree.ElementTree as ET
            from email.utils import parsedate_to_datetime
            rss_url = (
                f"https://feeds.finance.yahoo.com/rss/2.0/headline"
                f"?s={symbol}&region=US&lang=en-US"
            )
            resp = requests.get(rss_url, timeout=(5, 8),
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:15]:
                    title_el = item.find("title")
                    link_el  = item.find("link")
                    date_el  = item.find("pubDate")
                    headline = title_el.text.strip() if title_el is not None and title_el.text else ""
                    if not headline:
                        continue
                    pub_iso = ""
                    if date_el is not None and date_el.text:
                        try:
                            pub_iso = parsedate_to_datetime(date_el.text).isoformat()
                        except Exception:
                            pass
                    results.append({
                        "title": headline,
                        "summary": "",
                        "url": link_el.text.strip() if link_el is not None and link_el.text else "",
                        "source": "Yahoo Finance",
                        "published_at": pub_iso,
                        "provider": "yahoo_finance",
                    })
        except Exception:
            pass

    return results[:10]


# ── Main enrichment function ─────────────────────────────────────────────────

def enrich_ticker(symbol: str, company: str = "") -> Dict[str, Any]:
    """Fetch, deduplicate, classify, and rank all catalyst news for one ticker.

    Returns a dict with keys:
      catalysts         : list of enriched article dicts (sorted newest first)
      top_catalyst      : the single highest-impact+most-recent article
      catalyst_tier     : "high_impact" | "medium_impact" | "low_impact" | "none"
      catalyst_count    : int
      has_fresh_catalyst: bool (any article within PREFERRED_MAX_HOURS)
      sources_hit       : list of provider names that returned data
    """
    now    = _now_utc()
    cutoff = _cutoff_utc(LOOKBACK_MAX_HOURS)

    # Gather from all 7 providers
    raw: List[Dict] = []
    raw += _fetch_finnhub(symbol, cutoff, now)
    raw += _fetch_newsapi(symbol, company, cutoff)
    raw += _fetch_polygon(symbol, cutoff)
    raw += _fetch_fmp(symbol)
    raw += _fetch_alpha_vantage(symbol)
    raw += _fetch_finviz_news(symbol)     # ← Source 6: Finviz News API
    raw += _fetch_yahoo_news(symbol)      # ← Source 7: Yahoo Finance

    # Track which providers returned something
    sources_hit = list({a["provider"] for a in raw if a.get("title")})

    # Filter, enrich, deduplicate
    seen_fingerprints: set = set()
    enriched: List[Dict] = []
    for article in raw:
        title   = (article.get("title") or "").strip()
        summary = (article.get("summary") or "").strip()
        if not title:
            continue
        if _is_noise(title, summary):
            continue
        if _is_generic_roundup(title):
            continue
        published_at = article.get("published_at", "")
        fp = _fingerprint(title, symbol=symbol, day=str(published_at)[:10])
        if fp in seen_fingerprints:
            continue
        seen_fingerprints.add(fp)
        dt    = _parse_iso(published_at)
        hours = _hours_old(dt)
        if hours > LOOKBACK_MAX_HOURS:
            # Keep as extended-window fallback if nothing within 72h
            if hours <= 168:  # 7-day extended window
                impact = _classify_impact(title, summary)
                if impact != "noise":
                    enriched.append({
                        **article,
                        "symbol": symbol,
                        "impact_tier": impact,
                        "hours_old": round(hours, 2),
                        "recency_tier": "extended",
                        "recency_multiplier": 0.3,
                        "is_fresh": False,
                        "is_extended": True,
                        "sort_key": (3, hours),  # rank below all fresh articles
                    })
            continue
        impact = _classify_impact(title, summary)
        if impact == "noise":
            continue
        recency_tier = _recency_tier(hours)
        enriched.append({
            **article,
            "symbol": symbol,
            "impact_tier": impact,
            "hours_old": round(hours, 2),
            "recency_tier": recency_tier,
            "recency_multiplier": _recency_multiplier(recency_tier),
            "is_fresh": hours <= PREFERRED_MAX_HOURS,
            "is_extended": False,
            # sort_key: lower = better (high impact + more recent wins)
            "sort_key": (
                0 if impact == "high_impact" else (1 if impact == "medium_impact" else 2),
                hours,
            ),
        })

    enriched.sort(key=lambda x: x["sort_key"])

    # If only extended-window articles found, use them; otherwise prefer fresh
    fresh_articles = [a for a in enriched if not a.get("is_extended")]
    top = fresh_articles[0] if fresh_articles else (enriched[0] if enriched else None)
    top_tier = top["impact_tier"] if top else "none"
    has_fresh = any(a["is_fresh"] for a in enriched)

    return {
        "symbol": symbol,
        "catalysts": enriched,
        "top_catalyst": top,
        "catalyst_tier": top_tier,
        "catalyst_count": len(enriched),
        "has_fresh_catalyst": has_fresh,
        "sources_hit": sources_hit,
    }


def enrich_all(
    symbols_data: List[Dict[str, Any]],
    rate_limit_delay: float = 0.15,
    max_tickers: int = 100,
) -> Dict[str, Dict]:
    """Enrich a list of ticker dicts (each must have 'symbol' key).
    Returns {symbol: enrichment_result}.

    max_tickers: cap enrichment to top N candidates (sorted by _pre_score if present).
    rate_limit_delay: seconds between tickers (0.15s is safe for all 7 sources).
    """
    sorted_data = sorted(
        symbols_data,
        key=lambda r: r.get("_pre_score", 0),
        reverse=True
    )[:max_tickers]

    results: Dict[str, Dict] = {}
    for row in sorted_data:
        sym     = str(row.get("symbol", "")).upper().strip()
        company = str(row.get("company", ""))
        if not sym:
            continue
        results[sym] = enrich_ticker(sym, company)
        time.sleep(rate_limit_delay)
    return results
