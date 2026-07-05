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
DENYLIST = frozenset({
    "AI", "CEO", "USA", "GDP", "CPI", "ETF", "SEC", "IRA", "FDA", "EPS",
    "FCF", "R&D", "CFO", "IPO", "USD", "Q1", "Q2", "Q3", "Q4", "YOY",
})

_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

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


def validate_ticker(sym: str) -> dict[str, Any]:
    """Validate a candidate ticker symbol. Fail-closed: unknown/unverifiable → not valid."""
    symbol = (sym or "").strip().upper()
    if not symbol:
        return _result(False, VERDICT_INVALID, "empty symbol", symbol)
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
