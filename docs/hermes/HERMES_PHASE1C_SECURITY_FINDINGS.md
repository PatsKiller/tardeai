# Hermes Phase 1C — Security Findings

**Date:** 2026-05-30
**Status:** AUDIT COMPLETE — no grants applied

---

## Sensitive Columns Found

Only 3 columns matched sensitive patterns across 392 tables:

| Table | Column | Type | Action |
|-------|--------|------|--------|
| `telegram_proposal_messages` | `chat_id` | Personal Telegram ID | DENY table |
| `paper_trade_commands` | `chat_id` | Personal Telegram ID | DENY table |
| `iris_run_log` | `tokens_used` | LLM token count (not a secret) | ALLOW |

## Tables Denied (14)

| Table | Reason |
|-------|--------|
| `personal_situation` | Personal key-value store (SSDI amounts, health data, income) |
| `personal_tax_history` | AGI, taxable income, deductions, tax rates |
| `personal_history` | Personal life events |
| `tax_events` | Tax-sensitive transactions, trust transfers |
| `telegram_proposal_messages` | Contains chat_id |
| `paper_trade_commands` | Contains chat_id |
| `accounts` | Institution-specific account identifiers |
| `account_transfers` | Account transfer details |
| `account_value_anchors` | Account valuations |
| `portfolio_income_goals` | Personal income targets |
| `trade_instructions` | Execution instructions with account specifics |
| `system_controls` | System operational config (may contain runtime secrets) |
| `config_documents` | Configuration storage |
| `config_change_proposals` | Config change records |

## Tables Needing Operator Review (6)

| Table | Question |
|-------|----------|
| `incubator_universe` | Contains operator research notes — useful but potentially private |
| `incubator_events` | State changes — useful for Hermes incubator agent |
| `watchlist_items` | LLM health assessments — probably safe |
| `john_decision_history` | Operator decisions — extremely useful for Hermes learning but personal |
| `john_decision_queue` | Active decision queue — timing-sensitive |
| `action_queue` | Active actions — check for sensitive payloads |

## Masked Columns

| Column | Tables Affected | Masking Rule |
|--------|----------------|-------------|
| `account` | paper_trade_proposals, paper_trades, stopped_out_watch, holdings, cost_basis_anchors | Mask to account type ('IRA', 'Roth', '401k', 'Taxable') |
| `broker_order_id` | broker_reconciliation_items | Exclude from view |
| `client_order_id` | broker_reconciliation_items | Exclude from view |
| `raw_response` | watchlist_agent_results | Exclude (large, may contain prompts) |
| `raw_payload` | news_articles | Exclude (large, raw HTML) |
| `embedding` | content_embeddings | Exclude from metadata view (large 768-dim vector) |
| `tfidf_terms` | content_embeddings | Exclude from metadata view (large JSONB) |
| `input_data_snapshot` | watchlist_agent_results | Exclude (large) |
| `full_result` | watchlist_agent_results | Exclude (large JSONB) |
| `full_narrative` | watchlist_agent_results | Exclude (large text) |

## Architecture Decision: Views Over Direct Grants

For tables with sensitive columns, Hermes accesses data through **views** rather than direct table grants. This ensures:

1. Sensitive columns are never exposed even if Hermes queries `SELECT *`
2. Account identifiers are masked to type only
3. Large binary/JSONB fields are excluded to prevent accidental data exfiltration
4. Views can be updated to add/remove columns without changing role grants

## Open Questions

1. Should `john_decision_history` be exposed? It would make Hermes' operator-decision learning much more effective, but contains personal decision patterns.
2. Should `incubator_universe` be exposed? The incubator agent needs it, but it may contain private research notes.
3. Should `watchlist_items.llm_health` be exposed? Probably safe — it's LLM-generated health assessments, not personal data.
4. The `account` masking loses which specific account holds a position. Is account-type-only sufficient for Hermes trade reflection?

## No Secrets Found in Proposed Allow List

All 32 ALLOW tables and 8 ALLOW_WITH_MASK tables were verified to contain no API keys, passwords, tokens, cookies, broker credentials, or personal identifiers (after masking).
