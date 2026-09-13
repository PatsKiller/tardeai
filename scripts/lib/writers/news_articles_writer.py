"""news_articles — the ONE write path for the catalyst_news store.

WHY
---
On 2026-09-13 sixteen files carried their own INSERT or UPDATE against
news_articles. Each had its own column list, its own truncation lengths, its own
dedupe rule (source_url globally; source_url per symbol; symbol+title;
source+symbol+title; ON CONFLICT DO NOTHING against a table with no unique index,
which dedupes nothing) and no identity at all — the subject_guid column existed
and every insert wrote NULL into it. That is the shape of the Finviz incident: a
row's meaning decided by whichever writer happened to run.

This module is the only place the store's SQL lives. Producers stay plural
(Yahoo RSS, Finviz, Hermes, topic monitor, Telegram, Alpha Vantage, SEC EDGAR);
the write path is singular.

THE RULES IT OWNS
-----------------
* Column list and order (COLUMNS); a row's columns are the keys it carries, so a
  producer that never wrote `summary` still does not, and a column default
  (relevance_score DEFAULT 0.5) still applies where the producer said nothing.
* Coercion: title[:500], summary[:1000], source_url[:500]; list/dict JSON fields
  serialised once, here.
* ONE dedupe rule: a row is a duplicate when a row with the same `symbol` already
  carries the same `source_url` (when the new row has one) or the same `title`.
  Per symbol, because a headline tagged CVX,NOC,LMT is a catalyst for each of
  them (finviz_proactive_research's rule, kept). Legacy writers that deduped
  differently are listed in docs/implementation/sot/phase9_news_articles_notes.md.
* Conflict rule: ON CONFLICT DO NOTHING. Unenforced today — the table has no
  unique index (proposed migration in the notes) — so the SELECT-before-INSERT
  above is what actually dedupes.
* Rails: non-empty title and source; source not a retired provider
  (scripts/lib/retired_providers, read from config/data_source_authority.json);
  relevance_score finite and within [0, 100] (the column carries two scales
  today, 0-1 from content_scoring and 0-100 from the SEC/Alpha Vantage lanes —
  recorded as a finding, not silently rescaled); sentiment_score finite within
  [-1, 1]; published_at a datetime/date/ISO string/SQL_NOW or None.
* Identity: subject_guid / issuer_guid / identity_status / identity_tagged_at are
  populated ONLY through the existing resolvers — identity_registry (registry
  first, following supersede chains) then security_identity's spine when the row
  carries a CIK or company — never computed here, never invented. A symbol the
  registry does not know stays NULL, exactly as backfill_research_identity leaves
  it. Topic rows (topic_ingestion; symbol = topic_id) take the same deterministic
  topic GUID backfill_subject_identity mints for them.
* Receipt: every call returns a NewsArticlesWriteReceipt@v1 — rows_in,
  rows_written, rows_duplicate, rows_rejected with reasons. Rejected rows are
  returned and logged, never dropped.

Source labels are preserved verbatim ("finviz_news", "yahoo_rss", "hermes",
"search:brave", "topic_google_news_rss", "av:Benzinga", "telegram_article").

AUTHORITY: READ_ONLY_ADVISORY. Ingestion only; no prices, no positions, no
financial action. It runs nothing against a database by itself — callers pass a
cursor and own the transaction.
"""
from __future__ import annotations

