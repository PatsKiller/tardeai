# Hermes Phase 1C — Production Read Access Map

**Date:** 2026-05-30
**Status:** DOCUMENTED ONLY — no grants applied, no views created

---

## Summary

392 total tables audited. Classification:

| Classification | Count |
|----------------|-------|
| ALLOW (via safe view) | 32 |
| ALLOW_WITH_COLUMN_MASK (via filtered view) | 8 |
| DENY | 14 |
| NEEDS_OPERATOR_REVIEW | 6 |
| NOT_RELEVANT (DOF, MARL, legacy, hermes_*) | ~332 |

---

## 1. Market / Ticker Intelligence — ALLOW

| Table | Classification | Hermes Purpose | Denied Columns | View |
|-------|---------------|----------------|----------------|------|
| `ticker_snapshot_daily` | ALLOW | Current technicals for ticker research | none | `hermes_v_ticker_context` |
| `fundamental_data` | ALLOW | Fundamentals for dossiers | none | `hermes_v_ticker_context` |
| `market_quotes` | ALLOW | Latest prices | none | direct |
| `market_quote_snapshots` | ALLOW | Historical price context | none | direct |
| `indicator_confluence_cache` | ALLOW | Confluence/signal strength | none | direct |
| `fused_signals` | ALLOW | Multi-source signal fusion | none | `hermes_v_ticker_context` |
| `catalyst_events` | ALLOW | Catalyst tracking | none | direct |

## 2. Strategy / Scoring — ALLOW

| Table | Classification | Hermes Purpose | Denied Columns | View |
|-------|---------------|----------------|----------------|------|
| `trade_ai_scans` | ALLOW | Scan results, signals | none | direct |
| `ticker_strategy_classifications` | ALLOW | Strategy assignments | none | direct |
| `strategy_performance_snapshots` | ALLOW | Strategy track records | none | direct |
| `strategy_lesson_rollup` | ALLOW | Learned strategy patterns | none | direct |
| `strategy_registry` | ALLOW | Strategy definitions | none | direct |
| `strategy_signals` | ALLOW | Signal history | none | direct |
| `finviz_screeners` | ALLOW | Screener config (no secrets) | none | direct |

## 3. Proposals / Paper Trading — ALLOW via view

| Table | Classification | Hermes Purpose | Denied Columns | View |
|-------|---------------|----------------|----------------|------|
| `paper_trade_proposals` | ALLOW | Proposal review, challenge | none | `hermes_v_proposal_context` |
| `paper_trades` | ALLOW | Trade lifecycle, reflection | none | `hermes_v_trade_reflection_context` |
| `trade_closed` | ALLOW | Historical trade outcomes | none | `hermes_v_trade_reflection_context` |
| `paper_trade_multi_reviews` | ALLOW | LLM review context | none | direct |
| `proposal_outcome_chain` | ALLOW | Outcome tracking | none | direct |
| `proposal_event_log` | ALLOW | Proposal lifecycle events | none | direct |
| `paper_execution_quality` | ALLOW | Execution quality metrics | none | direct |

## 4. Research / Intelligence — ALLOW

| Table | Classification | Hermes Purpose | Denied Columns | View |
|-------|---------------|----------------|----------------|------|
| `news_articles` | ALLOW | News research, reframing | none | `hermes_v_news_research_context` |
| `youtube_transcripts` | ALLOW | Transcript analysis | none | direct |
| `sec_form4` | ALLOW | Insider trading signals | none | direct |
| `fred_economic_series` | ALLOW | Macro context | none | direct |
| `content_embeddings` | ALLOW | RAG metadata (not vectors for writing) | `embedding` (large) | `hermes_v_rag_context_metadata` |
| `intelligence_entities` | ALLOW | Entity intelligence grades | none | direct |
| `content_entity_links` | ALLOW | Entity-content links | none | direct |
| `watchlist_agent_results` | ALLOW | Agent outputs | `raw_response` (large) | `hermes_v_agent_results_context` |
| `deep_overnight_llm_results` | ALLOW | Deep analysis results | none | direct |
| `llm_intelligence_cache` | ALLOW | Cached LLM outputs | none | direct |
| `agent_intelligence_rules` | ALLOW | Rule namespace | none | direct |
| `research_insights` | ALLOW | Extracted insights | none | direct |
| `social_posts` | ALLOW | Social intelligence | none | direct |
| `social_sentiment_history` | ALLOW | Sentiment trends | none | direct |

