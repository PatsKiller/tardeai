# Hermes Phase 28D — Journal/Backtesting Librarian Check Design

**Date:** 2026-06-01
**Status:** COMPLETE — design only, no DB writes

---

## Purpose

Define how the Hermes Librarian should evaluate journal and backtesting outputs to generate Research Backlog items. All checks are read-only analysis producing file output.

---

## Librarian Checks for Journal/Backtesting

### Trade Journal Checks

| Check | ID | Trigger | Backlog Type |
|-------|----|---------|-------------|
| Stale trade thesis | JRN-1 | Thesis review older than 90 days with no update | stale_trade_thesis |
| Missing exit lesson | JRN-2 | Closed trade with no thesis review or learning digest entry | journal_lesson_missing |
| Missing catalyst at entry | JRN-3 | Trade opened without catalyst_events record in ±24h window | missing_trade_catalyst |
| Weak catalyst at entry | JRN-4 | Trade catalyst grade = WEAK_GENERIC or STALE_CATALYST | weak_trade_catalyst |
| Journal note too vague | JRN-5 | Learning digest item lacks specific action or lesson | morning_brief_vague_recommendation |
| Case study missing actionability | JRN-6 | Thesis review lacks next-trade guidance | journal_lesson_missing |

### Backtesting Checks

| Check | ID | Trigger | Backlog Type |
|-------|----|---------|-------------|
| Backtest contradiction | BT-1 | Strategy backtest win_rate < 40% but still active | backtest_contradiction |
| Failed setup pattern | BT-2 | Same entry pattern fails 3+ times in backtest | backtest_contradiction |
| Repeated mistake pattern | BT-3 | Same exit reason (stopped out, timed out) 3+ times | strategy_underperformance |
| Strategy underperformance | BT-4 | Strategy sharpe < 0.5 or profit_factor < 1.0 in backtest | strategy_underperformance |
| Proposal rejected but backtest favorable | BT-5 | Rejected proposal would have been profitable in replay | rejected_proposal_favorable_backtest |
| Proposal accepted but backtest unfavorable | BT-6 | Approved proposal lost money, backtest confirms pattern | accepted_proposal_unfavorable_backtest |

### Momentum Scout Checks

| Check | ID | Trigger | Backlog Type |
|-------|----|---------|-------------|
| Scout false positive | MS-1 | GO candidate that failed within 24h | momentum_scout_weak_catalyst |
| Scout missed winner | MS-2 | NO_GO candidate that moved 5%+ in intended direction | momentum_scout_missing_news |
| Missing news at scout time | MS-3 | Incubator symbol with no news_articles in ±48h | momentum_scout_missing_news |
| Weak catalyst at scout | MS-4 | Incubator symbol with grade WEAK_GENERIC | momentum_scout_weak_catalyst |

### Communication Checks

| Check | ID | Trigger | Backlog Type |
|-------|----|---------|-------------|
| Morning brief vague recommendation | COM-1 | Per actionability standard (Phase 20C) | morning_brief_vague_recommendation |
| Analyst context missing | COM-2 | Symbol in portfolio with zero external analyst sources | analyst_context_missing |
| Source refresh needed | COM-3 | Hermes source_discovery row older than 60 days | source_refresh_needed |

---

## Output Format

All checks produce Research Backlog candidate items with:
- check_id
- backlog_type
- symbol
- severity (high/medium/low)
- evidence (specific row IDs, dates, scores)
- requested_research (what to investigate)
- owner_agent
- priority

---

## Prerequisites

These checks require safe views that **do not yet exist**:
- hermes_v_journal_learning_context (for JRN-1 through JRN-6)
- hermes_v_backtest_results_context (for BT-1 through BT-6)
- hermes_v_screener_context (for MS-1 through MS-4)
- hermes_v_catalyst_quality_context (for JRN-3, JRN-4, MS-4)

Until views are created, checks can only run against surfaces already visible to Hermes (proposals, trades, news, pipeline health).

---

## No DB Writes

All outputs are Research Backlog candidates in file form. Actual staging requires a separate Phase approval (same pattern as Phase 22).
