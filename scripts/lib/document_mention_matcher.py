"""Document mention matcher. The desk tagger is not used and is not modified.

A company phrase binds only when its content tokens equal one official name
and that name has at least two content tokens. A one-token name ("Apple Inc."
is the word "apple") binds only with its own ticker right after it, as "(SYM)"
or "$SYM" within a short window. The word alone is not proof of the issuer.

A ticker never binds alone, in any form. "$SYM", "(SYM)" and bare abbreviations
such as "(ARR)", "(ETH)" or "(DRAM)" are only ever read next to the company name
of that same symbol, and the name row does the binding.

The identity registry has no company names. The book is the Schwab instrument
description (the store company_name_index reads) plus symbol_profiles phrases
for symbols that description does not already name.

When the document is filed under a symbol the text does not name, no rows are
returned: one hit on another company is not proof of the subject.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

#: The decision authority this module writes. `document_mentions.role_source` is constrained by
#: sql/document_mentions.sql to ('deterministic','model','operator'); a rule that reads the text and
#: compares content tokens is deterministic, and 'document_mention_matcher' -- the value this module
#: wrote until LQ-20261107-1266 -- is not in that set, so every insert raised CheckViolation and the
#: lane wrote nothing. The matcher's identity is not a decision authority: it is recorded per run in
#: the lane receipt ("matcher": "rebuild") and per row by matched_via/matched_text.
#: tests/test_document_mention_matcher_role_source_lq1266_20261108.py parses the allowed set out of
#: the DDL and fails if this value -- or any other the code can emit -- is not a member.
ROLE_SOURCE = "deterministic"

_LEGAL = frozenset({
    "inc", "incorporated", "corp", "corporation", "ltd", "llc", "lp", "co", "company", "plc", "the", "and",
})
_TOKEN = re.compile(r"[a-z0-9]+")
_ASCII_WORD = re.compile(r"[0-9A-Za-z]+")
_ANCHOR_WINDOW = 40


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


def _anchored(text: str, official: str, symbol: str) -> bool:
    """A one-token name binds only with its own ticker right after it: "(SYM)" or "$SYM", case-exact."""
    want = content_tokens(official)
    if len(want) != 1 or not symbol:
        return False
    ticker = re.compile(r"\(\s*\$?%s\s*\)|\$%s(?![0-9A-Za-z])" % (re.escape(symbol), re.escape(symbol)))
    for match in _ASCII_WORD.finditer(text or ""):
        word = match.group().casefold()
        if word != want[0] or word in _LEGAL:
            continue
        if ticker.search(text[match.end():match.end() + _ANCHOR_WINDOW]):
            return True
    return False


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


def _company_phrase():
    """The phrase cutter already loaded in this process, else scripts.lib.

    document_mentions still imports lib.company_name_index when the legacy
    extractor runs. That file is claimed, so this module does not import it a
    second time under the other name.
    """
    import sys

    for key in ("scripts.lib.company_name_index", "lib.company_name_index"):
        mod = sys.modules.get(key)
        if mod is not None and hasattr(mod, "company_phrase"):
            return mod.company_phrase
    from scripts.lib.company_name_index import company_phrase

    return company_phrase


def _add_phrase(book: dict[str, list[str]], symbol: str, phrase: str | None) -> None:
    if not symbol or not phrase:
        return
    bucket = book.setdefault(symbol, [])
    if phrase not in bucket:
        bucket.append(phrase)


def names_from_profile_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Issuer phrases from symbol_profiles.description_1s. Same cut as company_phrase."""
    phrase_of = _company_phrase()
    out: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        _add_phrase(out, symbol, phrase_of(row.get("description_1s") or row.get("description")))
    return out


def names_from_instrument_records(records: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """Issuer phrases from Schwab instrument evidence. description is the issuer name."""
    phrase_of = _company_phrase()
    out: dict[str, list[str]] = {}
    if not isinstance(records, Mapping):
        return out
    for symbol, rec in records.items():
        if not isinstance(rec, Mapping):
            continue
        sym = str(symbol or "").strip().upper()
        _add_phrase(out, sym, phrase_of(rec.get("description") or rec.get("company")))
    return out


def mention_names(instruments: Mapping[str, Any] | None, profile_rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Instrument descriptions first. Profile phrases fill symbols the instrument book missed."""
    book = names_from_instrument_records(instruments)
    for symbol, phrases in names_from_profile_rows(profile_rows).items():
        for phrase in phrases:
            _add_phrase(book, symbol, phrase)
    return book


def _row(symbol: str, *, via: str, matched: str, role: str | None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "subject_guid": None,
        "issuer_guid": None,
        "identity_status": None,
        "matched_via": via,
        "matched_text": matched,
        "role": role,
        "role_source": ROLE_SOURCE if role else None,
        # The DDL's contract (LQ-20261107-1275): role_confidence is NULL when deterministic. The
        # matcher's agreement is exact token equality, never a probability -- it either holds or the
        # row is not emitted -- so a number here would be a confidence that measures nothing.
        "role_confidence": None,
    }


def match_mentions(
    text: str,
    *,
    names: Mapping[str, Iterable[str]] | None = None,
    own_symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Mentions whose name and symbol agree. Undecided rows keep role None and are not guessed."""
    book = _names_map(names)
    body = text or ""
    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol, official_names in book.items():
        for official in official_names:
            if len(content_tokens(official)) >= 2:
                binds = _phrase_in(body, official) and name_agrees(official, symbol, book)
            else:
                # A one-token name binds only with its own ticker: the ticker is the agreement here.
                binds = _anchored(body, official, symbol)
            if not binds:
                continue
            by_symbol.setdefault(symbol, _row(symbol, via="company_name", matched=official, role=None))
            break
    found = list(by_symbol.values())
    own = (own_symbol or "").strip().upper()
    if not found:
        return found
    if own and not any(row["symbol"] == own for row in found):
        # Filed under a symbol the text does not name: no rows, never the lone hit as subject.
        return []
    if len(found) == 1:
        found[0]["role"] = "subject"
        found[0]["role_source"] = ROLE_SOURCE
    elif own:
        for row in found:
            row["role"] = "subject" if row["symbol"] == own else "mentioned"
            row["role_source"] = ROLE_SOURCE
    return found
