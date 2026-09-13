# Phase 9 — one write module for `hermes_research_intelligence`

Branch `feat/sot-p9-hermes-research` · 2026-09-13 · domain `research_thesis` · AUTHORITY READ_ONLY_ADVISORY.

## The defect, measured

`python3 scripts/check_data_source_authority.py --json` on `origin/main` (6644600c7):
`"hermes_research_intelligence": 32` writer files — 17 INSERT paths and 19 UPDATE paths across 32
files (one, `scripts/backfill_hermes_trade_links.py`, only matched the gate's case-insensitive regex:
`update hermes_research_intelligence` in lower case). Each carried its own column list, defaults and
coercions: TEXT[] as a `'{"a","b"}'` literal in three files, `ARRAY[...]` in two, a Python list in
four; `freshness_date` as `CURRENT_DATE`, `now()::date`, `NOW()` (a timestamp into a DATE column) or an
ISO string; `evidence_json` with and without `::jsonb`. `hermes_backlog_drain.py` used a fourth,
dynamic path (`hermes_staging_ingest.build_insert`) that the gate cannot see at all.

Identity: **0 of the 32 legacy writers set `subject_guid`** (or `issuer_guid`/`identity_status`).
Verified with `git grep -c subject_guid origin/main -- <the 32 files>` → no match in any file. Every
row was inserted with NULL identity and depended on `scripts/backfill_research_identity.py`
running later. The registry declares `subject_guid` a `required_field` for this domain.

## What shipped

**Write module:** `scripts/lib/writers/hermes_research_writer.py` (new; `scripts/lib/writers/` is a new
package). The registry's `writer_target`, `scripts/lib/hermes_librarian/librarian.py`, re-exports every
public function and its own backlog INSERT now calls the module — so `from
lib.hermes_librarian.librarian import write_research_rows` is the documented entry. **Why a leaf module
rather than SQL inside librarian.py:** librarian.py imports taxonomy/graph/freshness/retention/
rag_health; eight scheduled producers (catalyst engine every 30 min, stop_health_check every 10 min,
grok_stop_review, protection advisor, youtube discovery, topic bridge, SIEM backlog, gain guardian)
would otherwise pull the whole librarian package to stage one row. The leaf has no librarian
dependency and no import-time side effects.

Public surface:

| function | owns |
|---|---|
| `write_research_rows(target, rows, *, producer, source="hermes", run_id, identity_columns, drop_unknown, registry)` | INSERT … RETURNING id; column allowlist; coercion; rails; identity; defaults `created_at=NOW()`, `freshness_date=CURRENT_DATE`, `status='staged'` |
| `update_research_rows(target, *, where, where_params, set_fields, set_raw, from_clause, alias, touch_updated_at, …)` | the one UPDATE emitter; WHERE mandatory; SET columns allowlisted; status/thesis_type/confidence rails |
| `set_status`, `archive_rows_where`, `archive_with_tags_union`, `transition_if_status`, `fill_if_null`, `record_remediation_outcome`, `set_fields_by_id`, `patch_evidence_json_path`, `blend_quality_score`, `stamp_learning_cycle`, `link_from_join` | one named shape per legacy UPDATE writer — each reproduces that writer's exact semantics (CASE-guarded transitions, idempotent tag append, COALESCE-keep, jsonb_set, join updates with the legacy alias) |
| `rollback_sql_for_status(id, status)` | the reversal statement the coordinator files in `hermes_promotion_audit.rollback_sql` |
| `resolve_subject_identity(row)` · `identity_columns_available(target)` | identity (below) |
| `WriteReceipt` (`HermesResearchWriteReceipt@v1`) | rows_in / rows_written / rows_rejected[{index, reason, row}] / ids / identity counters / dropped_columns / table / source / producer / run_id / written_by |

`target` is a DB-API cursor **or** a `fn(sql, params, fetch=)` executor (the `db_adapter._execute`
shape four producers pass). Commit stays with the caller, as before. Rejected rows are returned on
the receipt **and** logged at WARNING; they are never counted as written (producers now add
`rc.rows_written`, not `1`).

