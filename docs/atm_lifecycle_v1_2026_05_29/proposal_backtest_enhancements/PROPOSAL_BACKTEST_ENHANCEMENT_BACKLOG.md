# Proposal/Backtest Enhancement Backlog — 2026-05-29

## P0 — Must fix before next trading day

- [ ] **Fix `expired` case inconsistency** — `_expire_stale_proposals()` in api_v2.py:7501 sets lowercase `expired` instead of `EXPIRED`. 3 rows affected. Single-line fix.
- [ ] **Fix hygiene panel classification field** — api_v2.py:20497-20504 uses `signal_decision` instead of `status`. Proposals with status=EXPIRED but signal_decision=GO are misclassified in ATM Control Room.

## P1 — Important next

- [ ] **Add `run_type` column to backtesting Trades table** — Backtesting.tsx:432-447. API returns run_type but table doesn't display it. Users can't tell which trades are real vs hypothetical.
- [ ] **Surface classification completeness metric** — 3,592/3,593 (99.97%) classified exists only in docs. Add to filter-options data quality section (api_v2.py:19148).
- [ ] **SHFS id=860 manual classification** — Run dry-run classifier with gemma3:12b, review output, apply if evidence sufficient. Likely `speculative_growth` with `requires_review=true`.
- [ ] **Reconcile bidirectional proposal/trade links** — 33 paper_trades have proposal_id but only 20 proposals have paper_trade_id. 13 orphan links to investigate.
- [ ] **Fix ATM expiry to update primary status** — Setting `atm_expired_at` doesn't change `status` from PENDING. Should also set status=EXPIRED.
- [ ] **Add proposal lifecycle inspector** — Single endpoint/view aggregating status + enrichment + satellite data + linked trade outcome.

## P2 — Polish

- [ ] **Add `source_trade_id` FK to strategy_backtest_trades** — Enable direct trace from replay result to originating real trade.
- [ ] **Add `source_proposal_id` FK to strategy_backtest_trades** — Enable trace from replay result to originating proposal.
- [ ] **Add `is_hypothetical`/`source_type` enum to strategy_backtest_trades** — Currently inferred from broker IS NULL (fragile).
- [ ] **Real-time duplicate detection** — Current dedup audit is batch-only via lifecycle_trace.py. Add real-time check.
- [ ] **Unified proposal detail endpoint** — Currently `/api/v2/proposal-detail/<id>` queries wrong table (watchlist_proposals).
- [ ] **Add source badges to mixed-mode backtesting charts** — When "All Run Types" selected, charts mix 3,516 champion + 77 replay with no labeling.
- [ ] **Add next_action computed field to proposal API** — Derived from enrichment_status + status + action_state.
- [ ] **Fix "Clear" button on backtesting page** — Consider keeping run_type filter on Clear, or at minimum adding a warning banner.
- [ ] **LLM review coverage status** — Surface which proposals/backtests have been reviewed by LLM.
- [ ] **Screenshots for all backtesting tabs** — Current Playwright crawler covers routes but not tab-level screenshots.

## P3 — Technical debt

- [ ] **Migrate trade_closed schema** — No CREATE TABLE migration exists. Schema inferred from queries.
- [ ] **Migrate trade_transactions schema** — No CREATE TABLE migration exists. Purely import data.
- [ ] **Track strategy_backtest_results schema drift** — API expects columns not in migration DDL (run_type, total_pnl, avg_pnl, etc.).
- [ ] **Track broker/account columns on strategy_backtest_trades** — Added outside migration tracking.
- [ ] **Add FK constraints** — paper_trades.proposal_id, paper_trade_proposals.paper_trade_id, run_id joins all lack FK constraints.
- [ ] **Reconcile 4 overlapping status dimensions** — status, lifecycle_status, action_state, paper_submit_state create confusion.
- [ ] **Reconcile 3 stale-detection systems** — phase6_proposal_staleness_policy, cleanup_stale_proposals, _expire_stale_proposals have different thresholds and behaviors.
