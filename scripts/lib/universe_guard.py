#!/usr/bin/env python3
"""Engine Room v1 (WS-3): universe guard applied AT GENERATION, not just at lint.

Content generators (topic synthesizer, auto-research) call check_prose() on the prose
they are about to persist. Every ticker-ish token and corporate-name mention is resolved
against the known reference (symbol_profiles ∪ watchlist ∪ holdings). The result is
stored in evidence_json["universe_guard"], so:
  - the QA lint can tell "real peer outside our universe" from "fabricated entity"
  - unknown entities are DISCLOSED in the brief instead of silently shipped
Deterministic, zero LLM. Never blocks a write — it annotates and demotes.
"""
from __future__ import annotations

import re
from typing import Iterable

# Same detectors as research_intelligence_qa_lint (kept in sync deliberately —
# generator and lint must agree on what counts as an entity mention)
TICKERISH_RE = re.compile(r"\b[A-Z]{2,5}\b")
CORP_NAME_RE = re.compile(
    r"\b((?:[A-Z][a-z]{2,}\s+){1,4}(?:Inc|Corp|Corporation|Ltd|Group|Holdings|"
    r"Medical|Pharma|Bio|Biotech|Health|Technologies|Industries|Farm|Labs|"
    r"Therapeutics|Sciences)\b(?:\s*&\s*[A-Z][a-z]+)*)")

CAPS_ALLOW = {
    "RSI", "ATR", "SMA", "EMA", "ETF", "ETFS", "IRA", "ROTH", "MAGI", "IRMAA",
    "SSDI", "SGA", "RMD", "MAPT", "CEF", "CEFS", "NAV", "USA", "US", "NYSE",
    "SEC", "FED", "FRED", "CMS", "SSA", "IRS", "GDP", "CPI", "PCE", "AI",
    "LLM", "API", "CEO", "CFO", "IPO", "YTD", "LT", "ST", "OK", "PE", "EPS",
    "REIT", "REITS", "VIX", "SPY", "QQQ", "OCO", "GTC", "RTH", "DCA", "MAX",
    "HIGH", "LOW", "NEAR", "STOP", "GO", "WAIT", "NOGO", "TIER", "THE", "AND",
    "FOR", "NOT", "NEW", "ALL", "ONE", "TWO", "BUY", "SELL", "HOLD", "TRIM",
    "TIPS", "BDC", "BDCS", "JEPI", "SCHD", "FAQ", "NASDAQ", "AMEX", "OTC",
}

_REF_CACHE: dict = {"symbols": None, "names": None}


def known_reference(db_query) -> tuple[set[str], str]:
    """(known symbols, lowercase company-name blob) from tables we actually track.
    Cached per process — reference tables move on cron cadence."""
    if _REF_CACHE["symbols"] is not None:
        return _REF_CACHE["symbols"], _REF_CACHE["names"]
    syms: set[str] = set()
    names: list[str] = []
    try:
        rows = db_query("""SELECT upper(symbol) AS s, coalesce(description_1s,'') AS n
                           FROM symbol_profiles""") or []
        for r in rows:
            if r.get("s"):
                syms.add(r["s"])
            if r.get("n"):
                names.append(str(r["n"]))
    except Exception:
        pass
    try:
        rows = db_query("SELECT DISTINCT upper(symbol) AS s FROM watchlist_items WHERE symbol IS NOT NULL") or []
        syms |= {r["s"] for r in rows if r.get("s")}
    except Exception:
        pass
    _REF_CACHE["symbols"] = syms
    _REF_CACHE["names"] = " ".join(names).lower()
    return syms, _REF_CACHE["names"]


def check_prose(prose: str, *, known_symbols: set[str], known_names_blob: str = "",
                own_entities: Iterable[str] = ()) -> dict:
    """Resolve entity mentions in prose. Returns a dict for evidence_json["universe_guard"]:
    {checked: N, known: [...], unknown_tickers: [...], unknown_names: [...]}"""
    own = {str(e).upper() for e in own_entities if e}
    own_blob = " ".join(str(e) for e in own_entities if e).lower()
    known, unknown_t, unknown_n = [], [], []
    seen = set()
    for tok in TICKERISH_RE.findall(prose or ""):
        if tok in seen or tok in CAPS_ALLOW:
            continue
        seen.add(tok)
        if tok in known_symbols or tok in own:
            known.append(tok)
        else:
            unknown_t.append(tok)
    for m in CORP_NAME_RE.finditer(prose or ""):
        name = (m.group(1) or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        if key in known_names_blob or key in own_blob:
            known.append(name)
        else:
            unknown_n.append(name)
    return {"checked": len(seen), "known": known[:20],
            "unknown_tickers": unknown_t[:10], "unknown_names": unknown_n[:10]}


def disclosure_line(guard: dict) -> str | None:
    """One-line disclosure to append to a brief when it names untracked entities."""
    un = (guard.get("unknown_tickers") or []) + (guard.get("unknown_names") or [])
    if not un:
        return None
    return ("Entities named outside the tracked universe: "
            + ", ".join(un[:6]) + " — verify identity before acting.")