**Rails** (mirroring the DDL's CHECKs, so a bad value is a receipt entry instead of a constraint
error some writer swallows): `confidence_score` in [0, 1]; `thesis_type` ∈ {bullish, bearish,
neutral, mixed}; `status` ∈ {staged, reviewed, promoted, rejected, archived}; `research_type`,
`topic`, `summary` non-empty (NOT NULL); JSONB strings must parse; numeric columns must be numeric;
unknown columns reject unless `drop_unknown=True` (the backlog drain, mirroring `build_insert`'s
KNOWN_COLUMNS filter). UPDATE with an empty WHERE raises — a whole-table UPDATE never reaches the DB.

**Migrated (32 → 1):**
api_v2.py (operator-knowledge hunk only; 86 broker-string hits elsewhere untouched) ·
backfill_hermes_strategy_tags · backfill_hermes_trade_links · backfill_trade_instances ·
catalyst_momentum_engine · grok_stop_review · hermes_autonomous_librarian_backlog_loop ·
hermes_backlog_drain (INSERT via build_insert + UPDATE) · hermes_coordinator (UPDATE + rollback string) ·
hermes_health_inspector (2 INSERT + 1 UPDATE) · hermes_outcome_grader · hermes_outcome_learning ·
hermes_tag_engine (2) · hermes_topic_monitor_bridge · hermes_youtube_discovery ·
holding_protection_advisor · ingest_reground_retirement_gaps · lib/gain_guardian_publish ·
lib/health_learning_engine (2 INSERT + 1 UPDATE) · lib/hermes_librarian/{freshness, librarian,
retention, taxonomy} · options_research_bridge · repair_health_threshold_tuning_noise ·
repair_hermes_backlog_taxonomy · research_critique_pipeline (2) · research_intelligence_narrative_enrich ·
research_intelligence_refresh · siem_to_hermes_backlog · stop_health_check · topic_research_synthesizer.

Nothing left un-migrated. No file in the list contains `place_order`/`submit_order`/`cancel_order`;
api_v2.py does, and only its one hunk was edited.

## Identity — rules (a)–(e)

The table **has** identity columns (`subject_guid UUID, issuer_guid UUID, identity_status TEXT,
identity_tagged_at TIMESTAMPTZ`, plus `gics_sector`) from `sql/research_identity_tags.sql`. Evidence
they exist in production without querying it: the live broker projection
`scripts/lib/data_broker/subject_research.py` SELECTs `subject_guid, issuer_guid, gics_sector` and
filters `WHERE subject_guid=%s::uuid`; `backfill_research_identity.py` has been tagging them
(docstring: 16,594 of 16,746 symbol rows resolvable). Because I could not run the DDL probe against
the live DB, the module **probes `information_schema.columns` once per process** and omits the
identity columns when absent — so a table without the migration still accepts rows. Tests pin both
branches.

- **(a)** `subject_guid`/`issuer_guid`/`identity_status`/`identity_tagged_at` are populated only through
  `resolve_subject_identity`, which calls `scripts.lib.identity_registry` (`load_cached`,
  `lookup_symbol`, `subject_guid_of`, `resolve_guid`) and `scripts.lib.security_identity.
  resolve_identity_spine`. No UUID is computed in the module. NULL is written only where the legacy
  writers wrote NULL (all of them) *and* the resolver has nothing — i.e. never NULL where a
  symbol/cik/company resolves.
- **(b)** Registry-first: an explicit `subject_guid` on the row is kept but upgraded along the
  supersede chain (`resolve_guid`); else `symbol → lookup_symbol → subject_guid_of` (exactly what
  `backfill_research_identity.py` / `lib.research_identity.resolve` writes, so write-time and
  backfill GUIDs are identical); else `cik`/`company`/`identifiers` hints → `resolve_identity_spine`
  → issuer-derived security GUID (CANDIDATE) or identifier-derived (CONFIRMED). Hints are consumed,
  never written. **Difference from legacy:** there was no legacy identity path to differ from — the
  legacy difference is 32 × NULL versus the backfill's later `RI.resolve`; the module uses the
  backfill's resolver so there is one answer.
