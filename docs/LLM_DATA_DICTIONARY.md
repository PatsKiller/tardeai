# LLM Data Dictionary — How Data Flows to Every Model Call

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.


**Last updated:** 2026-05-13
**Canonical engine:** `scripts/llm_context_engine.py`

---

## Principle

Every LLM call in the system receives actual data from the database.
No prompt passes only IDs, trigger names, or vague descriptions when
real numbers are available. Models cannot hallucinate what they can read.

This applies to ALL models: qwen3:14b (STANDARD), gemma3-overnight
(BATCH_OVERNIGHT), Anthropic Sonnet (CRITICAL_CLOUD).

---

## Data Flow Architecture

```
DB Tables                    Context Engine              Prompt Builder           LLM
────────────                 ──────────────              ─────────────            ───
ticker_snapshot_daily  ─┐
trade_closed           ─┤
paper_trades           ─┤─→ build_context() ─→ formatted data block ─→ prompt ─→ gemma3/qwen3
stopped_out_watch      ─┤      + anti-hallucination      + task instructions       /Sonnet
news_articles          ─┤         block
holdings.json          ─┤
paper_trade_proposals  ─┘
```

---

## Context Types and Their Data Sources

### 1. `strategy_classification`
**Used by:** Deep overnight queue, incubator screener, multi-strategy classifier
**Purpose:** Evaluate whether a symbol's current strategy assignment is correct

| Data Field | Source | Table/Column |
|-----------|--------|--------------|
| Current price | `ticker_snapshot_daily.data->>'price'` | Latest snapshot date |
| RSI (14-day) | `ticker_snapshot_daily.rsi` | Latest snapshot date |
| RVOL | `ticker_snapshot_daily.data->>'rvol'` | Latest snapshot date |
| Sector | `ticker_snapshot_daily.data->>'sector'` | Latest snapshot date |
| Beta | `ticker_snapshot_daily.data->>'beta'` | Latest snapshot date |
| P/E ratio | `ticker_snapshot_daily.data->>'pe'` | Latest snapshot date |
| Dividend yield | `ticker_snapshot_daily.data->>'div_yield'` | Latest snapshot date |
| SMA50/200 distance | `ticker_snapshot_daily.data->>'sma50'`, `sma200` | Latest snapshot date |
| Week performance | `ticker_snapshot_daily.perf_week_pct` | Latest snapshot date |
| Current strategy | `ticker_strategy_classifications.strategy_type` | WHERE active=true |
| Confidence | `ticker_strategy_classifications.confidence` | WHERE active=true |
| Paper trade history | `paper_trades` WHERE symbol=X AND closed | W/L count, total PnL |
| Historical trades | `trade_closed` WHERE symbol=X | W/L count, stop usage |
| Recent news | `news_articles` WHERE symbol=X, last 7d | Title, sentiment, source |

### 2. `trade_review`
**Used by:** Deep overnight closed_trade_review, multi-tier trade reviewer
**Purpose:** Post-trade analysis of closed positions

| Data Field | Source | Table/Column |
|-----------|--------|--------------|
| Entry price | `trade_closed.buy_price` | WHERE id=trade_id |
| Exit price | `trade_closed.sell_price` | WHERE id=trade_id |
| P&L (dollars) | `trade_closed.pnl` | WHERE id=trade_id |
| P&L (percent) | `trade_closed.pnl_pct` | WHERE id=trade_id |
| Hold duration | `trade_closed.hold_days` | WHERE id=trade_id |
| Stop used | `trade_closed.stop_used` | NULL = no stop |
| R-multiple | `trade_closed.r_multiple` | WHERE id=trade_id |
| Trade type | `trade_closed.trade_type` | DAY/SWING/SHORT/LONG |
| Account | `trade_closed.account` | schwab_rollover_ira etc |
| Past symbol trades | `trade_closed` WHERE symbol=X | Total W/L, stop rate |
| + All strategy_classification data above | | |

### 3. `risk_synthesis`
**Used by:** Deep overnight risk_synthesis, morning brief
**Purpose:** Portfolio-level risk assessment

| Data Field | Source | Table/Column |
|-----------|--------|--------------|
| Portfolio total value | `holdings.json → portfolio_totals.total_value` | JSON file |
| Each position symbol | `holdings.json → holdings[].symbol` | Top 25 by value |
| Position market value | `holdings.json → holdings[].market_value` | Per position |
| Position % of portfolio | `holdings.json → holdings[].portfolio_pct` | Per position |
| Day change | `holdings.json → holdings[].day_change` | Per position |

### 4. `recovery_watch`
**Used by:** Deep overnight recovery_watch_review, recovery dashboard
**Purpose:** Should we re-enter a stopped-out position?

