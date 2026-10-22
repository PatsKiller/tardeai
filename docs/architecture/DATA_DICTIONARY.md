# Data dictionary — one source for every fact

```
Status:      ACTIVE (granted rows bind; PROPOSED rows await the operator's grant, AGENTS.md §17)
as_of:       2026-10-22T16:00:00-04:00
Measured at: registry config/data_source_authority.json; counts are the rows' dated `measured` snapshots
```

**Rendered from `config/data_source_authority.json` (the AGENTS.md §7A registry) by `scripts/render_data_dictionary.py`. Do not edit by hand** — `--check` fails CI when this file and the registry disagree. Architecture: [`CIO_PROSPECT_DATA_FOUNDATION.md`](CIO_PROSPECT_DATA_FOUNDATION.md). Every granted domain: [`docs/SOURCE_OF_TRUTH.md`](../SOURCE_OF_TRUTH.md).

One source of data (operator 2026-10-22). Every fact names one domain; every domain one store and one writer; every page reads through a projection. Proposed rows live in proposed_domains[] until the operator grants them (AGENTS.md §17); scripts/check_data_source_authority.py warns on them and fails on granted ones. docs/architecture/DATA_DICTIONARY.md is rendered from here by scripts/render_data_dictionary.py.

## How to read this

- **One fact → one domain → one store → one writer → one projection.** A page, an API or an alert reads the store through its projection, never a copy.
- **APPROVED** rows bind: `scripts/check_data_source_authority.py` fails CI on a second writer (`DICTIONARY_SECOND_WRITER`) or a page/API reading a derived or retiring copy (`NON_AUTHORITATIVE_READ`) above the ceilings recorded at the grant. **PROPOSED** rows are the agent's proposal: the same checks print as warnings and never fail, because nobody has granted them.
- **Copies.** `derived` = an export or view of the store (generated, never written independently); `retiring` = to be archived with a tripwire, never deleted (AGENTS.md §0 rule 6); `history` = an append-only log the row's writer or projection reads; `excluded` = deliberately outside the dictionary (the broker execution subsystem, AGENTS.md §0 rule 2).
- **Divergent copies are never auto-merged** (AGENTS.md §0 rule 5): both paths, hashes and timestamps are reported to the operator.

## The key

- Per security: **`security_guid`** · per company: **`issuer_guid`** · GUID authority: scripts/lib/security_identity.py (ROOT GUID AUTHORITY) via scripts/lib/identity_registry.py
- `subject_guid` — equals security_guid for a security subject (AGENTS.md identity table); accepted on read, mapped, never stored as a second key
- `subject_key` — InstrumentRecord@v1 legacy key; alias only
- `symbol` — display alias; never a key

## Entities at a glance

