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


def extract(text: str, *, own_symbol: Optional[str] = None,
            registry: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Mentions with a deterministic role where one can be decided.

    Returns rows ready to persist. A row whose role could not be decided
    deterministically is returned with `role=None` — the caller decides whether
    to hand it to the model or leave it out. It is NEVER guessed here.
    """
    from lib.inbound_identity_tagger import tag_inbound  # noqa: PLC0415

    tag = tag_inbound(text, registry=registry)
    found = tag.get("resolved") or []
    if not found:
        return []

    own = (own_symbol or "").strip().upper() or None
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


def persist(conn, *, source_table: str, source_id: Any,
            rows: Iterable[dict[str, Any]]) -> int:
    """Idempotent write. Re-running the extractor is a no-op, not a duplicate."""
    cur = conn.cursor()
    n = 0
    for r in rows:
        if not r.get("role") or not r.get("role_source"):
            continue                      # undecided: not this function's call
        cur.execute(
            """INSERT INTO document_mentions
                 (source_table, source_id, symbol, subject_guid, issuer_guid,
                  identity_status, role, role_source, role_confidence,
                  matched_via, matched_text)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_table, source_id, issuer_guid, role)
               DO NOTHING""",
            (source_table, int(source_id), r["symbol"], r["subject_guid"],
             r["issuer_guid"], r.get("identity_status"), r["role"],
             r["role_source"], r.get("role_confidence"),
             r.get("matched_via"), r.get("matched_text")))
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return n
