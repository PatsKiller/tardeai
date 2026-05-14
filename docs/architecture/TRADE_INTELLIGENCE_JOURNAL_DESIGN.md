# Trade Intelligence Journal -- Design Document

**Author:** Session 42 design pass
**Date:** 2026-05-14
**Status:** DRAFT -- pending operator approval

## 1. Problem Statement

The Automated Journal is a transaction log. It records entry/exit/PnL but doesn't capture the reasoning, doesn't analyze whether we got stopped too soon, doesn't show competing strategies, and the learning isn't visible to the operator.

The system has the data. The data is siloed across 5+ tables. The UI shows none of it.

## 2. Current State (from Phase 1 + Phase 2 inventory)

### What exists (infrastructure ~60% complete)

| Table | Rows | Content Quality | Problem |
|---|---|---|---|
| `proposal_agent_reviews` | 292 | 141 have summaries (48%), 151 are stubs | Stubs created but never populated by agent |
| `watchlist_agent_results` | active | Rich narratives from maria/steph/risk_agent for INFU, GCTS, BLBD | Not joined to proposals or journal |
| `trade_thesis_outcomes` | 4 | thesis_result populated, MFE/MAE all NULL | Script exists but doesn't compute MFE/MAE or price recovery |
| `paper_trade_outcome_analytics` | has schema | Hold time, R-multiple, exit reason | Partially used |
| `paper_trade_proposals` | 61 | Has signal_score, signal_grade, critic_confidence, critic_reasoning | No ranking pass -- all strategies shown equally |

### Multi-strategy problem (measured)

| Symbol | Strategies Matched | All Shown Equally? |
|---|---|---|
| ALGS | 5 (gap_and_go, momentum_scalp, speculative_growth, swing_breakout, swing_trade) | Yes |
| BLBD | 5 (core_growth_compounder, earnings_catalyst, sector_rotation, swing_breakout, swing_trade) | Yes |
| GCTS | 5 (momentum_scalp, recovery_watch, sector_rotation, speculative_growth, swing_breakout) | Yes |
| FNKO | 5 (gap_and_go, momentum_scalp, speculative_growth, swing_breakout, swing_trade) | Yes |

### What's missing

1. **Wiring**: `watchlist_agent_results` narratives are not joined to `proposal_agent_reviews` or the journal
2. **Price recovery**: `post_trade_thesis_reviewer.py` doesn't compute post-exit price action
3. **Auto-trigger**: Post-trade analysis is manual, no cron
4. **Ranking**: No best-fit selection when multiple strategies match
5. **API**: No single endpoint that aggregates all intelligence for one trade
6. **UI**: Journal shows transactions only, no expandable reasoning/analysis panels

## 3. Five Operator Questions (the acceptance test)

Every closed trade row in the new journal MUST answer:

| # | Question | Data Source |
|---|----------|-------------|
| Q1 | What did the agent think when it proposed this? | `watchlist_agent_results.full_narrative` joined to proposal |
| Q2 | What other strategies were considered, why did this one win? | All proposals for same symbol + signal_score comparison |
| Q3 | What happened to price after we exited -- did we leave money on the table? | NEW: price-recovery data in `post_trade_analysis` |
| Q4 | Was the stop too tight or appropriate? | NEW: stop_too_tight boolean from post-exit price action |
| Q5 | What's the lesson for next time? | NEW: LLM-generated lesson_text from post-trade analyzer |

If a deliverable doesn't move at least one of these from "no" to "yes," it's out of scope.

## 4. Architecture

### 4.1 Data Layer

#### Existing tables -- no schema changes needed

| Table | Role in Journal |
|---|---|
| `paper_trades` | Core trade record (entry, exit, PnL, verdict) |
| `paper_trade_proposals` | Proposal context (score, grade, stops, targets, catalyst, strategy) |
| `proposal_agent_reviews` | Agent votes per proposal (141/292 populated) |
| `watchlist_agent_results` | Full agent narratives (summary, full_narrative, recommendation, confidence) |
| `trade_thesis_outcomes` | Thesis comparison (expected vs actual R, thesis_result) |
| `agent_intelligence_rules` | Captured lessons (config jsonb) |

#### New table: `post_trade_price_analysis`