import json
import logging
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parents[2]
_ROOT = _HERE.parents[3]
for _p in (_ROOT, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

log = logging.getLogger(__name__)

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "NewsArticlesWriteReceipt@v1"
TABLE = "news_articles"
WRITTEN_BY = "scripts/lib/writers/news_articles_writer.py"

#: Canonical column order. A row contributes the subset of these it carries.
COLUMNS: tuple[str, ...] = (
    "symbol", "strategy_type", "title", "summary", "source", "source_url",
    "published_at", "relevance_score", "sentiment", "sentiment_score",
    "strategy_tags", "agent_tags", "raw_payload",
)
#: Added by sql/research_identity_tags.sql. Written only when the table has them.
IDENTITY_COLUMNS: tuple[str, ...] = ("subject_guid", "issuer_guid", "identity_status", "identity_tagged_at")
JSON_COLUMNS: tuple[str, ...] = ("strategy_tags", "agent_tags", "raw_payload")
MAXLEN: dict[str, int] = {"title": 500, "summary": 1000, "source_url": 500}
RAG_STATUSES: frozenset[str] = frozenset({"pending", "approved", "low_quality", "blocked"})

#: Provider label prefixes whose remainder names the provider (retired check).
_SOURCE_PREFIXES: tuple[str, ...] = ("search:", "topic_", "av:", "google_news:")


class SqlNow:
    """Marker: render NOW() in the VALUES clause (transaction time, as legacy SQL did)."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "SQL_NOW"


SQL_NOW = SqlNow()


class NewsArticleRejected(ValueError):
    """A single-row update was refused by a rail. Loud on purpose."""


@dataclass
class WriteReceipt:
    """What one call did. rows_in == rows_written + rows_duplicate + rows_rejected."""

    source: str | None = None
    run_id: str | None = None
    rows_in: int = 0
    rows_written: int = 0
    rows_duplicate: int = 0
    rows_rejected: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)
    ids: list[Any] = field(default_factory=list)
    identity_resolved: int = 0
    identity_unresolved: int = 0
    identity_lookup_failed: int = 0
    identity_columns_present: bool | None = None
    schema: str = SCHEMA
    table: str = TABLE
    written_by: str = WRITTEN_BY
    authority: str = AUTHORITY

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── provenance / rails ───────────────────────────────────────────────────────


def provider_token(source: Any) -> str:
    """The provider a source label names: 'search:brave' -> 'brave', 'av:X' -> 'x'."""
    s = str(source or "").strip().lower()
    for pre in _SOURCE_PREFIXES:
        if s.startswith(pre):
            return s[len(pre):]
    return s


def source_is_retired(source: Any) -> bool:
    from lib.retired_providers import is_retired
    return is_retired(source) or is_retired(provider_token(source))


def _finite(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _as_json(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def validate_article(row: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Coerce one row or name the rail it failed. Never raises."""
    title = str(row.get("title") or "").strip()
    if not title:
        return None, "EMPTY_TITLE"
    source = str(row.get("source") or "").strip()
    if not source:
        return None, "EMPTY_SOURCE"
    if source_is_retired(source):
        return None, f"RETIRED_PROVIDER:{provider_token(source)}"
    out: dict[str, Any] = {}
    for col in COLUMNS:
        if col not in row:
            continue
        val = row[col]
        if col in MAXLEN and isinstance(val, str):
            val = val[: MAXLEN[col]]
        if col in JSON_COLUMNS:
            val = _as_json(val)
        out[col] = val
    out["title"] = out["title"][: MAXLEN["title"]] if isinstance(out.get("title"), str) else title
    out["source"] = source
    if out.get("relevance_score") is not None:
        rel = _finite(out["relevance_score"])
        if rel is None or rel < 0 or rel > 100:
            return None, f"RELEVANCE_OUT_OF_RANGE:{row.get('relevance_score')!r}"
    if out.get("sentiment_score") is not None:
        s = _finite(out["sentiment_score"])
        if s is None or s < -1 or s > 1:
            return None, f"SENTIMENT_OUT_OF_RANGE:{row.get('sentiment_score')!r}"
    pub = out.get("published_at")
    if pub is not None and not isinstance(pub, (SqlNow, datetime, date, str)):
        return None, f"BAD_PUBLISHED_AT:{type(pub).__name__}"
    return out, None


# ── identity ─────────────────────────────────────────────────────────────────

_IDENTITY_COLUMNS_PRESENT: bool | None = None


def _first(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return next(iter(row.values()), None)
    try:
        return row[0]
    except (IndexError, KeyError, TypeError):
        return None


def identity_columns_present(cur, *, refresh: bool = False) -> bool:
    """Does the live table carry the identity columns? Probed once per process.

    The migration (sql/research_identity_tags.sql) is applied by the operator; a
    writer that assumed it would fail every insert on a tree where it is not.
    """
    global _IDENTITY_COLUMNS_PRESENT
    if _IDENTITY_COLUMNS_PRESENT is not None and not refresh:
        return _IDENTITY_COLUMNS_PRESENT
    try:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name = ANY(%s)",
            (TABLE, list(IDENTITY_COLUMNS)),
        )
        have = {str(_first(r)) for r in (cur.fetchall() or [])}
    except Exception as exc:  # noqa: BLE001 - probe failure is "unknown", not "absent"
        log.warning("[%s] identity column probe failed: %s", TABLE, exc)
        return False
    _IDENTITY_COLUMNS_PRESENT = all(c in have for c in IDENTITY_COLUMNS)
    return _IDENTITY_COLUMNS_PRESENT


def resolve_identity(symbol: Any, *, cik: Any = None, company: Any = None,
                     subject_kind: str = "security", registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Registry first, spine second, never minted here.

    Returns {subject_guid, issuer_guid, identity_status, resolved_via, lookup_failed}.
    `resolved_via` is "registry" | "spine" | "topic" | None.

    * registry: identity_registry.lookup_symbol follows supersede chains
      (resolve_guid) to the active entity; the durable key is
      subject_guid_of(entity) = security > issuer > ticker alias — the same call
      backfill_research_identity makes, so an insert-time GUID equals the one the
      backfill would have stamped later.
    * spine: only when the row carries a CIK or company and the registry does not
      know the symbol; security_identity.resolve_identity_spine — deterministic
      UUIDv5, identical to what identity_registry.register would mint.
    * topic: topic_ingestion rows, whose symbol is a topic_monitor.topic_id;
      backfill_subject_identity.topic_guid, CONFIRMED, as that backfill stamps.
    * otherwise NULL: unexamined, so the backfills still see the row.
    """
    out: dict[str, Any] = {"subject_guid": None, "issuer_guid": None, "identity_status": None,
                           "resolved_via": None, "lookup_failed": False}
    sym_raw = str(symbol or "").strip()
    if not sym_raw:
        return out
    if subject_kind == "topic":
        from backfill_subject_identity import topic_guid
        out.update({"subject_guid": topic_guid(sym_raw), "identity_status": "CONFIRMED", "resolved_via": "topic"})
        return out
    from lib.cio_subject_guid import NON_ENTITY_SYMBOLS
    from lib.security_identity import normalize_symbol, resolve_identity_spine
    from lib import identity_registry as R
    sym = normalize_symbol(sym_raw)
    if sym in NON_ENTITY_SYMBOLS:
        return out
    try:
        doc = registry if registry is not None else R.load_cached()
        ent = R.lookup_symbol(doc, sym)
    except Exception as exc:  # noqa: BLE001 - a registry that cannot be read is not "unknown symbol"
        log.warning("[%s] identity registry unreadable for %s: %s", TABLE, sym, exc)
        out["lookup_failed"] = True
        return out
    if ent:
        guid = R.subject_guid_of(ent, sym)
        if guid:
            out.update({"subject_guid": guid, "issuer_guid": ent.get("issuer_guid"),
                        "identity_status": ent.get("identity_status") or "UNRESOLVED", "resolved_via": "registry"})
            return out
    if cik or company:
        spine = resolve_identity_spine({"symbol": sym, "cik": cik, "company": company})
        guid = R.subject_guid_of(spine, sym)
        if guid:
            out.update({"subject_guid": guid, "issuer_guid": spine.get("issuer_guid"),
                        "identity_status": spine.get("identity_status"), "resolved_via": "spine"})
    return out


# ── dedupe ───────────────────────────────────────────────────────────────────


def is_duplicate(cur, symbol: Any, source_url: Any = None, title: Any = None) -> bool:
    """THE dedupe rule: same symbol and (same source_url, when given, or same title)."""
    clauses, params = [], []
    if source_url:
        clauses.append("source_url = %s")
        params.append(str(source_url)[: MAXLEN["source_url"]])
    if title:
        clauses.append("title = %s")
        params.append(str(title)[: MAXLEN["title"]])
    if not clauses:
        return False
    if symbol is None:
        sym_clause = "symbol IS NULL"
    else:
        sym_clause = "symbol = %s"
        params.insert(0, symbol)
    cur.execute(f"SELECT id FROM news_articles WHERE {sym_clause} AND ({' OR '.join(clauses)}) LIMIT 1", params)
    return cur.fetchone() is not None


# ── insert ───────────────────────────────────────────────────────────────────


def write_news_articles(cur, rows: Iterable[Mapping[str, Any]], *, source: str | None = None,
                        run_id: str | None = None, subject_kind: str = "security",
                        identity_columns: bool | None = None, dedupe: bool = True) -> WriteReceipt:
    """Insert article rows. The only INSERT against news_articles in the tree.

    `source` is the default label for rows that do not carry their own and the
    receipt's label. `subject_kind="topic"` marks rows whose symbol is a
    topic_monitor.topic_id. `identity_columns` overrides the live-table probe
    (tests). Caller owns commit/rollback; a database error propagates.
    """
    rows = list(rows)
    rc = WriteReceipt(source=source, run_id=run_id, rows_in=len(rows))
    if not rows:
        return rc
    rc.identity_columns_present = (identity_columns if identity_columns is not None
                                   else identity_columns_present(cur))
    registry = None
    for idx, raw in enumerate(rows):
        row = dict(raw)
        if source and not row.get("source"):
            row["source"] = source
        clean, reason = validate_article(row)
        if clean is None:
            rc.rows_rejected += 1
            rej = {"index": idx, "reason": reason, "symbol": row.get("symbol"),
                   "title": str(row.get("title") or "")[:120], "source": row.get("source")}
            rc.rejected.append(rej)
            log.warning("[%s] rejected row %s", TABLE, rej)
            continue
        if dedupe and is_duplicate(cur, clean.get("symbol"), clean.get("source_url"), clean.get("title")):
            rc.rows_duplicate += 1
            continue
        cols = [c for c in COLUMNS if c in clean]
        vals = [clean[c] for c in cols]
        if rc.identity_columns_present:
            if registry is None and subject_kind != "topic":
                from lib import identity_registry as R
                try:
                    registry = R.load_cached()
                except Exception:  # noqa: BLE001
                    registry = {}
            ident = resolve_identity(clean.get("symbol"), cik=row.get("cik"), company=row.get("company"),
                                     subject_kind=subject_kind, registry=registry)
            if ident["lookup_failed"]:
                rc.identity_lookup_failed += 1
            if ident["subject_guid"]:
                rc.identity_resolved += 1
                cols += ["subject_guid", "issuer_guid", "identity_status", "identity_tagged_at"]
                vals += [ident["subject_guid"], ident["issuer_guid"], ident["identity_status"], SQL_NOW]
            else:
                rc.identity_unresolved += 1
        placeholders = ["NOW()" if isinstance(v, SqlNow) else "%s" for v in vals]
        params = [v for v in vals if not isinstance(v, SqlNow)]
        cur.execute(
            f"INSERT INTO news_articles ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) "
            f"ON CONFLICT DO NOTHING RETURNING id",
            params,
        )
        new_id = _first(cur.fetchone())
        if new_id is None:
            rc.rows_duplicate += 1  # DO NOTHING fired (only once a unique index exists)
            continue
        rc.rows_written += 1
        rc.ids.append(new_id)
    return rc


# ── updates: one function per row kind ───────────────────────────────────────


def _one(cur, sql: str, params: Iterable[Any]) -> int:
    cur.execute(sql, list(params))
    n = getattr(cur, "rowcount", None)
    return int(n) if isinstance(n, int) and n >= 0 else 0


def set_sentiment(cur, article_id: Any, sentiment: Any, sentiment_score: Any) -> int:
    """sentiment_processor: label + score in [-1, 1]."""
    s = _finite(sentiment_score) if sentiment_score is not None else 0.0
    if s is None or s < -1 or s > 1:
        raise NewsArticleRejected(f"SENTIMENT_OUT_OF_RANGE:{sentiment_score!r}")
    return _one(cur, f"UPDATE news_articles SET sentiment = %s, sentiment_score = %s WHERE id = %s",
                (sentiment, sentiment_score, article_id))


def set_rag_status(cur, article_id: Any, status: Any, reason: Any) -> int:
    """topic_curator: LLM / ensemble verdict for one row."""
    st = str(status or "").strip()
    if st not in RAG_STATUSES:
        raise NewsArticleRejected(f"BAD_RAG_STATUS:{status!r}")
    return _one(cur, f"UPDATE news_articles SET rag_status=%s, rag_reason=%s WHERE id=%s",
                (st, str(reason or "")[:200], article_id))


def approve_pending_by_relevance(cur, *, source_prefix: str = "topic_", min_relevance: float = 0.4,
                                 reason: str | None = None) -> int:
    """topic_curator: set-based auto-approval of pending rows above a relevance floor."""
    floor = _finite(min_relevance)
    if floor is None or floor < 0 or floor > 100:
        raise NewsArticleRejected(f"RELEVANCE_OUT_OF_RANGE:{min_relevance!r}")
    return _one(cur, f"UPDATE news_articles SET rag_status='approved', rag_reason=%s "
                     f"WHERE rag_status='pending' AND source LIKE %s AND relevance_score >= %s",
                (reason or f"auto: relevance >= {min_relevance}", f"{source_prefix}%", floor))


def set_strategy_classification(cur, article_id: Any, strategy_type: Any, retirement_relevance: Any) -> int:
    """_news_strategy_classifier: keyword classification of one row."""
    return _one(cur, f"UPDATE news_articles SET strategy_type = %s, retirement_relevance = %s WHERE id = %s",
                (strategy_type, retirement_relevance, article_id))


def reassign_strategy_type(cur, old: str, new: str) -> int:
    """api_v2 admin backfill: rename one strategy_type value across the store."""
    if not old or not new:
        raise NewsArticleRejected("EMPTY_STRATEGY_TYPE")
    return _one(cur, f"UPDATE news_articles SET strategy_type=%s WHERE strategy_type=%s", (new, old))


def archive_article(cur, article_id: Any, reason: Any) -> int:
    """iris_taxonomy_agent hygiene: archive (never delete) with the reason."""
    return _one(cur, f"UPDATE news_articles SET hygiene_status='archived', demoted_at=NOW(), demoted_reason=%s WHERE id=%s",
                (reason, article_id))


def flag_title_duplicates(cur, *, days: int = 90) -> int:
    """iris_taxonomy_agent 3g: mark later near-identical titles is_duplicate within a window."""
    d = int(days)
    if d <= 0:
        raise NewsArticleRejected(f"BAD_WINDOW_DAYS:{days!r}")
    return _one(cur, f"""
        UPDATE news_articles SET is_duplicate = TRUE
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY LEFT(LOWER(TRIM(title)), 60)
                    ORDER BY relevance_score DESC NULLS LAST, created_at ASC
                ) as rn
                FROM news_articles WHERE created_at > NOW() - make_interval(days => %s)
            ) sq WHERE rn > 1
        ) AND NOT COALESCE(is_duplicate, FALSE)
    """, (d,))


def set_region(cur, article_id: Any, region: Any, geo_keywords: Any) -> int:
    """inference_layers / region_tag_news: keyword region classification."""
    return _one(cur, f"UPDATE news_articles SET region=%s, geo_keywords=%s, region_tagged_at=now() WHERE id=%s",
                (region, _as_json(geo_keywords), article_id))


def set_deep_curation(cur, article_id: Any, verdict: Any, weight: Any, rag_status: str | None = None) -> int:
    """run_deep_overnight_llm_queue: deep-curation verdict, optionally promoting rag_status."""
    if rag_status is not None and rag_status not in RAG_STATUSES:
        raise NewsArticleRejected(f"BAD_RAG_STATUS:{rag_status!r}")
    sql = f"UPDATE news_articles SET deep_curation_verdict=%s, deep_curation_at=NOW(), deep_curation_weight=%s"
    params: list[Any] = [verdict, weight]
    if rag_status:
        sql += ", rag_status=%s"
        params.append(rag_status)
    sql += " WHERE id=%s"
    params.append(article_id)
    return _one(cur, sql, params)


__all__ = [
    "AUTHORITY", "SCHEMA", "TABLE", "COLUMNS", "IDENTITY_COLUMNS", "SQL_NOW", "SqlNow",
    "WriteReceipt", "NewsArticleRejected",
    "provider_token", "source_is_retired", "validate_article", "identity_columns_present",
    "resolve_identity", "is_duplicate", "write_news_articles",
    "set_sentiment", "set_rag_status", "approve_pending_by_relevance", "set_strategy_classification",
    "reassign_strategy_type", "archive_article", "flag_title_duplicates", "set_region", "set_deep_curation",
]
