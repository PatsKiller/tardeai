# Phase 9 — `watch_directives`: one write module

Branch `feat/sot-p9-watch-directives` · 2026-09-13 · One Source of Truth (AGENTS.md §7A rule 1)

## Result

| | before | after |
|---|---|---|
| files that INSERT/UPDATE `watch_directives` (gate regex, `check_data_source_authority.count_writers`) | **18** (baseline ceiling) | **1** — `scripts/lib/writers/watch_directives_writer.py` |
| creation-time dedup rules | 5 different ones (two producers had none for tickers) | 1 — `find_existing_directive` |
| INSERT column lists | 7 variants | 1 |
| status vocabulary | implicit, per file | `STATUSES` in the module |

Gate: `python3 scripts/check_data_source_authority.py --json` → `watch_directives: 1`, `findings: []`.

## Where the SQL lives

`scripts/lib/writers/watch_directives_writer.py` (new). `scripts/lib/two_way_curation.py` — the
registry's `writer_target` — re-exports it (`write_watch_directives`, `find_existing_directive`,
`update_watch_directive`, `touch_watch_directive_serviced`, `set_watch_directive_status`,
`WD_NOW`, `WatchDirectiveWriteReceipt`). Why a separate file rather than inline in
two_way_curation: two_way_curation.py is CRLF and 1,120 lines of curation logic; the write
module needs to be importable from producers that never touch the curation loop
(hygiene, dedup, api_v2 row actions) without dragging that in, and the gate counts by SQL
text, so the SQL must physically live in exactly one file.

**Proposal for the operator (registry, not edited here):** set `domains[watch_directives].writer`
to `scripts/lib/writers/watch_directives_writer.py`, `writer_status` → `CONSOLIDATED`, and lower
`data_source_authority_baseline.json` `writers.watch_directives` 18 → 1. The `WRITER_MISSING`
check only requires the path to exist.

### Public functions

| function | row kind / legacy shapes it replaces |
|---|---|
| `write_watch_directives(target, rows, *, source, run_id=None, on_duplicate="reuse"\|"reuse_exact"\|"insert", resolve_identity=True) -> WriteReceipt` | every INSERT (10 legacy variants) |
| `find_existing_directive(target, kind, label, spec, *, include_family=True)` | the ONE dedup rule (see below) |
| `update_watch_directive(target, id_or_ids, *, source, rationale_append=None, **cols)` | every `UPDATE … SET … updated_at=NOW() WHERE id=%s` / `id = ANY(%s)`; columns allowlisted in `UPDATE_COLUMNS`; timestamps take `NOW` or `None` |
| `touch_watch_directive_serviced(target, id, *, source)` | `last_serviced_at=NOW()` (5 files) |
| `set_watch_directive_status(target, ids, status, *, source, **extra)` | pause/resume/archive/expired transitions (6 files) |
| `expire_watch_directives_past_ttl(target, *, source)` | hygiene TTL fold (set-based predicate, RETURNING id,label) |
| `touch_quiet_watch_directives_serviced(target, *, source, stale_hours=24)` | drain `--touch-quiet` (set-based NOT EXISTS predicate) |
| `resolve_directive_subject(kind, spec)` | identity (below) |

`target` is a cursor, a connection, or an executor callable shaped like `db_adapter._execute(sql, params, fetch)`;
producers used both styles and a module that forced one would have made half of them open a second
connection inside another's transaction.

`WriteReceipt`: `table, source, operation, run_id, rows_in, rows_written, rows_rejected[{row, reason}],
ids, reused[{id, label, match, …identity}], details` + `.directive_id`, `.ok`. Rejections are logged at
WARNING on `tradeai.writers.watch_directives` and returned; nothing is dropped silently.

### Rails (all pre-existing behaviour made explicit)

`kind ∈ {ticker, sector, trend}` · label non-empty · `spec` is a JSON object (str is parsed) ·
ticker spec has a plausible `symbol` (`^[A-Z0-9][A-Z0-9.\-/^=]{0,14}$` after upper/strip) ·
`status ∈ {active, paused, archived, needs_review, expired, proposed}` · priority non-empty ≤ 32 ·
`ttl_days` int ≥ 0 or NULL · `created_by` non-empty (defaults to `source`).

## The ONE dedup rule (`find_existing_directive`)

Legacy rules found (each in its own file):

