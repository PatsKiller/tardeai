"""One exact-symbol matcher for every lane that finds tickers in text (RE-6, LQ-20261107-191).

WHY
---
The 11-07 audit found five lanes each deciding "is this ticker in this text" their own way, and each way wrong:

    aegis-transcript-discovery      ILIKE '%DRS%'  -> matched "cdrs" and "BDRs"
    material-change-detector         news tagged T counted TELUS (TSX:T), T-Mobile, Tesla
    hermes-watchlist-scorer          scored OVER, WITH, PICKS as tickers
    hermes-momentum-catalyst-scalp   attached pages that never named the company
    identity sweep                   stamped VIG "unresolvable" when it was never in the registry

This module answers two separate questions and nothing else:

1. ``mention(text, symbol)`` — does THIS text name THIS security? Whole word, case-sensitive, ``$`` allowed;
   not inside ``T-Mobile``/``S&P``/``BRK.BX``; not after a foreign exchange prefix (``TSX:T``); and a ticker
   that is also an English word or a single letter (``A``, ``T``, ``ON``) counts only as a cashtag or with the
   company's name, as does any ticker in an all-caps headline.
2. ``registry_status(symbol)`` / ``partition(symbols)`` — is it a security at all? The identity registry
   answers, by entity status and not by membership: OVER is a minted UNRESOLVED entity, so it is
   ``registry_unresolved`` and dropped unless the lane's own instrument store vouches for it. The reasons are the ones LQ-188 put
   on ``cio_subject_guid.lookup_subject`` so a lane and the identity sweep report the same thing.

An unreadable or empty registry RAISES ``RegistryUnavailable``: rejecting every symbol because the file was
missing would look exactly like a quiet day.

``pg_word_regex(symbol)`` gives the SQL prefilter that replaces ``ILIKE '%sym%'`` (pass it as a parameter to
``col ~ %s``); the rows it returns still go through ``mention()``, which holds the rules SQL cannot.

Pure apart from the default registry read. No network, no DB, no writes. READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from lib import identity_registry
from lib.hermes_scalp_catalyst_record import name_phrases

AUTHORITY = "READ_ONLY_ADVISORY"

# Registry answers. The two "not found" reasons are LQ-188's lookup_subject reason strings, verbatim.
IN_REGISTRY = "in_registry"
#: by_symbol has it, but the entity is UNRESOLVED_WITH_REASON: 340 of 5,792 on 11-07, real tickers (ABB, ACLX)
#: and words the watchlist feed minted on 08-27 (OVER, WITH, PICKS, SEES, WAGMI, ABOVE) alike.
REGISTRY_UNRESOLVED = "registry_unresolved"
#: Entity statuses that identify a security (identity_registry: CONFIRMED > CANDIDATE > UNRESOLVED).
RESOLVED_STATUSES = frozenset({"CONFIRMED", "CANDIDATE"})
REGISTRY_NO_ENTITY = "registry_answered_no_entity"
NOT_IN_REGISTRY = "symbol_not_in_registry"
NOT_A_SYMBOL = "not_a_symbol"

# Why a text does not count as a mention.
NO_MENTION = "no_mention"
AMBIGUOUS = "ambiguous_ticker_needs_cashtag_or_name"
FOREIGN_LISTING = "foreign_exchange_prefix"

#: A US ticker: 1-6 letters/digits starting with a letter, optional one class suffix (BRK.B, BF-B).
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z0-9]{1,2})?")
#: Unicode-aware boundaries, as in hermes_scalp_catalyst_record: "BETR" is not a word inside "Betrüger".
_NB, _NA = r"(?<![^\W_])", r"(?![^\W_])"
_CANDIDATE = re.compile(_NB + r"\$?(" + _SYMBOL.pattern + r")" + _NA)

#: Exchange prefixes that name the US listing. Any other prefix (TSX, ASX, LSE, B3, ...) is another security.
#: Press releases spell the venue long ("NasdaqGS:", "NYSE American:", "NYSEAM:"), so a prefix is compared
#: upper-cased with its spaces removed, and also by its last word.
US_EXCHANGES = frozenset({"NYSE", "NASDAQ", "NASDAQGS", "NASDAQGM", "NASDAQCM", "NYSEARCA", "NYSEAMERICAN",
                          "NYSEAM", "NYSEMKT", "AMEX", "ARCA", "BATS", "CBOE", "OTC", "OTCMKTS", "OTCQX", "OTCQB",
                          "OTCPK", "PINK", "US"})
_PREFIX = re.compile(r"([A-Za-z]{2,12})(?:\s+([A-Za-z]{2,12}))?\s*:\s*$")

#: Tickers that are also everyday words in headlines. A bare upper-case hit is not trusted for these.
COMMON_WORD_TICKERS = frozenset("""
A I AN AM AS AT BE BY DO GO HE IF IN IS IT ME MY NO OF ON OR SO TO UP US WE
ALL AND ANY ARE BIG BUT CAN CAR CEO DAY EAT FOR FUN GET HAS HOW KEY LOW MAN NEW NOW OLD ONE OUT
OWN RUN SEE SHE SUN THE TOO TWO USA WAY WHO WHY YOU
BEST BODY CASH CODE EVER FAST FIVE FREE GOOD HOME HOPE JUST LIFE LOVE MAIN MOST NEXT NICE OPEN OVER PEAK
PLAY REAL SAFE SEES TRUE WELL WITH WORK PICKS WAGMI
""".split())

_CURLY = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


class RegistryUnavailable(RuntimeError):
    """The identity registry could not answer (missing, unreadable or empty). Never read as "no symbols"."""


def normalize(symbol: Any) -> str:
    return str(symbol or "").strip().upper().lstrip("$")


def is_symbol_shape(symbol: Any) -> bool:
    return bool(_SYMBOL.fullmatch(normalize(symbol)))


def _shouting(text: str) -> bool:
    """An all-caps headline: every word looks like a ticker, so only cashtags and names are trusted."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) >= 0.7


