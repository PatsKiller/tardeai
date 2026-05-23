# Intelligence Flow Full Findings — 2026-05-22

## Executive Summary

End-to-end audit of the Trade AI v12 intelligence pipeline confirms the system is **architecturally account-agnostic** with 2 minor hardcoding defaults to fix. The enterprise backtester, outcome scorer, RAG engine, and agent collaboration layer all support multi-account operation. Schwab/Fidelity accounts exist in the registry but are disabled (no trade data flowing yet — by design).

---

## 1. Accounts & Broker Infrastructure

### Accounts Table
| Label | Broker | Mode | Enabled |
|-------|--------|------|---------|
| alpaca_paper | alpaca | paper | YES |
| schwab_rollover_ira | schwab | live | NO |
| schwab_roth_ira | schwab | live | NO |
| schwab_taxable | schwab | live | NO |
| fidelity_401k | fidelity | live | NO |

### Trades by Account
| Account | Total | Open | Closed |
|---------|-------|------|--------|
| ALPACA_PAPER | 24 | 3 | 9 |
| TOS_PAPER | 7 | 2 | 2 |

**Finding:** Two account labels in use (ALPACA_PAPER, TOS_PAPER). The "TOS_PAPER" label is legacy from ThinkOrSwim migration. Schema supports any account_label.

---

## 2. Enterprise Backtester — GOOD

**File:** `scripts/enterprise_backtester.py`

- Reads from both `paper_trades` AND `trade_closed` (real trades)
- Reads `account` field from paper_trades (no hardcoding)
- Writes to `strategy_backtest_runs` + `strategy_backtest_trades` (account-agnostic)
- 33 backtest runs completed
- Can process Schwab/Fidelity trades after import without code changes

**Verdict:** Account-agnostic. No fixes needed.

---

## 3. Proposal Backtest Engine — MINOR ISSUE

**File:** `scripts/proposal_backtest_engine.py`

- Queries `paper_trades` + `trade_closed` with no account filter
- Aggregates by strategy only, not by account
- No hardcoded account name

**Finding:** Could be improved by supporting per-account backtesting, but not blocking.

---

## 4. Outcome Scoring — GOOD

**File:** `scripts/paper_outcome_analytics.py`

- Reads from `paper_trades` table
- Writes to `paper_trade_outcome_analytics` with `paper_trade_id` FK
- Aggregates by `strategy_id` only
- Account context preserved via trade ID join

**Verdict:** Account-agnostic. No fixes needed.

---

## 5. ATM Auto-Approver — HARDCODING FOUND

**File:** `scripts/atm_auto_approver.py`
**Line 255:** `target = p["target_account"] or "alpaca_paper"`

**Issue:** Defaults to `"alpaca_paper"` if proposal has no target_account. Should require the proposal to specify an account.

**Risk:** LOW — currently only alpaca_paper is enabled, so the default is functionally correct. Becomes a real issue when Schwab/Fidelity are enabled.

**Recommended fix:** Change to require target_account, reject/defer if missing.

---

## 6. Proposal Agent Review — HARDCODING FOUND

**File:** `scripts/proposal_agent_review.py`
**Line 265:** `account = proposal.get('proposed_account', 'ALPACA_PAPER')`

**Issue:** Defaults to `'ALPACA_PAPER'` if proposed_account missing. Does include account-aware logic for IRA/Roth/taxable distinction.

**Risk:** LOW — same as ATM approver. Functionally correct now, needs fix for multi-account.

---

## 7. Proposal Schema — HARDCODING FOUND

**Table:** `paper_trade_proposals`
**Column:** `proposed_account TEXT DEFAULT 'TOS_PAPER'`

**Issue:** Schema default hardcodes `'TOS_PAPER'`. All new proposals get this unless explicitly set.

**Risk:** LOW-MEDIUM — the incubator promoter and auto_proposal_generator do set the account explicitly, but any code path that doesn't will get the wrong default.

---

## 8. RAG/Vector Engine — GOOD

**Indexer:** `scripts/rag_indexer.py`
- Indexes 11+ source types (news, social, agent_result, cio_decision, etc.)
- 16,543 embeddings in `content_embeddings`
- No account/broker hardcoding
- Universal indexer — any source type can be added

**Retriever:** `scripts/rag_retrieval.py`
- Queries `content_embeddings` across all sources
- Supports `CATEGORY:` prefix for strategy searches
- No account/broker hardcoding

**Gap:** RAG metadata doesn't explicitly tag `account_label` in embeddings. Trade outcomes are linked by `paper_trade_id` (which has account via join) but the embedding itself doesn't carry it.

---

## 9. Agent Collaboration — GOOD

**File:** `scripts/agent_collab.py`
- Pulls from `watchlist_agent_results`
- Symbol-based context injection
- No broker/account hardcoding

