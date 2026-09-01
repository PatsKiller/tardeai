"""Ticker validation for TICKER_CANDIDATE intake.

A discovered token only counts as a real ticker if it survives:
  1. shape check (1-10 chars, A-Z / digits / . / -),
  2. denylist of finance-vocabulary lookalikes (AI, CEO, GDP, ...),
  3. existence in symbol_profiles (upper(symbol)) in the live DB.

Verdicts:
  VALID            — in symbol_profiles, not denylist-shaped → tradeable-name confidence
  NEEDS_VALIDATION — ambiguous: IS in symbol_profiles but denylisted-shaped or 1-char
                     (e.g. "AI" is both the acronym and C3.ai) → operator/LLM must confirm
  INVALID          — bad shape, denylisted with no profile, or unknown symbol

Research-directive / topic-monitor slugs (D124_..., SU_INDUSTRY_..., K_...,
theme keys with underscores) are not securities. They must be refused before
identity resolution — an edge to a topic is worse than a missing edge.

DB reads go through db_adapter._execute (auto-commit per statement — no
transaction is ever held open across this module).
"""
from __future__ import annotations

from typing import Any
import re

VERDICT_VALID = "VALID"
VERDICT_INVALID = "INVALID"
VERDICT_NEEDS_VALIDATION = "NEEDS_VALIDATION"

# Finance-vocabulary tokens that constantly get extracted as "tickers".
# Benefit / prose acronyms (SSDI, IRMAA, NEED, FIND, TO, ASSET) are English —
# they are not securities and must never enter a symbol column via extraction.
# Do NOT put real listed tickers here just because the word is English: LIVE,
# GIFT, EW, ROC etc. are legitimate symbol_profiles rows.
DENYLIST = frozenset({
    "AI", "CEO", "USA", "GDP", "CPI", "ETF", "SEC", "IRA", "FDA", "EPS",
    "FCF", "R&D", "CFO", "IPO", "USD", "Q1", "Q2", "Q3", "Q4", "YOY",
    "SSDI", "IRMAA", "NEED", "FIND", "TO", "ASSET", "HEALTH",
    "BOND", "RATES", "CASH", "TAX", "NONE", "NULL", "TRUE", "FALSE",
})

_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# Topic-monitor / research-directive ids land in news_articles.symbol via
# topic_ingestion (symbol = topic_id). They are themes, not tickers.
# Underscore alone is structural (no listed ticker in symbol_profiles has one).
# Prefix patterns catch the same class without relying solely on "_".
# Never widen these to catch short real names — that is a deliberate register.
_RESEARCH_DIRECTIVE_PREFIX_RE = re.compile(
    r"^(?:"
    r"[DK]\d+_"                 # D124_EARNINGS_..., D23_DEFENSE_...
    r"|K_[A-Z0-9]"              # K_LEGAL_DOCUMENTS_...
    r"|SU_(?:INDUSTRY|SECTOR)_" # sector/industry theme keys
    r"|AI_[A-Z]"                # AI_DATACENTER_BUILDOUT (not the AI ticker)
    r")"
)

# Verb boundaries that end the company-name prefix of description_1s
# ("Alphabet Inc. offers various products..." → "Alphabet Inc.").
_NAME_BOUNDARY_RE = re.compile(
    r"\s+(?:offers|provides|operates|engages|develops|designs|manufactures|"
    r"produces|distributes|owns|invests|focuses|specializes|is|are|and its|"
    r"together with|seeks|tracks)\b", re.IGNORECASE)