| Entity | Domain | Status | Authoritative store | Single writer | Refresh lane | Freshness SLA | Readers |
|---|---|---|---|---|---|---|---|
| CIO prospect — the per-security truth | **cio_prospect** | PROPOSED | `cio_prospect` (table) | `scripts/lib/cio_instrument_record.py` | n8n_shadow_then_live: cio-opportunity-curator, cio-entry-state (dispatcher rows; shadow -> canary -> cutover under AGENTS.md §23.21) | stage/conviction 30 min in market hours; thesis 24 h; every field carries evidence_at and expires_at and renders its age | Home, Watch, Trade AI, Options, Open Trades, Telegram, Proposals, Re-entry |
| Security identity | **security_identity** | PROPOSED | `runtime/identity_registry.json` (file) | `scripts/lib/identity_registry.py` | n8n: catalyst-graph, identity-sweep-stage0, mint-identity-registry | 24 h; a symbol without a CONFIRMED GUID renders 'identity unresolved', never a placeholder | Home, Watch, Trade AI, Options, Open Trades, Telegram, Proposals, Re-entry |
| Positions, cash and cost basis | **positions_store** | PROPOSED | `positions_current` (table) | `scripts/positions_sync.py` | host: positions-sync · n8n never-list → host | 30 min in market hours (positions_sync.stale_after_minutes_market) | Home, Open Trades, Re-entry, Options, Telegram, Proposals |
| Transactions and lots | **transactions** | PROPOSED | `trade_transactions` (table) | UNCONSOLIDATED → `scripts/schwab_transaction_ingest.py` (exists) | host: schwab-transaction-ingest-at-3-18-33-48-9-16 · n8n never-list → host | 15 min in market hours; lots with each positions run | Open Trades, Re-entry, Home |
| Stops (observed at the broker) | **broker_stops** | PROPOSED | `stop_lifecycle` (table) | `scripts/stop_lifecycle_monitor.py` | host: stop-health-check · n8n never-list → host | 10 min in market hours | Open Trades, Home, Telegram |
| Watchlist membership | **watchlist_membership** | PROPOSED | `watchlist_items` (table) | UNCONSOLIDATED → `scripts/lib/writers/watchlist_items_writer.py` (to_build) | n8n: hermes-watchlist-scorer, watchlist-enrichment-sweep, materialize-watchlist-strategy-cards | membership event-driven; scores 15 min in market hours | Watch, Home, Trade AI, Telegram |
| Scanner results | **scanner_results** | PROPOSED | `trade_ai_scans` (table) | UNCONSOLIDATED → `scripts/lib/writers/trade_ai_scans_writer.py` (to_build) | n8n: trade-ai-scalp-live (AGENTS.md §23.3 live exception), orchestrator-slot | 5 min in market hours for scalp rows; daily for the full scan | Trade AI, Watch, Home, Telegram |
| Catalysts | **catalyst_events** | PROPOSED | `catalyst_events` (table) | UNCONSOLIDATED → `scripts/news_to_catalyst.py` (exists) | n8n_shadow_then_live: news-to-catalyst, hermes-news-bridge | 6 h; news_articles 18 h (registry catalyst_news) | Watch, Trade AI, Home, Telegram, Options |
| Scores (fused signals) | **fused_signals** | PROPOSED | `fused_signals` (table) | `scripts/signal_fusion.py` | n8n_shadow_then_live: signal-fusion-full, signal-fusion-active | 30 min in market hours | Trade AI, Watch, Options |
| CIO decisions | **cio_decisions** | PROPOSED | `cio_decisions` (table) | UNCONSOLIDATED → `scripts/lib/cio_instrument_record.py` (exists) | n8n_shadow_then_live: cio-entry-state | append-only; current state lives in cio_prospect | Home, Watch, Trade AI, Proposals |
| CIO theses | **cio_theses** | PROPOSED | `cio/cio_theses.jsonl` (file) | `scripts/lib/cio_theses.py` | n8n_shadow_then_live: cio-opportunity-curator | 24 h | Watch, Home, Trade AI, Options, Re-entry |
| Options ideas | **options_ideas** | PROPOSED | `options_approval_queue` (table) | UNCONSOLIDATED → `scripts/options_desk_enterprise.py` (exists) | host: options-tick · n8n never-list → host | 15 min in market hours | Options, Proposals, Telegram, Home |
| Paper proposals | **paper_proposals** | PROPOSED | `paper_trade_proposals` (table) | UNCONSOLIDATED → `scripts/lib/proposal_lifecycle.py` (to_build) | host: auto-proposal, paper-execution-sweep · n8n never-list → host | 5 min in market hours | Proposals, Home, Telegram, Trade AI |
| Paper trades | **paper_trades** | PROPOSED | `paper_trades` (table) | UNCONSOLIDATED → `scripts/paper_execution_sweep.py` (exists) | host: paper-execution-sweep, alpaca-paper-reconciler · n8n never-list → host | 5 min in market hours | Proposals, Open Trades, Home |
| Alerts | **alert_events** | PROPOSED | `alert_events` (table) | UNCONSOLIDATED → `scripts/alert_event_writer.py` (exists (wire it; AGENTS.md §13.5 — do not build a second)) | event: the producing lanes | event-driven | Home, Watch, Open Trades, Telegram |
| Operator messages | **comms_intents** | PROPOSED | `communication_events` (table) | UNCONSOLIDATED → `scripts/lib/comms/client.py` (exists) | host: n8n-comms-intent-consumer (canary) orchestrates; the gateway sends · n8n never-list → host | P1 immediate; P2 held 22:00-07:00 ET to the digest | Telegram, Home |

## Entity by entity

### CIO prospect record — `cio_prospect` (PROPOSED)

**Operator decision (§17):** Grant cio_prospect as the single per-security store: a Postgres table keyed by security_guid, written only by InstrumentRecordStore (scripts/lib/cio_instrument_record.py); opportunity_assessment becomes its export (superseded, not removed).

- **Facts:** stage, conviction, stance, catalyst grade, next trigger, what's missing, next action, conflicts, unified edge
- **Store of record:** `cio_prospect` (table) — One row per security_guid (current state) plus cio_prospect_events (append-only change log, same writer). Postgres, so it is Supabase-portable (AGENTS.md §24.9). Not created: the migration is its own operator-approved PR after this row is granted.
- **Single writer:** `scripts/lib/cio_instrument_record.py` — InstrumentRecordStore is the only write path (extend InstrumentRecord@v1, AGENTS.md §13.5; never a parallel type). The curator, entry-state runner, thesis store, wake dispatch and belief writer CALL it; none writes the table. apply_cognition / apply_belief rails unchanged: BEHAVIOR_FIELDS are refused, MBI_BEHAVIOR = 0.
- **Cadence:** */30 09:00-16:00 Mon-Fri curator pass + */10 entry-state pass + event-driven wake writes · stale after 0.5 h
- **Freshness SLA:** stage/conviction 30 min in market hours; thesis 24 h; every field carries evidence_at and expires_at and renders its age
- **Refresh lane:** n8n_shadow_then_live: cio-opportunity-curator, cio-entry-state (dispatcher rows; shadow -> canary -> cutover under AGENTS.md §23.21) — n8n schedules gathering and refresh; the host runs the lane; only the CIO writer writes. Model calls only through registered capabilities (AGENTS.md §23.4).
- **Read path (projection):** `cio_prospect` — to_build (scripts/lib/data_broker/cio_prospect.py)
- **Readers:** Home, Watch, Trade AI, Options, Open Trades, Telegram, Proposals, Re-entry
- **Supersedes (on grant):** opportunity_assessment — marked, never removed, until their readers move
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 0 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `data/cio/cio_opportunity_projection.json` (file) | derived | opportunity view exported from cio_prospect by the CIO writer; registry domain opportunity_assessment is superseded, not removed, until its readers move | 1 |
| `cio/cio_instrument_records.jsonl` (file) | derived | today InstrumentRecordStore's file; phase 1 dual-writes it beside the table, phase 4 makes it an export; retired later by archive + tripwire, never deleted | 0 |
| `cio/ticker_research_state.jsonl` (file) | retiring | per-symbol decision/evidence watermark folds into cio_prospect; archive + tripwire after the compare phase | 0 |
| `cio/security_research_spine.jsonl` (file) | history | SecurityResearchSpine@v1 contribution ledger (NO SILOS); its summary becomes the prospect's research section; view_for_silo reads the prospect | — |
| `cio_entry_states` (table) | retiring | entry state becomes cio_prospect.stage written through InstrumentRecordStore; readers (options_engine, notify_material_change) move to the projection; then archive + tripwire | 0 |
| `decision_packets` (table) | history | per-run Watch decision log; the current per-symbol decision is read from cio_prospect | — |
| `cio/cio_investment_brief.json` (file) | derived | operator product rendered from cio_prospect (CIOOperatorProduct@v1) | 1 |
| `watchlist_research_cards` (table) | retiring | private per-desk research (NO SILOS defect); contribute into the spine; archive + tripwire | 1 |
| `advisor_recommendations` (table) | retiring | dead since 2026-07-20; archive + tripwire | 1 |