```sql
CREATE TABLE post_trade_price_analysis (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER NOT NULL REFERENCES paper_trades(id) UNIQUE,
    proposal_id INTEGER REFERENCES paper_trade_proposals(id),
    symbol TEXT NOT NULL,

    -- Price action after exit (from market data)
    exit_price_actual NUMERIC,
    price_15min_after NUMERIC,
    price_1h_after NUMERIC,
    price_4h_after NUMERIC,
    price_eod NUMERIC,
    max_favorable_after_exit NUMERIC,
    max_adverse_after_exit NUMERIC,

    -- Verdicts
    stop_too_tight BOOLEAN,
    would_have_recovered BOOLEAN,
    held_too_short BOOLEAN,
    held_too_long BOOLEAN,
    thesis_outcome TEXT CHECK (thesis_outcome IN ('FULL','PARTIAL','FAILED','INCONCLUSIVE')),

    -- Learning
    lesson_text TEXT,

    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    analyzer_version TEXT DEFAULT 'v1.0'
);
```

This is separate from `trade_thesis_outcomes` because:
- `trade_thesis_outcomes` compares expected vs actual R (pre-existing)
- `post_trade_price_analysis` answers "what happened AFTER we exited" (new)

### 4.2 Service Layer

#### Service A: Trade Intelligence Aggregator (NEW API endpoint)

**Path:** `GET /api/v2/trade/{trade_id}/intelligence`

Joins across 6 tables in one query. Returns:

```json
{
  "trade": { /* paper_trades row */ },
  "proposal": { /* paper_trade_proposals row: score, grade, catalyst, stops, targets */ },
  "agent_reasoning": {
    "reviews": [
      {"agent": "maria", "vote": "GO", "confidence": 0.57, "summary": "...", "narrative": "..."},
      {"agent": "steph", "vote": "AVOID", "confidence": 0.55, "summary": "...", "narrative": "..."},
      {"agent": "risk_agent", "vote": "WAIT", "confidence": 0.45, "summary": "...", "narrative": "..."}
    ]
  },
  "competing_strategies": [
    {"strategy": "earnings_catalyst", "score": 38, "grade": "B", "status": "APPROVED_FOR_PAPER_TEST"},
    {"strategy": "swing_breakout", "score": 38, "grade": "B", "status": "APPROVED_FOR_PAPER_TEST"},
    {"strategy": "momentum_scalp", "score": null, "grade": null, "status": "not_proposed"}
  ],
  "post_trade": {
    "thesis_result": "THESIS_INVALIDATED",
    "stop_too_tight": true,
    "would_have_recovered": true,
    "price_1h_after": 8.55,
    "price_eod": 8.62,
    "lesson_text": "..."
  },
  "prior_outcomes_context": "=== PRIOR OUTCOMES FOR INFU... (Fix 6 block)"
}
```

**Implementation:** Add to `scripts/api_v2.py` as a new route handler. No new file needed.

#### Service B: Strategy Ranker (NEW ranking pass)

**File:** Add function to `scripts/auto_proposal_generator.py`

```python
def rank_strategies_for_symbol(proposals_for_symbol):
    """Given all proposals for one symbol, mark top pick(s).

    Rules:
    - Sort by signal_score DESC
    - Top score gets is_top_pick=True
    - Anything within 5% of top score is tied (also top_pick)
    - Everything else gets suppressed_reason set
    """
```

Called inside `run_auto_proposals()` after all strategies are evaluated for a symbol but before INSERT. Adds `is_top_pick` boolean and `rank_among_peers` integer to the proposal row.

**Schema addition (2 columns):**
```sql
ALTER TABLE paper_trade_proposals
  ADD COLUMN IF NOT EXISTS is_top_pick BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS rank_among_peers INTEGER;
```

#### Service C: Enhanced Post-Trade Analyzer (EXTEND existing script)

**File:** `scripts/post_trade_thesis_reviewer.py` (extend, not replace)

New responsibilities added to existing `review_trade()`:
1. Pull post-exit price data (15m, 1h, 4h, EOD) from Alpaca market data API
2. Compute `stop_too_tight`: price went 2%+ above stop within 1h of exit
3. Compute `would_have_recovered`: EOD price > entry price
4. Compute `held_too_short` / `held_too_long`: compare hold_time to strategy YAML norm
5. Write to `post_trade_price_analysis` table
6. Generate `lesson_text` via LLM call
7. Write lesson to `agent_intelligence_rules`

