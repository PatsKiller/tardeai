# Recommendation Intelligence Engine

**Status:** Active (Phase 1 — foundation shipped 2026-06-18)
**Goal:** trace every ticker from its originating recommendation source → execution → outcome → rotation,
attributable by source / strategy / account, and use the results to improve future recommendations.

This is a **unification + activation layer**, not a new silo. Every source in Trade AI already carries
attribution; this engine connects them into one auditable lineage and computes the cross-source analytics
that did not previously exist.

## Data model

Self-bootstrapping (the engine runs `CREATE TABLE IF NOT EXISTS` on start):

- **`rec_ticker_attribution`** — one row per `(symbol, source_type, source_ref_table, source_ref_id)`.
  Columns: `source_detail` (jsonb), `rationale`, `account`, `first_seen_at`, `last_seen_at`, `occurrences`,
  `executed`. UPSERT keeps the earliest `first_seen_at` and latest `last_seen_at`, ORs the `executed` flag.
  `source_type` ∈ `watchlist | directive | proposal | scan | rotation | hermes_research | cio | holding |
  execution`.
- **`rec_rotation_links`** — rotation edges `(from_symbol → to_symbol, account, executed, occurred_at,
  source_type, rotation_pair_id)` — the chain spine for AAPL→NVDA→AVGO.
- **`lifecycle_events`** (existing immutable spine, `lifecycle_event_writer.write_event()`) — reused for the
  append-only event history; Phase 2 wires lifecycle/journal events for add→promote→execute→rotate→exit.

## Ingestion engine

`scripts/recommendation_intelligence_engine.py` (daily cron 07:10; `--dry-run`, `--analytics`):
ingests `watchlist_items`, `watch_directives` (ticker), `paper_trade_proposals` (executed flag from
`outcome_trade_id`/`executed_at`), `trade_ai_scans` (GO/WAIT), `hermes_research_intelligence`,
`cio_decisions`, `rotation_pairs` + rotation feedback (`llm_feedback_observations` acted rows),
`holdings.json` (held = executed), `paper_trades` (executions + realized P&L). Idempotent UPSERT; each source
commits independently so one bad row can't roll back the run. Live: **3,434 tickers, 415 multi-source, 108
executed.**

## Analytics

`analytics(cur)` (exposed via API): coverage by source, **return by ORIGIN source** (closed trades grouped by
the proposal's `discovery_source` — e.g. screener 66.7% win / +7.2% avg vs incubator 15.8% / −0.28%),
performance by strategy, multi-source tickers (earliest→latest source), rotation links.

## API

- `GET /api/v2/rec-intel/summary` — full analytics payload (cached 5 min).
- `GET /api/v2/rec-intel/ticker?symbol=X` — full per-ticker provenance: every source that introduced it
  (chronological), earliest + most-recent source, executed flag, realized P&L on executed legs, rotation
  edges. (e.g. GCTS: scan 05-04 → watchlist 05-11 → proposal 05-11 → executed 05-13 → research 06-03 →
  directive 06-17.)

## UI

`/v3/rec-intel` (nav "Rec Intelligence"): summary tiles, a **Trace-a-ticker** lineage lookup, the
Return-by-Origin-Source table, Coverage-by-Source bars, Performance-by-Strategy, and a clickable
Multi-Source-Tickers grid (earliest→latest source). Read-only; no broker action.

## Roadmap (phases)

- **Phase 1 (done):** data model, ingestion across all sources, attribution + execution flagging, analytics,
  API, UI, cron.
- **Phase 2 (next):** lifecycle/journal events for each transition (added→promoted→executed→rotated→exited)
  via `lifecycle_event_writer` + the v3 Journal page; richer rotation-chain construction (multi-hop) and
  rotation-outcome measurement (did the rotation beat holding the original?).
- **Phase 3:** feedback/learning loop — feed per-source realized outcomes back into Hermes ranking /
  confidence (adjust `source_performance.scar_factor` + `hermes_weight_calibration`) so good sources rank
  higher over time. Hooks already exist (`proposal_outcome_chain`, `agent_recommendation_outcomes`,
  `source_maturity`); Phase 3 closes the loop into ranking.