def _ambiguous(sym: str) -> bool:
    core = re.split(r"[.\-]", sym)[0]
    return len(core) == 1 or sym in COMMON_WORD_TICKERS


def _occurrence_problem(text: str, start: int, end: int) -> Optional[str]:
    """Why the occurrence text[start:end] (ticker without ``$``) is not this security, or None."""
    before, after = text[:start], text[end:]
    if re.match(r"[.\-][A-Za-z0-9]", after) or re.search(r"[A-Za-z0-9][.\-]$", before):
        return NO_MENTION  # T-Mobile, Sell-T, BRK.B when asked for BRK
    if re.match(r"&[A-Za-z]", after) or re.search(r"[A-Za-z]&$", before):
        return NO_MENTION  # S&P, AT&T when asked for AT or P
    m = _PREFIX.search(before.rstrip("(").rstrip())
    if m:
        last = m.group(2) or m.group(1)
        if (m.group(1) + (m.group(2) or "")).upper() in US_EXCHANGES or last.upper() in US_EXCHANGES:
            return None
        if last.isupper():
            return FOREIGN_LISTING  # an exchange CODE (TSX, KLSE, ENXTPA); "Today:" in prose is not one
    return None


def mention(text: Any, symbol: Any, *, company_names: Iterable[str] = ()) -> dict[str, Any]:
    """Does ``text`` name ``symbol``? -> {"matched", "how": cashtag|ticker|company|None, "reason"}."""
    sym = normalize(symbol)
    body = str(text or "").translate(_CURLY)
    if not body or not _SYMBOL.fullmatch(sym):
        return {"matched": False, "how": None, "reason": NO_MENTION if sym else NOT_A_SYMBOL}
    ambiguous = _ambiguous(sym) or _shouting(body)
    blocked: Optional[str] = None
    bare_ok = False
    for m in re.finditer(_NB + r"(\$?)" + re.escape(sym) + _NA, body):
        start = m.start() + len(m.group(1))
        problem = _occurrence_problem(body, start, m.end())
        if problem:
            blocked = blocked or problem
            continue
        if m.group(1):
            return {"matched": True, "how": "cashtag", "reason": None}
        if ambiguous:
            blocked = blocked or AMBIGUOUS
        else:
            bare_ok = True
    if bare_ok:
        return {"matched": True, "how": "ticker", "reason": None}
    for phrase in name_phrases(company_names):
        words = [re.escape(w) for w in phrase.split()]
        if re.search(_NB + r"[\s\-_]+".join(words) + _NA, body, re.I):
            return {"matched": True, "how": "company", "reason": None}
    return {"matched": False, "how": None, "reason": blocked or NO_MENTION}