**File:** `scripts/agent_outcome_linker.py`
- Links agent recommendations to trade outcomes
- Uses symbol + time window matching
- No account assumptions

---

## 10. Enrichment Coverage

| Source | Count |
|--------|-------|
| Screener symbols | 2,038 |
| Classified symbols | 9,410 |
| Content embeddings | 16,543 |
| Quote snapshots | 190 symbols |
| News articles | 4,200 |

### RAG Source Distribution
| Source Type | Count |
|-------------|-------|
| agent_result | 6,566 |
| news | 3,339 |
| social_post | 2,245 |
| fused_signal | 1,264 |
| decision_outcome | 860 |
| youtube | 818 |
| agent_synthesis | 780 |
| cio_decision | 446 |
| sec_form4 | 166 |
| fred_series | 28 |

---

## 11. Backtest Infrastructure

### Tables
- `strategy_backtest_runs` — 33 runs
- `strategy_backtest_trades` — trade-level results
- `strategy_backtest_results` — aggregate results
- `backtest_datasets` — input data
- `backtest_run_log` — execution log
- `backtest_learning_evidence_links` — links to strategy evidence
- `proposal_backtest_snapshots` — per-proposal backtest data
- `trade_backtest_results` — per-trade backtest results

### Multi-Account Support
- Enterprise backtester reads `account` field from paper_trades
- No Alpaca-specific filtering
- Can process Schwab/Fidelity rows if imported to paper_trades or trade_closed
- Schwab reconstructor (`schwab_reconstructor.py`) exists for import

---

## 12. Agent Infrastructure

### Agent Tables (20+)
agent_calibration, agent_curation_events, agent_decision_journal,
agent_discovery_log, agent_event_queue, agent_feedback_log,
agent_handoffs, agent_intelligence_rules, agent_learning_scores,
agent_performance_history, agent_recommendation_registry,
agent_recommendation_outcomes, and more.

### Agent Event Coverage (30 days)
Active — agent_curation_events populated from trade monitoring, stop adjustments, and proposal reviews.

---

## 13. Closed Trade Feedback Loop

### Current Flow
```
Trade closes → paper_trades.status='closed'
  → paper_outcome_analytics scores outcome
  → agent_outcome_linker links agent predictions
  → strategy_backtest_trades stores replay data
  → content_embeddings stores decision_outcome (860 entries)
  → classifier_health reads closed trades for strategy scoring
```

### Gap
- Not all closed trades have backtest coverage (some strategies have 0 backtest trades)
- RAG decision_outcome embeddings don't carry account_label as explicit metadata
- Strategy evidence summary aggregates by strategy only, not by account

---

## 14. Schwab/Fidelity Readiness

### What Exists
- `schwab_reconstructor.py` — imports Schwab transaction history
- `portfolio_repricer.py` — broker-specific pricing logic (intentional)
- Accounts table has schwab x3 + fidelity entries (disabled)
- Schema supports multi-broker via `account` + `broker` columns

### What's Missing
- No Fidelity import adapter (Schwab has one)
- Live accounts disabled — no trade data flowing
- No import pipeline for real broker closed trades into canonical tables
- No automated Schwab→paper_trades sync (reconstructor is manual)

---

## 15. Summary of Issues

| # | Issue | Severity | Location | Fix |
|---|-------|----------|----------|-----|
| 1 | ATM defaults to "alpaca_paper" | LOW | atm_auto_approver.py:255 | Require target_account |
| 2 | Agent review defaults to "ALPACA_PAPER" | LOW | proposal_agent_review.py:265 | Require proposed_account |
| 3 | Proposal schema defaults to "TOS_PAPER" | LOW-MED | paper_trade_proposals DDL | Remove default or set NULL |
| 4 | RAG metadata lacks account_label | LOW | content_embeddings | Add to metadata on writeback |
| 5 | Backtest aggregates by strategy only | LOW | proposal_backtest_engine.py | Add account parameter |
| 6 | No Fidelity import adapter | FUTURE | N/A | Build when Fidelity enabled |
| 7 | Schwab import is manual | FUTURE | schwab_reconstructor.py | Automate when live enabled |

---

## 16. Conclusion

The intelligence pipeline is **architecturally sound for multi-account operation**. The enterprise backtester, outcome scorer, RAG engine, and agent layer all work with account data when present. The 2 hardcoded defaults (ATM approver + agent review) are functionally correct for paper-only mode but should be fixed before enabling Schwab/Fidelity accounts.

**No trading behavior was changed.** This is an audit/documentation phase only.

---

## 17. Recommended Next Actions

1. Fix 2 hardcoded account defaults (low effort, low risk)
2. Add account_label to RAG metadata on writeback (enhancement)
3. Build Fidelity import adapter when ready to enable
4. Automate Schwab→canonical trade sync
5. Enable Schwab/Fidelity accounts only after live-readiness approval
6. Continue accumulating closed paper trades for strategy proof
