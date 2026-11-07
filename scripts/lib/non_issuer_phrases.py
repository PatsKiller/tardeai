"""Exchanges, wires and places — phrases that name a market or a location, never an issuer.

LQ-20261107-122 put this vocabulary in `inbound_identity_tagger` and checked it at the
three doors a company name can enter (bare ticker, company name, any-case window).
LQ-20261107-411 found the door it could not see. `company_name_index.resolve_name`
does not only look a name up, it NARROWS: it drops trailing tokens until the leading
words identify exactly one instrument ("NORFOLK SOUTHERN CORP" -> "NORFOLK" -> NSC).
The stoplist was checked against the words the TEXT contained, so

    "Las Vegas Review-Journal"  -> narrowed to "LAS VEGAS" -> LVS (Las Vegas Sands)
    "york university ..."       -> narrowed to "YORK"      -> YSS (York Space Systems)

bound a real issuer's symbol to a place. Both rows reached due-diligence questions.

The rule this module exists for: judge the words that were ACTUALLY MATCHED, not the
words that surrounded them. A real issuer whose name merely begins with a place
("Las Vegas Sands", "York Space Systems") survives, because the matcher accepts it at
the width where those extra words are present and this check passes at that width.

`inbound_identity_tagger.NON_ISSUER_PHRASES` is still its own copy (that file is under
another session's claim); it is a strict subset of this set and
`tests/test_place_name_match_lq411_20261107.py` fails if the two ever diverge. The
follow-up is for the tagger to import this module and delete its copy.
"""

from __future__ import annotations

from typing import Any

#: Exact, case-insensitive, whole phrase only. "Nasdaq Inc" and "New York Life" are
#: not in this list and still resolve normally. Deliberately NOT here: a single city
#: that is also an issuer's ordinary name (Atlanta Braves, Boston Scientific, Seattle
#: Genetics, Houston American), nor "United" or "Washington". "CBOE" is a real
#: issuer's ticker (Cboe Global Markets), so it is not stoplisted.
NON_ISSUER_PHRASES: frozenset[str] = frozenset({
    # exchanges
    "nasdaq", "nasdaq stock market", "nasdaq gs", "nasdaq global select",
    "nasdaq global market", "nasdaq capital market", "nyse", "nyse american",
    "nyse arca", "new york stock exchange", "amex", "otc", "otcqb",
    "otcqx", "otc markets",
    # wire services and news aggregators
    "globe newswire", "globenewswire", "business wire", "businesswire",
    "pr newswire", "prnewswire", "accesswire", "reuters", "associated press",
    "benzinga", "marketwatch", "seeking alpha", "tipranks", "investing.com",
    # places (the city or country, alone)
    "new york", "new york city", "new jersey", "los angeles", "san francisco",
    "san diego", "san jose", "silicon valley", "wall street", "hong kong",
    "london", "chicago", "toronto", "united states", "china", "europe", "asia",
    "japan",
    # LQ-20261107-411: the two the narrowing window reached. "New York" was already
    # here; "York" alone was not, so "York University", "York City" and a bare
    # "york" in prose narrowed onto York Space Systems (YSS).
    "york", "las vegas",
})

_TRAILING_JUNK = " .,;:!?\"'()"


def normalize_phrase(text: Any) -> str:
    """Whitespace-collapsed, casefolded phrase with trailing punctuation removed."""
    return " ".join(str(text or "").split()).casefold().rstrip(_TRAILING_JUNK)


def is_non_issuer_phrase(text: Any) -> bool:
    """True when `text` is an exchange, wire or place name and never an issuer."""
    return normalize_phrase(text) in NON_ISSUER_PHRASES