### Identity registry (GUIDs) — `security_identity` (PROPOSED)

**Operator decision (§17):** Grant the identity registry as a domain (store runtime/identity_registry.json, writer scripts/lib/identity_registry.py). Moving it to Postgres is a separate decision.

- **Facts:** issuer_guid, security_guid, listing_guid, ticker alias, CUSIP
- **Store of record:** `runtime/identity_registry.json` (file) — IdentityRegistry@v1 (10k+ entities). Target: a Postgres identity table set (issuer/security/listing/ticker_alias) byte-identical on GUIDs, dry-run diffed — its own operator decision; never re-mint.
- **Single writer:** `scripts/lib/identity_registry.py` — GUIDs are computed only by scripts/lib/security_identity.py (ROOT GUID AUTHORITY); minting only via mint_identity_registry.
- **Cadence:** premarket pipeline + catalyst-graph 06:10 (n8n) · stale after 24 h
- **Freshness SLA:** 24 h; a symbol without a CONFIRMED GUID renders 'identity unresolved', never a placeholder
- **Refresh lane:** n8n: catalyst-graph, identity-sweep-stage0, mint-identity-registry — existing lanes; nothing new is scheduled by this row
- **Read path (projection):** `none` — to_build (identity lookup projection)
- **Readers:** Home, Watch, Trade AI, Options, Open Trades, Telegram, Proposals, Re-entry
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 0 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `memory_r10_m2.memory_identity` (table) | retiring | shadow memory identity (third GUID-bearing store); archive + tripwire after the compare | 0 |
| `narrative_subjects` (table) | history | NarrativeSubjectLink@v1 tag log, not an identity | — |

### Positions (one authority) — `positions_store` (PROPOSED)

**Operator decision (§17):** Make positions_current the ONE positions/cash/basis authority and supersede holdings_accounts: holdings.json becomes a generated export (operator decision 2026-10-22); readers move in operator-approved batches.

- **Facts:** shares, cash, cost basis, broker market value
- **Store of record:** `positions_current` (table) — positions_current (+ position_snapshots history, position_lots, realized_lots, positions_sync_runs); cash as is_cash rows.
- **Single writer:** `scripts/positions_sync.py`
- **Cadence:** 9,24,39,54 09:00-16:00 Mon-Fri (lane positions-sync) · stale after 0.5 h
- **Freshness SLA:** 30 min in market hours (positions_sync.stale_after_minutes_market)
- **Refresh lane:** host: positions-sync · n8n never-list → host — a broker READ through the existing read clients; stays on the host (AGENTS.md §23.14). Agents may run broker reads only under a broker-read grant (§24.11).
- **Read path (projection):** `positions_context` — exists
- **Readers:** Home, Open Trades, Re-entry, Options, Telegram, Proposals
- **Supersedes (on grant):** holdings_accounts — marked, never removed, until their readers move
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 1 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `portfolios/state/holdings.json` (file) | derived | operator decision 2026-10-22: becomes a generated export written by ONE projector from positions_current + data-broker marks; its writers fall 7 -> 1 in operator-approved reader batches (plan docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md phase 4) | 5 |
| `schwab_positions_live` (table) | retiring | stale third copy (last write 2026-10-13); readers move to positions_context; archive + tripwire | 0 |

### Broker transactions — `transactions` (PROPOSED)

**Operator decision (§17):** Grant trade_transactions as the transactions domain with a 3-writer ceiling that may only fall (target schwab_transaction_ingest.py).

