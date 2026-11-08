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
_TICKER = re.compile(r"\$([A-Z]{1,5})\b|\(([A-Z]{1,5})\)")


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


def names_from_registry(doc: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """Company strings carried on the identity registry. An empty registry is an empty book."""
    out: dict[str, list[str]] = {}
    if not isinstance(doc, Mapping):
        return out
    explicit = doc.get("mention_names") if isinstance(doc.get("mention_names"), Mapping) else {}
    for symbol, values in explicit.items():
        seq = values if isinstance(values, (list, tuple)) else [values]
        cleaned = [str(value) for value in seq if str(value or "").strip()]
        if cleaned:
            out[str(symbol).upper()] = cleaned
    entities = doc.get("entities") if isinstance(doc.get("entities"), Mapping) else {}
    by_symbol = doc.get("by_symbol") if isinstance(doc.get("by_symbol"), Mapping) else {}
    for symbol, guid in by_symbol.items():
        entity = entities.get(guid) if isinstance(entities.get(guid), Mapping) else {}
        found: list[str] = []
        for key in ("company", "name", "legal_name"):
            if entity.get(key):
                found.append(str(entity[key]))
        for extra in entity.get("names") or []:
            if extra:
                found.append(str(extra))
        if not found:
            continue
        bucket = out.setdefault(str(symbol).upper(), [])
        for name in found:
            if name not in bucket:
                bucket.append(name)
    return out


def _ticker_symbol(match: re.Match[str]) -> str:
    return match.group(1) or match.group(2) or ""


def _ticker_near(text: str, symbol: str, official: str) -> bool:
    tokens = content_tokens(official)
    if len(tokens) < 2:
        return False
    phrase = re.compile(r"\b" + r"\W+".join(re.escape(tok) for tok in tokens) + r"\b", re.I)
    mark = re.compile(rf"\${symbol}\b|\({symbol}\)")
    for found in phrase.finditer(text or ""):
        window = (text or "")[max(0, found.start() - 80):found.end() + 80]
        if mark.search(window):
            return True
    return False


def agreement_ratio(phrase: str, symbol: str, names: Mapping[str, Iterable[str]]) -> float | None:
    """1.0 when the phrase's content tokens equal the registry name. Anything shorter is not a measure."""
    if not name_agrees(phrase, symbol, names):
        return None
    return 1.0


def _row(symbol: str, *, via: str, matched: str, role: str | None, confidence: float | None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "subject_guid": None,
        "issuer_guid": None,
        "identity_status": None,
        "matched_via": via,
        "matched_text": matched,
        "role": role,
        "role_source": "document_mention_matcher" if role else None,
        "role_confidence": confidence if role else None,
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
            if not _phrase_in(text or "", official) or not name_agrees(official, symbol, book):
                continue
            confidence = agreement_ratio(official, symbol, book)
            by_symbol.setdefault(symbol, _row(symbol, via="company_name", matched=official, role=None, confidence=confidence))
            break
    # A ticker counts only in uppercase and only beside that same registry name.
    for match in _TICKER.finditer(text or ""):
        symbol = _ticker_symbol(match)
        official = next((row["matched_text"] for row in [by_symbol.get(symbol)] if row), None)
        if symbol not in book or not official or not _ticker_near(text or "", symbol, official):
            continue
    found = list(by_symbol.values())
    own = (own_symbol or "").strip().upper()
    if own and found and all(row["symbol"] != own for row in found):
        return []
    if len(found) == 1 and (not own or found[0]["symbol"] == own):
        found[0]["role"] = "subject"
        found[0]["role_source"] = "document_mention_matcher"
        found[0]["role_confidence"] = agreement_ratio(found[0]["matched_text"], found[0]["symbol"], book)
    elif own and any(row["symbol"] == own for row in found):
        for row in found:
            row["role"] = "subject" if row["symbol"] == own else "mentioned"
            row["role_source"] = "document_mention_matcher"
            row["role_confidence"] = agreement_ratio(row["matched_text"], row["symbol"], book)
    return found
