"""Pick one symbol's Hermes scalp-catalyst research record from a day file (pure; 2026-10-22, Gate 1).

The store is ``data/hermes/momentum_catalysts/<day>_catalysts.jsonl`` (single writer
``hermes_momentum_catalyst_researcher.py --source scalp``; location: lib/hermes_catalyst_store.py). Two readers
must pick the same record the same way:

- ``lib.data_broker.scalp_list.get_scalp_catalyst`` — the Active Trader alert's ``catalyst_line`` fallback;
- ``lib.scanner_candidate_projection`` — the Shared Momentum projection's AT catalyst fallback.

2026-10-23 (CIO data quality): a record is FOUND only when its headline or source names the company
(:func:`verify_identity`: whole-word ticker or company name; generic index pages rejected); otherwise
it is UNVERIFIED_IDENTITY (AARD -> an Archrock headline, YMAT / INVE -> the nfl.com "ALL NEWS" page). Callers pass
``company_names`` (their read of the SEC ticker map, parsed by :func:`sec_name_index`); without them the ticker
alone must match.

Stdlib only (json, re, datetime, urllib.parse). No environment read, no file I/O, no network, no write: the caller reads the lines.
READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import unquote, urlparse

NO_CLEAR_CATALYST = "no_clear_catalyst"
UNVERIFIED_IDENTITY = "UNVERIFIED_IDENTITY"
#: Where callers find company names (read by the caller, parsed by :func:`sec_name_index`).
SEC_TICKERS_REL = "data/runtime/sec_company_tickers.json"


def _research_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif not value:
        return None
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    # naive = host-local, as lib.data_broker.scalp_list._utc reads it (the writers stamp datetime.now())
    return (dt if dt.tzinfo else dt.astimezone()).astimezone(timezone.utc)


# ── identity: is the record about this company? (2026-10-23, CIO data quality) ──────────────────────────────
#
# The researcher searches "<SYM> stock latest news" and takes the first result's title as the headline. Nothing
# checked that the result was about the company: on 2026-10-23 AARD (Aardvark Therapeutics) resolved to an
# Archrock (AROC) headline and YMAT / INVE to the nfl.com "ALL NEWS" index page, all FOUND. The rule (operator
# ruling 2026-10-10: the matcher is whole-word): the headline (``catalyst_summary``) or its source (``sources[0]``:
# title, snippet, URL slug) names the ticker as a whole word (upper case, optional ``$``, never case-folded) or the
# company name as a whole phrase (case-insensitive; without its legal suffix, or its first distinctive
# word); a generic index page is never evidence, and a headline taken from one is never verified. Anything else is
# UNVERIFIED_IDENTITY. Read side only: the researcher, its queries, model prompts and live lanes are unchanged.

IDENTITY_SCHEMA = "HermesCatalystIdentity@v1"
VERIFIED = "VERIFIED"

#: Legal-form and share-class words dropped from a company name before matching.
_LEGAL = frozenset(
    "inc inc. incorporated corp corp. corporation co co. company companies ltd ltd. limited llc l.l.c. lp l.p. plc "
    "p.l.c. sa s.a. nv n.v. ag se spa s.p.a. ab asa oyj holding holdings group the class a b c ordinary shares "
    "share common stock adr ads sponsored de del sab cv".split()
)
_LEGAL_BARE = frozenset(w.strip(".") for w in _LEGAL)
#: First words too common to identify a company on their own.
_COMMON_FIRST = frozenset(
    "american america first united global general national international new china chinese world capital "
    "financial energy health healthcare medical pharma bio biotech technology technologies tech digital data "
    "great north south east west western eastern pacific atlantic royal standard advanced applied community "
    "federal liberty pioneer premier summit universal".split()
)
#: Index-page titles: "ALL NEWS", "Latest headlines", "Top stories", "Breaking news", "News", "Markets" ...
_GENERIC_TITLE = re.compile(
    r"^\s*(all|latest|top|breaking|more|today'?s|recent|daily|market|markets|business|stock|stocks|world)?\s*"
    r"(news|headlines|stories|articles|updates|markets|stocks|home|homepage)?"
    r"(\s*(&|and|\||-|:)\s*(news|headlines|analysis|videos|updates|stories))?\s*$",
    re.I,
)
#: URL path segments that mark a listing, not an article.
_INDEX_SEGMENTS = frozenset(
    "series category categories tag tags topic topics section sections hub hubs archive archives author authors "
    "search page".split()
)
_INDEX_LAST = frozenset(
    "all-news allnews news latest latest-news headlines top-stories topstories markets stocks home index "
    "index.html index.htm default.aspx".split()
)


# Word boundaries are Unicode-aware: "BETR" is not a word inside "Betrüger".
_NB, _NA = r"(?<![^\W_])", r"(?![^\W_])"


def _sym_pattern(symbol: str) -> re.Pattern:
    """The ticker in upper case as a whole word, optional ``$`` — never case-folded ("Host a call" is not HOST)."""
    return re.compile(rf"{_NB}\$?{re.escape(symbol)}{_NA}")


def _phrase_pattern(phrase: str) -> re.Pattern:
    words = [re.escape(w) for w in phrase.split()]
    return re.compile(_NB + r"[\s\-_]+".join(words) + _NA, re.I)


def name_phrases(names: Iterable[str]) -> list[str]:
    """Match phrases for company names: the name without legal suffixes, and its first word when distinctive
    (>= 5 letters, not a common word). "Aardvark Therapeutics, Inc." -> ["aardvark therapeutics", "aardvark"]."""
    out: list[str] = []
    for raw in names or []:
        text = re.sub(r"/[a-z]{2,4}/?$", "", str(raw or "").strip().lower())   # "KEYCORP /NEW/", "... CV/"
        words = [w.strip(".,()/") for w in re.split(r"[\s,]+", text) if w.strip(".,()/")]
        while words and words[-1].strip(".") in _LEGAL_BARE:
            words.pop()
        if not words:
            continue
        core = " ".join(words)
        if len(core) >= 3 and core not in out:
            out.append(core)
        first = words[0]
        if len(words) > 1 and len(re.sub(r"[^a-z]", "", first)) >= 5 and first not in _COMMON_FIRST \
                and first not in out:
            out.append(first)
    return out


def generic_index_page(title: Any, url: Any) -> Optional[str]:
    """Why a source is a generic index page, or None. Title-only rows (no URL) are judged on the title."""
    t = str(title or "").strip()
    if t and _GENERIC_TITLE.match(t):
        return f"generic title {t!r}"
    u = str(url or "").strip()
    if not u:
        return None
    try:
        parsed = urlparse(u)
    except ValueError:
        return None
    segs = [s.lower() for s in unquote(parsed.path or "").split("/") if s]
    if not segs:
        return "site home page"
    hit = next((s for s in segs if s in _INDEX_SEGMENTS), None)
    if hit:
        return f"index URL (/{hit}/)"
    if segs[-1] in _INDEX_LAST:
        return f"index URL (/{segs[-1]})"
    return None


def _slug_text(url: Any) -> str:
    try:
        path = unquote(urlparse(str(url or "")).path or "")
    except ValueError:
        return ""
    return re.sub(r"[/\-_.+]+", " ", path)


def _mentions(text: str, symbol: str, phrases: list[str]) -> Optional[str]:
    if not text:
        return None
    if symbol and _sym_pattern(symbol).search(text):
        return f"ticker {symbol}"
    for p in phrases:
        if _phrase_pattern(p).search(text):
            return f"company {p!r}"
    return None


def verify_identity(symbol: str, record: Mapping[str, Any], company_names: Iterable[str] = ()) -> dict[str, Any]:
    """{"status": VERIFIED | UNVERIFIED_IDENTITY, "reason", "evidence", "names"} for one catalyst record.

    The headline is ``catalyst_summary``; its source is ``sources[0]`` (the researcher takes the headline from the
    first source). A record with no sources is judged on its headline alone."""
    sym = str(symbol or "").strip().upper()
    phrases = name_phrases(company_names)
    out: dict[str, Any] = {"schema": IDENTITY_SCHEMA, "symbol": sym, "names": phrases}
    headline = str(record.get("catalyst_summary") or "").strip()
    sources = [s for s in (record.get("sources") or []) if isinstance(s, Mapping) and not s.get("error")]
    first = sources[0] if sources else None
    why_generic = generic_index_page(headline, None) if headline else None
    if first is not None:
        why_generic = why_generic or generic_index_page(first.get("title"), first.get("url"))
    if why_generic:
        return {**out, "status": UNVERIFIED_IDENTITY, "reason": f"headline source is a {why_generic}",
                "evidence": None}
    checks = [("headline", headline)]
    if first is not None:
        checks += [("source title", str(first.get("title") or "")),
                   ("source snippet", str(first.get("content") or first.get("snippet") or "")),
                   ("source URL", _slug_text(first.get("url")))]
    for where, text in checks:
        hit = _mentions(text, sym, phrases)
        if hit:
            return {**out, "status": VERIFIED, "reason": f"{where} names the {hit}", "evidence": where}
    named = " / ".join([sym] + phrases) if phrases else sym
    return {**out, "status": UNVERIFIED_IDENTITY,
            "reason": f"neither the headline nor its source names {named} (whole word)", "evidence": None}


def sec_name_index(doc: Any) -> dict[str, list[str]]:
    """{TICKER: [company titles]} from a parsed SEC ``company_tickers.json`` document (the caller reads the file
    ``<state>/`` + :data:`SEC_TICKERS_REL`; this module does no I/O)."""
    by: dict[str, list[str]] = {}
    rows = doc.values() if isinstance(doc, dict) else (doc if isinstance(doc, list) else [])
    for r in rows:
        if isinstance(r, Mapping) and r.get("ticker") and r.get("title"):
            by.setdefault(str(r["ticker"]).upper(), []).append(str(r["title"]))
    return by


def select_scalp_catalyst(symbol: str, lines: Iterable[str],
                          company_names: Iterable[str] = ()) -> dict[str, Any] | None:
    """The newest research record for ``symbol`` (ties: the later line). None when the symbol is absent; else
    status FOUND | NONE_FOUND | UNVERIFIED_IDENTITY with catalyst_type, summary, confidence, source_count,
    researched_at, source. A catalyst whose headline and source do not name the company (whole word) or that came
    from a generic index page is UNVERIFIED_IDENTITY, never FOUND; ``identity`` says why."""
    sym = str(symbol or "").strip().upper()
    best: dict[str, Any] | None = None
    best_ts: datetime | None = None
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or str(rec.get("symbol") or "").upper() != sym:
            continue
        ts = _research_ts(rec.get("research_timestamp"))
        if best is None or (ts is not None and (best_ts is None or ts >= best_ts)):
            best, best_ts = rec, ts
    if best is None:
        return None
    ctype = str(best.get("catalyst_type") or "").strip() or NO_CLEAR_CATALYST
    status, identity = "NONE_FOUND", None
    if ctype != NO_CLEAR_CATALYST:
        identity = verify_identity(sym, best, company_names)
        status = "FOUND" if identity["status"] == VERIFIED else UNVERIFIED_IDENTITY
    return {
        "status": status,
        "identity": identity,
        "catalyst_type": ctype,
        "summary": str(best.get("catalyst_summary") or "").strip() or None,
        "confidence": best.get("confidence"),
        "source_count": best.get("source_count"),
        "researched_at": best.get("research_timestamp"),
        "source": "hermes_momentum_catalyst_researcher",
    }