| file | rule |
|---|---|
| two_way_curation (drain + ensure_directive) | exact `(kind, label)`, **any status** |
| claude_challenger_curator | exact `(trend, label)` any status → refresh + `status='active'` (resurrects archived rows); else `family_gate` |
| hermes_think_tank `_find_existing` | normalised label among active same-kind; trend → canonical family (first match, not most-hits); sector → `spec.finviz_sector/gics_sector` |
| sector_research_universe `_find_directive` | sector → spec sector name; trend → `spec.finviz_industry`; **no label match at all** |
| seed_quantum_chips / api_v2 create | ticker → `UPPER(spec->>'symbol')` among active |
| api_v2 rotation research-gaps | `(created_by='rotation_advisor', label, active)` |
| strategy_planner (ticker), telegram (all kinds) | **none** — duplicates on every re-add (contradicts operator decision 2026-06-21 "don't stack a second active ticker directive") |
| lib/watch_directive_gate `family_gate` | canonical family among active trends, survivor = most hits |

Consolidated precedence (first hit wins):

1. **sector/trend**: exact `(kind, label)` among **non-archived** rows → `match="label"`.
   Not for ticker: a ticker's label is a *list name* several symbols legitimately share
   ("White House Quantum Computing" is on GFS, IBM, QBTS, RGTI); the symbol is the identity (rule c).
2. same subject among **active** same-kind rows: ticker → `UPPER(spec.symbol)`; sector →
   `spec.finviz_sector`/`gics_sector`; trend → `spec.finviz_industry`.
3. **sector/trend**: normalised label equal among active same-kind rows.
4. **trend**, `include_family=True`: same canonical family; survivor = most hits, then oldest
   (the Watch Desk v2 B1 rule). `watch_directive_gate.family_gate` now delegates to this and adds only
   the active-trend cap.

### Divergences from legacy (deliberate, all in the direction of less clutter)

- **Archived rows are never reused or resurrected.** two_way_curation would attach new hits to an
  archived directive; claude_challenger flipped archived dups back to `active` every run — which is the
  "regrowth" the 07-01 cleanup and Sunday hygiene fight. Exact match now stops at `status <> 'archived'`.
- **Tickers dedup by symbol everywhere** (strategy_planner, telegram, two_way drain, rotation gaps now
  reuse an existing active ticker directive instead of stacking). Telegram tells the operator
  "(existing directive #N reused — no duplicate created)"; rotation `_mkdir` returns None ("already covered").
- **Sector/trend rows gain label dedup where they had none** (sector_research_universe, api_v2 sector create).
- `claude_challenger`'s legacy INSERT set `created_at, updated_at = NOW()` explicitly; those are the
  column DEFAULTs, so the module's 10-column INSERT is value-identical.
- All legacy INSERTs that omitted `status/priority/ttl_days/trade_ai_enabled/hermes_enabled` relied on
  DEFAULTs (`active`, `normal`, NULL, true, true); the module writes those values explicitly — same row.
- `api_v2._watch_directive_create` returns **400 with the rejection reasons** when the module rejects
  the row, instead of the legacy silent `directive_id: null` 200.
- `strategy_planner` / `seed_quantum_chips` raise on a rejected row (planner's existing per-directive
  try/except turns that into the legacy "rollback and skip").
- `drain_hermes_directive_staging --touch-quiet`: `interval '24 hours'` literal is now the parameter
  `(%s || ' hours')::interval` with `'24'` — same predicate.
- Legacy `UPDATE … SET status='paused'` literals are now `status=%s` parameters — same statement.
- `hermes_think_tank._find_existing` and `sector_research_universe._find_directive` are kept as thin
  wrappers over the module (their callers depend on the `int | None` shape).

## Identity (rules a–e)

- **(e) The table has NO identity column.** `migrations/2026-06-08_watch_directives.sql` defines
  `watch_directives` without `subject_guid`/`security_guid`; no later migration adds one; no legacy
  writer resolved one (grep for `subject_guid|security_guid|resolve_guid` across the 18 files: 0). The
  module adds none.
- **(a)/(b)** The module still resolves a ticker directive's subject through the existing resolvers only —
  `resolve_directive_subject`: registry-first `identity_registry.lookup_symbol(load_cached(), sym)` →
  `identity_registry.resolve_guid` (follows supersede chains), then
  `security_identity.resolve_identity_spine({symbol, company, cik})` → `identity_registry.subject_guid_of`
  (security > issuer > ticker alias — the same alias GUID `memory_fact.subject_from_security` defines).
  The GUID travels on the receipt (`details[i].subject_guid`, `identity_source ∈ {registry, spine}`),
  is never minted locally, and an unreadable registry is recorded as `identity_lookup_failed`, never as
  a made-up GUID. Nothing is written to the table for it.
- **(c)** A symbol-only row round-trips to the GUID the registry holds when the watch item is minted
  (test `test_symbol_only_row_resolves_to_the_registry_guid_when_minted`), to the ticker-alias GUID when
  it is not, and a `company`/`cik` row to the issuer-derived security GUID. "Never NULL where it resolved
  before" is trivially met: nothing resolved before.
