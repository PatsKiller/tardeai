# Hermes Phase 28E — Trade AI to Hermes Backlog Integration Plan

**Date:** 2026-06-01
**Status:** COMPLETE — design only, no implementation

---

## Backlog Item Types

### 1. stale_trade_thesis

| Field | Value |
|-------|-------|
| Trigger | Thesis review older than 90 days, symbol still in portfolio |
| Data sources | hermes_v_journal_learning_context (future), hermes_v_trade_reflection_context |
| Required evidence | Thesis review date, current position status, days since last review |
| Owner agent | Hermes Librarian Agent |
| Priority logic | HIGH if position size > 2% of portfolio, MEDIUM otherwise |
| Operator visibility | Research Backlog dashboard card |
| Forbidden | No thesis modification, no position change, no trade |
| Future staged-write | hermes_research_intelligence (research_type='research_backlog') |

### 2. missing_trade_catalyst

| Field | Value |
|-------|-------|
| Trigger | Trade opened with no catalyst_events in ±24h window |
| Data sources | hermes_v_trade_reflection_context, hermes_v_catalyst_quality_context (future) |
| Required evidence | Trade entry date/time, catalyst search window result |
| Owner agent | Source Discovery Agent |
| Priority logic | MEDIUM — historical, learning value |
| Forbidden | No trade modification |
| Future staged-write | hermes_research_intelligence (research_type='research_backlog') |

### 3. weak_trade_catalyst

| Field | Value |
|-------|-------|
| Trigger | Trade catalyst grade = WEAK_GENERIC or STALE_CATALYST |
| Data sources | hermes_v_catalyst_quality_context (future) |
| Required evidence | Catalyst grade, quality_score, headline_age_hours |
| Owner agent | Source Discovery Agent |
| Priority logic | MEDIUM if trade is open, LOW if closed |
| Forbidden | No catalyst modification, no trade modification |

### 4. journal_lesson_missing

| Field | Value |
|-------|-------|
| Trigger | Closed trade with no thesis review or learning digest entry |
| Data sources | hermes_v_journal_learning_context (future), hermes_v_trade_reflection_context |
| Required evidence | Trade close date, search for matching thesis_review or digest_item |
| Owner agent | Hermes Librarian Agent |
| Priority logic | HIGH if losing trade, MEDIUM if winning trade |
| Forbidden | No journal creation (Hermes does not write journal) |

### 5. backtest_contradiction

| Field | Value |
|-------|-------|
| Trigger | Strategy win_rate < 40% in backtest but strategy still active |
| Data sources | hermes_v_backtest_results_context (future) |
| Required evidence | Strategy name, backtest win_rate, profit_factor, sample size |
| Owner agent | Hermes Librarian Agent |
| Priority logic | HIGH — strategy-level risk |
| Forbidden | No strategy deactivation |

### 6. rejected_proposal_favorable_backtest

| Field | Value |
|-------|-------|
| Trigger | Rejected proposal would have been profitable in replay |
| Data sources | hermes_v_proposal_context, hermes_v_backtest_results_context (future) |
| Required evidence | Proposal ID, rejection reason, backtest replay result |
| Owner agent | Hermes Librarian Agent |
| Priority logic | MEDIUM — learning value, may indicate over-strict rejection |
| Forbidden | No proposal status change |

### 7. accepted_proposal_unfavorable_backtest

| Field | Value |
|-------|-------|
| Trigger | Approved trade lost money, backtest confirms losing pattern |
| Data sources | hermes_v_proposal_context, hermes_v_trade_reflection_context, backtest |
| Required evidence | Trade P&L, backtest replay result, pattern match |
| Owner agent | Hermes Librarian Agent |
| Priority logic | HIGH — repeated losses indicate strategy weakness |
| Forbidden | No trade modification |

### 8. strategy_underperformance

| Field | Value |
|-------|-------|
| Trigger | Strategy sharpe < 0.5 or profit_factor < 1.0 over 20+ trades |
| Data sources | hermes_v_backtest_results_context (future) |
| Required evidence | Strategy name, sharpe, profit_factor, trade count, period |
| Owner agent | Hermes Librarian Agent |
| Priority logic | HIGH — strategy-level decision required |
| Forbidden | No strategy modification |

### 9. momentum_scout_weak_catalyst

| Field | Value |
|-------|-------|
| Trigger | Incubator GO candidate with grade WEAK_GENERIC |
| Data sources | hermes_v_screener_context (future), catalyst_quality |
| Required evidence | Symbol, screener run, catalyst grade, score |
| Owner agent | Source Discovery Agent |
| Priority logic | MEDIUM — may prevent bad proposal |
| Forbidden | No incubator modification |

### 10. momentum_scout_missing_news

| Field | Value |
|-------|-------|
| Trigger | Incubator symbol with no news_articles in ±48h |
| Data sources | hermes_v_screener_context (future), hermes_v_news_research_context |
| Required evidence | Symbol, last_news_date, screener run date |
| Owner agent | Source Discovery Agent |
| Priority logic | MEDIUM |
| Forbidden | No news creation |

### 11. morning_brief_vague_recommendation

| Field | Value |
|-------|-------|
| Trigger | Per actionability standard (16 fields, 11 failure classes) |
| Data sources | File scan of data/portfolios/reports/ or alert_events metadata |
| Required evidence | Brief excerpt, missing fields count, actionability score |
| Owner agent | Hermes Librarian Agent |
| Priority logic | MEDIUM — operator quality |
| Forbidden | No brief modification, no alert send |

### 12. analyst_context_missing

| Field | Value |
|-------|-------|
| Trigger | Portfolio symbol with zero external analyst sources in Hermes |
| Data sources | hermes_research_intelligence, portfolio symbols |
| Required evidence | Symbol, search for source_discovery rows, external URL count |
| Owner agent | Source Discovery Agent |
| Priority logic | LOW if position small, MEDIUM if > 2% |
| Forbidden | No auto-discovery |

### 13. source_refresh_needed

| Field | Value |
|-------|-------|
| Trigger | Hermes source_discovery row freshness_date > 60 days |
| Data sources | hermes_research_intelligence (source_discovery rows) |
| Required evidence | Row ID, symbol, freshness_date, days stale |
| Owner agent | Source Discovery Agent |
| Priority logic | LOW — informational |
| Forbidden | No auto-refresh |

---

## Integration Flow

```
Trade AI Data (safe views)
    ↓ read-only
Hermes Librarian (dry-run checks)
    ↓ file output
Research Backlog candidates
    ↓ operator approval
hermes_research_intelligence (staged, research_type='research_backlog')
    ↓ operator review
Source Discovery / SearXNG enrichment
    ↓ operator approval
Staged source_discovery rows
```

**Every step requires explicit approval. No autonomous pipeline.**
