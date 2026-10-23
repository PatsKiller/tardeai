# CIO prospect data foundation — one store, one writer, the CIO as integrator

```
Status:      DRAFT — PROPOSED. Binding once AGENTS.md 18.0.0 is ratified (§20) and each registry row is
             granted by the operator (§17). Until then nothing here changes runtime behaviour.
as_of:       2026-10-22T16:00:00-04:00
Measured at: origin/main 82180caba (repository scan); live store counts from a read-only inventory
             2026-10-22 ~11:29-11:35 ET (SELECT count/max, file stat; no writes)
```

Data dictionary (rendered from the registry, binding per row once granted): [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md).
Registry: `config/data_source_authority.json` (AGENTS.md §7A) — `proposed_domains[]`, `data_dictionary`,
`domains[].store_presence`. Enforcement: `scripts/check_data_source_authority.py` via `scripts/lib/data_dictionary.py`.

---

## 1. The direction

Operator, 2026-10-22, verbatim:

> "The CIO agent is supposed to tie all of this together, and it should all be in persistent memory. One data store
> with everything; use the CIO agent and n8n to accomplish this. This was supposed to be the baseline of the site."

> "Make sure this is the foundation of the data in the site. Make sure that this is hard-coded in agents.md and you
> set the architecture of how this should work. And we should also have a data dictionary that shows one source of
> data."

This document is the architecture. The data dictionary is the registry rows plus their rendering. The AGENTS.md text
is the 18.0.0 amendment (PROPOSED), delivered as an operator-applied patch, because agents never edit AGENTS.md (§20).

**What this PR does not do:** no migration is applied, no table is created, no data is moved, nothing is deleted or
archived, no lane, cron, timer or n8n workflow changes, and no page reads anything new. Every runtime step below is a
later PR with its own operator decision.

## 2. What was measured

