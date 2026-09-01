# Phase 113B — Hermes Proposal Draft Sandbox Design

Status:      DRAFT
as_of:       2026-06-01T15:53:13-04:00
Measured at: efcc51365 / not measured

## Architecture

The sandbox is completely isolated from real proposal tables and the execution path.

### Storage Options (choose one)

**Option A — File-only (simplest)**
- Draft packets written to `hermes_sidecar/drafts/proposals/`
- One JSON file per draft: `{symbol}_{timestamp}.json`
- No DB writes, no schema changes
- Cleanup: `rm hermes_sidecar/drafts/proposals/*.json`

**Option B — hermes_proposal_drafts table (auditable)**
- New table `hermes_proposal_drafts` in the hermes_* namespace
- Columns: id, symbol, thesis, evidence_json, catalyst, risk, entry_price, stop_price, target_price, position_size_rationale, confidence, quality_score, hermes_agent, created_at
- `source='hermes'` CHECK constraint (same as other hermes_* tables)
- hermes_staging_writer role can INSERT
- Trade AI has NO FK or join path to this table
- Cleanup: `TRUNCATE hermes_proposal_drafts`

**Recommendation**: Option B — it's auditable, queryable, and fits the existing hermes_* table pattern.

### Isolation Rules

1. **No writes to paper_trade_proposals** — ever
2. **No writes to paper_trades** — ever
3. **No broker access** — no Alpaca API calls
4. **No signal_id** — Hermes drafts are not linked to strategy_signals
5. **No enrichment pipeline** — drafts don't enter the proposal enrichment loop
6. **No ATM evaluation** — auto-approver never sees hermes drafts
7. **No execution sweep** — paper_execution_sweep ignores hermes drafts
8. **Operator promote step** — moving a draft to a real proposal requires explicit operator action (separate approval, not this phase)

### Sandbox Workflow

```
Hermes Research → Draft Packet → Quality Score → Sandbox Review → [STOP]
                                                                    |
                                                       Operator decides:
                                                       - Archive (most)
                                                       - Manual promote to real proposal (rare, future phase)
```

### What Hermes Needs to Produce a Draft

1. Symbol + thesis (from ticker_challenger or research)
2. Catalyst evidence (from news_articles, SearXNG, browser)
3. Entry/stop/target levels (from DB views: ticker_snapshot_daily, indicator_confluence_cache)
4. Position size rationale (from portfolio_snapshots, risk parameters)
5. Account fit (from hermes_v_portfolio_context view — masked account types only)
6. Why-not-trade section (explicit invalidation criteria)