def _result(valid: bool, verdict: str, reason: str, symbol: str,
            profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or {}
    return {
        "valid": valid,
        "verdict": verdict,
        "reason": reason,
        "symbol": symbol,
        "company_name": profile.get("company_name"),
        "exchange": profile.get("exchange"),          # not tracked in symbol_profiles yet
        "instrument_type": profile.get("instrument_type"),
        "sector": profile.get("sector"),
    }


def derive_company_name(description_1s: str | None) -> str | None:
    """Best-effort company name from the profile's first business-summary sentence."""
    text = (description_1s or "").strip()
    if not text:
        return None
    m = _NAME_BOUNDARY_RE.search(text)
    name = text[:m.start()] if m else text.split(",")[0]
    name = name.strip().rstrip(".,;:")
    # A name longer than ~8 words means the boundary heuristic missed — don't guess.
    if not name or len(name.split()) > 8:
        return None
    return name


def _lookup_profile(sym: str) -> dict[str, Any] | None:
    """Fetch the symbol_profiles row (or None). Never raises; None on DB-unavailable."""
    try:
        from db_adapter import _execute
        row = _execute(
            """SELECT upper(symbol) AS symbol, description_1s, sector, industry,
                      instrument_type, quote_type
               FROM symbol_profiles WHERE upper(symbol) = %s LIMIT 1""",
            (sym,), fetch="one")
    except Exception:
        return None
    if not row:
        return None
    return {
        "symbol": row.get("symbol"),
        "company_name": derive_company_name(row.get("description_1s")),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "instrument_type": row.get("instrument_type") or (
            (row.get("quote_type") or "").lower() or None),
        "exchange": None,  # symbol_profiles does not carry exchange yet
    }


def is_research_directive_slug(sym: str) -> bool:
    """True when `sym` is a topic/research-directive id, not a security ticker.

    topic_ingestion writes topic_id into news_articles.symbol. Those ids must
    never reach catalyst_events or identity resolution. Structural tests only —
    never widen this to catch short real names (that is a deliberate register).
    """
    symbol = (sym or "").strip().upper()
    if not symbol:
        return False
    if "_" in symbol:
        return True
    if _RESEARCH_DIRECTIVE_PREFIX_RE.match(symbol):
        return True
    return False


def validate_ticker(sym: str) -> dict[str, Any]:
    """Validate a candidate ticker symbol. Fail-closed: unknown/unverifiable → not valid."""
    symbol = (sym or "").strip().upper()
    if not symbol:
        return _result(False, VERDICT_INVALID, "empty symbol", symbol)
    if is_research_directive_slug(symbol):
        return _result(False, VERDICT_INVALID,
                       "research-directive / topic slug — not a security", symbol)
    if not _SHAPE_RE.match(symbol):
        return _result(False, VERDICT_INVALID, "not a plausible ticker shape", symbol)

    denylisted = symbol in DENYLIST
    ambiguous_shape = denylisted or len(symbol) == 1

    profile = _lookup_profile(symbol)

    if profile is None:
        if denylisted:
            return _result(False, VERDICT_INVALID,
                           "denylisted finance-vocabulary token", symbol)
        return _result(False, VERDICT_INVALID,
                       "not found in symbol_profiles (or DB unavailable)", symbol)

    if ambiguous_shape:
        # In profiles, but the token doubles as common finance vocabulary
        # (or is 1-char) — a human/LLM pass must confirm the company was meant.
        reason = ("in symbol_profiles but denylisted-shaped — ambiguous"
                  if denylisted else "in symbol_profiles but 1-char — ambiguous")
        return _result(False, VERDICT_NEEDS_VALIDATION, reason, symbol, profile)

    return _result(True, VERDICT_VALID, "matched symbol_profiles", symbol, profile)


def gate_catalyst_symbol(sym: str) -> tuple[bool, str]:
    """Fail-closed gate before news→catalyst ingestion / identity bind.

    Order is load-bearing:
      1. research-directive / topic slugs → refuse (never reach identity)
      2. known ticker universe (symbol_profiles) via validate_ticker
         — English words and benefit acronyms without a profile stay out
    Refusing an unrecognized symbol is correct: an edge to the wrong company
    is worse than a missing edge.
    """
    symbol = (sym or "").strip().upper()
    if not symbol:
        return False, "empty symbol"
    if is_research_directive_slug(symbol):
        return False, "research-directive / topic slug — not a security"
    result = validate_ticker(symbol)
    if result["verdict"] == VERDICT_VALID:
        return True, result["reason"]
    # NEEDS_VALIDATION (e.g. AI) — still a real profile row, but ambiguous.
    # Catalyst ingestion may carry it; identity bind still requires a registry
    # hit, so we do not mint. Accept for catalyst row creation only when the
    # profile exists — the ambiguity is about company-intent, not "is it junk".
    if result["verdict"] == VERDICT_NEEDS_VALIDATION and result.get("company_name"):
        return True, result["reason"]
    if result["verdict"] == VERDICT_NEEDS_VALIDATION:
        return True, result["reason"]
    return False, result["reason"]


def gate_watchlist_symbol(
    sym: str,
    *,
    portfolio_symbols: frozenset[str] | None = None,
) -> tuple[bool, str]:
    """Fail-closed gate before watchlist agent LLM jobs.

    Accept VALID symbol_profiles rows, or portfolio-held tickers that pass shape
    check (covers profile-sync lag). Rejects numeric garbage (e.g. 543354104).
    """
    symbol = (sym or "").strip().upper()
    if not symbol:
        return False, "empty symbol"
    if is_research_directive_slug(symbol):
        return False, "research-directive / topic slug — not a security"
    if not _SHAPE_RE.match(symbol):
        return False, "not a plausible ticker shape"
    if portfolio_symbols and symbol in portfolio_symbols:
        return True, "portfolio-held symbol"
    result = validate_ticker(symbol)
    if result["verdict"] == VERDICT_VALID:
        return True, result["reason"]
    return False, result["reason"]
