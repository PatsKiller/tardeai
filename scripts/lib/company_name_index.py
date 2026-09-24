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

import json
import os
import re
from functools import lru_cache
from pathlib import Path
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
    # scripts.lib FIRST (scripts/lib/__init__.py: "prefer scripts.lib.X"). Bare
    # `lib.` first loaded a second copy of schwab_instrument_evidence beside the
    # scripts.lib one as soon as the desk intent analyzer began resolving company
    # names, and assert_single_import_identity() then raised in the same process.
    try:
        from scripts.lib.schwab_instrument_evidence import load  # noqa: PLC0415
    except Exception:
        from lib.schwab_instrument_evidence import load  # type: ignore  # noqa: PLC0415
    return (load() or {}).get("instruments") or {}



# ── names the house already holds ────────────────────────────────────────────
# 2026-09-13 litmus test: "what's the outlook for SpaceX" resolved no symbol and
# was treated as unanswerable, while the book holds 400 SPCX, the identity
# registry has SPCX CONFIRMED (CUSIP 84615Q103), config/ipo_lockups.json records
# "SpaceX (Space Exploration Technologies Corp)" and symbol_profiles describes it
# as "Space Exploration Technologies Corp. provides ...". The index knew only the
# Schwab instrument sweep, which had not swept SPCX. House-held names are merged
# in: the same exact/prefix maps, lists never collapsed, ambiguity still refuses.
_REPO = Path(__file__).resolve().parents[2]
_COMPANY_PHRASE_END = re.compile(
    r"\s(?:provides|is|are|operates|engages|designs|develops|offers|manufactures|focuses|"
    r"through|together|invests|seeks)\b|,",
    re.IGNORECASE,
)


def company_phrase(description: Any) -> Optional[str]:
    """Leading company name of a profile description, or None.

    "Space Exploration Technologies Corp. provides satellite-based ..." ->
    "Space Exploration Technologies Corp". More than 8 words is not a name.
    """
    s = str(description or "").strip()
    if not s:
        return None
    m = _COMPANY_PHRASE_END.search(s)
    head = (s[: m.start()] if m else s).strip().rstrip(".").strip()
    if not head or len(head.split()) > 8:
        return None
    # "The fund seeks ...", "This ETF invests ...": a description, not a name.
    if head.lower().split(" ", 1)[0] in ("the", "this", "it", "a", "an", "our", "its"):
        return None
    return head


def _lockup_names() -> list[tuple[str, str, str]]:
    """(name, symbol, source) from config/ipo_lockups.json `company` fields.

    "SpaceX (Space Exploration Technologies Corp)" yields the whole string, the
    brand before the parenthesis and the legal name inside it.
    """
    path = Path(os.environ.get("TRADEAI_IPO_LOCKUPS") or (_REPO / "config" / "ipo_lockups.json"))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[tuple[str, str, str]] = []
    for sym, rec in ((doc or {}).get("lockups") or {}).items():
        company = str((rec or {}).get("company") or "").strip() if isinstance(rec, dict) else ""
        if not company or not sym:
            continue
        names = [company]
        m = re.match(r"^\s*([^()]+?)\s*\(([^()]+)\)\s*$", company)
        if m:
            names += [m.group(1), m.group(2)]
        for n in names:
            out.append((n, str(sym).upper(), "ipo_lockups"))
    return out


def _held_symbols() -> list[str]:
    path = Path(os.environ.get("TRADEAI_HOLDINGS_PATH")
                or (_REPO / "data" / "portfolios" / "state" / "holdings.json"))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = doc.get("holdings") or doc.get("positions") or [] if isinstance(doc, dict) else []
    return sorted({str(r.get("symbol")).upper() for r in rows if isinstance(r, dict) and r.get("symbol")})


def _readonly_query(sql: str, params: Any = None, fetch: str = "all") -> list[dict[str, Any]]:
    """Read-only session, 3 s statement timeout, lazy driver import."""
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        connect_timeout=3,
        options="-c statement_timeout=3000",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if fetch == "all" else [cur.fetchone()]
        return [dict(r) for r in rows if r is not None]
    finally:
        conn.close()


