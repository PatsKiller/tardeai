"""Extract every issuer a document mentions, and decide which it is ABOUT.

DETERMINISTIC FIRST. THE MODEL ONLY ON THE RESIDUAL.
---------------------------------------------------
Extraction — tickers and company names — is a regex plus two lookups and needs no
model. Deciding which mention is the SUBJECT is judgment, and only sometimes:

    exactly one mention                     -> that one is the subject
    a mention equals the row's own symbol   -> that one is the subject
    neither                                 -> UNDECIDED, left for the model

The third case is the only place a model belongs, and it is a minority. Anything
it decides is written `role_source='model'` with a confidence, so it can be
re-audited separately from the deterministic rows for ever.

WHY THE SUBJECT/MENTIONED SPLIT MATTERS
---------------------------------------
    "Morgan Stanley estimates Apple foldable iPhone could generate…"

mentions MS and NDAQ; the article is ABOUT Apple. Morgan Stanley is the source of
the estimate. Recording all three as subjects attaches the article to issuers it
is not about and every downstream join inherits it — a wrong tag is worse than no
tag, because it looks like coverage.

`role='mentioned'` is NOT a lesser tag. "Every document that mentions this
issuer" is a legitimate and useful query; it simply must not be confused with
"every document about it".
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

SCHEMA = "DocumentMention@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

ROLE_SUBJECT = "subject"
ROLE_MENTIONED = "mentioned"
ROLE_UNRESOLVED = "unresolved"

DETERMINISTIC = "deterministic"

#: Sources this extractor knows how to read: (table, id column, text columns,
#: the column naming the row's own subject, if it has one).
SOURCES: dict[str, dict[str, Any]] = {
    "news_articles": {
        "id": "id",
        "text": ("title", "summary"),
        "own_symbol": "symbol",
    },
    "catalyst_events": {
        "id": "id",
        "text": ("headline", "description"),
        "own_symbol": "symbol",
    },
    # LLM-curated web research. The curation decides whether a finding is worth
    # keeping; identity decides what it is ABOUT. Two different questions, and
    # the second is deterministic.
    "hermes_external_research": {
        "id": "id",
        "text": ("question", "recommendation", "research_reason"),
        "own_symbol": "symbol",
    },
    "research_insights": {
        "id": "id",
        "text": ("headline", "structured_thesis", "key_arguments"),
        "own_symbol": "symbol",
    },
    # SEC insider transactions. `filer_name` is a PERSON, not an issuer, and is
    # deliberately excluded from the text scanned — a director's name must never
    # resolve to a company.
    "sec_form4": {
        "id": "id",
        "text": (),
        "own_symbol": "symbol",
        # No prose. The row is a transaction ("P", "S"), and its subject is the
        # symbol column. Scanning the body found 0 mentions in 300 rows and
        # reported them all as unmentioned, which is false — the filing IS about
        # that issuer. `filer_name` is a PERSON and is deliberately never scanned:
        # a director's name must not resolve to a company.
        "subject_is_own_symbol": True,
    },
}

#: Stores that have NO issuer and must never be given one.
#:
#: Macro data — FRED series, CPI, unemployment — belongs to no company. Forcing a
#: security GUID onto it would be the same invented-mapping error the identity
#: work exists to prevent, and every join through it would be false. Macro needs
#: its own identity axis (series id), which is a separate design.
#:
#: `topic_monitor` has no symbol column at all: it is a crawl configuration, not
#: a document about a security.
NO_ISSUER_BY_DESIGN: frozenset[str] = frozenset({
    "fred_economic_data",     # declared by fred_data_ingest; the table does not
                              # exist — see integrity check declared_output_missing
    "topic_monitor",
})


# ── false-positive company matches ───────────────────────────────────────────
#
# Measured 2026-11-07 on the live table: the company-name index bound wire-service names, exchanges,
# places and ordinary words to issuers ("GLOBE NEWSWIRE" -> GL 5,897 rows, "NASDAQ" -> NDAQ 20,549,
# "ENHANCED" -> ENHA 7,562, "BULLISH" -> BLSH 2,836, "NEW YORK" -> NYT 1,090, "Price Target" -> TROW).
# A wrong tag is worse than no tag: it looks like coverage and every join inherits it.
#
# The rule is deterministic and has two parts. A NAME THAT IS AMBIGUOUS binds an issuer only with
# CONTEXT: the row is filed under that very symbol, or the text names the symbol as a ticker
# ("(ENHA)", "NASDAQ: ENHA", "$ENHA"). Ambiguous means: on the stoplist below, a multi-word run built
# from finance-prose terms, or -- for a ticker_alias match -- a lone token that is an ordinary word.
# Distinctive names ("Apple", "Bloom Energy", "Morgan Stanley") are untouched.

APPLIES_TO_MATCHED_VIA: frozenset[str] = frozenset({"company_name", "ticker_alias"})

#: Wire services, exchanges, places, publishers, ordinary words. Casefolded, whole-string.
AMBIGUOUS_NAMES: frozenset[str] = frozenset({
    # wire services and publishers
    "globe newswire", "globe", "access newswire", "accesswire", "pr newswire", "business wire",
    "reuters", "associated press", "simply wall st", "simply wall street", "morningstar",
    "benzinga", "marketwatch", "investopedia", "zacks", "seeking alpha", "motley fool",
    # exchanges and market venues
    "nasdaq", "nyse", "new york stock exchange", "eastern time", "eastern progress",
    # places
    "new york", "san diego", "san francisco", "chicago", "canada", "america", "british columbia",
    "london", "boston", "texas", "california", "china", "europe", "asia", "united states",
    # ordinary words that are also issuer names
    "enhanced", "bullish", "bearish", "mixed", "ideal", "versus", "strategy", "next", "focus",
    "series", "outlook", "healthcare", "performance", "distribution", "invest", "day", "volatility",
    "bitcoin", "starlink", "spacex", "deep dive", "best growth stocks", "price target",
})

#: Prose terms: a multi-word run containing one is a phrase of analysis, not a company name.
PHRASE_TERMS: frozenset[str] = frozenset({
    "price", "target", "moving", "average", "liquidity", "volatility", "dive", "events", "dynamics",
    "allocations", "action", "mapping", "zones", "pulse", "insight", "sensitive", "driven", "critical",
})

#: An English hyphenation: a hyphen followed by a lower-case letter. A PROPER name hyphenates two
#: capitalised parts ("T-Mobile", "Bio-Rad", "Kimberly-Clark", "O-I Glass", "Asia-Pacific"); prose
#: glues a lower-case word onto the head ("Shell-company", "Cross-reference XLV", "New York-based",
#: "Post-mortem", "Net-net", "Research-only", "C-suite"). Measured 2026-11-07 on the live table: this
#: shape selects 848 rows, every sampled one a false positive, and keeps every genuine hyphenated
#: issuer name in the 100-row adjudicated sample (LQ-287) and the top-offender census alike.
_HYPHEN_PROSE = re.compile(r"(?<=[A-Za-z0-9])-[a-z]")

_NORM = re.compile(r"[^a-z0-9 ]+")


def _norm(text: Any) -> str:
    return " ".join(_NORM.sub(" ", str(text or "").casefold()).split())


def _is_ordinary_word(token: str) -> bool:
    """A lone token that is a common word or declared template chrome (fail closed: no list -> not judged here)."""
    try:
        from lib import inbound_identity_tagger as T  # noqa: PLC0415
    except Exception:
        return False
    up = token.upper()
    if up in T._STOPWORDS or up in T._TEMPLATE_CHROME or token.capitalize() in T._SENTENCE_STARTERS:
        return True
    common = T._common_words()
    return bool(common) and token.casefold() in common


def _has_context(symbol: str, text: str, own_symbol: Optional[str]) -> bool:
    sym = (symbol or "").upper()
    if not sym:
        return False
    if own_symbol and own_symbol.strip().upper() == sym:
        return True
    return bool(re.search(r"(?:\(|:\s*|\$)\s*" + re.escape(sym) + r"(?![A-Za-z0-9])", text or ""))


def false_positive_reason(matched_text: Any, symbol: Any, matched_via: Any, *, text: str = "",
                          own_symbol: Optional[str] = None) -> Optional[str]:
    """Why a name/alias match must not become a mention, or None. Never guesses: context only ever ALLOWS."""
    if matched_via not in APPLIES_TO_MATCHED_VIA:
        return None                                        # a ticker match is a different claim
    name = str(matched_text or "").strip()
    if not name:
        return None
    n = _norm(name)
    # Compared on the normalised forms so "Johnson & Johnson" / "Nasdaq-" still match their cleaned name;
    # what is refused is a name found only INSIDE a longer word ("Ideal" in "idealistic").
    if text and n and f" {n} " not in f" {_norm(text)} ":
        return "no_word_boundary"
    tokens = n.split()
    ambiguous = None
    if n in AMBIGUOUS_NAMES:
        ambiguous = "ambiguous_name"
    elif len(tokens) > 1 and any(t in PHRASE_TERMS for t in tokens):
        ambiguous = "prose_phrase"
    elif _HYPHEN_PROSE.search(name):
        # "Shell-company" -> SHEL and "Cross-reference XLV" -> CRT were written at 16:25 ET on
        # 2026-11-07, AFTER the stoplist shipped: neither name is on a list, and normalising the
        # hyphen away ("shell company", "cross reference xlv") made both look like stored names.
        ambiguous = "prose_compound"
    elif matched_via == "ticker_alias" and len(tokens) == 1 and _is_ordinary_word(name):
        ambiguous = "ordinary_word_alias"
    if ambiguous is None:
        return None
    return None if _has_context(str(symbol or ""), text, own_symbol) else ambiguous + "_without_context"


def extract(text: str, *, own_symbol: Optional[str] = None,
            registry: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Mentions with a deterministic role where one can be decided.

    Returns rows ready to persist. A row whose role could not be decided
    deterministically is returned with `role=None` — the caller decides whether
    to hand it to the model or leave it out. It is NEVER guessed here.
    """
    from lib.inbound_identity_tagger import tag_inbound  # noqa: PLC0415

    tag = tag_inbound(text, registry=registry)
    own = (own_symbol or "").strip().upper() or None
    found = [r for r in (tag.get("resolved") or [])
             if false_positive_reason(r.get("matched_text"), r.get("symbol"), r.get("matched_via"),
                                      text=text, own_symbol=own) is None]
    if not found:
        return []

    rows: list[dict[str, Any]] = []

    # Rule 1: a single mention is the subject.
    if len(found) == 1:
        r = found[0]
        rows.append(_row(r, ROLE_SUBJECT, DETERMINISTIC))
        return rows

    # Rule 2: the row's own symbol column names the subject; the rest are
    # mentions. This is the common shape — a news row already knows what it is
    # filed under, and the body names others in passing.
    if own and any(r["symbol"] == own for r in found):
        for r in found:
            rows.append(_row(r, ROLE_SUBJECT if r["symbol"] == own else ROLE_MENTIONED,
                             DETERMINISTIC))
        return rows

    # Rule 3: several mentions and none is the filed symbol. Undecidable without
    # judgment. Emit them as mentions with role=None so the caller can route them
    # to the model; guessing a subject here is the wrong-issuer error.
    for r in found:
        row = _row(r, None, None)
        rows.append(row)
    return rows