**Trigger:** Cron every 15 min during market hours (9:30-17:00 ET, Mon-Fri):
```
*/15 9-17 * * 1-5 cd $PROJ && flock -n /tmp/post_trade_analyzer.lock $PY scripts/post_trade_thesis_reviewer.py --apply >> logs/post_trade_analyzer.log 2>&1
```

### 4.3 UI Layer

#### Modify: `AutomatedTradeJournal.tsx`

Each closed-trade row gets a `[+] Expand` button that fetches `/api/v2/trade/{id}/intelligence` and renders four panels:

**Panel 1: Agent Reasoning (Q1)**
```
MARIA: HOLD (0.57) -- "INFU: neutral sentiment, HOLD signal..."
STEPH: AVOID (0.55) -- "micro-cap momentum, not aligned with income..."
RISK:  WAIT (0.45)  -- "negative price action, extreme relative vol..."
```

**Panel 2: Competing Strategies (Q2)**
```
  [star] earnings_catalyst  score 38  grade B  <- SELECTED
         swing_breakout     score 38  grade B
         momentum_scalp     --        --       (not proposed)
```

**Panel 3: Post-Trade Analysis (Q3, Q4)**
```
Stop too tight?      YES -- price recovered to $8.55 within 30min
Would have recovered? YES -- EOD at $8.62 (above $8.39 entry)
Hold time:           TOO SHORT (held 1.2h, strategy norm 24-72h)
Thesis:              PARTIAL -- RSI was correct, timing wrong
```

**Panel 4: Lesson (Q5)**
```
"INFU earnings_catalyst with 7.4% stop was too tight for a $8
 stock. Consider ATR-based stop (1.5x ATR = ~$0.80) instead of
 fixed percentage."
```

#### Optional: Strategy ranking badge on proposal list

On the proposals/screener view, show a "Top Pick" badge on the highest-ranked strategy per symbol. Suppressed strategies shown dimmed with "See all" expander.

## 5. Implementation Phases

Each phase committed separately. Operator approval before each.

| Phase | Deliverable | Files Changed | Effort | Risk |
|---|---|---|---|---|
| 3 | Trade Intelligence API endpoint | `api_v2.py` | 1-2 hrs | LOW -- read-only joins |
| 4 | Post-trade price analysis table + analyzer extension | `post_trade_thesis_reviewer.py`, new table | 2-3 hrs | MEDIUM -- market data API |
| 5 | Strategy Ranker + schema columns | `auto_proposal_generator.py`, ALTER TABLE | 1-2 hrs | LOW |
| 6 | UI expansion panels | `AutomatedTradeJournal.tsx` | 3-4 hrs | LOW |
| 7 | Cron + backfill for 9 closed trades | crontab, one-time script | 1 hr | LOW |

Total: ~8-12 hours across 2-3 sessions.

## 6. Acceptance Criteria

- Operator clicks any closed trade and sees Q1-Q5 answered
- Strategy ranker marks top pick per symbol on new proposals
- Post-trade analyzer runs automatically (cron)
- All 9 closed historical trades have backfilled analysis
- UI renders reasoning + analysis without page reload (async fetch)
- Feature is toggleable (no analysis = graceful empty state)

## 7. Out of Scope

- Real-time alerts on stop-too-tight findings
- Agent prompt changes (Fix 6 already deployed)
- New strategies or YAML edits
- Live trading enablement
- LLM model changes
- Strategy weight retuning

## 8. Operator Decisions (answered 2026-05-14)

| # | Question | Decision | Reasoning |
|---|----------|----------|-----------|
| Q1 | Strategy filtering | Rank within screener-matched set only | Don't bypass screener; it already filters by sector/cap/regime |
| Q2 | Tie-breaking | Show ties side-by-side when within 5% AND both >65% confidence | Two valid theses = operator's call, not computer pick |
| Q3 | Market data source | Alpaca market data API | Already configured, no rate limit, minute-bars available |
| Q4 | Lesson LLM | qwen3:14b (immediate after close) | GPU-resident, zero startup, fast feedback; don't compete with overnight gemma3 queue |
| Q5 | Backfill scope | 9 closed trades in current journal | Recent, have full data, proposal_id linked; can expand later |