- **(d)** `tests/test_watch_directives_writer_phase9.py` pins `TRADEAI_IDENTITY_REGISTRY` to a temp file
  (autouse) and clears `identity_registry._CACHE`.

### Proposed migrations (operator grant required — not applied)

1. `ALTER TABLE watch_directives ADD COLUMN subject_guid UUID NULL;` — populated by the module from the
   receipt's `subject_guid` for ticker rows (registry-first). Lets `watch_directive_hits` /
   `watchlist_items` join on identity instead of the ticker alias.
2. `ALTER TABLE watch_directives ADD COLUMN source TEXT, ADD COLUMN written_by TEXT, ADD COLUMN written_at TIMESTAMPTZ DEFAULT now();`
   — provenance columns the module already carries on the receipt (`source`, `run_id`). Today the
   only provenance column is `created_by`.
3. **Status CHECK discrepancy.** The migration's CHECK allows `('active','paused','archived','needs_review')`,
   yet `watch_directive_hygiene` writes `'expired'` (since Watch Desk v4 C2) and the family gate
   `'proposed'` (Watch Desk v2 B1), and api_v2 resumes from both. Either the CHECK was dropped live
   (no migration in the repo records it) or those writes have been failing. Verify with
   `\d+ watch_directives` on the live DB; if the CHECK is still there, the fix is
   `ALTER TABLE watch_directives DROP CONSTRAINT watch_directives_status_check; ALTER TABLE … ADD CHECK (status IN ('active','paused','archived','needs_review','expired','proposed'));`.
   The module accepts the six-value vocabulary the producers actually use.

## Files migrated (18 → all call the module)

`scripts/api_v2.py` (4 hunks only: row actions pause/resume/archive/merge-archive, create INSERT,
service-at-creation touch, rotation research-gaps `_mkdir`; authority/transition checks unchanged, in place) ·
`scripts/claude_challenger_curator.py` · `scripts/directive_keyword_enhancer.py` ·
`scripts/directive_promotion.py` · `scripts/hermes_think_tank.py` · `scripts/lib/two_way_curation.py` (CRLF preserved via
`safe_text_edit`) · `scripts/lib/watch_directive_gate.py` · `scripts/ops/drain_hermes_directive_staging.py` ·
`scripts/reclassify_knowledge_directives.py` · `scripts/research_critique_pipeline.py` (3 hunks) ·
`scripts/sector_research_universe.py` · `scripts/seed_quantum_chips_watchlist.py` · `scripts/strategy_planner.py` ·
`scripts/telegram_command_handler.py` (operator command path; stays the caller) · `scripts/watch_directive_dedup.py` ·
`scripts/watch_directive_hygiene.py` · `scripts/watch_directives_service.py` (4 hunks) ·
`scripts/lib/hermes_discovery/promotion.py` — **docstring only**: the gate's case-insensitive regex matched
"never a direct INSERT into watch_directives" in prose; the module never wrote the table (it routes via
`api_v2._watch_directive_create`, which now calls the write module). Reworded so the count is honest.

Not migrated: nothing. No writer sits in a broker/order file (grep `place_order|submit_order|cancel_order|2FA`
across the 18: only api_v2 matches, and only its four watch_directives hunks were touched).

## Tests

`tests/test_watch_directives_writer_phase9.py` — 36 tests, offline (recording cursor / executor):
negative control (baseline 18 > 1, `count_writers` = 1, only the module carries the SQL), rails
(7 rejection reasons, bad status, unknown column, executor-None), identity (registry-first, supersede chain,
alias fallback, issuer-derived, sector/trend None, no identity column), dedup rule (ticker-by-symbol with
shared label, family survivor by hits, sector name + normalised label, exact first), and one golden test
per legacy writer driving the real migrated function where its surface allows (two_way drain + ensure,
strategy_planner.approve, claude_challenger.infuse_trends, hermes_think_tank.upsert_themes,
sector_research_universe._find_directive, seed_quantum_chips._upsert_directive, telegram._handle_watch,
api_v2 create/update, directive_keyword_enhancer.backfill, directive_promotion touch,
watch_directive_hygiene._expire_ttl, watch_directive_dedup.apply_plan, watch_directives_service.pause_cold_trends,
watch_directive_gate family_gate/attach_alias) and call-site-row goldens for the three remaining hunks
(research_critique_pipeline shapes, api_v2 rotation gaps row, reclassify archive, drain quiet-touch).

Pre-existing suites for every touched module (17 files, 224 tests) stay green — the fakes in
`tests/test_two_way_curation.py` and `tests/test_drain_contention.py` key on the prefix
`SELECT id FROM watch_directives … (kind, label)` and on INSERT params starting `(kind, label, …)` with
`RETURNING id`; the module keeps both contracts on purpose.
