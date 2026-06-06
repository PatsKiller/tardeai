# Closed-Loop Learning Certification — ALL-TRADES RE-AUDIT (2026-06-06)

Commit audited: **db1aae3**. SELECT-only audit (no trading/GO-WAIT/strategy/order/broker/Phase-205 changes).

## Verdicts
- **STRUCTURE = PASS** — canonical `trade_instances` (broker/account-neutral) covers paper + imported
  Schwab; Hermes/journal/backtest link by `trade_instance_id`; targeting is all-trades; legacy keys are
  compat-only. The denominator is all-trades, not `paper_trades`.
- **DATA DENSITY = PARTIAL** — Hermes reflection backlog large (drain paused for cert), canonical edge
  comparison still paper-only, imports lack strategy/signal lineage, news symbol/date-only, fidelity 0.
- **AUTONOMOUS LEARNING = SHADOW_ONLY (graft BLOCKED)** — graft verdict INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT
  (n=3 < 20); production GO/WAIT and strategy scoring untouched. Correct safe state.

## 1. Canonical trade instance coverage — PASS
- total: **353** | by source_system: schwab_import 302, alpaca_paper 51 | by broker: schwab 302, alpaca 51
- by account: schwab_rollover_ira 187, schwab_taxable 102, alpaca_paper 43, schwab_roth_ira 13, ALPACA_PAPER 8
- by environment: live 302, paper 51 | by status: closed 187, open 152, cancelled 14
- paper represented 51 | schwab represented 302 | fidelity/manual 0 (no ledger yet — honest)
- missing strategy_id 302 (all imports), proposal_id 310, signal_id 339, trade_key 149 (opens + imports)
- NOTE (hygiene, not a failure): execution_account case split `alpaca_paper`(43)/`ALPACA_PAPER`(8) — normalize.

## 2. Legacy paper-only residue — PASS
- `closed_paper_trade` in canonical Hermes path: **0** (removed; replaced by closed_trade_needing_reflection).
- `paper_trade_id`: 62 script refs = **acceptable legacy compatibility** (columns retained, never canonical).
- `paper_trade_edge_comparison`: 4 refs = legacy source table (compat / backfill source).
- get_ticker_targets references `trade_instances` (5 hits). No new canonical logic is paper-only.

## 3. Hermes linkage — PASS (structure) / PARTIAL (density)
- total 1272 | by trade_instance_id 7 | only-paper-legacy-no-ti **0** | closed instances 187
- **closed_trade_needing_reflection backlog = 181** (schwab_import 152 + alpaca_paper 29) — ALL-TRADES.
- Density low (drain intentionally paused for certification); targeting is no longer paper-only.

## 4. Journal linkage — PASS
- total 19 | by trade_instance_id 15 | only-legacy 0 | (Schwab reviews resolve via trade_key). Imports included.

## 5. Backtest linkage — PASS
- total 95 | by trade_instance_id 92 | only-paper_trade_id 0 | imported 58 + paper 34. Covers imports.

## 6. Edge comparison linkage — RESOLVED 2026-06-06 (was PARTIAL)
> Imported trades now populate canonical trade_edge_comparison via per-trade backtest (101 total: paper 43 + schwab 58). See CLOSED_LOOP_IMPORTED_EDGE_COMPARISON_20260606.md.
- canonical `trade_edge_comparison`: 43, all by trade_instance_id, but **all alpaca_paper**.
- Reason: Schwab imports have no `proposal_backtest_snapshot` (proposal-time expected edge). Per-trade
  backtests exist for 58 imports → a per-trade-backtest edge could populate them (follow-on). Canonical
  table present + keyed; data density paper-only for now.

## 7. Learning / shadow — SHADOW_ONLY / BLOCKED (correct)
- candidate_shadow_scores 57 | candidate_shadow_efficacy 3 (by ti 3)
- outcome_fed_back 25/169 (15%) | proposal_outcome_chain by ti 27
- graft verdict: **INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT** (3 evaluable, 3 correct, n<20 floor)
- production GO/WAIT: UNCHANGED · production strategy scoring: UNCHANGED · graft: BLOCKED.

## 8. News / catalyst correlation — symbol/date only (gap)
- news_articles: 6184 rows, **no trade/proposal FK** (symbol+date only) → entry/hold/exit news = symbol/date only.
- Hermes research/reflection: **implemented + linked** by trade_instance_id (7).
- catalyst_at_entry: free text on 27 paper instances. analyst/sector: not structurally linked.
- 32 trade_instance symbols overlap news (symbol-level). Structured news→trade_instance link = MISSING.

## Data-density blockers (not structure failures)
1. Hermes backlog 181 (all-trades) — drain paused for cert; resume against closed_trade_needing_reflection.
2. Edge comparison paper-only — add per-trade-backtest edge for the 58 imported backtests.
3. Imports lack strategy_id/signal_id/proposal_id (upstream import ledger limitation).
4. News→trade_instance has no structured FK (symbol/date correlation only).
5. fidelity_import 0 (no closed-trade ledger yet); execution_account case normalization.

## Safety proof
ALPACA_MODE=paper · LLM_DISABLE_LIVE_EXECUTION=true. SELECT-only audit; no broker writes, no order/stop,
no GO/WAIT, no strategy, no live enablement, no Phase-205. No production learning graft.

---
## Post-f188ebe imported edge-comparison certification (2026-06-06)

Commit audited: **f188ebe**. SELECT-only. Denominator = trade_instances (not paper_trades).

### Edge comparison — RESOLVED (was PARTIAL)
- total **101**, all linked by trade_instance_id, 0 legacy-only, 0 duplicates.
- by source_system: alpaca_paper 43, schwab_import 58.
- expected_edge_source: proposal_backtest_snapshot 43 (paper), per_trade_backtest 58 (imported).
- fabricated expected edge for imports: **0** (expected_avg_r/win_rate NULL for all per_trade_backtest rows).
- realized_r null 67 / realized_pnl_pct null 9 (imports lack r_multiple — left NULL, honest).
- NOTE (minor lineage): proposal_snapshot_id is NULL on all 101 (paper rows carry expected_edge_source
  label but not the snapshot FK from the legacy table) — cosmetic provenance gap, not a fabrication.

### Other stages (unchanged since prior re-audit)
- trade_instances 353 (alpaca_paper 51 + schwab_import 302; fidelity 0). Imports lack strategy/signal/
  proposal lineage (302/339/310 missing) — upstream ledger limitation; trade_key missing 149 (opens).
- Hermes: 1277 total, 7 by trade_instance_id, 0 legacy-only; backlog closed_trade_needing_reflection 181
  (schwab 152 + paper 29) — all-trades targeting; drain NOT run (cert only).
- Journal 19 (15 ti); backtest 95 (92 ti: schwab 58 + paper 34).
- Shadow: scores 57, efficacy 3, outcome_fed_back 25/169; graft INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT.
- News: no structured FK to trade_instance (symbol/date only).

### Verdicts
- STRUCTURE = PASS · DATA DENSITY = PARTIAL (edge RESOLVED; Hermes/news/import-lineage still accumulating)
- AUTONOMOUS LEARNING = SHADOW_ONLY / DO_NOT_GRAFT (GO/WAIT + strategy untouched).

### Safety
ALPACA_MODE=paper, live disabled; SELECT-only; no broker/order/GO-WAIT/strategy/live/Phase-205; no graft.