`[VERIFIED]` read-only inventory, 2026-10-22 ~11:35 ET: 16 entities over 131 stores (Postgres `pg_stat_user_tables`,
`count(*)`/`max(ts)` SELECTs, file mtimes under `persistent-state`, grep of writers and readers, `crontab -l`,
`config/lane_registry.json`). Writer and page/API read counts below are `[VERIFIED]` by
`scripts/lib/data_dictionary.measure` on this branch (the numbers in each registry row's `measured`).

**The per-security prospect lives in at least eight CIO stores, none keyed by a GUID in Postgres:**

| Store | Per-symbol count | Keyed by | Writer(s) |
|---|---|---|---|
| `cio/ticker_research_state.jsonl` | 120 | security_guid (file) | unknown in inventory |
| `cio/security_research_spine.jsonl` | 295 | symbol (+subject_guid when known) | spine hooks |
| `cio/cio_theses.jsonl` | 688 | thesis id `symbol_<x>` | CIOThesisStore |
| `cio/cio_instrument_records.jsonl` | 1,140 | `subject_key` `HELD:X`/`WATCH:X` | InstrumentRecordStore |
| `cio_entry_states` | 1,241 | symbol | cio_entry_state_runner |
| `cio/cio_opportunity_projection.json` | 1,586 | symbol | cio_opportunity_curator |
| `decision_packets` | 1,841 | symbol | shadow_decision_service, run_ticket_review_job |
| `cio_decisions` | 3,889 | symbol (0 rows carry a GUID) | 5 writer files |

They disagree, silently. `[VERIFIED]` symbol matrix 2026-10-22 15:30Z: NVDA is `ADD` at conviction 78.5 in the
opportunity projection, `watch` in thesis v8 (2026-10-05), and its InstrumentRecord is `WATCH:NVDA` although it is
held; SPCX is `ADD` (80.3) beside thesis stance `watch`; NAVN ranks #1 (87.7) with no instrument record and no spine
row. No surface shows any of these conflicts.

**Other measured splits:**

- **Watch reads no CIO store.** The Watch projection ranks with `top_ideas.v2` (`scripts/lib/data_broker/watch_domains.py`
  `RANK_VERSION`), a rank that is not a registry domain, and takes positions from `holdings.json` as a fallback
  `[CODE]`.
- **Two registered authorities for positions:** `holdings_accounts` → `portfolios/state/holdings.json` (seven
  writers) and `positions_store` → `positions_current` (one writer). Five page/API files read `holdings.json`
  directly; so do the Watch and Re-entry projections themselves `[CODE]`.
- **Four watchlist membership lists:** `watchlist_items` (25 writer files), `watchlist.json`, `strategy_watchpool`
  (7,080 rows), `hermes_watchlist_lifecycle.json` (5,639 symbols).
- **No registry domain at all** for stops (`stop_lifecycle`), scans (`trade_ai_scans`, 6 writers), catalysts
  (`catalyst_events`, 3 writers, 13% rows without `subject_guid`), fused signals (921k rows, no GUID), CIO decisions
  and theses, options ideas (`options_approval_queue`, 4 writers), paper proposals (`paper_trade_proposals`,
  **51 writer files**), paper trades (32), alerts (`alert_events`, 17), comms (`communication_events`, 7).
- **The unified edge is never persisted.** `unified_edge_score.py` runs in memory inside
  `auto_proposal_generator._unified_edge`; nobody can inspect or replay the number that ranked a proposal.
- **Declared stores that do not exist:** `yfinance_info_snapshot` (migration never applied),
  `earnings_calendar` and `news_sentiment` (Alpha Vantage files never produced); also measured absent:
  `counterfactual_ledger`, `supervisor_ladder_receipts`, and the `gir_projection_dryrun.json` secondary file.
  Each is now marked `store_presence` in the registry.

## 3. The decision

**One persistent Postgres store holds the per-security truth: `cio_prospect`, one row per `security_guid`, written
only by the CIO agent's InstrumentRecordStore.** Everything else about a security is either an input the CIO reads,
a log the CIO appends, or a view rendered from the prospect.

### 3.1 One key — `security_guid`; `subject_guid` is an alias

AGENTS.md's identity table already settles the names; this design only picks within it:

| Name | Role in the prospect | Why |
|---|---|---|
| `security_guid` | **the primary key** | one row per specific instrument; survives a ticker change (identity table) |
| `issuer_guid` | carried, indexed | the default join for "everything about this company" (identity table: "Prefer `issuer_guid`") |
| `subject_guid` | accepted on read, mapped, never stored as a second key | the identity table defines it as "what a row is *about* … = `security_guid` today"; NO SILOS rule 1 keys the spine by it, which is the same value for a security |
| `subject_key` (`HELD:X`) | legacy alias kept for wake and belief paths | the kind prefix splits one security in two when it moves from watched to held (the NVDA case); `stage` replaces the kind |
| `symbol` | display alias | "a ticker is an alias, not an identity" |

GUIDs come only from `scripts/lib/security_identity.py` through `scripts/lib/identity_registry.py`. A symbol with no
CONFIRMED GUID gets no prospect row and renders "identity unresolved" — never a placeholder (§7 "Never mint a
placeholder identity").

### 3.2 Extend `InstrumentRecord@v1`; do not clone it (§13.5)

Pre-build check (§13.5), recorded: searched §13.4 and the docs index for *prospect*, *instrument record*, *opportunity*,
*decision object*, *spine*, *entry state*; searched for writes to `cio_instrument_records.jsonl`,
`cio_opportunity_projection.json`, `cio_entry_states`; checked `config/data_source_authority.json`,
`scripts/lib/data_broker/catalog.py` and the lane registry. Found: `InstrumentRecord@v1` + `InstrumentRecordStore`
(`scripts/lib/cio_instrument_record.py`, "the persistent unit", wired), `OpportunityAssessment@v1` (curator, wired,
registry domain `opportunity_assessment`), `SecurityResearchSpine@v1` (wired, no surface reads it),
`SymbolDecisionObject@v1` (assembler, prefers the spine), the `opportunity` projection. **Extending the persistent
unit rather than adding a type:** the prospect is `InstrumentRecord@v1` with the fields of §4 added, a Postgres
backend behind `InstrumentRecordStore`, and `OpportunityAssessment@v1` becoming its export. No new `@v1` name.

## 4. The prospect record

Field-level entries, types and source domains are rendered in [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md)
("`CIOProspect`"); the registry is the source. The semantics:

- **Identity:** `security_guid` (PK), `issuer_guid`, `symbol`, `subject_key` alias.
- **Stage** — one machine for every desk:

  ```
  watching ──► setup_forming ──► actionable ──► proposed ──► held ──► exit
      ▲                                                       │          │
      └────────────────────── re_entry ◄──────────────────────┘◄─────────┘
  ```

  A stage moves only on evidence the record names (`stage_changed_at` + the evidence id). `proposed` means a paper or
  operator proposal exists; `held` is read from `positions_context`, never set by judgment.
- **Conviction 0–100 + components:** `conviction_components` names each input with its value, source and
  `evidence_at` — `unified_edge` (persisted here for the first time), `fused_score`, `catalyst_grade`,
  `thesis_quality`, `risk_reward`, `regime_fit`. The conviction is reproducible from its components.
- **Stance:** `BUY_SETUP` / `ADD` / `HOLD` / `TRIM_REVIEW` / `EXIT_REVIEW` / `WATCH` / `AVOID` — posture and priority.
- **Catalyst grade:** Gate 2 (Momentum Core) of the Shared Momentum / Alerts redesign folds in here — its grade and
  the `event_guid` (`SecurityEvent@v1`) behind it — instead of a separate momentum store.
- **Next trigger:** the observable event or reference level that moves the stage next, and which lane observes it.
  A reference level is information, never an order.
- **What's missing:** the evidence the CIO still needs (data gaps from `data_gap_registry`, open research questions).
- **Next action:** who does what next — a research question, an operator review, wait for the trigger.
- **`evidence_at` / `expires_at`:** every record and every component carries both; a page renders age and shows
  "stale" after `expires_at`, never a stale value as current (§7A rule 3).
- **Conflicts:** every disagreement between inputs is a row in `conflicts[]` with both values, both sources and both
  times. **Shown, never silently resolved** — the NVDA `ADD` vs thesis `watch` case renders as a conflict on every
  surface until the CIO resolves it with a recorded reason. This is §0 rule 5 applied to judgment.
- **Unchanged InstrumentRecord fields:** `thesis_ref`, `cc_narrative`, `next_research_question`, `next_eligible_at`,
  `notify_priority`, `beliefs[]`, `lessons[]`, `operator_turns[]` keep their rails (`apply_cognition`, `apply_belief`).

**`MBI_BEHAVIOR = 0`.** The CIO sets stance and priority; it never sizes, orders, stops or weights. No prospect field
is in `BEHAVIOR_FIELDS` (a test pins it), and the unconditional raise at `cio_instrument_record.py` is untouched
(changing it is §17).

Storage sketch for the schema PR (**not applied here**; its own operator-approved migration, §24.9 Postgres-native):

```sql
-- sketch only
CREATE TABLE cio_prospect (
  security_guid uuid PRIMARY KEY, issuer_guid uuid NOT NULL, symbol text NOT NULL, subject_key text,
  stage text NOT NULL, stage_changed_at timestamptz, conviction numeric(5,2), conviction_components jsonb,
  stance text, catalyst_grade jsonb, next_trigger jsonb, whats_missing jsonb, next_action jsonb,
  thesis_ref text, research jsonb, conflicts jsonb NOT NULL DEFAULT '[]', cognition jsonb,
  evidence_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
  as_of timestamptz NOT NULL, writer text NOT NULL, revision bigint NOT NULL);
CREATE TABLE cio_prospect_events (                    -- append-only, same writer
  id bigserial PRIMARY KEY, security_guid uuid NOT NULL, at timestamptz NOT NULL, writer text NOT NULL,
  change jsonb NOT NULL, evidence jsonb, revision bigint NOT NULL);
```

## 5. Who writes, who gathers, who reads

### 5.1 One writer — the CIO agent

`InstrumentRecordStore` (`scripts/lib/cio_instrument_record.py`) is the only write path to `cio_prospect` and
`cio_prospect_events`, and appends the matching row to the `cio_decisions` log in the same write. The curator,
entry-state runner, thesis store, wake dispatch and belief writer **call** it; none of them writes a per-security
store of its own. A second writer fails CI once the row is granted (`DICTIONARY_SECOND_WRITER`).

Model calls the CIO makes (thesis acquisition, synthesis) go only through registered capabilities and the governed
bridge (§23.4, §12) — never a raw provider call.

### 5.2 n8n gathers and refreshes; the host keeps authority

n8n schedules the lanes that gather and refresh the CIO's inputs and fire the CIO's own passes (`cio-opportunity-curator`,
`cio-entry-state`, `signal-fusion-*`, `news-to-catalyst`, `hermes-watchlist-scorer`, …) — shadow → canary → cutover
under §23.21, each a dispatcher row and its own decision (§17, §23.11). The host runs every lane; n8n holds no
credential and writes no store (§23.23).

**The never-list stays on the host (§23.14):** stops, orders, paper execution, the options tick, senders and daemons.
`positions-sync`, `stop-health-check`, `options-tick`, `paper-execution-sweep` and the comms gateway are host lanes in
the dictionary (`refresh_lane.never_list: true`; a test pins it). A broker read by an agent needs a `broker-read`
grant (§24.11); n8n triggering a broker read lane needs its own §23 ruling.

### 5.3 Every page and alert is a reader, through a projection

A new data-broker projection `cio_prospect` (`scripts/lib/data_broker/cio_prospect.py`, to build) returns the record
in `BrokerReadEnvelope@v1` with `as_of`, age, `source`, `stale` and `conflicts`. Reader map:

| Surface | Reads today (measured / `[CODE]`) | Reads after the switch |
|---|---|---|
| **Home** | `/api/v3/cio/home` from `cio_investment_brief.json`, `cio_theses_projection.json`, `holdings.json` | `cio_prospect` + `positions_context` |
| **Watch** | `watch_intelligence` ranked by `top_ideas.v2`; positions from `holdings.json` fallback; no CIO store | `cio_prospect` ranking (stage, conviction, conflicts) — a change to what is ranked onto an operator surface is §17 |
| **Trade AI** | `runtime/trade_ai_cache.json` | scan projection (`scanner_results`) + the prospect's stage for each name |
| **Options** | `options_approval_queue`, `options_intent/latest.json`, `options_theses.jsonl` | `options_ideas` projection; qualification reads the prospect (NO SILOS rule 5) |
| **Open Trades** | `holdings.json`, `stop_lifecycle` | `positions_context` + observed-stop view + prospect stage `held`/`exit` |
| **Telegram** | cards built from per-desk stores; `holdings.json` in the command handler | cards rendered from `cio_prospect`; sends only as comms intents (§24.1) |
| **Proposals** | `paper_trade_proposals` (51 writers) | proposal projection; each proposal links its prospect revision |
| **Re-entry** | `reentry_decision_desk` projection, which reads `holdings.json` directly | the same projection reading `cio_prospect` (stage `re_entry`) + `positions_context` |

## 6. Data flow

```
 providers ──► owner lanes (§24.3; n8n-scheduled, host-run) ──► input stores (one writer each, §7A registry)
                                                                  │ quote_price · positions_store · catalyst_events
                                                                  │ fused_signals · research_thesis · watchlist_membership
                                                                  │ scanner_results · options_ideas · broker_stops (observed)
                                                                  ▼
                                  data-broker projections (read-only, as_of/age/source/stale)
                                                                  │
                                                                  ▼
 n8n fires the CIO pass ──► host lane ──► CIO agent (curator / entry-state / wake / belief / thesis)
                                              │   model calls only via registered capabilities
                                              ▼
                              InstrumentRecordStore  ── the ONLY writer ──►  cio_prospect (1 row / security_guid)
                                              │                              cio_prospect_events (append-only)
                                              └──────────────────────────►  cio_decisions (append-only log)
                                                                  │
                                                                  ▼
                                   projection `cio_prospect` (BrokerReadEnvelope@v1, conflicts shown)
                                                                  │
            ┌──────────┬──────────┬──────────┬──────────┬──────────┼──────────┬──────────┐
            ▼          ▼          ▼          ▼          ▼          ▼          ▼          ▼
          Home       Watch     Trade AI   Options  Open Trades Telegram  Proposals  Re-entry
                                                                  │
                         exports (generated, never written independently): cio_opportunity_projection.json,
                         cio_investment_brief.json, holdings.json (from positions_current), watchlist.json
```

## 7. Migration — shadow, compare, switch in batches, retire by archive

Every phase is its own PR and its own operator decision; each has a dry run (§0 rule 7) and a durable proof
(§0 rule 8). No phase deletes anything (§0 rule 6) and **no phase reconciles divergent copies by itself**: when two
copies disagree the report names both paths, hashes and timestamps and the operator decides (§0 rule 5, §17).

| Phase | What happens | Proof | Operator decision (§17) |
|---|---|---|---|
| **P0 (this PR)** | Architecture, dictionary rows (PROPOSED), CI checks (warn for proposed), AGENTS.md 18.0.0 patch | tests + rendered dictionary | grant each row; ratify 18.0.0 |
| **P1 Shadow** | Migration creates `cio_prospect` / `cio_prospect_events`; `InstrumentRecordStore` dual-writes (jsonl stays the store of record); a backfill from the eight stores is dry-run diffed first | row count per security_guid; dual-write parity report | migration grant; backfill `--apply` after the quoted dry run |
| **P2 Compare** | A read-only comparer reports, per security, every field where the prospect and each old store disagree | daily compare receipt; conflicts listed, never merged | review the conflict list; choose per store which is wrong |
| **P3 Switch readers** | Readers move to the `cio_prospect` projection in batches: (a) Home + Telegram cards, (b) Watch ranking, (c) Options + Proposals, (d) Open Trades + Re-entry. Positions: readers move to `positions_context`; **`holdings.json` becomes a generated export from `positions_current`** (operator decision 2026-10-22), its writers 7 → 1 | per batch: the page shows the same values from the projection; ceilings recorded | each batch; changing Watch ranking is "what is ranked onto an operator surface" |
| **P4 Retire** | Old stores become exports or are archived **with a tripwire** that fires if anything reads the archived path; ceilings in the registry fall to zero | tripwire armed; gate green at the lowered ceiling | each retirement (retiring a store or writer is §17) |

Rollback at every phase: readers switch back to the old store (still present until P4); the dual-write is turned off
by its flag; nothing is lost because nothing was deleted.

## 8. The data dictionary and its enforcement

- **One registry.** The dictionary is `config/data_source_authority.json` — proposed rows in `proposed_domains[]`
  (status `proposed`, `approval: null`), field level in `data_dictionary`, missing stores in
  `domains[].store_presence`. Proposed rows stay out of `domains[]`, so the data broker, the AGENTS.md §7A table and
  `UNAPPROVED_SOURCE` are unaffected until the operator grants them.
- **Granting a row** is the operator's act (§17). The agent then records it with
  `scripts/lib/data_dictionary.promote`, which moves the row into `domains[]` with the `approval` and a `dictionary`
  block whose ceilings are measured at grant time (writer files; page/API files reading each derived or retiring
  copy). Ceilings may only fall.
- **CI** (`scripts/check_data_source_authority.py`): `DICTIONARY_INVALID` always fails;
  `DICTIONARY_SECOND_WRITER` and `NON_AUTHORITATIVE_READ` fail for a granted row and warn for a proposed one.
- **The rendered dictionary** `docs/architecture/DATA_DICTIONARY.md` comes from `scripts/render_data_dictionary.py`;
  `--check` fails when it drifts (test + `ai_local_acceptance.sh`).

**What the scan cannot see** (stated so nobody reads a green gate as more than it is): reads or writes spelled other
than `INSERT INTO`/`UPDATE`/`COPY`/`FROM`/`JOIN` + the table name, or a file's declared markers; a file path assembled
far from its write call (some JSONL stores measure 0 writer files for that reason); an ORM; surfaces outside
`data_dictionary.surface_files` (API modules, `portfolio_server.py`, the Telegram command handler); data-broker
projections themselves (they are the read path, and some still read `holdings.json` — P3 moves them); anything outside
`scripts/`. The broker execution file set is never opened (§0 rule 2).

## 9. Decisions this needs from the operator (§17)

1. Grant (or reject) each proposed registry row — listed with its one-line decision in
   [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) "Entity by entity": `cio_prospect`, `security_identity`,
   `positions_store` (supersedes `holdings_accounts`), `transactions`, `broker_stops`, `watchlist_membership`
   (supersedes `watch_discovery`), `scanner_results`, `catalyst_events`, `fused_signals`, `cio_decisions`,
   `cio_theses`, `options_ideas`, `paper_proposals`, `paper_trades`, `alert_events`, `comms_intents`.
2. Ratify AGENTS.md 18.0.0 (`APPROVE_AGENTS_POLICY_18_0_0 <pr_number> <head_sha>`) or rule its class.
3. The P1 migration grant (new authoritative Postgres store).
4. Collapsing the two holdings copies (`holdings.json` → export of `positions_current`) — already ruled 2026-10-22;
   each reader batch is still a decision.
5. Changing what is ranked onto Watch (from `top_ideas.v2` to the prospect).
6. Each retirement in P4.

## 10. Open gaps, stated

- ~~`cio_prospect` projection, the Postgres backend of `InstrumentRecordStore`~~ — built inert in P1 (§11). The
  compare job (P2) and the single writer modules marked `to_build` in the registry do not exist yet.
- `open_trade_alerts` and `ticker_research_state.jsonl` have no identified writer in the inventory; they are listed,
  not classified as settled.
- The n8n placement of `positions-sync` and the transaction ingest (broker reads) needs a §23 ruling before n8n may
  trigger them; the dictionary keeps them on the host.
- Paper-trade and paper-proposal consolidation touches the paper adapter: execution-engineering grant territory
  (§0 rule 2). The dictionary records ceilings; it authorizes no code change there.

## 11. Build status — P0/P1 built, inert (2026-10-22)

Operator directive 2026-10-22: "start executing immediately ... for everything that's not built and not live".
Branch `feat/cio-prospect-p0-p1-20261022`. **Nothing below is live**: no migration is applied, no row is granted,
no lane is past shadow, no page reads anything new. Each piece names what turns it on.

| Piece | Where | State | Turned on by (§17) |
|---|---|---|---|
| Migration `cio_prospect` + `cio_prospect_events` (append-only trigger, no-delete trigger, writer column CHECKed to `InstrumentRecordStore`, least-privilege grants) and its archive-by-rename reverse | `migrations/2026_10_22_cio_prospect.sql`, `.down.sql` | written, **not applied**; proven on a throwaway initdb cluster in the test | the P1 migration grant naming the file's sha256 (printed by the plan tool) |
| Plan / dry run (static checks, inventory, grant strings bound to sha256; no `--apply`, no DB contact) | `scripts/cio_prospect_migration_plan.py` | runnable | — |
| `InstrumentRecord@v1` extended: `apply_prospect` rail (BEHAVIOR_FIELDS refused anywhere, MBI = 0), `conviction_from_components`, `unified_edge_component` (the unified edge persisted with its inputs), `prospect_row` / `prospect_event`, `InstrumentRecordStore.upsert_prospect` (jsonl first, then the Postgres dual-write), `ProspectPgBackend` | `scripts/lib/cio_instrument_record.py` | built; dual-write **inert** (`prospect_store_status`: row not granted, flag off) | row grant + migration + `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1`; no production caller yet (the curator/entry-state wiring is the next PR) |
| Shadow builder (one prospect per security_guid from the opportunity projection, theses, spine, instrument records, re-entry desk, Hermes, scanner cache, the positions_context projection for the held set, and read-only DB inputs) + comparison vs Home / Watch / Telegram | `scripts/lib/cio_prospect_builder.py`, `scripts/cio_prospect_shadow_build.py` | runnable; `--dry-run` writes nothing | — |
| Watchlist curation rules (one membership, ways in with a reason, expiry/invalidation out, size cap per stage, operator adds/stars and held never auto-dropped) | `config/cio_prospect_watchlist_rules.json` (PROPOSED), `scripts/lib/cio_prospect_watchlist_rules.py` | evaluated in the shadow; proposes only | the operator sets the caps and rules ("what is ranked onto an operator surface") |
| n8n lane `cio-prospect-shadow` (registry row, allowlist entry `--with-db`, DRAFT contract), `*/30 9-16 * * 1-5` ET | **stacked PR** `feat/cio-prospect-shadow-lane-20261022` (lane registry, allowlist, contract) | **shadow** (dispatcher fires `--dry-run`; `live_arg` null) | the cio owner marks the contract REVIEWED (§23.19; the contract gates fail until then, by design); canary (`--write-shadow`) is a later registry PR |
| Projection `cio_prospect` (BrokerReadEnvelope@v1; store only when live, else the shadow labelled SHADOW; say_so on gap; per-row stale after `expires_at`); `get_position_view` for TradeInView / Open Trades / Watch | `scripts/lib/data_broker/cio_prospect.py`, catalog entry | registered; no consumer | reader batches of §7 P3 |
| **Position lifecycle on the same record** (operator 2026-10-22, NAVN): `origin` (internal vs operator-initiated, linked by the learning-loop rules `trade_recommendation_linkage`, with the surfaces and values at the entry fill), `position_lifecycle` (fills, every observed stop, excursion, conviction while held, exit cause stop-out / trailing ratchet / target / manual sell, P/L and R), `post_exit_review` (deterministic facts + noise-vs-trend; model prose only through a registered capability — none exists, so it is null and says so), `reentry_advice` (the Re-Entry Desk classifier, conditions, alert levels, one described alert), `stage_phase` exit_review → re_entry_watch, and one append-only `cio_prospect_events` row per fact (idempotent `event_key`) | `scripts/lib/cio_prospect_lifecycle.py`, migration columns + event types, `scripts/lib/reentry_rules.py` (the desk's classifier moved verbatim, re-exported by the desk) | built; shadow | the reader batch below; a capability for review prose (§12, §23.4) if wanted |

Evidence: `tests/test_cio_prospect_foundation_20261022.py` (gate `cio_prospect_foundation_20261022`); quoted dry run
and comparison [`CIO_PROSPECT_SHADOW_COMPARISON_2026-10-22.md`](CIO_PROSPECT_SHADOW_COMPARISON_2026-10-22.md).

Pre-build check (§13.5), recorded: searched §13.4 for *prospect*, *instrument record*, *opportunity*, *unified edge*,
*watchlist curation*; found `InstrumentRecord@v1` / `InstrumentRecordStore` (extended, not cloned — no new `@v1`
type), `OpportunityAssessment@v1` (read as an input), `SecurityResearchSpine@v1` (read), `unified_edge_score`
(called, not reimplemented), `data_broker.positions_context` (the registered positions projection, reused for the held set; the Watch held reader was ruled out because its import closure reaches broker transport, which a dispatched lane may not import), `docs/cio/TWO_WAY_WATCHLIST_CURATION.md`
(the staging/drain path stays the membership writer; the new rules only propose). Nothing else does the per-security
assembly, so the builder is new. For the position lifecycle (NAVN scope, 2026-10-22) the search found the learning-loop linkage (`scripts/lib/trade_recommendation_linkage.py`, `trade_recommendation_links`, TradeInView's `RecommendationOriginCard`) and the Re-Entry Decision Desk classifier (`derive_intel_state`): both are reused — `match_trade` / `attribute` / `r_multiple` are called, not re-implemented, and the desk classifier was moved verbatim into `scripts/lib/reentry_rules.py` (re-exported by the desk) because the desk module's import closure reaches the market-quote provider and broker transport, which a dispatched lane may not import.

**Reader batch PROPOSED for the lane (not self-approved, §17):** the `cio-prospect-shadow` lane reads, READ ONLY, `schwab_round_trips` (+ `trade_closed.stop_used`), `trade_transactions` (proposed domain `transactions`), `stop_lifecycle` (proposed domain `broker_stops`, an observation), `trade_recommendation_links` (when the learning-loop migration is applied) and `ticker_prices` closes, to build the lifecycle. None is `positions_current`, so the UNAPPROVED_READER gate does not fire, but each is a reader the dictionary will count once those rows are granted; the operator grants or narrows this batch.

Backlog (open, in order): (1) operator grants — row `cio_prospect`, the P1 migration, the contract review;
(2) wire the curator and entry-state runner to call `upsert_prospect` (P1 dual-write); (3) the P2 compare job;
(4) a `catalyst_grade` (Gate 2) and `fused_score` producer keyed by GUID; (5) the reader batches (Home + Telegram
cards first); (6) AGENTS.md cites the behaviour rail as `cio_instrument_record.py:390`; it is now at line 450 (it was
already at 422 before this change) — the citation should name the symbol (`apply_cognition` raises
`BehaviorWriteRefused`) instead of a line (§20 PATCH).

## 12. Why the store is still shadow after approval E (audit 2026-10-23, task T-20261023-9c7a5c)

The operator approved item E on 2026-10-22 (~22:30 ET, "yes i approve 'approve all' (A–L)"): the `cio_prospect`
registry row, the migration (sha256 `6bac8924…`) and the read-only reader batch for the shadow lane. On 2026-10-23
the store still persisted nothing. Each live condition, checked:

| Condition | State found 2026-10-23 | Who closes it |
|---|---|---|
| Registry row granted (`domains[]` with an approval) | was still in `proposed_domains[]`, `approval: null` — the approval was never recorded | **recorded by this PR** (`data_dictionary.promote`, approval E quoted verbatim, scope = P1 dual-write + the lane's read-only reader batch) |
| Migration applied | `to_regclass('public.cio_prospect')` and `…_events` are NULL (read-only probe, role `trade_ai`, which has CREATE on `public`) | operator: rolled-back dry run, typed confirm, apply, verify (`scripts/cio_prospect_migration_plan.py` prints the file and sha) |
| `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1` | set in no environment file | operator, in the writer lane's environment, after the table exists |
| Lane `cio-prospect-shadow` | not on main: only in open PR #1953 (rebase task T-20261023-70df13); not in `n8n-live-lanes.env`; contract DRAFT (approval F marks it REVIEWED when it merges) | #1953 merge; the shadow lane never calls the store by design |
| A production caller of `InstrumentRecordStore.upsert_prospect` | **none** — only tests call it (backlog item 2 above) | a build PR: wire the curator / entry-state runner to call `upsert_prospect` |

So even with all four operator steps done, no row persists until item 2 of the backlog is built: the writer has no
caller. The registry grant and the migration are prerequisites, not the switch.
