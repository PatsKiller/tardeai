"""Read-only SEC EDGAR extension: submissions metadata + company facts (XBRL).

Official SEC source only (data.sec.gov). Reuses the canonical Trade AI
User-Agent and rate-limit conventions from scripts/sec_data_ingest.py. This
module NEVER writes to the production database; results are returned in memory.
A caller may inject a `fetcher` (url -> dict) for deterministic offline tests.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Callable, Optional

SEC_EDGAR = "https://data.sec.gov"
SEC_HEADERS = {
    "User-Agent": "TradeAI john@jwwhiting.com",
    "Accept": "application/json",
}
_RATE_SLEEP = 0.15  # SEC fair-access: ~6.7 req/s


def _default_fetcher(url: str, timeout: float = 15.0) -> dict:
    time.sleep(_RATE_SLEEP)
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class SecReadError(Exception):
    pass


def resolve_cik(symbol: str, fetcher: Optional[Callable[[str], dict]] = None) -> str:
    """Resolve a ticker to a 10-digit CIK via the official company_tickers.json.

    Falls back to the canonical sec_data_ingest resolver if the direct mapping
    lookup fails (both use the same official source).
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return ""
    fetcher = fetcher or _default_fetcher
    try:
        data = fetcher("https://www.sec.gov/files/company_tickers.json")
        for entry in (data or {}).values():
            if str(entry.get("ticker", "")).upper() == symbol:
                return str(entry["cik_str"]).zfill(10)
    except Exception:
        pass
    try:
        import sec_data_ingest as sdi  # canonical fallback

        return sdi._get_cik(symbol)
    except Exception:
        return ""


def get_submissions(cik: str, fetcher: Optional[Callable[[str], dict]] = None) -> dict:
    """Return the SEC submissions JSON for a CIK.

    Network/HTTP errors propagate (so callers can surface UNAVAILABLE rather
    than silently treating an outage as "no data"); a genuinely empty payload
    returns {}.
    """
    cik = _normalize_cik(cik)
    if not cik:
        return {}
    fetcher = fetcher or _default_fetcher
    return fetcher(f"{SEC_EDGAR}/submissions/CIK{cik}.json") or {}


def list_filings(
    cik: str,
    form: Optional[str] = None,
    limit: int = 10,
    fetcher: Optional[Callable[[str], dict]] = None,
) -> list[dict]:
    """Return normalized recent filings for a CIK (optionally filtered by form)."""
    sub = get_submissions(cik, fetcher=fetcher)
    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primary = recent.get("primaryDocument") or []
    items = recent.get("items") or []
    out: list[dict] = []
    form = (form or "").upper()
    for i, f in enumerate(forms):
        if form and str(f).upper() != form:
            continue
        acc = (accessions[i] if i < len(accessions) else "").replace("-", "")
        doc = primary[i] if i < len(primary) else ""
        out.append(
            {
                "form": f,
                "filing_date": dates[i] if i < len(dates) else "",
                "accession_number": accessions[i] if i < len(accessions) else "",
                "primary_document": doc,
                "items": items[i] if i < len(items) else "",
                "sec_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc}/{doc}"
                    if acc and doc
                    else ""
                ),
            }
        )
        if len(out) >= limit:
            break
    return out


def get_company_facts(
    cik: str, fetcher: Optional[Callable[[str], dict]] = None
) -> dict:
    """Return the company facts (XBRL) JSON for a CIK.

    Network/HTTP errors propagate; a genuinely empty payload returns {}.
    """
    cik = _normalize_cik(cik)
    if not cik:
        return {}
    fetcher = fetcher or _default_fetcher
    return fetcher(f"{SEC_EDGAR}/api/xbrl/companyfacts/CIK{cik}.json") or {}


def get_company_concept(
    cik: str,
    tag: str,
    fetcher: Optional[Callable[[str], dict]] = None,
) -> dict:
    """Return a single XBRL concept time series (us-gaap default).

    The `tag` is a taxonomy concept name (e.g. "AccountsPayableCurrent") and its
    exact casing is preserved — it is NOT lowercased.
    """
    cik = _normalize_cik(cik)
    if not cik:
        return {}
    tag = (tag or "").strip()
    fetcher = fetcher or _default_fetcher
    return fetcher(f"{SEC_EDGAR}/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json") or {}


def _normalize_cik(cik: str) -> str:
    if not cik:
        return ""
    cik = str(cik).strip()
    digits = "".join(ch for ch in cik if ch.isdigit())
    return digits.zfill(10) if digits else ""


def latest_values(facts: dict) -> dict:
    """Flatten companyfacts JSON into tag -> latest context dict.

    Preserves the full XBRL context (value, units, start, end, form, fp, fy,
    frame, filed) so downstream filing-diff can establish like-for-like period
    semantics. For a tag, the most recent row by (end, filed) is selected.
    """
    out: dict = {}
    units_by_tag = (facts or {}).get("facts", facts or {})
    # SEC API returns {"facts": {"us-gaap": {...}}} for companyfacts endpoint.
    if isinstance(units_by_tag, dict) and "us-gaap" in units_by_tag:
        units_by_tag = units_by_tag["us-gaap"]
    for tag, body in (units_by_tag or {}).items():
        if not isinstance(body, dict):
            continue
        units = body.get("units") or {}
        best = None
        for unit, rows in units.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or row.get("val") is None:
                    continue
                end = row.get("end") or ""
                filed = row.get("filed") or ""
                if best is None or (end, filed) > (best["end"], best.get("filed") or ""):
                    best = {
                        "value": row.get("val"),
                        "units": unit,
                        "start": row.get("start"),
                        "end": end,
                        "form": row.get("form"),
                        "fp": row.get("fp"),
                        "fy": row.get("fy"),
                        "frame": row.get("frame"),
                        "filed": filed,
                    }
        if best is not None:
            out[tag] = best
    return out