- **Facts:** transaction, realized lot, tax lot
- **Store of record:** `trade_transactions` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/schwab_transaction_ingest.py` (exists) — 3 writers measured 2026-10-22 (schwab_transaction_ingest, snaptrade_activity_ingest, paper_scale). Lots are written only by positions_sync.py (position_lots/realized_lots).
- **Cadence:** 3,18,33,48 09:00-16:00 + 18:15; snaptrade 07:20 · stale after 0.5 h
- **Freshness SLA:** 15 min in market hours; lots with each positions run
- **Refresh lane:** host: schwab-transaction-ingest-at-3-18-33-48-9-16 · n8n never-list → host — broker read; host only (AGENTS.md §23.14)
- **Read path (projection):** `positions_context` — exists
- **Readers:** Open Trades, Re-entry, Home
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 3 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `portfolios/state/tax_lots.json` (file) | derived | export rebuilt from trade_transactions; readers move to positions_context | 1 |
| `schwab_cost_basis_lots` (table) | retiring | stale since 2026-06-10; archive + tripwire | 0 |
| `cost_basis_anchors` (table) | retiring | orphan since 2026-07-16; archive + tripwire | 1 |

### Observed broker stops — `broker_stops` (PROPOSED)

**Operator decision (§17):** Grant stop_lifecycle as the observed-stop domain (read-only observation; no stop or order authority; code changes need an execution-engineering grant).

- **Facts:** stop
- **Store of record:** `stop_lifecycle` (table)
- **Single writer:** `scripts/stop_lifecycle_monitor.py` — Observation only: the row records what the broker shows. Nothing in the dictionary grants any stop or order change (AGENTS.md §0 rules 1-2); code changes here need an execution-engineering grant.
- **Cadence:** */10 09:00-16:00 via stop_health_check · stale after 0.25 h
- **Freshness SLA:** 10 min in market hours
- **Refresh lane:** host: stop-health-check · n8n never-list → host — stop lanes are on the n8n never-list (AGENTS.md §23.14); stays cron/systemd
- **Read path (projection):** `none` — to_build (read-only stop view)
- **Readers:** Open Trades, Home, Telegram
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 1 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `stop_last_known` (table) | retiring | write-only near-copy (no reader); archive + tripwire | 0 |
| `manual_broker_stops` (table) | retiring | 0 active rows, last 2026-10-05; archive + tripwire | 0 |
| `broker_order_intents` (table) | excluded | broker execution subsystem (AGENTS.md §0 rule 2): inventoried by SELECT only, never dictionary-managed | — |
| `trade_approvals` (table) | excluded | broker execution subsystem (AGENTS.md §0 rule 2): never dictionary-managed | — |

### Watchlist (one list) — `watchlist_membership` (PROPOSED)

**Operator decision (§17):** Grant watchlist_items as the ONE membership list with a writer ceiling that may only fall; supersede watch_discovery; strategy_watchpool, watchlist.json and hermes_watchlist_lifecycle.json become derived or retired.

- **Facts:** membership, origin, operator star
- **Store of record:** `watchlist_items` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/lib/writers/watchlist_items_writer.py` (to_build) — 15+ writer files measured 2026-10-22. Membership changes only by the CIO curator and operator commands; everything else contributes candidates.
- **Cadence:** event-driven membership; scores */15 in market hours · stale after 0.25 h
- **Freshness SLA:** membership event-driven; scores 15 min in market hours
- **Refresh lane:** n8n: hermes-watchlist-scorer, watchlist-enrichment-sweep, materialize-watchlist-strategy-cards — existing n8n lanes
- **Read path (projection):** `watch_intelligence` — exists (ranks with top_ideas.v2; must read cio_prospect)
- **Readers:** Watch, Home, Trade AI, Telegram
- **Supersedes (on grant):** watch_discovery — marked, never removed, until their readers move
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 25 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `portfolios/state/watchlist.json` (file) | derived | legacy personal watchlist; stops being a write target and becomes an export | 3 |
| `strategy_watchpool` (table) | retiring | a second membership list (7,080 rows); fold into watchlist_items origin; archive + tripwire | 1 |
| `runtime/hermes_watchlist_lifecycle.json` (file) | derived | third membership/lifecycle list; becomes a projection of watchlist_items | 0 |
| `operator_starred_symbols` (table) | retiring | stars become watchlist_items origin=operator_star; archive + tripwire | 2 |
| `watch_candidate_events` (table) | retiring | dead feed since 2026-07-16 (registry watch_discovery); archive + tripwire | 0 |

### Trade AI scans — `scanner_results` (PROPOSED)

**Operator decision (§17):** Grant trade_ai_scans as the scanner domain with a 6-writer ceiling that may only fall (target a single writer module).

