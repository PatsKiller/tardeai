# INTELLIGENCE-FLOW-1 — End-to-End Integration Audit

**Date:** 2026-05-22
**Purpose:** Verify account-agnostic enrichment, backtesting, agent/RAG flow

## Key Findings

### What Works (Account-Agnostic)
- **Enterprise backtester:** Reads from paper_trades + trade_closed, includes account field, no hardcoding
- **Outcome scoring:** Links via paper_trade_id (which carries account), no hardcoding
- **RAG engine:** Generic indexer/retriever, 16,543 embeddings across 11 source types
- **Agent collaboration:** Symbol-based context, no account hardcoding
- **Schema:** paper_trades has `account` column, indexed on (account, status)
- **Accounts table:** 5 accounts (alpaca_paper, schwab x3, fidelity), broker column present

### Hardcoding Issues Found (2)
1. **atm_auto_approver.py:255** — defaults to `"alpaca_paper"` if target_account NULL
2. **paper_trade_proposals schema** — `proposed_account DEFAULT 'TOS_PAPER'`

### Coverage
- Screener symbols: 2,038
- Classified symbols: 9,410
- RAG documents: 16,543
- Quote snapshots: 190 symbols
- News articles: 4,200
- Backtest runs: 33
- Agent events (30d): varies

### Gaps
- No explicit `broker` column on paper_trade_proposals (encoded in account_label)
- Closed trades missing backtest coverage for some strategies
- RAG writebacks don't explicitly tag account_label in metadata
- Schwab/Fidelity accounts disabled — no trade data flowing yet (by design)
- Backtest aggregates by strategy only, not by account (minor)

### Not Changed
- No trading behavior modified
- No strategy activation changed
- No YAML/Finviz criteria changed
- No .env modified
- No orders/trades/approvals created
