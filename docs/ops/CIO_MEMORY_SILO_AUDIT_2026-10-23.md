# CIO memory silo audit — every per-security fact vs the CIO record (2026-10-23)

```
Status:      ACTIVE
as_of:       2026-10-23T10:15:00-04:00
Measured at: origin/main 53aa1b619 (code); live stores read-only 2026-10-23 09:15–09:50 ET (file reads under
             persistent-state/data, single-symbol SELECTs through a server-enforced READ ONLY session; no writes)
```

Operator, 2026-10-23, verbatim: *"Anything that's such as a security catalyst related to the security, anything for
the security . The CIO agent needs to have it in memory. We should have no silos."*

Governing rules: AGENTS.md §26 (18.0.0 — the CIO prospect record is the single per-security truth, one store / one
writer, conflicts shown never resolved), §7A (one read path through projections), "Shared security research — NO
SILOS". Architecture: [`docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md`](../architecture/CIO_PROSPECT_DATA_FOUNDATION.md).

## 0. Summary

**46 producers of per-security facts inventoried. 3 WIRED, 16 PARTIAL, 27 SILO.** Two further defects are not
producers but CIO paths that never transition when a position is sold (InstrumentRecord `HELD:*`, `cio_theses`).

| Status | Count | Meaning |
|---|---|---|
| WIRED | 3 | the fact reaches CIO memory keyed by GUID (prospect, M2 or the GUID-keyed wake feed) and is current |
| PARTIAL | 16 | it reaches a CIO store only as a score, a headline, a symbol-keyed copy, a dormant path, or only the in-memory shadow prospect |
| SILO | 27 | no CIO consumer reads it at all |

Three findings frame everything below:

1. **The integrator exists but persists nothing yet.** `scripts/lib/cio_prospect_builder.py` assembles one prospect per
   `security_guid` and records conflicts, but runs only as a `--dry-run` shadow (lane `cio-prospect-shadow`, stacked
   PR #1953, DRAFT contract) and `InstrumentRecordStore.upsert_prospect` has no production caller; the Postgres
   dual-write is inert until the operator grants the `cio_prospect` row and the P1 migration `[CODE]`
   (`cio_instrument_record.py` `prospect_store_status`). So "reaches the prospect" below means *the shadow sees it*.
   Wiring a producer into the builder is still the right step (§26: the record is the integrator); it becomes memory
   when the operator turns the store on.
2. **The CIO's live per-security judgment is the opportunity curator, and it reads no catalyst, news, SEC, scanner,
   Active Trader, alert, proposal or options store.** `data_broker/opportunity.py` `gather()` (:516–646) reads quotes,
   price stats, indicators, analyst targets, entry ladders, watchlist strategy cards, Hermes score components,
   fundamentals, profiles, positions context, the re-entry desk and sector weights `[CODE]`.
3. **Almost every persisted store is symbol-keyed.** GUID-capable carriage exists upstream (the Trade AI orchestrator
   stamps `security_guid` on observations; `scanner_candidate_projection` resolves GUIDs on read) and is dropped at
   persistence (`trade_ai_scans`, `alert_events`, `fused_signals`, the Gate 4 ledger, `paper_trade_proposals`) `[CODE]`.

## 1. The two contradictions the operator saw (P1)

### 1.1 SAIQ — two catalyst verdicts, none on the CIO record `[VERIFIED]`

Read-only, 2026-10-23 ~09:20 ET:

| Source | What it says about SAIQ | As of |
|---|---|---|
| `trade_ai_cache.json` (Trade AI scan, decision MANUAL_REVIEW) | catalyst "WISeSat.Space and SEALSQ Advance Satellite Cybersecurity Hardening…", `catalyst_verified: false`, confidence 0.0 | published 2026-10-20, observed 12:55Z today |
| `catalyst_events` (newest typed rows) | "Morning Market Movers: SAIQ…" `news_momentum`, confidence 0.56 → **"verified"** by the projection's legacy rule (`confidence >= 0.3`, `LEGACY_CONFIDENCE_THRESHOLD`) | 2026-10-05 |
| Hermes momentum catalyst research (`data/hermes/momentum_catalysts/2026-10-23_catalysts.jsonl`) | `no_clear_catalyst` | 08:25Z today |
| CIO opportunity projection | **no catalyst factor at all** (factors: technical, momentum, risk_reward, portfolio_fit) | 13:00Z today |
| CIO prospect (shadow) | `catalyst_grade: null` — listed in `NOT_WIRED_COMPONENTS` | — |

Mechanism `[CODE]`: there is no single catalyst verdict. At least four independent ones exist — the catalyst_record
projection's legacy threshold (every news-derived row has relevance > 0.3, so every one reads "verified"), the Hermes
scalp catalyst search, the Trade AI scan's own `catalyst_verified` (`trade_ai_orchestrator.py:1002–1065`), and the Hermes
watchlist scorer's `news_catalyst` — each from a different store and window, none reconciled, none on the CIO record.
**Also measured:** SAIQ's `catalyst_events` rows carry `subject_guid d2d4c0a0-…` while the identity registry's
`security_guid` is `214d27ec-…` (7 rows; NVDA and NAVN rows match the registry) — an identity split on the catalyst
store itself.

### 1.2 NAVN — held after the sale `[VERIFIED]`

- `trade_transactions`: NAVN Buy 500 @ 25.64 on 2026-10-19 11:01; **Sell 500 @ 26.02 on 2026-10-22 15:59 ET**.
- `positions_current`: no NAVN row (max `as_of` 09:09 ET today).
- `holdings.json`: NAVN removed only at the **09:07 ET run today** (`removed: ["NAVN"]`). The eight prior
  `schwab_position_sync` runs logged `schwab_rollover_ira: degraded_noop … no Schwab login token` — the file was stale
  for ~18 h with no staleness guard (`logs/schwab_position_sync.log`; run times inferred from the cron, the log has no
  timestamps).
- `cio_opportunity_projection.json` as_of 13:00Z today: **NAVN `ADD`, conviction 83.7, `position_status: owned`,
  reentry_state "CURRENTLY HELD"** — the curator's held flag is `positions_context.owned = bool(shares)` from
  `holdings.json` (`positions_context.py:93`; `opportunity.py:344–361`), with no cross-check against fills.
- The shadow prospect *does* catch it — `held` conflict (opportunity "owned" vs not held) and `stance_after_exit`
  (ADD vs exited, `schwab_round_trips srt:607228`) — but the shadow is not read by any surface.
- Related, never-transitioning paths `[CODE]`: InstrumentRecord `HELD:<SYM>` is never moved to EXIT
  (`cio_migrate_instrument_records.py:184` mints it; nothing transitions it; `wake_subject_selector.py:295–345` and
  `cio_wake_dispatcher.py:681` wake HELD records by cadence with no holdings check). Live: a `HELD:ARKX` tip exists
  while ARKX is not in `holdings.json`. `cio_theses` reads no holdings (NAVN thesis still `active`). M2 has a declared
  `held_view` predicate with no producer.

## 2. The inventory

Columns: **Store** · **Key** (GUID or symbol) · **Reaches the CIO today — how, latency** · **Verdict** · **Priority**.
CIO consumers checked: `cio_prospect_builder` (FILES / DB_QUERIES / LIFECYCLE_QUERIES), `InstrumentRecordStore`,
`cio_opportunity_curator` + `data_broker/opportunity.gather`, `cio_entry_state_runner`, `CIOEnvelopeIntegrator` (M2;
only two envelope callers: `options_memory_projector.py`, `aec_command_center_cycle.py:334`), `cio_belief_writer`,
persistent wake (`persistent_agent_wake`, `wake_subject_selector`, `cio_wake_*`, `symbol_thesis_event_wake`), the CIO
event bus, the material-change scan/publisher, the research spine, `cio_theses`. Evidence: `[CODE]` file:line from the
read-only sweep at 53aa1b619 unless marked `[VERIFIED]`.

### 2.1 Catalysts, news, sentiment, SEC, fundamentals

| # | Producer → store | Key | Reaches the CIO today | Verdict | P |
|---|---|---|---|---|---|
| 1 | news_ingestion → `news_articles`, `sentiment_observations` | symbol + subject/issuer GUID (`writers/news_articles_writer.py:89`) | article *count* only: `material_change_detector.py:686` news bursts → `material_changes` (GUID) → wake; sentiment unread | PARTIAL | P2 |
| 2 | news_to_catalyst (+ news_ingestion, sec_filing_events) → `catalyst_events` | symbol + `subject_guid` (87% populated) | reentry-desk copy → prospect `unified_edge.catalyst_strength` only; headline string on the entry-state card (`cio_entry_state_runner.py:118`); new catalysts → material_changes → wake. Curator does not read it | PARTIAL → **wired by PR-A** | **P1** |
| 3 | catalyst_momentum_engine → `hermes_research_intelligence` (`momentum_catalyst`) | symbol | indirect: hermes_news_bridge → news_articles → news_to_catalyst → #2 (≤12 h) | PARTIAL | P3 |
| 4 | Hermes momentum catalyst research → `data/hermes/momentum_catalysts/<day>_catalysts.jsonl` | symbol | none (readers: social_scalp_scanner, scanner_candidate_projection, scalp_list, Gate 4, catalyst graph) | SILO → **wired by PR-A** | **P1** |
| 5 | catalyst graph → `data/cio/catalyst_graph_latest.json` | subject/issuer/event GUID | none (only `cio_event_lifecycle_census.py`) | SILO | P2 |
| 6 | `catalyst_symbol_impact` | symbol | none | SILO | P3 |
| 7 | `cio_graph_impact*` (computed on request) | — | API-time only, not in memory | SILO | P3 |
| 8 | social / sentiment → `social_posts`, `social_sentiment_history`, `intelligence_entities.social_score` | symbol | one weighted factor inside the Hermes composite; the prospect selects `hermes_composite_score` and never uses it | SILO | P2 |
| 9 | aegis → `advisor_observations`, `aegis_*`, `watchlist_agent_jobs` | symbol | none; "aegis" is an allowed spine silo but no aegis script contributes | SILO | P2 |
| 10 | SEC filings → `data/cio/sec_filing_events.jsonl` (+ catalyst_events rows) | symbol | high-severity 8-K → material_changes (GUID) → wake (pointer only) | PARTIAL | P2 |
| 11 | SEC XBRL / forms → `sec_xbrl`, `sec_form` | symbol | `sec_xbrl` read only by `options_cio_review.py`; `sec_form` none | SILO | P3 |
| 12 | fundamentals → `fundamental_data` | symbol | curator "fundamental" factor score (≤7 d + 30 m) | PARTIAL | P3 |

### 2.2 Scanner, Trade AI, Active Trader, alerts, fused signals

| # | Producer → store | Key | Reaches the CIO today | Verdict | P |
|---|---|---|---|---|---|
| 13 | Trade AI scans → `trade_ai_scans` (6 writers, UNCONSOLIDATED) | symbol (no GUID column) | prospect `scanner_score` (weight 0.10) + "scanner_verdict" way-in (shadow) | PARTIAL | P2 |
| 14 | Trade AI cache → `runtime/trade_ai_cache.json` (`source_observations`, `setup_run_summary`) | symbol; observations carry `security_guid`, ignored | prospect fallback decision only; its **catalyst** fields unread (→ PR-A); `setup_run_summary` unread | PARTIAL → catalyst **wired by PR-A** | P1/P2 |
| 15 | Finviz screens (screener, movers, scalp/hot lists) | symbol | only where they feed #13/#14 | SILO | P3 |
| 16 | Active Trader alerts → `data/active_trader/momentum_alerts.jsonl` | symbol | none (readers: scanner_candidate_projection, unified_momentum_alert, momentum_setup_evidence) | SILO | P2 |
| 17 | AT premarket heads-ups (`premarket_watch`) | symbol | none | SILO | P2 |
| 18 | L2 / microstructure → `data/active_trader/micro/<day>/<SYM>.jsonl` | symbol | none | SILO | P3 |
| 19 | MomentumSetupEvidence@v1 / SetupReadiness@v1 (`momentum_setup_evidence.py`; readiness on PR #1989, unmerged) | symbol; `lineage.security_guid` passed through | computed on read, never persisted except readiness inside the Gate 4 ledger row | SILO | P2 |
| 20 | Gate 4 unified alerts → `data/runtime/unified_momentum_alerts.jsonl` (UnifiedMomentumAlert@v1, shadow) | `day:SYMBOL:event` | none | SILO | P2 |
| 21 | `alert_events` (17 writers) | symbol | none (only `broker_access.py:688` stop-health) | SILO | P2 |
| 22 | `fused_signals` (`signal_fusion.py`) | symbol, no GUID | `cio_decision_engine.py:74` → `cio_decisions`, lane **PAUSED since 2026-08-08**; prospect lists it NOT_WIRED | SILO | P2 |

**No scan, AT alert, Gate 4 alert or fused signal ever wakes the CIO** `[CODE]`: the only per-security event-bus emitter
is `cio_entry_state_runner.py:471` (`watch.new_signal`); `symbol_thesis_event_wake.py:27–37` maps
`social_material_transition` / `candidate_discovery`, which no scanner or AT code emits.

### 2.3 Watch, proposals, analyst, options

| # | Producer → store | Key | Reaches the CIO today | Verdict | P |
|---|---|---|---|---|---|
| 23 | watch directives → `watch_directives`, `watch_directive_hits` | directive id; nullable GUID columns | none | SILO | P2 |
| 24 | directive promotion → `watchlist_items.in_directive_watch` (+ PR #1960 in flight) | symbol (+ nullable GUID) | only indirectly via status='active'; the flag itself is never selected | PARTIAL | P2 |
| 25 | `watchlist_items` (25 writer files) | symbol (+ nullable GUID) | builder (shadow), curator universe, entry-state universe, material_change_detector | PARTIAL | P3 |
| 26 | `strategy_watchpool` | strategy+symbol | none | SILO | P3 |
| 27 | `hermes_watchlist_lifecycle.json` | symbol | builder `hermes_score` + a lifecycle conflict (shadow) | PARTIAL | P3 |
| 28 | `watchlist.json` | symbol | one-off `cio_watch_instrument_admit` → WATCH records (not scheduled) | PARTIAL | P3 |
| 29 | `operator_starred_symbols` | symbol | builder query selects **`created_at`; the column is `starred_at`** `[VERIFIED]` information_schema → the read errors, `operator_star` never fires; entry-state reads it | PARTIAL (broken) → **fixed by PR-A** | **P1** |
| 30 | proposals → `paper_trade_proposals` (51 writer files) | proposal id / symbol, no GUID | entry-state universe only; prospect stage `proposed` is never set by any code | PARTIAL | P2 |
| 31 | analyst targets → `yahoo_analyst_targets_history`, `pro_analyst_pills_latest.json` | symbol | curator "analyst" factor score | PARTIAL | P3 |
| 32 | rating / PT changes → Discovery Inbox (`hermes_analyst_signal_discovery.py`) | symbol | none | SILO | P2 |
| 33 | analyst / PT headlines → `catalyst_events` → `material_changes` | symbol + subject_guid | material_changes → wake feed → persistent wake | WIRED (wake) | — |
| 34 | analyst reports / urgent changes (PDFs + registry) | symbol | none (operator email) | SILO | P3 |
| 35 | Research Intelligence briefs → `ri_snapshots`, `research_intelligence_feedback`, `ri_research_queue` | item / symbol | none | SILO | P3 |
| 36 | options theses → `data/cio/options_theses.jsonl` | option_strategy_guid + underlying issuer_guid | **M2 via `options_memory_projector`** run each options tick (≤15 min; its own lane RETIRED, `NO_CONSUMER_REASON` text stale); the prospect reads no options | PARTIAL | P2 |
| 37 | `options_approval_queue` | proposal / symbol | none | SILO | P2 |
| 38 | `data/options_intent/latest.json` | intent / symbol | none | SILO | P3 |

### 2.4 Positions, fills, stops, exits, re-entry, journey

The broker execution file set was not opened (§0 rule 2); broker sync modules are named, not read.

| # | Producer → store | Key | Reaches the CIO today | Verdict | P |
|---|---|---|---|---|---|
| 39 | broker syncs → `holdings.json` `holdings[]` | symbol + account | nearly every CIO held check (curator, entry state, re-entry desk, material scan, prospect held set) — **single point of failure: a no-op sync leaves it stale with no guard (NAVN, ~18 h)** | WIRED (SPOF) | **P1** |
| 40 | `holdings.json` `resolved_sector_contributors` (lookthrough, daily) | symbol | sector readers; NAVN still listed today | SILO (stale) | P3 |
| 41 | `positions_current` (`positions_sync.py`) | account + symbol | none — deliberately, the reader batch is not approved | SILO (by design) | approval |
| 42 | `trade_transactions` (transaction ingest) | symbol + dedupe_key | `last_sell_date` only (`positions_context.py:78–86`) → "recently sold"; never used to contradict "owned" | PARTIAL → **guard by PR-B** | **P1** |
| 43 | `schwab_round_trips` + `trade_closed` (journal builder) | `srt:<id>` + symbol | prospect lifecycle (shadow) only | SILO | P2 |
| 44 | `stop_lifecycle` (observed stops) | symbol + order_id | prospect lifecycle `stop_history` (shadow) only | SILO | P2 |
| 45 | re-entry desk → `reentry_decision_desk_latest.json` | symbol | entry-state runner, curator `reentry_rows()`, prospect FILES (minutes) | WIRED | — |
| 46 | TradeInView journey (`data_broker/trade_journey.py`, PR #1955 unmerged) | symbol / round_trip_key | none; reads the prospect once it is live | SILO | P2 |

Transition defects (not producers): **D1** InstrumentRecord `HELD:*` never moves to EXIT and keeps being woken (P1 —
ARKX live). **D2** `cio_theses` never reads positions; a sold name keeps an `active` held thesis (P2).

## 3. Wiring plan (prioritized)

Rule for every item (§26): the CIO record is the integrator. A producer's fact enters through the existing integrator
path — the prospect builder's inputs → `apply_prospect` → `InstrumentRecordStore` → `cio_prospect` /
`cio_prospect_events` (append-only, idempotent `event_key`) — or, for cognitive memory, `CIOEnvelopeIntegrator`
envelopes. **No new parallel store.** A new reader or writer that needs a §7A/§26 grant is built inert and listed in §4.

### P1 — facts the CIO currently contradicts

| Item | Change | PR |
|---|---|---|
| P1-1 catalysts (#2, #4, #14) — SAIQ | the prospect's `catalyst_grade` carries the facts from `catalyst_events` (through the registered `catalyst_record` projection, new bulk read), the Trade AI scan, the Hermes momentum catalyst research and (only when the store is unread) the desk copy; verdict VERIFIED / UNVERIFIED / DISAGREE / NONE; two verdicts → `catalyst` conflict; a row under another GUID → `catalyst_identity` conflict; a scanner-cited catalyst missing from the store → named gap; no grade invented; a change is a prospect `update` event | PR-A |
| P1-2 starred (#29) | builder query reads `starred_at` | PR-A |
| P1-3 held after sale (#39, #42) — NAVN | `positions_context` marks a holding whose broker sell fill is newer than the holdings snapshot (`sold_after_snapshot`); the curator records it as a `held` conflict on the assessment (shown on every surface that renders the assessment) and, behind a config switch that is **off** until the operator turns it on, stops advising ADD/HOLD on it | PR-B |
| P1-4 `HELD:*` never transitions (D1) — ARKX | wake selection should treat a HELD record whose security is no longer held as an exit-review subject; the prospect already derives `stage` from positions + round trips and supersedes the kind prefix once live. **Plan only** (touches which subjects the CIO wakes; owner review) | — |
| P1-5 holdings staleness (#39) | a broker sync that no-ops for an account should mark that account's holdings stale. **Broker sync code — out of scope without an `execution-engineering` grant (§0 rule 2).** Reported for the operator | — |

### P2 — facts the CIO never sees

| Item | Plan |
|---|---|
| P2-1 momentum signals (#16, #17, #19, #20, #21) | fold the Gate 4 ledger rows (`unified_momentum_alerts.jsonl`, which already carries SetupReadiness@v1 from PR #1989 — reuse it, never recompute) into a prospect `signals` block keyed by GUID, with a `watch.new_signal` wake on READY; AT alerts reach the record through the Gate 4 ledger (the AT engine logs the unified alert beside its legacy alert, PR #1971), not by reading `scripts/active_trader/**` (broker execution file set) |
| P2-2 proposals (#30) | the builder reads open proposals through a proposal projection and sets stage `proposed` with the proposal id as evidence; `paper_trade_proposals` is a proposed domain (`paper_proposals`) — reader grant needed |
| P2-3 watch directives (#23, #24) | directive id + reason as a prospect `watchlist` way-in (`origin: operator_directive`); coordinate with PR #1960 (directive flag source) |
| P2-4 options (#36, #37) | the prospect reads the options thesis head per underlying `issuer_guid` (NO SILOS rule 5); the M2 path stays |
| P2-5 SEC filings, social, aegis, catalyst graph (#5, #8, #9, #10) | contribute to the research spine (`contribute(...)`, CIO-owned) so the prospect's `research` block carries them; the catalyst graph is GUID-keyed already — read it as an input |
| P2-6 fused signals (#22) | carry `security_guid` at write; then the NOT_WIRED `fused_score` component (weight is §17) |
| P2-7 round trips, stops, journey (#43, #44, #46) | already in the prospect lifecycle (shadow); live once the store is granted; TradeInView reads the prospect (PR #1955) |
| P2-8 rating changes (#32), theses on exit (D2) | rating-change events into the spine; the thesis store reads the prospect stage |

### P3 — later

#3, #6, #7, #11, #12, #15, #18, #25–#28, #31, #34, #35, #38, #40: enrich or consolidate once P1/P2 land; most already
reach the CIO as a score.

## 4. Approvals the operator holds (§17)

1. **Grant the `cio_prospect` registry row, the P1 migration (`migrations/2026_10_22_cio_prospect.sql`, sha256 from
   `scripts/cio_prospect_migration_plan.py`) and the `cio-prospect-shadow` contract REVIEW** — until then every wiring
   above lands in the shadow only and nothing is CIO *memory*. This is the single unblocking decision.
2. **The `cio-prospect-shadow` lane reader batch** (CIO_PROSPECT_DATA_FOUNDATION.md §11): add `catalyst_events`
   (through `catalyst_record`) and the Hermes momentum catalyst day files (PR-A).
3. **Turn on the sold-after-snapshot stance guard** (PR-B, `config/opportunity_conviction.yaml`
   `position_conflict.suppress_add_hold`, default false) — it changes what Home's ADD list shows, which is "what is
   ranked onto an operator surface".
4. **Proposed domains to grant before P2 readers:** `catalyst_events`, `scanner_results`, `alert_events`,
   `fused_signals`, `paper_proposals`, `options_ideas`, `positions_store` reader batch for the CIO.
5. **Broker sync staleness guard** (P1-5): needs an `execution-engineering` grant naming the sync file, or an
   operator decision on where the guard lives.
6. **SAIQ identity split:** 7 `catalyst_events` rows under `subject_guid d2d4c0a0-…` vs registry `214d27ec-…` — the
   operator decides which is right (§0 rule 5: reported, not remediated).

## 5. What this audit cannot see

The sweep is grep- and read-based: writes spelled other than the store name, paths assembled far from the write, n8n
workflow bodies, `ops/wake_selection_feed.py` (not in this repo), and the broker execution file set (not opened). The
NAVN sync timing is inferred from the cron because the log has no timestamps. A row marked SILO means no CIO consumer
was found, not that none can exist.