- **Facts:** scan decision, scan score
- **Store of record:** `trade_ai_scans` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/lib/writers/trade_ai_scans_writer.py` (to_build) — 6 writer files measured 2026-10-22 (orchestrator, continuous runner, social scalp scanner, premarket watcher, symbol enrichment, backfill).
- **Cadence:** 17:30 full; */15 07:00-09:00; scalp-live */5 in market hours · stale after 0.1 h
- **Freshness SLA:** 5 min in market hours for scalp rows; daily for the full scan
- **Refresh lane:** n8n: trade-ai-scalp-live (AGENTS.md §23.3 live exception), orchestrator-slot — the one n8n live lane stays under its §23.3 conditions
- **Read path (projection):** `none` — to_build (scan projection; the UI reads trade_ai_cache.json today)
- **Readers:** Trade AI, Watch, Home, Telegram
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 6 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `runtime/trade_ai_cache.json` (file) | derived | UI read path today; becomes a projection stamped with run_id | 1 |
| `scalp_scan_results` (table) | retiring | fold into trade_ai_scans run_type; archive + tripwire | 1 |

### Catalyst events (SecurityEvent@v1) — `catalyst_events` (PROPOSED)

**Operator decision (§17):** Grant catalyst_events (SecurityEvent@v1) as the one catalyst store with a 3-writer ceiling; news_to_catalyst.py is the target single writer.

- **Facts:** catalyst, event_guid, catalyst date
- **Store of record:** `catalyst_events` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/news_to_catalyst.py` (exists) — 3 writers measured 2026-10-22 (news_to_catalyst, news_ingestion, lib/sec_filing_events). News and filings emit documents; only news_to_catalyst mints events (event_guid).
- **Cadence:** 45 6,12,18 + ingest tails · stale after 6 h
- **Freshness SLA:** 6 h; news_articles 18 h (registry catalyst_news)
- **Refresh lane:** n8n_shadow_then_live: news-to-catalyst, hermes-news-bridge — news-to-catalyst is in n8n shadow
- **Read path (projection):** `catalyst_record` — exists
- **Readers:** Watch, Trade AI, Home, Telegram, Options
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 3 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `hermes/momentum_catalysts/<date>_catalysts.jsonl` (file) | derived | parallel per-day catalyst file; becomes a projection of catalyst_events | 0 |
| `catalyst_quality_results` (table) | retiring | dead since 2026-05-07; archive + tripwire | 1 |

### Fused signals — `fused_signals` (PROPOSED)

**Operator decision (§17):** Grant fused_signals as the score domain (single writer signal_fusion.py).

- **Facts:** fused score, component scores
- **Store of record:** `fused_signals` (table)
- **Single writer:** `scripts/signal_fusion.py`
- **Cadence:** 07,13 full + */30 04:00-16:00 active · stale after 0.5 h
- **Freshness SLA:** 30 min in market hours
- **Refresh lane:** n8n_shadow_then_live: signal-fusion-full, signal-fusion-active — shadow first
- **Read path (projection):** `none` — to_build (score projection)
- **Readers:** Trade AI, Watch, Options
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 1 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `hermes_score_history` (table) | history | component score history (hermes watchlist scorer) | — |

### CIO decision log — `cio_decisions` (PROPOSED)

**Operator decision (§17):** Grant cio_decisions as the append-only CIO decision log (5-writer ceiling, target the CIO writer); current state is read from cio_prospect.

- **Facts:** decision, decision reason
- **Store of record:** `cio_decisions` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/lib/cio_instrument_record.py` (exists) — 5 writers measured 2026-10-22 (cio_decision_engine PAUSED, cio_entry_state_runner, buy_ready_cio_review, options_cio_review, options_thesis_lifecycle RETIRED). Append-only log: the decision is appended by the CIO writer in the same write as the prospect change. Current state is never read from the log.
- **Cadence:** */10 09:00-16:00 · stale after 0.5 h
- **Freshness SLA:** append-only; current state lives in cio_prospect
- **Refresh lane:** n8n_shadow_then_live: cio-entry-state — rides the cio_prospect lanes
- **Read path (projection):** `cio_prospect` — to_build
- **Readers:** Home, Watch, Trade AI, Proposals
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 5 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `trade_thesis_reviews` (table) | history | nightly thesis review log (18:40) | — |

### Thesis documents — `cio_theses` (PROPOSED)

**Operator decision (§17):** Grant cio_theses.jsonl as the thesis-document store (single writer CIOThesisStore).

- **Facts:** thesis, thesis version
- **Store of record:** `cio/cio_theses.jsonl` (file)
- **Single writer:** `scripts/lib/cio_theses.py` — CIOThesisStore; the prospect carries thesis_ref + stance, never a copy of the text.
- **Cadence:** 17:17 + curator + operator commands · stale after 24 h
- **Freshness SLA:** 24 h
- **Refresh lane:** n8n_shadow_then_live: cio-opportunity-curator — thesis acquisition model calls only through registered capabilities
- **Read path (projection):** `cio_prospect` — to_build
- **Readers:** Watch, Home, Trade AI, Options, Re-entry
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 0 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `cio/cio_theses_projection.json` (file) | derived | thesis view; served via the projection | 2 |

### Options proposal lifecycle — `options_ideas` (PROPOSED)

**Operator decision (§17):** Grant options_approval_queue as the options-idea lifecycle (4-writer ceiling, target options_desk_enterprise.py; host only).

- **Facts:** options idea, options approval state
- **Store of record:** `options_approval_queue` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/options_desk_enterprise.py` (exists) — 4 writers measured 2026-10-22 (options_desk_enterprise, alpaca_paper, prime_rubric, api_v2). Expression ranking is a consumer of the prospect, never a second research store (NO SILOS).
- **Cadence:** options-tick 7,22,37,52 in market hours · stale after 0.25 h
- **Freshness SLA:** 15 min in market hours
- **Refresh lane:** host: options-tick · n8n never-list → host — order/paper-adjacent; stays on the host (AGENTS.md §23.14)
- **Read path (projection):** `option_chain` — exists (chain); idea projection to_build
- **Readers:** Options, Proposals, Telegram, Home
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 4 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `options_intent/latest.json` (file) | derived | intent matcher view | 2 |
| `cio/options_theses.jsonl` (file) | history | options expression sub-document of the prospect; projector lane RETIRED | — |
| `option_chain_snapshots` (table) | retiring | duplicate of options_chain_snapshots, no reader since 2026-10-14; archive + tripwire | 0 |
| `proxy_option_candidates` (table) | retiring | dead since 2026-07-06; archive + tripwire | 1 |

