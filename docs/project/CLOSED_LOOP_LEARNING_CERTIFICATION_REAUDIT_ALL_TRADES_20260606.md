# Closed-Loop Learning Certification — ALL-TRADES RE-AUDIT (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T10:57:07-04:00
Measured at: efcc51365 / not measured

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
- News: structured FK ADDED 2026-06-06 (trade_instance_news; 35 links/27 instances; entry/pre_entry/hold/exit). See CLOSED_LOOP_NEWS_LINKAGE_20260606.md.

### Verdicts
- STRUCTURE = PASS · DATA DENSITY = PARTIAL (edge RESOLVED; Hermes/news/import-lineage still accumulating)
- AUTONOMOUS LEARNING = SHADOW_ONLY / DO_NOT_GRAFT (GO/WAIT + strategy untouched).

### Safety
ALPACA_MODE=paper, live disabled; SELECT-only; no broker/order/GO-WAIT/strategy/live/Phase-205; no graft.

---
## Post-6c3d62f news-linkage certification (2026-06-06)

Commit audited: **6c3d62f**. SELECT-only. Denominator = trade_instances.

### News correlation — RESOLVED (was symbol/date-only)
- Structured FK **`trade_instance_news`** present: 35 links across 27 trade_instances
  (schwab_import 32, alpaca_paper 3); by relation entry_window 16, pre_entry 13, hold_window 4, exit_window 2.
- Summary counts on trade_instances: entry-news 12, hold-news 2, exit-news 1 instances.
- Open-trade hold_window capped (no firehose). Recent-corpus limit (~6wk) → older imports unlinked, honest.

### Full stage snapshot @6c3d62f
- trade_instances 353 (alpaca_paper 51 + schwab_import 302). Imports lack strategy/signal/proposal (302/339/310).
- Edge comparison 101 (paper 43 proposal-edge + schwab 58 per-trade-backtest; 0 fabricated) — RESOLVED.
- News linkage trade_instance_news 35/27 — RESOLVED (structured FK).
- Hermes 1277 total, 7 by trade_instance_id; backlog 181 (schwab 152 + paper 29) — all-trades, drain paused.
- Journal 19 (15 ti); backtest 95 (92 ti). Shadow 57 / efficacy 3 / outcome_fed_back 25/169.
- Graft INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT. closed_paper_trade in canonical path = 0.

### Verdicts
- STRUCTURE = PASS · DATA DENSITY = PARTIAL (edge + news RESOLVED; Hermes backlog + import lineage still accumulating)
- AUTONOMOUS LEARNING = SHADOW_ONLY / DO_NOT_GRAFT (GO/WAIT + strategy untouched).

### Remaining density gaps (not structure)
1. Hermes reflection backlog 181 (all-trades; drain paused per operator).
2. Imported trades lack strategy/signal/proposal lineage (upstream import-ledger limitation).
3. News corpus recent (~6wk) — older imported trades unlinked until corpus deepens.
4. Minor: proposal_snapshot_id NULL on paper edge rows (provenance label only); trade_key NULL on 149 opens.

### Safety
ALPACA_MODE=paper, live disabled; SELECT-only; no broker/order/GO-WAIT/strategy/live/Phase-205; no graft.

---
## Post structured-news-linkage certification — NOISE GUARD (2026-06-06)

Commit audited: **01d3c66**. SELECT-only; no new news links created (read-only validation of existing).

### News linkage — STRUCTURED_LINKAGE_ADDED · DATA_DENSITY_PARTIAL · NOISE_BLOCKED (PASS)
- trade_instance_news: 35 links / 27 distinct trade_instances (schwab_import 32, alpaca_paper 3).
- by window: entry_window 16, pre_entry 13, hold_window 4, exit_window 2.
- linked: imported 26 instances + paper 1.
- **Noise guard (all PASS):**
  - max news links per trade_instance: **3** (not a firehose)
  - avg links per linked trade: **1.30**
  - OPEN trades with hold_window links: **0** (firehose prevented — open trades capped at entry window)
  - non-ticker / topic news linked: **0** (ticker filter holds)
  - total **35** ≈ expected range, NOT 15,108.
- Unlinked reason: older imports predate the ~6-week news corpus; topic/non-ticker excluded; open trades
  capped to entry window. Honest — never fabricated.

### Status of the rest (stable @01d3c66)
- trade_instances 353 (alpaca_paper 51 + schwab_import 302); imports lack strategy/signal/proposal lineage.
- Edge 101 (paper 43 proposal-edge + schwab 58 per-trade-backtest; 0 fabricated; 0 dup) — RESOLVED.
- Hermes 1277 / 7 by ti; backlog 181 (schwab 152 + paper 29) — all-trades; drain paused.
- Journal 15 by ti; backtest 92 by ti. Shadow 57 / efficacy 3 / outcome_fed_back 25/169.
- Graft INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT; closed_paper_trade canonical-path refs 0; paper_trade_id 62 (compat).

### Verdicts
- STRUCTURE = PASS · EDGE = RESOLVED · NEWS = STRUCTURED_LINKAGE_ADDED (noise-blocked)
- DATA DENSITY = PARTIAL (corpus depth + Hermes backlog + import lineage)
- AUTONOMOUS LEARNING = SHADOW_ONLY / DO_NOT_GRAFT (GO/WAIT + strategy untouched).

### Safety
ALPACA_MODE=paper, live disabled; SELECT-only; no broker/order/GO-WAIT/strategy/live/Phase-205; no graft.

---
## Re-audit snapshot v5 (2026-06-06, post backtesting-integrity fixes)

Commit audited: **d8c5581**. SELECT-only. Denominator = trade_instances.

### Closed-loop coverage (continuing to fill)
- trade_instances 353 (alpaca_paper 51 + schwab_import 302).
- execution lineage signal/broker/candidate 27% / 84% / 84% · trade_key 100%.
- Hermes: related_trade_id 13 · trade_instance_id-linked **41** · backlog 149 (drains via manual batches).
- backtest→trade_instance 92 · edge_comparison **101** (schwab 58 + paper 43) · news links 35.
- shadow scores 57 · outcome_fed_back 15% · graft INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT.
- closed_paper_trade in canonical Hermes path: 0 (all-trades targeting intact).

### Backtesting-page integrity — ALL 9 actionable items RESOLVED this session
1 last-run badge (per-pipeline last_runs + last_run_overall) · 2 cadences confirmed · 4 missed-opps dedup
(proposal_id, 1461→168) · 5 missed-opps verdict (sim_outcome_verdict incl MIXED) · 6 optimization
(DISTINCT ON strategy_family, 267→5) · 7 LLM review Ollama health gate (SKIPPED_LLM_UNHEALTHY, no flood;
1671 infra retryable vs 60 parser classified; llm_review_runs 3) · 8 stale-basis pollution (10 invalidated)
· 9 per-row provenance (paper/imported_backtest/simulation + trade_instance_id lineage). 3 endpoint
freshness + 10 learning-shadow-only confirmed.

### Verdicts
- STRUCTURE = PASS · DATA DENSITY = PARTIAL (improving; Hermes backlog 149 + import lineage upstream)
- PAGE INTEGRITY = PASS (all 9 audit items resolved; page now operator-grade with honest labels)
- AUTONOMOUS LEARNING = SHADOW_ONLY / DO_NOT_GRAFT (GO/WAIT + strategy untouched).

### Safety
SELECT-only audit. ALPACA_MODE=paper, live disabled. No broker/order/GO-WAIT/strategy/live/Phase-205.
