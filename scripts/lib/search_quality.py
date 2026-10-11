"""search_quality.py — is a free answer good enough, or may the question escalate to paid search?

The measurable rule (``config/search_routing_policy.json`` ``quality``, per class):

  * ``min_results``   results with a URL;
  * ``min_trusted``   results whose host is a trusted financial domain (or a subdomain of one);
  * ``min_relevant``  results that mention the symbol (whole word, case-sensitive) or at least half of the
                      query's key terms, in title or snippet;
  * ``min_fresh``     when ``freshness_hours`` is set: results whose publish time is KNOWN and inside the
                      window — an undated result is not fresh.

SUFFICIENT when every count meets its minimum. Pure: no network, no writes.
AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse

SCHEMA = "SearchQuality@v1"

#: Words that carry no subject: a query's key terms are what is left after these.
GENERIC = frozenset(
    "a an and or of for the to in on at by with from is are was be this that what which who how why when "
    "stock stocks share shares news latest today premarket catalyst catalysts price market markets company "
    "update updates report reports analysis analyst outlook 2025 2026 2027 site com www http https".split()
)
_REL = re.compile(r"(\d+)\s*(minute|min|hour|hr|day|week|month|year)s?\s+ago", re.I)
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%Y-%m-%d %H:%M:%S",
                 "%Y%m%dT%H%M%S", "%Y%m%dT%H%M")


def host(url: str) -> str:
    try:
        h = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    return h[4:] if h.startswith("www.") else h


def trusted(url: str, domains: Iterable[str]) -> bool:
    h = host(url)
    if not h:
        return False
    for d in domains:
        d = str(d).lower().strip()
        if d and (h == d or h.endswith("." + d)):
            return True
    return False


def key_terms(query: str, symbol: Optional[str] = None) -> list[str]:
    sym = str(symbol or "").lower()
    out = []
    for t in re.findall(r"[A-Za-z][A-Za-z0-9\-\.]{2,}", str(query or "")):
        tl = t.lower().strip(".-")
        if tl in GENERIC or tl == sym or tl.startswith("site:") or tl in out:
            continue
        out.append(tl)
    return out[:6]


def _text(r: Mapping[str, Any]) -> str:
    return " ".join(str(r.get(k) or "") for k in ("title", "description", "snippet", "content"))


def relevant(r: Mapping[str, Any], *, symbol: Optional[str], terms: list[str]) -> bool:
    """A row a symbol-keyed store already tagged with this symbol (``tagged_symbol``) is relevant by
    construction; otherwise the symbol or half the key terms must appear in title or snippet."""
    if symbol and str(r.get("tagged_symbol") or "").upper() == str(symbol).upper():
        return True
    text = _text(r)
    if symbol:
        if re.search(rf"(?<![A-Za-z0-9])\$?{re.escape(str(symbol).upper())}(?![A-Za-z0-9])", text):
            return True
    if not terms:
        return not symbol
    low = text.lower()
    hits = sum(1 for t in terms if t in low)
    return hits >= max(1, math.ceil(len(terms) / 2))


def published_at(r: Mapping[str, Any], now: datetime) -> Optional[datetime]:
    """Best-effort publish time from published_at / published / page_age / age; None when unknown."""
    for k in ("published_at", "published", "page_age", "publishedDate", "time_published", "age"):
        v = r.get(k)
        if not v:
            continue
        s = str(v).strip()
        m = _REL.search(s)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            mult = {"minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800,
                    "month": 2592000, "year": 31536000}[unit]
            return now - timedelta(seconds=n * mult)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def assess(results: list[Mapping[str, Any]], *, query: str, symbol: Optional[str], cfg: Mapping[str, Any],
           trusted_domains: Iterable[str], now: datetime) -> dict[str, Any]:
    """Counts against the class minimums, and whether the answer is SUFFICIENT."""
    domains = list(trusted_domains)
    terms = key_terms(query, symbol)
    rows = [r for r in results if isinstance(r, Mapping) and str(r.get("url") or "").startswith("http")]
    n_trusted = sum(1 for r in rows if trusted(str(r.get("url")), domains))
    n_relevant = sum(1 for r in rows if relevant(r, symbol=symbol, terms=terms))
    fresh_h = cfg.get("freshness_hours")
    n_fresh = None
    if fresh_h:
        window = timedelta(hours=float(fresh_h))
        n_fresh = 0
        for r in rows:
            ts = published_at(r, now)
            if ts is not None and -timedelta(hours=1) <= now - ts <= window:
                n_fresh += 1
    need = {k: int(cfg.get(k) or 0) for k in ("min_results", "min_trusted", "min_relevant", "min_fresh")}
    got = {"min_results": len(rows), "min_trusted": n_trusted, "min_relevant": n_relevant,
           "min_fresh": n_fresh if n_fresh is not None else need["min_fresh"]}
    missing = [k for k in need if got[k] < need[k]]
    return {"schema": SCHEMA, "sufficient": not missing, "missing": missing, "results": len(rows),
            "trusted": n_trusted, "relevant": n_relevant, "fresh": n_fresh, "key_terms": terms}


__all__ = ["SCHEMA", "assess", "trusted", "relevant", "published_at", "key_terms", "host"]
