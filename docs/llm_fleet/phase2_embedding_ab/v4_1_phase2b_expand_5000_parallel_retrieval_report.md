# Phase 2B Parallel Retrieval Quality Comparison

**Date:** 2026-05-14T11:56:51.029407
**Baseline:** nomic-embed-text (table: content_embeddings, 14797 docs)
**Candidate:** qwen3-embedding:8b (table: content_embeddings_qwen3_test, 4897 docs)
**Queries:** 40 | **Top-K:** 10
**Production changed:** False | **Routing changed:** False

## Aggregate Metrics

| Metric | Baseline | Candidate | Delta |
|--------|----------|-----------|-------|
| Avg Similarity | 0.6121 | 0.6465 | +0.0344 |
| Avg Latency (ms) | 28 | 274 | +246 |
| Avg Diversity | 1.35 | 2.98 | +1.63 |
| Avg Top-5 Overlap | 0.0028 | -- | -- |
| Avg Top-10 Overlap | 0.0026 | -- | -- |
| Empty Queries | 0 | 0 | -- |

## Verdict: **QWEN3_BETTER**

Qwen3 embedding model shows higher similarity scores and equal or better diversity. Consider promotion to production.

## Per-Query Results (first 10)

### Q1: Show current portfolio composition and allocation

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6551 | Candidate avg sim: 0.6803
- Baseline diversity: 1 | Candidate diversity: 3
- Baseline latency: 22ms | Candidate latency: 1492ms

**Baseline top-3:**
  1. [agent_result:572863603] score=0.6768 — XLB steph: HOLD
  2. [agent_result:459282179] score=0.6712 — GLXG steph: TRIM
  3. [agent_result:1008374104] score=0.6669 — ETOR steph: RESEARCH_MORE

**Candidate top-3:**
  1. [youtube:842] score=0.7207 — Puzzle Wealth Streamline Your Deals with Expert Operations
  2. [youtube:962] score=0.7022 — My Portfolio Is At An ALL-TIME HIGH | Portfolio Update May 2026
  3. [news:4041] score=0.7022 — My Portfolio Is At An ALL-TIME HIGH | Portfolio Update May 2026

### Q2: What are the largest positions by market value?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6136 | Candidate avg sim: 0.5726
- Baseline diversity: 1 | Candidate diversity: 4
- Baseline latency: 367ms | Candidate latency: 423ms

**Baseline top-3:**
  1. [agent_result:1606140095] score=0.6473 — KBR steph: SELL
  2. [agent_result:1051353832] score=0.6248 — LMT maria_research: TRIM
  3. [agent_result:1628040969] score=0.6216 — NEE steph: HOLD

**Candidate top-3:**
  1. [youtube:842] score=0.6002 — Puzzle Wealth Streamline Your Deals with Expert Operations
  2. [social_post:2130] score=0.5830 — Clues for potential Stock market directions.                     
              
  3. [agent_result:115008672] score=0.5774 — SP500-D risk_agent: SKIP

### Q3: Find recent analysis for AVAV

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6432 | Candidate avg sim: 0.5700
- Baseline diversity: 1 | Candidate diversity: 4
- Baseline latency: 14ms | Candidate latency: 181ms

**Baseline top-3:**
  1. [agent_result:892102685] score=0.6583 — GLOB maria: HOLD
  2. [agent_result:492522555] score=0.6507 — BZ risk_agent: NONE
  3. [agent_result:1239192047] score=0.6472 — SHV maria: HOLD

**Candidate top-3:**
  1. [fused_signal:535] score=0.5918 — AVAL signal:
  2. [agent_result:1082930466] score=0.5879 — AVAV risk_agent: HOLD
  3. [brave_cache:0] score=0.5866 — brave:AVAV

### Q4: What is the current watchlist thesis for RKLB?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5960 | Candidate avg sim: 0.6370
- Baseline diversity: 1 | Candidate diversity: 4
- Baseline latency: 24ms | Candidate latency: 400ms

**Baseline top-3:**
  1. [agent_result:726386754] score=0.6317 — AJG maria: HOLD
  2. [agent_result:250113488] score=0.5974 — NPK maria: HOLD
  3. [agent_result:1061582367] score=0.5959 — PEW maria: HOLD

**Candidate top-3:**
  1. [cio_decision:386708566] score=0.6489 — RKLB CIO: HOLD
  2. [cio_decision:532644568] score=0.6489 — RKLB CIO: HOLD
  3. [cio_decision:180617163] score=0.6489 — RKLB CIO: HOLD

### Q5: Find recovery watch evidence for TDG

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5801 | Candidate avg sim: 0.6324
- Baseline diversity: 2 | Candidate diversity: 2
- Baseline latency: 16ms | Candidate latency: 189ms