## 5. Portfolio / Risk — ALLOW_WITH_COLUMN_MASK

| Table | Classification | Hermes Purpose | Denied Columns | View |
|-------|---------------|----------------|----------------|------|
| `stopped_out_watch` | ALLOW | Recovery analysis | `account` masked to type only | `hermes_v_portfolio_context` |
| `stopped_out_watch_history` | ALLOW | Historical recovery | `account` masked | via view |
| `recovery_outcome_log` | ALLOW | Recovery outcomes | none | direct |
| `broker_reconciliation_items` | ALLOW_WITH_MASK | Recon issues | `broker_order_id`, `client_order_id` denied | via view |
| `holdings` | ALLOW_WITH_MASK | Current positions | `account` masked to type | `hermes_v_portfolio_context` |
| `cost_basis_anchors` | ALLOW_WITH_MASK | Cost basis context | `account` masked | via view |
| `portfolio_snapshots` | ALLOW | Portfolio history | none | direct |
| `portfolio_intelligence_events` | ALLOW | Portfolio events | none | direct |

## 6. System / Pipeline — ALLOW

| Table | Classification | Hermes Purpose | Denied Columns | View |
|-------|---------------|----------------|----------------|------|
| `pipeline_runs` | ALLOW | Pipeline health | none | `hermes_v_pipeline_health_context` |
| `pipeline_stages` | ALLOW | Stage definitions | none | direct |
| `pipeline_stage_runs` | ALLOW | Stage execution history | none | direct |
| `system_health_checks` | ALLOW | Health check results | none | direct |
| `system_health_events` | ALLOW | Health events | none | direct |
| `alert_events` | ALLOW | Alert history | none | direct |
| `alert_effectiveness` | ALLOW | Alert quality | none | direct |
| `notification_log` | ALLOW | Notification history | none | direct |
| `daily_system_metrics` | ALLOW | System KPIs | none | direct |

## 7. DENY — Sensitive / Personal / Credentials

| Table | Reason |
|-------|--------|
| `personal_situation` | Personal key-value store (SSDI, income, health data) |
| `personal_tax_history` | AGI, taxable income, deductions, tax returns |
| `personal_history` | Personal life events |
| `tax_events` | Tax-sensitive transactions including trust transfers |
| `telegram_proposal_messages` | Contains `chat_id` (personal identifier) |
| `paper_trade_commands` | Contains `chat_id` |
| `accounts` | Account names/types may include institution identifiers |
| `account_transfers` | Transfer details between accounts |
| `account_value_anchors` | Account valuations |
| `portfolio_income_goals` | Personal income targets |
| `trade_instructions` | Execution instructions with account details |
| `system_controls` | System config that may contain operational secrets |
| `config_documents` | May contain configuration with sensitive values |
| `config_change_proposals` | Config change records |

## 8. NEEDS_OPERATOR_REVIEW

| Table | Reason |
|-------|--------|
| `incubator_universe` | May contain operator's private research notes |
| `incubator_events` | Incubator state changes — review before granting |
| `watchlist_items` | Contains LLM health assessments — probably safe but verify |
| `john_decision_history` | Operator decision log — useful for Hermes learning but personal |
| `john_decision_queue` | Active decision queue — timing-sensitive |
| `action_queue` | Active action items — check for sensitive payloads |

---

## Masking Rules

| Column Pattern | Rule |
|----------------|------|
| `account` | Mask to account type only (e.g., 'IRA', 'taxable') — strip institution name |
| `chat_id` | DENY — personal Telegram identifier |
| `broker_order_id`, `client_order_id` | DENY — broker-specific identifiers |
| `raw_response` | Exclude from views (large, may contain prompt leaks) |
| `embedding` | Exclude from metadata views (large JSONB vectors) |

---

## Not Relevant (~332 tables)

These are excluded from the Hermes read map:

- `dof_*` (31 tables) — DOF Auction system, not trade-related
- `marl_*` (7 tables) — MARL simulation, experimental
- `hermes_*` (6 tables) — Hermes already owns these
- `content_embeddings_qwen3_*` (2 tables) — Shadow/test embedding indexes
- Legacy/backup tables
- Intermediate pipeline tables not useful for research