- **(c)** Symbol-only row → the registry's GUID (test `test_symbol_only_row_round_trips_to_the_
  registry_guid` asserts equality with `resolve_guid` and with `research_identity.resolve`). A bare
  **unregistered** ticker gets NULL, never a ticker-derived GUID: minting the alias GUID is the
  registry's job (`identity_registry.register`, run by `mint_identity_registry.py`), not a producer's,
  and the producer must never write the registry file (host `data/`). NULL is what the backfill
  leaves, so `backfill_research_identity.py` (`WHERE subject_guid IS NULL`) still picks the row up.
- **(d)** `tests/test_sot_p9_hermes_research_writer.py` pins `TRADEAI_IDENTITY_REGISTRY` to a temp
  file in an autouse fixture and clears `identity_registry._CACHE`.
- **(e)** n/a — the table has identity columns; none were added.

`CASH`/`PORTFOLIO`/`MMKT` and symbol-less topic rows are `NOT_APPLICABLE` (no lookup), matching
`lib.cio_subject_guid.NON_ENTITY_SYMBOLS`.

## Provenance

Columns the table actually has and the module carries: `source` (origin; DDL CHECK `= 'hermes'`),
`hermes_agent_name` (producer), `model_used`, `prompt_hash`, `context_type_used`, `lane_used`,
`trigger_source`, `trigger_id`, `budget_tier`, `budget_decision`, `research_expires_at`,
`downstream_outcome`. `created_at`/`updated_at` are the write times. `producer=` fills
`hermes_agent_name` only when the row lacks it; `source=` fills `source` only when the row lacks it.

There is **no** `run_id`, `written_by` or `written_at` column. `run_id` rides on the receipt only
(the backlog drain passes its `run_id`; it also keeps it in `evidence_json` as before).

## Deviations from legacy, each deliberate

1. **gain_guardian_publish** omitted `hermes_agent_name` and `model_used` (both NOT NULL in the DDL) and
   wrote `source='gain_guardian'` against a DDL `CHECK (source = 'hermes')`. The module fills
   `hermes_agent_name='gain_guardian'` from `producer`; `source` and the missing `model_used` are left
   exactly as legacy. If the CHECK and NOT NULLs still stand in production this path fails at the DB
   as it always would have (it is only reachable after the operator's `--promote`; memory says Gain
   Guardian is still SHADOW). Operator decision: relax the CHECK to admit `gain_guardian`, or have the
   publisher write `source='hermes'` + `hermes_agent_name='gain_guardian'`.
2. **Rejected rows do not raise.** A row off its rail (e.g. an LLM `confidence` > 1) used to surface as
   a psycopg2 CHECK error — in `holding_protection_advisor` that aborted the whole run; in
   `grok_stop_review`/`stop_health_check` it was swallowed by a bare `except`. Now it is a receipt entry
   + WARNING log and the batch continues. Producers that need the id (`topic_monitor_bridge`,
   `siem_to_hermes_backlog`, `api_v2`, health inspector, backlog loop/drain) check `rc.ids` and take
   their existing error path.
3. **Param order** follows the module's canonical `COLUMNS` order, not each legacy writer's. Values
   and columns are identical (golden tests render both to a column→value map and compare).
4. `freshness_date NOW()` (a timestamptz cast into DATE, gain_guardian) → module default `CURRENT_DATE`.
   Same date.
5. `hermes_staging_ingest.build_insert` stamped `created_at` with a Python UTC timestamp; the module
   uses `NOW()`.

## Left as-is, on purpose

- `DELETE FROM hermes_research_intelligence` in `lib/hermes_librarian/retention.py` (purge archived >
  180 d) and `research_critique_pipeline.retention_purge`. The gate does not count DELETE and the brief
  scoped INSERT/UPDATE. AGENTS.md §0 rule 6 says never delete — these are pre-existing and I did not
  widen them; **proposal:** route them through an `archive_purge(...)` in this module that moves rows to
  an archive table instead, once the operator grants the migration.
- `hermes_staging_ingest.build_insert` (generic `hermes_*` CLI ingest) still builds INSERTs for any table
  name it is handed. Its only `hermes_research_intelligence` caller (the drain) now uses the module.
  **Proposal:** in `build_insert`, refuse `hermes_research_intelligence` with a pointer to the module.

## Proposed migrations (not applied — operator grant required)

```sql
-- provenance the brief asks for, which the table lacks
ALTER TABLE hermes_research_intelligence
  ADD COLUMN IF NOT EXISTS run_id      TEXT,
  ADD COLUMN IF NOT EXISTS written_by  TEXT,   -- 'scripts/lib/writers/hermes_research_writer.py'
  ADD COLUMN IF NOT EXISTS written_at  TIMESTAMPTZ;
