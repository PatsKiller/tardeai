# Phase 9 — `news_articles`: one write module

**Date:** 2026-09-13 · **Branch:** `feat/sot-p9-news-articles` · **Domain:** `catalyst_news`
**Write module:** `scripts/lib/writers/news_articles_writer.py`, re-exported by
`scripts/news_ingestion.py` (the registry's `writer_target`).
**Writer count (gate regex):** 16 → 1.

## Why a lib module, re-exported

`scripts/news_ingestion.py` is a scheduled producer: it reads `.env`, opens its own
connection, fetches RSS. `scripts/api_v2.py`, `telegram_command_handler.py` and the
inference layer must call the writer without importing a producer. So the SQL lives
in `scripts/lib/writers/news_articles_writer.py` and `news_ingestion.py` imports and
re-exports every public name — a producer that follows the registry
(`writer_target: scripts/news_ingestion.py`) and one that imports the lib module get
the same object (`tests/…::test_news_ingestion_is_the_registry_target_and_re_exports_the_module`).

The module spells the table name out in its SQL (`INSERT INTO news_articles (…`,
`UPDATE news_articles SET …`) — the gate counts *source text*, and an interpolated
`{TABLE}` would have made the writer invisible (count 0, observed during the work).

## Public functions

| function | legacy writer(s) it replaces |
|---|---|
| `write_news_articles(cur, rows, *, source, run_id, subject_kind, identity_columns, dedupe) -> WriteReceipt` | news_ingestion, symbol_enrichment, premarket_watcher, finviz_proactive_research, hermes_news_bridge, telegram_command_handler, external_market_data_ingest, topic_ingestion |
| `is_duplicate(cur, symbol, source_url=None, title=None)` | the pre-INSERT `SELECT` every producer carried |
| `set_sentiment(cur, id, sentiment, score)` | sentiment_processor |
| `set_rag_status(cur, id, status, reason)` · `approve_pending_by_relevance(cur, *, source_prefix, min_relevance, reason)` | topic_curator (3 sites) |
| `set_strategy_classification(cur, id, strategy_type, retirement_relevance)` | _news_strategy_classifier (3 sites) |
| `reassign_strategy_type(cur, old, new)` | api_v2 `/api/v2/admin/backfill-news-strategy` |
| `archive_article(cur, id, reason)` · `flag_title_duplicates(cur, *, days)` | iris_taxonomy_agent (hygiene, 3g) |
| `set_region(cur, id, region, geo_keywords)` | inference_layers, region_tag_news |
| `set_deep_curation(cur, id, verdict, weight, rag_status=None)` | run_deep_overnight_llm_queue |
| `resolve_identity(symbol, *, cik, company, subject_kind, registry)` · `validate_article(row)` · `source_is_retired(source)` | new — identity and rails, previously nowhere |

`WriteReceipt` (`NewsArticlesWriteReceipt@v1`): `rows_in, rows_written, rows_duplicate,
rows_rejected, rejected[{index, reason, symbol, title, source}], ids, identity_resolved,
identity_unresolved, identity_lookup_failed, identity_columns_present, table, source,
written_by`. Rejected rows are returned and logged at WARNING.

## Dedupe — what the legacy writers did, and the ONE rule now

| writer | legacy rule | delta under the one rule |
|---|---|---|
| finviz_proactive_research | `source_url AND symbol` | **identical** (this is the rule kept) |
| news_ingestion (yahoo/benzinga) | `symbol AND title` | superset: url match also dedupes |
| news_ingestion (google-family sources) | `source_url` **globally** (any symbol) | now per symbol: a Google RSS item that surfaces for two tickers is stored for each (finviz semantics) |
| symbol_enrichment, premarket_watcher | `source_url` globally | per symbol (rows are per-symbol anyway; EDGAR/Yahoo URLs are per company) |
| topic_ingestion | `source_url` globally | per topic_id — a URL is stored once per topic that surfaced it |
| telegram_command_handler | `source_url` globally | identical in effect: all manual adds share `symbol='manual_add'` |
| hermes_news_bridge | `source='hermes' AND symbol AND title` | source qualifier dropped: a Hermes topic whose title equals an existing headline for the same symbol is now a duplicate |
| external_market_data_ingest (Alpha Vantage) | `ON CONFLICT DO NOTHING` — **a no-op**: the table has no unique index, so nothing was ever deduped | now deduped like everyone else |

**The rule:** duplicate ⇔ an existing row has the same `symbol` and (the same `source_url`
when the new row has one, or the same `title`). One `SELECT id … LIMIT 1` before each
insert. `ON CONFLICT DO NOTHING RETURNING id` is emitted on every insert so the moment a
unique index exists it becomes the enforced rule.

## Identity — rules (a)–(e)

The table **has** identity columns: `subject_guid`, `issuer_guid`, `identity_status`,
`identity_tagged_at` (`sql/research_identity_tags.sql`). **None of the eight legacy INSERT
writers populated them**; two after-the-fact backfills did, and they resolve differently:

| resolver | path | notes |
|---|---|---|
| `scripts/backfill_research_identity.py` → `lib.research_identity.resolve` | `identity_registry.lookup_symbol` (follows `resolve_guid` chains) → `subject_guid_of(entity)` = security > issuer > ticker alias; status default `UNRESOLVED`; unknown symbol → **NULL, untouched** | never downgrades an existing status |
| `scripts/backfill_subject_identity.py` → `lib.cio_subject_guid.lookup_identity_envelope` | `lookup_symbol` → `entity["subject_guid"]`; status default `CANDIDATE`; `CASH/PORTFOLIO/MMKT` → not applicable; **topic ids** (rows whose `symbol` is a `topic_monitor.topic_id`) → `topic_guid()` CONFIRMED; everything else examined → `UNRESOLVABLE` | distinguishes "registry unreadable" from "unknown" and refuses to write on a read failure |

Both agree on the GUID for any registered symbol (`entity["subject_guid"]` is set from
`subject_guid_of(spine)` at registration). The write module takes the **registry-first
path** (rule b): `identity_registry.load_cached()` → `lookup_symbol` (which follows
`resolve_guid` supersede chains) → `subject_guid_of(entity, sym)`; `NON_ENTITY_SYMBOLS`
from `cio_subject_guid` are skipped; a registry read failure is counted in the receipt
(`identity_lookup_failed`) and writes NULL rather than a wrong answer.

- **(a)** identity columns populated only through the existing resolvers; never NULL
  where the resolver has a GUID (legacy inserts always wrote NULL — strict improvement).
- **(b)** registry-first as above; when the row carries `cik`/`company` and the registry
  does not know the symbol, `security_identity.resolve_identity_spine` → deterministic
  UUIDv5 identical to what `identity_registry.register` would mint (test pins equality).
  The write module never calls `register()` — the registry is host data.
- **(c)** ticker is an alias: a symbol-only row resolves to
  `subject_guid_of(lookup_symbol(...))`, the same GUID `research_identity.resolve` gives
  it today (test pins equality). Symbol text is stored as given — topic ids are
  lower-case and the backfill joins them to `topic_monitor.topic_id`.
- **(d)** tests pin `TRADEAI_IDENTITY_REGISTRY` to a temp file (autouse) and mint only
  there.
- **(e)** not applicable — the table has identity columns. The module probes
  `information_schema.columns` once per process and writes the identity columns only
  when all four exist (the migration is operator-applied; a writer that assumed it would
  fail every insert where it is not).
- Topic rows: `topic_ingestion` passes `subject_kind="topic"` and the row takes
  `backfill_subject_identity.topic_guid(topic_id)`, `CONFIRMED` — exactly what that
  backfill stamps later. Unknown securities stay NULL/unexamined so both backfills still
  see them.

## Provenance and rails

- `source` labels preserved verbatim; `source_is_retired()` refuses a row whose label —
  or the provider after a `search:` / `topic_` / `av:` / `google_news:` prefix — is
  `retired` in `config/data_source_authority.json` (`finnhub`, `newsapi`, `polygon`,
  `fmp`), via `scripts/lib/retired_providers.is_retired`.
- Rails: non-empty `title`/`source`; `relevance_score` finite in `[0, 100]`;
  `sentiment_score` finite in `[-1, 1]`; `published_at` datetime/date/str/`SQL_NOW`/None.
- **Finding — two scales in one column.** `relevance_score` receives `0–1` from
  `content_scoring` (news_ingestion, finviz, hermes, telegram, topic) and `0–100` from
  symbol_enrichment/premarket (`quality` ints 65–88) and Alpha Vantage
  (`round(relevance*100)`). The rail admits both (`[0,100]`) so no legacy row is
  rejected; values are **not** rescaled (row semantics preserved). This is the analyst-
  rating defect's shape and should be resolved by the operator — see proposals.
- `written_by` / `written_at` columns do not exist; the receipt carries `written_by`.
  Not added (no migration without a grant).

## Coercions kept vs. unified

| item | legacy | module |
|---|---|---|
| title length | 500 (most), 300 (symbol_enrichment, premarket), 200 (AV) | 500 in the module; those callers still pre-truncate to 300/200, so stored values are unchanged |
| summary / source_url | 1000 / 500 | same |
| `published_at = NOW()` (symbol_enrichment, premarket, telegram) | SQL `NOW()` | `SQL_NOW` marker renders `NOW()` — transaction time, unchanged |
| hermes `created_at = now()` | explicit | omitted — column `DEFAULT NOW()` is identical |
| AV `strategy_tags %s::jsonb` cast | cast | no cast (as the other six writers) — Postgres casts the text parameter |
| column order | per writer | canonical `COLUMNS` order; only the keys a row carries are emitted, so column defaults still apply where a producer said nothing |
| JSON fields | callers `json.dumps` | accepted as str or list/dict (serialised once, here) |

## Migrated files (16)

`scripts/news_ingestion.py`, `symbol_enrichment.py`, `premarket_watcher.py`,
`finviz_proactive_research.py`, `hermes_news_bridge.py`, `telegram_command_handler.py`,
`external_market_data_ingest.py`, `topic_ingestion.py`, `sentiment_processor.py`,
`topic_curator.py`, `_news_strategy_classifier.py`, `iris_taxonomy_agent.py`,
`api_v2.py` (one hunk; the file carries broker markers — nothing else touched),
`inference_layers.py`, `run_deep_overnight_llm_queue.py`, `region_tag_news.py`.

Behavioural notes per caller: news_ingestion scores before the dedupe SELECT now (was
after; pure-CPU, negligible); finviz/topic/telegram keep an `is_duplicate` pre-check so
a duplicate costs no scoring; hermes/telegram/AV count writes from the receipt instead of
assuming success; api_v2 opens a cursor via `db_adapter._get_conn` under `USE_DB` and
swallows/prints errors exactly as `_db_write` did; inference_layers gained
`_tag_news_region()` (cursor + commit/rollback) in place of `_db_exec(sql)`.

## Writers the gate cannot see (not migrated — reported)

- `scripts/backfill_research_identity.py` and `scripts/backfill_subject_identity.py`
  write `UPDATE {table} SET subject_guid=…` with an **interpolated table name** across
  several tables, so the regex never counts them. They are operator-run (`--apply`)
  identity backfills; left untouched here because they are multi-table and the second is
  shared with `catalyst_events`, `hermes_external_research`, `research_insights`,
  `hermes_research_intelligence`. **Proposal:** route their `news_articles` branch through
  a `set_identity_tag(cur, id, tag, gics)` in this module when those stores get their own
  Phase 9 pass, so identity on this table has one write path too.

## Proposed migrations / registry edits (operator)

1. `config/data_source_authority.json` · `catalyst_news`: set
   `"writer": "scripts/lib/writers/news_articles_writer.py"` (the file the gate counts) or
   keep `scripts/news_ingestion.py` as the declared writer with the lib module named in a
   note; drop `writer_status: UNCONSOLIDATED` / `writer_target`.
2. `config/data_source_authority_baseline.json`: `writers.news_articles` 16 → 1
   (`--write-baseline` after merge).
3. `CREATE UNIQUE INDEX … ON news_articles (symbol, source_url) WHERE source_url <> ''`
   — makes the emitted `ON CONFLICT DO NOTHING` the enforced rule instead of a
   SELECT-then-INSERT race.
4. Decide the `relevance_score` scale (0–1 is `content_scoring`'s) and rescale the
   0–100 lanes at their call sites; then tighten the rail to `[0, 1]`.
5. Optional provenance columns `written_by TEXT`, `written_at TIMESTAMPTZ DEFAULT NOW()`.

## Tests

`tests/test_sot_p9_news_articles_writer.py` — 61 tests, pure (fake cursor, temp
registry): a golden test per legacy writer (8 INSERT, 8 UPDATE shapes), retired-provider
and off-rail rejection, label preservation, the one dedupe rule (per-symbol, url-or-title,
in-batch), identity rules (a)–(e) including a registry supersede chain and the
spine fallback, and the negative control (baseline 16 > 1; `count_writers` == 1; the one
file is the module; no legacy file matches the regex and every one imports the module).