### Paper trade proposals — `paper_proposals` (PROPOSED)

**Operator decision (§17):** Grant paper_trade_proposals with its measured 51-writer ceiling that may only fall; a lifecycle module becomes the only UPDATE path in batches.

- **Facts:** proposal, proposal status
- **Store of record:** `paper_trade_proposals` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/lib/proposal_lifecycle.py` (to_build) — 51 writer files measured 2026-10-22: the worst multi-writer store. One lifecycle state machine becomes the only UPDATE path, in batches. Paper submit paths are broker-adjacent: execution-engineering grant territory (AGENTS.md §0 rule 2).
- **Cadence:** many crons (auto-proposal */10, sweeps */5) · stale after 0.1 h
- **Freshness SLA:** 5 min in market hours
- **Refresh lane:** host: auto-proposal, paper-execution-sweep · n8n never-list → host — paper lanes are on the n8n never-list (AGENTS.md §23.14)
- **Read path (projection):** `none` — to_build (proposal projection)
- **Readers:** Proposals, Home, Telegram, Trade AI
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 51 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `paper_trading/paper_trade_statistics_latest.json` (file) | derived | statistics export | 1 |

### Paper trades — `paper_trades` (PROPOSED)

**Operator decision (§17):** Grant paper_trades with its measured 32-writer ceiling; consolidation only under an execution-engineering grant.

- **Facts:** paper fill, paper position
- **Store of record:** `paper_trades` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/paper_execution_sweep.py` (exists) — 32 writer files measured 2026-10-22. Consolidation touches the paper adapter: only under an execution-engineering grant.
- **Cadence:** paper-execution-sweep */5; alpaca paper sync hourly · stale after 0.1 h
- **Freshness SLA:** 5 min in market hours
- **Refresh lane:** host: paper-execution-sweep, alpaca-paper-reconciler · n8n never-list → host — paper lanes are on the n8n never-list
- **Read path (projection):** `none` — to_build
- **Readers:** Proposals, Open Trades, Home
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 32 writer file(s) of the store

### Alert facts — `alert_events` (PROPOSED)

**Operator decision (§17):** Grant alert_events as the alert-fact domain (17-writer ceiling, target the existing scripts/alert_event_writer.py).