-- source CHECK vs gain_guardian (see deviation 1)
```
`ADD COLUMN` takes ACCESS EXCLUSIVE (sql/research_identity_tags.sql documents the 2026-07-02 lock
incident) — run once, off-peak, `lock_timeout='5s'`. When granted, the module's `WriteReceipt` fields
map 1:1 onto these columns.

## Registry proposal (operator integrates; I did not edit the registry or baseline)

`config/data_source_authority.json`, domain `research_thesis`:
```json
"writer": "scripts/lib/writers/hermes_research_writer.py",
"writer_status": "CONSOLIDATED",
"writer_target": null,
"_writer_note": "Consolidated 2026-09-13 (Phase 9): 32 → 1. librarian.py re-exports the module."
```
`config/data_source_authority_baseline.json`: `"hermes_research_intelligence": 1` (regenerate with
`--write-baseline` after merge; the gate reads 1 today).

Note `tests/test_data_source_authority_20260913.py::test_unconsolidated_stores_have_a_shrinking_ceiling`
asserts baseline ≥ 2 **only while** `writer_status == "UNCONSOLIDATED"`, so flipping the status and the
baseline together keeps it green.

## Gates (verbatim, this branch)

```
$ python3 scripts/check_data_source_authority.py --json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['writers'],d['findings'])"
{'market_quotes': 3, 'symbol_profiles': 8, 'yahoo_analyst_targets_history': 1, 'news_articles': 16, 'ticker_prices': 4, 'sector_rs_daily': 1, 'market_regime_snapshots': 1, 'options_iv_history': 1, 'hermes_research_intelligence': 1, 'watch_directives': 18, 'watch_candidate_events': 1, 'private_company_proxies': 1, 'ticker_dividend_data': 1, 'fred_economic_series': 2, 'fundamental_data': 1, 'watchlist_agent_results': 1, 'agent_debate_log': 2, 'ai_reports': 4} []
```
(before, on origin/main: `'hermes_research_intelligence': 32`)

Test files for the integrator: `tests/test_sot_p9_hermes_research_writer.py` (47 tests: 15 INSERT
goldens + build_insert golden, 10 UPDATE goldens, 8 rail cases + 2 refusal tests, 6 identity tests,
3 producer-through-module tests, 2 reduction controls).

Pre-existing failures in adjacent suites, none touching a migrated hunk (verified against origin/main):
`test_stop_fixed_trailing_validation` (16 — needs `apps/command-center-v3/node_modules/.bin/tsc`, absent in
this worktree), `test_stop_policy` (4 — family tiers from live data + a missing
`stop_policy_migration_report` artifact), `test_stop_alert_pl` (2 — asserts a `pl_if_fired` string that
is absent from api_v2.py on origin/main too), `test_llm_consumption` (1 — lane-registry default_mode).