def mentions(text: Any, symbol: Any, *, company_names: Iterable[str] = ()) -> bool:
    return mention(text, symbol, company_names=company_names)["matched"]


def find_symbols(text: Any, universe: Iterable[str], *,
                 names_by_symbol: Optional[Mapping[str, Iterable[str]]] = None) -> list[str]:
    """Universe symbols ``text`` names, in order of first appearance. ``universe`` is the validated set
    (``partition`` output), so a word that is not a security can never come back."""
    body = str(text or "").translate(_CURLY)
    allowed = {normalize(s) for s in universe or ()}
    names = names_by_symbol or {}
    out: list[str] = []
    for m in _CANDIDATE.finditer(body):
        sym = m.group(1)
        if sym in allowed and sym not in out and mentions(body, sym, company_names=names.get(sym, ())):
            out.append(sym)
    return out


def _by_symbol(registry: Optional[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    doc = identity_registry.load_cached() if registry is None else registry
    by = doc.get("by_symbol") if isinstance(doc, Mapping) else None
    if not isinstance(by, Mapping) or not by:
        raise RegistryUnavailable("identity registry has no by_symbol index (missing, unreadable or empty)")
    return doc, by


def _status(doc: Mapping[str, Any], by: Mapping[str, Any], sym: str) -> str:
    if not _SYMBOL.fullmatch(sym):
        return NOT_A_SYMBOL
    if not by.get(sym):
        return NOT_IN_REGISTRY
    entity = identity_registry.lookup_symbol(doc, sym)
    if not entity:
        return REGISTRY_NO_ENTITY
    return IN_REGISTRY if entity.get("identity_status") in RESOLVED_STATUSES else REGISTRY_UNRESOLVED


def registry_status(symbol: Any, registry: Optional[Mapping[str, Any]] = None) -> str:
    """in_registry | registry_unresolved | registry_answered_no_entity | symbol_not_in_registry | not_a_symbol. Raises
    RegistryUnavailable when the registry cannot answer. ``registry`` defaults to the cached live file."""
    doc, by = _by_symbol(registry)
    return _status(doc, by, normalize(symbol))


def partition(symbols: Iterable[Any], registry: Optional[Mapping[str, Any]] = None, *,
              known_instruments: Iterable[str] = ()) -> tuple[list[str], list[dict[str, str]]]:
    """Split ``symbols`` into (securities to keep, [{symbol, status}] rejected), order kept, duplicates dropped.

    Kept: CONFIRMED/CANDIDATE registry entities, plus ``known_instruments`` (symbols the caller read from its own
    instrument or price store: instrument_facts, ticker_prices) that the registry has not minted or not resolved.
    Both halves are needed: LQ-188 found 939 of 940 unresolved news symbols were never minted (membership alone
    drops real ETFs), and the registry holds OVER/WITH as UNRESOLVED entities (membership alone keeps words)."""
    doc, by = _by_symbol(registry)
    known = {normalize(s) for s in known_instruments or ()}
    keep: list[str] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in symbols or ():
        sym = normalize(raw)
        if sym in seen:
            continue
        seen.add(sym)
        status = _status(doc, by, sym)
        if status == IN_REGISTRY or (status != NOT_A_SYMBOL and sym in known):
            keep.append(sym)
        else:
            rejected.append({"symbol": sym or str(raw), "status": status})
    return keep, rejected


def pg_word_regex(symbol: Any) -> str:
    """Postgres ARE for ``col ~ %s``: the ticker as a case-sensitive whole word, ``$`` allowed. A prefilter
    only; pass the rows through ``mention()``. Raises ValueError for anything that is not a ticker shape."""
    sym = normalize(symbol)
    if not _SYMBOL.fullmatch(sym):
        raise ValueError(f"not a ticker: {symbol!r}")
    escaped = re.sub(r"([.\-])", r"\\\1", sym)
    return r"(^|[^[:alnum:]_])\$?" + escaped + r"([^[:alnum:]_]|$)"
