"""Company name -> symbol, sourced from the broker instrument feed.

NOTHING HERE IS INVENTED
------------------------
The operator's constraint, and it is the right one: do not hand-roll a
ticker-to-name map. The name comes from the SAME authoritative record as the
CUSIP — Schwab `/marketdata/v1/instruments`, already swept and stored:

    "V":   {"description": "VISA INC A",           "identifiers": {"cusip": "92826C839"}}
    "NOC": {"description": "NORTHROP GRUMMAN COR", "identifiers": {"cusip": "666807102"}}
    "JPM": {"description": "JPMORGAN CHASE & CO",  "identifiers": {"cusip": "46625H100"}}

4,997 instruments, 4,997 with a description. The data was already on disk and had
simply never been indexed for lookup, so "Visa" was unresolvable while "V" was.
This builds an index over it. If the broker does not know a name, neither do we —
that is the correct answer, not a reason to guess.

WHY NORMALISATION IS NEEDED AND WHERE IT STOPS
----------------------------------------------
Broker descriptions are UPPERCASE, abbreviated and TRUNCATED — "NORTHROP GRUMMAN
COR" is not a typo, it is a fixed-width field. So a raw string compare fails on
exactly the names an operator types. Normalisation strips punctuation and legal
suffixes (INC, CORP/COR, CO, LTD, PLC, CLASS A) and nothing else.

**Ambiguity is never resolved by guessing.** If a normalised name or prefix maps
to more than one symbol, this returns None and the caller records an unresolved
mention. A wrong symbol on a financial question is worse than no symbol: it
attaches an operator's intent to the wrong issuer, and every join downstream
inherits the error.

NO MODEL RUNS HERE
------------------
String normalisation and dictionary lookup. Genuine ambiguity — a name the feed
does not carry at all — is `identity_resolution_advisor`'s job, and it writes
CANDIDATE only.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Optional

SCHEMA = "CompanyNameIndex@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Legal-form suffixes carried by the feed and never spoken by an operator.
#: "COR" is Schwab's truncation of CORPORATION, not a distinct form.
_SUFFIXES = (
    "INCORPORATED", "CORPORATION", "COMPANY", "HOLDINGS", "HOLDING",
    "INC", "CORP", "COR", "CO", "LTD", "LLC", "LP", "PLC", "NV", "SA", "AG",
    "TRUST", "GROUP", "CL A", "CL B", "CLASS A", "CLASS B",
)
_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(name: Any) -> str:
    """Uppercase, depunctuate, drop trailing legal forms and class markers.

    Trailing-only: "CO" inside "COCA COLA" must survive, so suffixes are stripped
    from the end and never from the middle.
    """
    s = _PUNCT.sub(" ", str(name or "").upper())
    s = _WS.sub(" ", s).strip()
    changed = True
    while changed and s:
        changed = False
        for suf in _SUFFIXES:
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
        # A dangling single letter is a share class ("VISA INC A" -> "VISA A").
        if len(s) > 2 and s[-2] == " " and s[-1].isalpha():
            s = s[:-2].strip()
            changed = True
    return s


def _instruments() -> dict[str, Any]:
    try:
        from lib.schwab_instrument_evidence import load  # noqa: PLC0415
    except Exception:
        from scripts.lib.schwab_instrument_evidence import load  # type: ignore  # noqa: PLC0415
    return (load() or {}).get("instruments") or {}


@lru_cache(maxsize=1)
def _build() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(exact normalised name -> symbols, first-token -> symbols).

    Both map to LISTS. Collapsing to a single symbol would silently pick a winner,
    and picking a winner is the failure this module exists to avoid.
    """
    exact: dict[str, list[str]] = {}
    first: dict[str, list[str]] = {}
    for sym, rec in _instruments().items():
        norm = normalize_name((rec or {}).get("description"))
        if not norm:
            continue
        exact.setdefault(norm, []).append(sym)
        head = norm.split(" ", 1)[0]
        if len(head) >= 3:
            first.setdefault(head, []).append(sym)
    return exact, first


def refresh() -> None:
    """Drop the cache after a new sweep."""
    _build.cache_clear()


def resolve_name(name: Any) -> Optional[dict[str, Any]]:
    """Company name -> {symbol, description, cusip}, or None.

    None covers three cases and deliberately does not distinguish them to the
    caller: unknown to the feed, ambiguous, or too short to be meaningful. All
    three mean "do not attach this question to an issuer".
    """
    norm = normalize_name(name)
    if len(norm) < 3:
        return None
    exact, first = _build()

    hits = exact.get(norm)
    if not hits:
        head = norm.split(" ", 1)[0]
        # Only fall back to a single-word head when the query IS that one word;
        # "NORTHROP" -> NOC is wanted, but "APPLE HOSPITALITY" must not collapse
        # to APPLE.
        if norm == head:
            hits = first.get(head)
    if not hits or len(set(hits)) != 1:
        return None                      # unknown, or ambiguous — never guess

    sym = hits[0]
    rec = _instruments().get(sym) or {}
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "symbol": sym,
        "description": rec.get("description"),
        "cusip": (rec.get("identifiers") or {}).get("cusip"),
        "matched_on": "exact" if exact.get(norm) else "first_token",
        "source": "schwab_instruments",
        "financial_action": False,
    }
