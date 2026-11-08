"""Document mention matcher. The desk tagger is not used and is not modified.

A company phrase binds only when its content tokens equal the registry name's
content tokens, and that name has at least two content tokens. A ticker binds
when it appears as $SYM or (SYM). One shared word is not a company.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

_LEGAL = frozenset({
    "inc", "incorporated", "corp", "corporation", "ltd", "llc", "lp", "co", "company", "plc", "the", "and",
})
_TOKEN = re.compile(r"[a-z0-9]+")
_TICKER = re.compile(r"(?:\$|\()\s*([A-Za-z]{1,5})\b\)?")


def content_tokens(name: str) -> list[str]:
    return [tok for tok in _TOKEN.findall(str(name or "").casefold()) if tok not in _LEGAL]


def _names_map(names: Mapping[str, Iterable[str]] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for symbol, values in (names or {}).items():
        sym = str(symbol or "").strip().upper()
        if not sym:
            continue
        out[sym] = [str(value) for value in values if str(value or "").strip()]
    return out


def name_agrees(phrase: str, symbol: str, names: Mapping[str, Iterable[str]]) -> bool:
    """True when the phrase is that symbol's full name, not a shorter or different one."""
    got = content_tokens(phrase)
    if len(got) < 2:
        return False
    for official in _names_map(names).get(symbol.upper(), []):
        if got == content_tokens(official):
            return True
    return False


def _phrase_in(text: str, official: str) -> bool:
    want = content_tokens(official)
    if len(want) < 2:
        return False
    hay = content_tokens(text)
    width = len(want)
    return any(hay[i:i + width] == want for i in range(len(hay) - width + 1))


def _tickers_in(text: str, symbols: set[str]) -> list[str]:
    found: list[str] = []
    for match in _TICKER.finditer(text or ""):
        sym = match.group(1).upper()
        if sym in symbols and sym not in found:
            found.append(sym)
    return found


def _row(symbol: str, *, via: str, matched: str, role: str | None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "subject_guid": None,
        "issuer_guid": None,
        "identity_status": None,
        "matched_via": via,
        "matched_text": matched,
        "role": role,
        "role_source": "document_mention_matcher" if role else None,
        "role_confidence": 1.0 if role else None,
    }


def match_mentions(
    text: str,
    *,
    names: Mapping[str, Iterable[str]] | None = None,
    own_symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Mentions whose name and symbol agree. Undecided rows keep role None and are not guessed."""
    book = _names_map(names)
    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol, official_names in book.items():
        for official in official_names:
            if not _phrase_in(text or "", official):
                continue
            if not name_agrees(official, symbol, book):
                continue
            by_symbol.setdefault(symbol, _row(symbol, via="company_name", matched=official, role=None))
    for symbol in _tickers_in(text or "", set(book)):
        by_symbol.setdefault(symbol, _row(symbol, via="ticker", matched=symbol, role=None))
    found = list(by_symbol.values())
    own = (own_symbol or "").strip().upper()
    if len(found) == 1:
        found[0]["role"] = "subject"
        found[0]["role_source"] = "document_mention_matcher"
        found[0]["role_confidence"] = 1.0
    elif own and any(row["symbol"] == own for row in found):
        for row in found:
            row["role"] = "subject" if row["symbol"] == own else "mentioned"
            row["role_source"] = "document_mention_matcher"
            row["role_confidence"] = 1.0
    return found
