# Hermes Phase 28A — Trade AI Data Surface Inventory

**Date:** 2026-06-01
**Status:** COMPLETE — read-only audit

---

## Data Surface Map

### 1. Trade Journal

| Item | Value |
|------|-------|
| Tables | trade_thesis_reviews, weekly_learning_digests, weekly_learning_digest_items, strategy_lesson_rollup |
| Learning governance | learning_hypotheses, learning_experiments, learning_evidence, learning_recommendations |
| Scripts | journal_learning.py, report_journal_lesson_quality.py, journal_agent_coach.py |
| Safe for Hermes read | REVIEW — thesis narratives and outcome data are private |
| Contains sensitive data | NO (account info not in journal) |
| Existing Hermes visibility | **NO — no safe view exists** |
| Recommended path | Create hermes_v_journal_learning_context (masked, no raw thesis text) |

### 2. Backtesting Results

| Item | Value |
|------|-------|
| Tables | strategy_backtest_runs, strategy_backtest_trades, strategy_backtest_results, backtest_datasets, champion_challenger_results |
| Scripts | proposal_backtest_engine.py, backtest_analyzer.py, trade_backtest_engine.py |
| Safe for Hermes read | YES — aggregate results are not sensitive |
| Contains sensitive data | NO |
| Existing Hermes visibility | **NO — no safe view exists** |
| Recommended path | Create hermes_v_backtest_results_context (aggregate stats only) |

### 3. Momentum Scout / Morning Scout

| Item | Value |
|------|-------|
| Tables | screener_run_health, screener_symbol_membership, incubator_universe, incubator_events |
| Scripts | finviz_screener_runner.py, screener_run_health.py, morning_digest.py |
| Safe for Hermes read | YES — symbol names and scores only |
| Contains sensitive data | NO |
| Existing Hermes visibility | **NO — no safe view exists** |
| Recommended path | Create hermes_v_screener_context (GO/WAIT/NO counts, catalyst flags) |

### 4. Morning Briefs

| Item | Value |
|------|-------|
| Storage | Files: data/portfolios/reports/ (markdown) + Telegram delivery |
| Scripts | aegis_morning_brief_delivery.py |
| DB table | NONE — file-based only |
| Safe for Hermes read | YES via file access (no sensitive data in briefs) |
| Contains sensitive data | Portfolio values (masked in digest summaries) |
| Existing Hermes visibility | **NO — not in DB, no safe view** |
| Recommended path | File-based Librarian scan of data/portfolios/reports/ |

### 5. Catalyst / News Enrichment

| Item | Value |
|------|-------|
| Tables | catalyst_events, news_articles |
| Quality fields | source_ranking, noise_filter_passed, high_impact_keywords |
| Scripts | catalyst_enrichment.py, news_to_catalyst.py, catalyst_intelligence.py, proposal_catalyst_quality.py |
| Safe for Hermes read | YES |
| Contains sensitive data | NO (raw payloads excluded from view) |
| Existing Hermes visibility | **YES — hermes_v_news_research_context (4.9K rows)** |
| Recommended path | Already visible; add catalyst_events view for quality flags |

### 6. Analyst / External Sources

| Item | Value |
|------|-------|
| Tables | news_articles (multi-source), intelligence_entities |
| Existing Hermes visibility | **YES — via hermes_v_news_research_context and hermes_v_agent_results_context** |
| Gap | No external analyst commentary (Seeking Alpha, etc.) — addressed by SearXNG source_discovery |

### 7. Telegram / AI Analyst Outbound

| Item | Value |
|------|-------|
| Tables | alert_events (telegram_message_id, 30-day retention), notification_log (body_summary, 30-day) |
| Full payloads stored | **NO** |
| Existing Hermes visibility | YES (metadata via hermes_readonly grants) |
| Recommended path | Future hermes_advisory_message_reviews table (Phase 20D design) |

### 8. Proposal Lifecycle

| Item | Value |
|------|-------|
| Tables | paper_trade_proposals, proposal_event_log, proposal_execution_readiness, proposal_evidence_snapshots, proposal_outcome_chain |
| Existing Hermes visibility | **YES — hermes_v_proposal_context (account masked)** |

### 9. Trade Reflection

| Item | Value |
|------|-------|
| Tables | paper_trades (closed trades) |
| Existing Hermes visibility | **YES — hermes_v_trade_reflection_context (account masked, 157 rows)** |

### 10. Pipeline Health

| Item | Value |
|------|-------|
| Tables | pipeline_runs, agent_runs |
| Existing Hermes visibility | **YES — hermes_v_pipeline_health_context (2.9K rows)** |

---

## Summary

| Surface | Hermes Visibility | Safe View | Action |
|---------|------------------|-----------|--------|
| Trade Journal | **NOT VISIBLE** | None | Create view |
| Backtesting | **NOT VISIBLE** | None | Create view |
| Momentum Scout | **NOT VISIBLE** | None | Create view |
| Morning Briefs | **NOT VISIBLE** | File only | File-based scan |
| Catalyst/News | VISIBLE | hermes_v_news_research_context | Add catalyst_events view |
| Analyst Sources | VISIBLE | via news + agent views | SearXNG fills gap |
| Telegram/AI | PARTIAL (metadata) | Direct grant | Future message review table |
| Proposals | VISIBLE | hermes_v_proposal_context | Complete |
| Trade Reflection | VISIBLE | hermes_v_trade_reflection_context | Complete |
| Pipeline Health | VISIBLE | hermes_v_pipeline_health_context | Complete |