def subject_from_symbol(symbol: Any, *,
                        registry: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """The subject of a row that has no prose — a filing, a transaction.

    Deterministic and single-valued: the row is about its symbol, or about
    nothing resolvable. There is no judgment here and no model.
    """
    from lib import research_identity as RI  # noqa: PLC0415

    doc = registry if registry is not None else RI.load_registry()
    tag = RI.resolve(doc, symbol)
    if tag is None:
        return []
    return [_row({"symbol": tag["symbol"], "subject_guid": tag["subject_guid"],
                  "issuer_guid": tag["issuer_guid"],
                  "identity_status": tag["identity_status"],
                  "matched_via": "ticker", "matched_text": tag["symbol"]},
                 ROLE_SUBJECT, DETERMINISTIC)]


def _row(r: dict[str, Any], role: Optional[str],
         role_source: Optional[str]) -> dict[str, Any]:
    return {
        "symbol": r["symbol"],
        "subject_guid": r["subject_guid"],
        "issuer_guid": r["issuer_guid"],
        "identity_status": r.get("identity_status"),
        "matched_via": r.get("matched_via"),
        "matched_text": r.get("matched_text"),
        "role": role,
        "role_source": role_source,
        "role_confidence": None,
    }


#: A sentinel for "no issuer". `issuer_guid` stays NULL in the row — NULL means UNKNOWN and must never
#: be rewritten — but the uniqueness rule needs a value, because PostgreSQL treats every NULL as
#: distinct and the old index therefore never fired: measured 2026-11-07, 1,599 (document, role)
#: groups carried duplicates, 32,550 rows have a NULL issuer and every duplicate is in them.
_ISSUER_SENTINEL = "00000000-0000-0000-0000-000000000000"
_CONFLICT_EXPR = ("(source_table, source_id, "
                  "COALESCE(issuer_guid, '00000000-0000-0000-0000-000000000000'::uuid), role)")
_CONFLICT_PLAIN = "(source_table, source_id, issuer_guid, role)"
_COALESCE_INDEX = "uq_docmentions_issuer_coalesce"
_MEMO_ATTR = "_dm_conflict_target"      # memo on the CONNECTION: one probe per connection, not per document


def _conflict_target(cur) -> str:
    """The ON CONFLICT clause this database supports.

    The expression index arrives with migrations/2026_11_07_document_mentions_issuer_coalesce.sql, which the
    operator applies — possibly AFTER this code ships. So the clause is chosen from what the database
    actually has, exactly like the LQ-273 lane keeps its pre-migration UPDATE: before the index the old
    clause still works (the old index is left in place), after it the NULL-issuer duplicate cannot land.
    Probed once per connection (memoised on the connection object, which psycopg2 exposes from its cursor).
    """
    conn = getattr(cur, "connection", None)
    if conn is not None and hasattr(conn, _MEMO_ATTR):
        return getattr(conn, _MEMO_ATTR)
    target = _CONFLICT_PLAIN
    cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s LIMIT 1", (_COALESCE_INDEX,))
    if cur.fetchone():
        target = _CONFLICT_EXPR
    if conn is not None:
        try:
            setattr(conn, _MEMO_ATTR, target)
        except (AttributeError, TypeError):
            # A connection object that forbids attributes re-probes on the next call: correct, just
            # one extra read-only query per document.
            return target
    return target


def persist(conn, *, source_table: str, source_id: Any,
            rows: Iterable[dict[str, Any]]) -> int:
    """Idempotent write. Re-running the extractor is a no-op, not a duplicate."""
    cur = conn.cursor()
    target = None                             # probed lazily: an undecided row must reach no query at all
    n = 0
    for r in rows:
        if not r.get("role") or not r.get("role_source"):
            continue                      # undecided: not this function's call
        if target is None:
            target = _conflict_target(cur)
        cur.execute(
            f"""INSERT INTO document_mentions
                 (source_table, source_id, symbol, subject_guid, issuer_guid,
                  identity_status, role, role_source, role_confidence,
                  matched_via, matched_text)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT {target}
               DO NOTHING""",  # noqa: S608 -- target is one of two literals above, never input
            (source_table, int(source_id), r["symbol"], r["subject_guid"],
             r["issuer_guid"], r.get("identity_status"), r["role"],
             r["role_source"], r.get("role_confidence"),
             r.get("matched_via"), r.get("matched_text")))
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return n