**Baseline top-3:**
  1. [agent_result:1689694993] score=0.5957 — LITE risk_agent: HOLD
  2. [agent_result:492522555] score=0.5926 — BZ risk_agent: NONE
  3. [agent_result:169737314] score=0.5886 — DOX risk_agent: SKIP

**Candidate top-3:**
  1. [agent_result:544054387] score=0.6390 — TDG steph: HOLD
  2. [agent_result:1344926865] score=0.6383 — TDG steph: TRIM
  3. [agent_result:1159152436] score=0.6383 — TDG steph: TRIM

### Q6: What changed in RTX after stop-out?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6196 | Candidate avg sim: 0.7222
- Baseline diversity: 1 | Candidate diversity: 1
- Baseline latency: 26ms | Candidate latency: 394ms

**Baseline top-3:**
  1. [agent_result:220443609] score=0.6421 — KBR maria: AVOID
  2. [agent_result:1213992893] score=0.6404 — LDOS maria: AVOID
  3. [agent_result:1006034360] score=0.6373 — NOC maria: HOLD

**Candidate top-3:**
  1. [agent_result:153868872] score=0.7222 — RTX risk_agent: SELL
  2. [agent_result:1082763067] score=0.7222 — RTX risk_agent: SELL
  3. [agent_result:1741023860] score=0.7222 — RTX risk_agent: SELL

### Q7: Show recent closed trades with bad exits

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6690 | Candidate avg sim: 0.6118
- Baseline diversity: 2 | Candidate diversity: 4
- Baseline latency: 24ms | Candidate latency: 198ms

**Baseline top-3:**
  1. [agent_result:867901237] score=0.7036 — KBR risk_agent: SELL
  2. [agent_result:638451197] score=0.6938 — EYE risk_agent: HOLD
  3. [trade_review:32] score=0.6777 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)

**Candidate top-3:**
  1. [youtube:842] score=0.6419 — Puzzle Wealth Streamline Your Deals with Expert Operations
  2. [trade_outcome:19] score=0.6349 — FLYW trade outcome: UNKNOWN  (momentum_scalp)
  3. [trade_outcome:12] score=0.6259 — FLYW trade outcome: loss (swing_trade)

### Q8: Find failed breakout trades in the journal

- Top-5 overlap: 0.11 | Top-10 overlap: 0.05
- Baseline avg sim: 0.6464 | Candidate avg sim: 0.5976
- Baseline diversity: 2 | Candidate diversity: 6
- Baseline latency: 25ms | Candidate latency: 194ms

**Baseline top-3:**
  1. [trade_review:32] score=0.7541 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [trade_review:132] score=0.7151 — INFU overnight review: WIN $+67.83 (swing_breakout)
  3. [trade_review:222] score=0.6470 — GCTS overnight review: LOSS $-12.38 (momentum_scalp)

**Candidate top-3:**
  1. [news:3607] score=0.6104 — Yon Hybrid Momentum + Breakout Scanner with BB Squeeze — Indicator by ykm4evr - 
  2. [trade_review:32] score=0.6092 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  3. [youtube:246] score=0.6090 — Bitcoin Weekly Candle Close 🚨 Breakout or Bull Trap?

### Q9: What patterns exist in automated journal entries?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5004 | Candidate avg sim: 0.5789
- Baseline diversity: 2 | Candidate diversity: 4
- Baseline latency: 18ms | Candidate latency: 386ms

**Baseline top-3:**
  1. [trade_review:32] score=0.5197 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [trade_review:202] score=0.5089 — GCTS overnight review: LOSS $-9.38 (momentum_scalp)
  3. [agent_result:1382901955] score=0.5023 — APPS maria: HOLD

**Candidate top-3:**
  1. [news:3729] score=0.6240 — Behavioral Patterns of JEPI and Institutional Flows - Stock Traders Daily
  2. [youtube:842] score=0.6138 — Puzzle Wealth Streamline Your Deals with Expert Operations
  3. [youtube:819] score=0.5796 — SSI Update: New SSA Bank Account Monitoring Rules Explained

### Q10: Show journal evidence for early exits

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5985 | Candidate avg sim: 0.6015
- Baseline diversity: 2 | Candidate diversity: 3
- Baseline latency: 12ms | Candidate latency: 172ms

**Baseline top-3:**
  1. [trade_review:32] score=0.6482 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [trade_review:132] score=0.6101 — INFU overnight review: WIN $+67.83 (swing_breakout)
  3. [trade_review:202] score=0.6049 — GCTS overnight review: LOSS $-9.38 (momentum_scalp)

**Candidate top-3:**
  1. [fused_signal:1168] score=0.6169 — EXK signal:
  2. [fused_signal:659] score=0.6083 — WENT signal:
  3. [fused_signal:540] score=0.6033 — JUST signal:

---
*Generated by compare_phase2b_parallel_retrieval.py*