- **Facts:** alert
- **Store of record:** `alert_events` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/alert_event_writer.py` (exists (wire it; AGENTS.md §13.5 — do not build a second)) — 17 writer files measured 2026-10-22. An alert_events row is not a send (AGENTS.md 4.3.0 ruling 4); sends are comms intents.
- **Cadence:** event-driven · stale after 24 h
- **Freshness SLA:** event-driven
- **Refresh lane:** event: the producing lanes — no new schedule
- **Read path (projection):** `none` — to_build
- **Readers:** Home, Watch, Open Trades, Telegram
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 17 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `alert_occurrences` (table) | derived | occurrence dedupe view of alert_events | 0 |
| `open_trade_alerts` (table) | derived | per-desk alert table; writer unknown in the 2026-10-22 inventory — classify before approval | 1 |
| `watch_alerts` (table) | derived | Watch desk alert view (watch_alerts_eval) | 1 |

### Notification intents and deliveries — `comms_intents` (PROPOSED)

**Operator decision (§17):** Grant communication_events as the notification-intent domain (gateway-only sends, AGENTS.md §24.1; 7-writer ceiling, target scripts/lib/comms/client.py).

- **Facts:** notification intent, delivery receipt
- **Store of record:** `communication_events` (table)
- **Single writer:** UNCONSOLIDATED → `scripts/lib/comms/client.py` (exists) — 7 writer files measured 2026-10-22 (comms client, delivery, classify, lifecycle, portal, outbound identity, ...). AGENTS.md §24.1: the host communications gateway is the only sender; senders emit intents.
- **Cadence:** event-driven · stale after 1 h
- **Freshness SLA:** P1 immediate; P2 held 22:00-07:00 ET to the digest
- **Refresh lane:** host: n8n-comms-intent-consumer (canary) orchestrates; the gateway sends · n8n never-list → host — senders stay on the host; the P1 path never depends on n8n
- **Read path (projection):** `none` — to_build (notification outbox projection exists in comms)
- **Readers:** Telegram, Home
- **Measured 2026-10-22 (repo scan, scripts/lib/data_dictionary.measure):** 7 writer file(s) of the store

| Copy | Role | How | Page/API files reading it (measured) |
|---|---|---|---|
| `communication_outbox` (table) | history | delivery receipts (same gateway) | — |
| `telegram_outbox` (table) | derived | second outbox (report_capture); becomes a view | 1 |
| `runtime/notification_intent_receipts.jsonl` (file) | history | router receipt of the same send | — |
| `notification_log` (table) | retiring | fourth record of a send; archive + tripwire | 1 |

## Field level

### `CIOProspect` — domain `cio_prospect`; InstrumentRecord@v1 (AGENTS.md §13.4; extended, not cloned, per §13.5)

| Field | Type | Meaning | Source domain | Required |
|---|---|---|---|---|
| `security_guid` | uuid | THE key: one row per security (AGENTS.md identity: security_guid is the specific instrument) | security_identity | yes |
| `issuer_guid` | uuid | the default join for 'everything about this company' | security_identity | yes |
| `subject_guid` | uuid (alias) | accepted on read and mapped: equals security_guid for a security subject today; never a second key | security_identity |  |
| `subject_key` | string (alias) | legacy InstrumentRecord@v1 key (HELD:X / WATCH:X / EXIT:X); kept as an alias so wake and belief paths keep working; the stage replaces the kind split | cio_prospect |  |
| `symbol` | string | display alias; tickers are reassigned, never a key | security_identity |  |
| `stage` | enum | watching -> setup_forming -> actionable -> proposed -> held -> exit / re_entry | cio_prospect | yes |
| `stage_changed_at` | timestamptz | when the stage last moved, with the evidence that moved it | cio_prospect |  |
| `conviction` | 0-100 | the CIO's conviction | cio_prospect | yes |
| `conviction_components` | object | named components that sum to the conviction: unified_edge, fused_score, catalyst_grade, thesis_quality, risk_reward, regime_fit — each with value, source, evidence_at | fused_signals / catalyst_events / cio_theses |  |
| `stance` | enum | BUY_SETUP / ADD / HOLD / TRIM_REVIEW / EXIT_REVIEW / WATCH / AVOID — priority and posture only; never a size, order or stop (MBI_BEHAVIOR = 0) | cio_prospect | yes |
| `catalyst_grade` | A-F + score | Gate 2 (Momentum Core) folds in here: the momentum/catalyst grade with its event_guid | catalyst_events |  |
| `next_trigger` | object | the observable event or level that moves the stage next, with the source that will observe it (reference level, never an order) | cio_prospect |  |
| `whats_missing` | list | evidence the CIO still needs before the next stage (data gaps, questions) | cio_prospect |  |
| `next_action` | object | who does what next: research question, operator review, wait-for-trigger | cio_prospect |  |
| `thesis_ref` | string | pointer to the thesis document version (cio_theses); never a copy of the text | cio_theses |  |
| `research` | object | SecurityResearchSpine@v1 summary (view_for_silo) — the same for every desk | research_thesis |  |
| `position_ref` | object | account_key list + qty from positions_context when held; read, never written | positions_store |  |
| `evidence_at` | timestamptz | the newest evidence time behind the record | cio_prospect | yes |
| `expires_at` | timestamptz | when the record is stale and renders as stale | cio_prospect | yes |
| `conflicts` | list | every disagreement between inputs (e.g. opportunity stance ADD vs thesis stance watch): both values, both sources, both times — shown, never silently resolved | cio_prospect |  |
| `next_eligible_at / notify_priority / cc_narrative / next_research_question` | InstrumentRecord@v1 | the existing cognition fields, unchanged (apply_cognition) | cio_prospect |  |
| `beliefs[] / lessons[] / operator_turns[]` | InstrumentRecord@v1 | unchanged; written only by their existing rails (apply_belief, cognition, operator turns) | cio_prospect |  |
| `as_of / writer / revision` | meta | write time, the single writer's id, monotonic revision | cio_prospect | yes |

### Key facts — where each one is true

| Fact | Entity | Domain | Store | Field | Unit | Meaning | Never read it from |
|---|---|---|---|---|---|---|---|
| **shares** | Positions | `positions_store` | `positions_current` | qty | shares | broker-reported quantity per (account_key, symbol) | a number from a report, a chat, a CSV or another account |
| **cash** | Positions | `positions_store` | `positions_current` | qty where is_cash | USD | broker-reported cash per account | a computed residual |
| **cost basis** | Positions | `positions_store` | `positions_current` | cost_basis_total | USD | broker average cost x shares, same account (positions.cost_basis_truth: broker) | a CSV lot or manual repair that disagrees with the broker; another account's basis |
| **mark** | Quotes | `quote_price` | `market_quotes` | price, as_of | USD | data-broker quote at read time with its age (resolve_mark / value_and_pl) | a stored current_price; any price without an age |
| **stop** | Stops | `broker_stops` | `stop_lifecycle` | stop_price, state, observed_at | USD | the stop the broker shows, as observed; read-only | stop_last_known or any agent-set value |
| **catalyst** | Catalysts | `catalyst_events` | `catalyst_events` | event_guid, event_type, period, state | - | a SecurityEvent@v1 (issuer, type, period), SCHEDULED -> OCCURRED -> POST_EVENT -> SUPERSEDED | a headline without an event_guid |
| **fused score** | Scores | `fused_signals` | `fused_signals` | score, components, as_of | 0-100 | signal fusion output per symbol and time | a recomputed score in a page handler |
| **unified edge** | Scores | `cio_prospect` | `cio_prospect` | conviction_components.unified_edge | 0-100 | today computed in memory inside auto_proposal_generator and never persisted; persisted as a conviction component so it is inspectable and reproducible | an in-memory value nobody can replay |
| **decision** | CIO decisions | `cio_decisions` | `cio_decisions` | decision, reason, decided_at | - | append-only CIO decision log | current state read from the log (read cio_prospect.stage/stance) |
| **stance** | CIO prospect | `cio_prospect` | `cio_prospect` | stance | enum | the CIO's one stance per security | a desk's private stance (NO SILOS) |
| **options idea** | Options | `options_ideas` | `options_approval_queue` | idea, status, blocked_reason | - | an options proposal and its lifecycle state | an idea qualified from a watchlist-only memo when the prospect holds CIO research |
| **paper proposal** | Proposals | `paper_proposals` | `paper_trade_proposals` | status | - | a paper proposal and its lifecycle | a status set by a second writer |
| **alert** | Alerts | `alert_events` | `alert_events` | alert_type, symbol, fired_at | - | an alert fact (not a send) | a send without a comms intent |
| **operator message** | Operator messages | `comms_intents` | `communication_events` | intent, priority, receipt | - | a notification intent and its delivery receipt | a direct Telegram send |
| **watchlist membership** | Watchlist | `watchlist_membership` | `watchlist_items` | security_guid, status, origin | - | is this security on the watchlist, and who put it there | watchlist.json, strategy_watchpool or hermes_watchlist_lifecycle.json |
| **identity** | Security identity | `security_identity` | `runtime/identity_registry.json` | issuer_guid, security_guid | UUIDv5 | durable identity; a ticker is an alias | a ticker used as a key, a placeholder GUID |

## Declared stores measured missing

| Domain | Status | What | Why | Measured |
|---|---|---|---|---|
| `intelligence_gir_projection` | SECONDARY_MISSING | runtime/gir_projection_dryrun.json absent (table intelligence.gir_entity present) | dry-run artifact only; the table is the store | 2026-10-22T11:35-04:00 |
| `supervisor_ladder_receipts` | MISSING | runtime/supervisor_ladder_receipts.jsonl absent | measured absent; verify the detector writes it | 2026-10-22T11:35-04:00 |
| `counterfactual_ledger` | MISSING | cio/counterfactual_ledger.jsonl absent | measured absent; daily builder not producing — verify before relying on it | 2026-10-22T11:35-04:00 |
| `yfinance_info_snapshot` | MISSING | table yfinance_info_snapshot does not exist | migration migrations/2026_10_10_yfinance_info_snapshot.sql never applied; no producer until the owner lane is decided (§D.12) | 2026-10-22T11:35-04:00 |
| `earnings_calendar` | MISSING | runtime/alpha_vantage/earnings_calendar_latest.json absent | unscheduled; Alpha Vantage returns a premium-endpoint error | 2026-10-22T11:35-04:00 |
| `news_sentiment` | MISSING | runtime/alpha_vantage/news_sentiment_latest.json absent | unscheduled (needs a cron/n8n grant) | 2026-10-22T11:35-04:00 |

## Other granted domains

These carry no dictionary block yet; their store, writer and read path are in [`docs/SOURCE_OF_TRUTH.md`](../SOURCE_OF_TRUTH.md). A domain marked superseded becomes a derived copy when the superseding row is granted.

`quote_price`, `symbol_identity`, `analyst_opinion`, `catalyst_news`, `technicals`, `sector_momentum`, `industry_momentum`, `market_regime`, `earnings_date`, `holdings_accounts` (superseded by `positions_store` on grant), `options_iv`, `research_thesis`, `watch_directives`, `watch_discovery` (superseded by `watchlist_membership` on grant), `web_search`, `private_company`, `dividends`, `macro`, `fundamentals`, `agent_opinion`, `agent_debate`, `ai_reports`, `redeploy_analytics`, `inverse_stoplights`, `data_gaps`, `operator_conversation`, `intelligence_memory_contexts`, `intelligence_retrieval_receipts`, `supervisor_heartbeats`, `approval_packages`, `platform_conformance`, `intelligence_gir_projection`, `supervisor_breaches`, `research_write_path_receipts`, `edge_fanout_work_items`, `intelligence_research_index`, `sec_filing_events`, `agent_checkpoints`, `lesson_promotions`, `contradiction_verdicts`, `agent_registry`, `model_chooser_receipts`, `supervisor_ladder_receipts`, `maturity_scores`, `conformance_gate_receipts`, `supervisor_recoveries`, `capital_plan_decisions`, `cio_operator_artifacts`, `counterfactual_ledger`, `active_trader_microstructure`, `opportunity_assessment` (superseded by `cio_prospect` on grant), `finviz_enrichment`, `scalp_list`, `social_posts`, `yfinance_info_snapshot`, `earnings_calendar`, `news_sentiment`

## Surfaces scanned for copy reads

`scripts/api_v2.py`, `scripts/api_v3_*.py`, `scripts/portfolio_server.py`, `scripts/telegram_command_handler.py`

- **Home** — apps/command-center-v3 Home -> /api/v3/cio/home, /api/v2/portfolio
- **Watch** — Watch desk -> /api/v3/data-broker/watch (watch_intelligence)
- **Trade AI** — Trade AI scanner -> /api/v2 trade-ai routes
- **Options** — Trading -> Options -> /api/v2 options routes
- **Open Trades** — Open Trades -> /api/v2/open-trades
- **Telegram** — Telegram cards and commands (telegram_command_handler, comms gateway)
- **Proposals** — Proposals -> /api/v2 proposals routes
- **Re-entry** — Re-entry desk -> reentry_decision_desk projection