| Data Field | Source | Table/Column |
|-----------|--------|--------------|
| Exit price | `stopped_out_watch.exit_price` | WHERE symbol=X, active |
| Stop price at exit | `stopped_out_watch.stop_price` | WHERE symbol=X |
| Date stopped out | `stopped_out_watch.stopped_out_at` | WHERE symbol=X |
| Days since exit | Computed from stopped_out_at | |
| Reason for exit | `stopped_out_watch.reason` | WHERE symbol=X |
| Thesis at exit | `stopped_out_watch.thesis_at_exit` | WHERE symbol=X |
| Realized P&L | `stopped_out_watch.realized_pnl` | WHERE symbol=X |
| Current price | `ticker_snapshot_daily.data->>'price'` | Latest |
| Recovery % from exit | Computed: (current - exit) / exit * 100 | |
| Current RSI | `ticker_snapshot_daily.rsi` | Latest |
| Week performance | `ticker_snapshot_daily.perf_week_pct` | Latest |
| + Recent news for symbol | | |

### 5. `covered_call`
**Used by:** Deep overnight covered_call_scoring
**Purpose:** Should we sell covered calls on this position?

| Data Field | Source | Table/Column |
|-----------|--------|--------------|
| Current price | `ticker_snapshot_daily.data->>'price'` | Latest |
| RSI | `ticker_snapshot_daily.rsi` | Latest |
| Beta | `ticker_snapshot_daily.data->>'beta'` | Latest |
| Dividend yield | `ticker_snapshot_daily.data->>'div_yield'` | Latest |
| RVOL | `ticker_snapshot_daily.data->>'rvol'` | Latest |
| Week performance | `ticker_snapshot_daily.perf_week_pct` | Latest |
| SMA50 distance | `ticker_snapshot_daily.data->>'sma50_pct'` | Latest |
| Aegis verdict | `aegis_covered_call_candidates.verdict` | Latest |
| Aegis reasoning | `aegis_covered_call_candidates.reasoning` | Latest |

### 6. `proposal`
**Used by:** Deep overnight proposal_review
**Purpose:** Should this proposal be approved for paper trading?

| Data Field | Source | Table/Column |
|-----------|--------|--------------|
| Proposed entry | `paper_trade_proposals.proposed_entry` | WHERE id=proposal_id |
| Proposed stop | `paper_trade_proposals.proposed_stop` | WHERE id=proposal_id |
| Proposed target | `paper_trade_proposals.proposed_target1` | WHERE id=proposal_id |
| Shares | `paper_trade_proposals.proposed_shares` | WHERE id=proposal_id |
| Strategy | `paper_trade_proposals.strategy_id` | WHERE id=proposal_id |
| Signal grade/score | `paper_trade_proposals.signal_grade`, `signal_score` | WHERE id=proposal_id |
| Catalyst | `paper_trade_proposals.catalyst` | WHERE id=proposal_id |
| Catalyst verified | `paper_trade_proposals.catalyst_verified` | WHERE id=proposal_id |
| Computed R:R | (target - entry) / (entry - stop) | |
| Computed dollar risk | abs(entry - stop) * shares | |
| Current price | `ticker_snapshot_daily.data->>'price'` | Latest |
| Current RSI | `ticker_snapshot_daily.rsi` | Latest |
| Current RVOL | `ticker_snapshot_daily.data->>'rvol'` | Latest |

---

## Anti-Hallucination Block

Appended to every context output:

```
CRITICAL INSTRUCTIONS:
- Use ONLY the data provided above in your analysis
- Do NOT invent, estimate, or assume numbers not in the data
- Do NOT claim patterns unless the data explicitly supports them
- If data is missing, say "data not available" — do not fill gaps
- If you reference a number (price, count, %, date), it must appear
  in the data above
```

---

## Scripts Already Data-Rich (No Engine Needed)

These scripts load their own comprehensive data and don't need migration:

| Script | Data Loading | Why Already Rich |
|--------|-------------|------------------|
| `process_watchlist_agent_jobs.py` | Scan intel, RAG context, sentiment, research advisories, cross-agent views | Most data-rich prompt in the system |
| `stop_decision_brief.py` | Holdings, enrichment cache, stops, news, technicals, earnings, signals | Loads 8+ data sources per brief |
| `scoring.py` | Actual news headlines for catalyst scoring | Headlines injected directly |
| `incubator_llm_screener.py` | Technical snapshot, news, social, web news, indicator confluence | 4 strategy-specific prompt builders |

---

## How to Add a New Context Type

1. Add a `get_[type]_context(symbol, conn)` function to `llm_context_engine.py`
2. Add routing in `build_context()`: `elif context_type == '[type]': ...`
3. Use in your script: `ctx = build_context(symbol=sym, context_type='[type]', conn=conn)`
4. Anti-hallucination block is automatically appended
5. Update this document with the new data fields
