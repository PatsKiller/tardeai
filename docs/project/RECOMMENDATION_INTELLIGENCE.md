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

## Phase 2 — lifecycle journaling + rotation outcomes (done 2026-06-18)

- **Lifecycle events.** `emit_lifecycle_events()` appends immutable lineage events to the existing
  `lifecycle_events` spine — `rec_promoted_to_proposal` (one per proposal), `rec_executed` (one per trade),
  `rec_rotated` (one per rotation edge) — via bulk `INSERT ... SELECT ... WHERE NOT EXISTS` (idempotent,
  `source_table='rec_intel'`). Live: 198 promoted + 51 executed events. Exposed at
  `GET /api/v2/rec-intel/lifecycle[?symbol=X]` and shown as a **Lifecycle Journal** on the page.
- **Rotation outcomes.** `measure_rotations()` computes, for each executed rotation edge, the from-leg
  return vs the to-leg return since the rotation (cached prices) → `rotation_alpha_pct` (to − from). Answers
  "did rotating beat holding the original?" Stored on `rec_rotation_links`; summarized in
  `rotation_outcomes`. (0 measured today — no executed rotations yet; infra ready.)
- **Multi-hop chains.** `build_chains()` assembles A→B→C from the rotation edges (`rotation_chains`).

## Phase 3 — feedback / learning loop (done 2026-06-18)

`compute_source_quality()` turns each ORIGIN source's REALIZED outcomes into a bounded ranking multiplier
(0.50–1.50; 1.0/neutral until 5+ trades), persisted append-only to `rec_source_quality` + written to
`data/runtime/rec_source_quality_latest.json` (integration contract). Live: **screener 1.349× (boosted),
direct/manual 0.92×, incubator 0.718× (demoted)** — the system learned the screener earns more rank than the
incubator. `get_source_quality(source)` is the advisory consumer helper. **Wired into ranking (opt-in):**
`auto_proposal_generator` re-ranks candidate signals by `signal_score × get_source_quality(discovery_source)`
when `REC_SOURCE_WEIGHTING=1` (default OFF — advisory ranking only; never changes risk gates, sizing, or
whether a proposal can execute). Surfaced as the **Source Learning** panel on the page.

## Roadmap (next)

- Construct real rotation edges from executed trade pairs (close X → open Y same account within a window) so
  rotation-outcome measurement has data; today edges come only from persisted `rotation_pairs` + acted
  rotation feedback (both currently sparse).
- Optionally extend the learning multiplier into Hermes watchlist ranking (`hermes_score_weights`), behind
  the same opt-in flag.