def _profile_names() -> list[tuple[str, str, str]]:
    """(company phrase, symbol, source) for HELD symbols, through the broker's
    symbol_profile projection. Off in CI, without DB credentials, or when
    TRADEAI_HOUSE_NAMES_DB=0 -- offline tests never touch the database."""
    if os.environ.get("TRADEAI_HOUSE_NAMES_DB", "1") == "0" or os.environ.get("TRADE_AI_CI") == "1":
        return []
    if not (os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")):
        return []
    held = _held_symbols()
    if not held:
        return []
    try:
        try:
            from scripts.lib.data_broker.symbol_profile import get_symbol_profiles  # noqa: PLC0415
        except Exception:
            from lib.data_broker.symbol_profile import get_symbol_profiles  # type: ignore  # noqa: PLC0415
        profiles = get_symbol_profiles(_readonly_query, held)
    except Exception:
        return []
    out: list[tuple[str, str, str]] = []
    for sym, p in (profiles or {}).items():
        phrase = company_phrase((p or {}).get("description"))
        if phrase:
            out.append((phrase, str(sym).upper(), "symbol_profiles"))
    return out


def _house_names() -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for name, sym, src in _lockup_names() + _profile_names():
        key = (normalize_name(name), sym)
        if key[0] and key not in seen:
            seen.add(key)
            out.append((name, sym, src))
    return out

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
    # Names the house holds (IPO lockups, held symbols' profiles). Appended, never
    # overriding: a name that now maps to two symbols stays ambiguous and refuses.
    for name, sym, _src in _house_names():
        norm = normalize_name(name)
        if not norm:
            continue
        bucket = exact.setdefault(norm, [])
        if sym not in bucket:
            bucket.append(sym)
        head = norm.split(" ", 1)[0]
        if len(head) >= 3:
            fb = first.setdefault(head, [])
            if sym not in fb:
                fb.append(sym)
    return exact, first


def refresh() -> None:
    """Drop the cache after a new sweep."""
    _build.cache_clear()


def is_exact_name(name: Any) -> bool:
    """True when `name` normalises to a STORED name that maps to exactly one symbol.

    resolve_name reports matched_on="exact" for a query whose every token is a
    leading prefix of one unique stored name ("NORTHROP" -> "NORTHROP GRUMMAN").
    That is right for a capitalised mention, but lowercase prose windows need the
    stricter claim: the words ARE the stored name, not merely its opening words.
    """
    norm = normalize_name(name)
    if len(norm) < 3:
        return False
    exact, _first = _build()
    hits = exact.get(norm) or []
    return len(set(hits)) == 1


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
    matched_on = "exact"

    if not hits:
        # PROGRESSIVE PREFIX. The feed CONTRACTS words, it does not merely
        # truncate: "NORFOLK SOUTHN CORP" for Norfolk Southern. "SOUTHN" is not a
        # prefix of "SOUTHERN" and "SOUTHERN" is not a prefix of "SOUTHN", so no
        # token rule matches them and fuzzy matching would be a guess.
        #
        # Narrowing works instead: drop trailing query tokens until the LEADING
        # tokens identify exactly one instrument. "NORFOLK SOUTHERN" -> "NORFOLK"
        # -> NSC. "NORTHROP" -> NOC. And "APPLE HOSPITALITY" -> "APPLE" stays
        # ambiguous (AAPL and APLE), so it resolves to nothing — narrowing must
        # never widen into a guess.
        tokens = norm.split()
        for k in range(len(tokens), 0, -1):
            prefix = " ".join(tokens[:k])
            cands = sorted({sym for name, syms in exact.items()
                            if name == prefix or name.startswith(prefix + " ")
                            for sym in syms})
            if len(cands) == 1:
                hits, matched_on = cands, ("exact" if k == len(tokens) else "name_prefix")
                break
            if len(cands) > 1:
                # Ambiguous at this width; a SHORTER prefix can only be more
                # ambiguous, so stop rather than keep shrinking into a guess.
                return None

    # COMPACTED BRAND. The feed often glues a spoken two-word name into one
    # token: "SENTINELONE INC A" for "Sentinel One". Progressive prefix cannot
    # see that — "SENTINEL" is not a prefix of "SENTINELONE" under the
    # space-bounded rule above. Compacting spaces is not fuzzy matching: it is
    # the exact normalised form the feed already stores. Ambiguity still refuses.
    # Turn-393 class: "Sentinel One" / "sentinel one" → S (84601d7d…).
    if not hits:
        compact = norm.replace(" ", "")
        if compact != norm and len(compact) >= 3:
            compact_hits = exact.get(compact)
            if compact_hits and len(set(compact_hits)) == 1:
                hits, matched_on = compact_hits, "compacted"

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
        "matched_on": matched_on,
        "source": "schwab_instruments",
        "financial_action": False,
    }
