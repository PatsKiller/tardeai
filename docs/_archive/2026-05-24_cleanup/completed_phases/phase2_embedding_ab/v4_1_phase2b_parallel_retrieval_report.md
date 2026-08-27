# Phase 2B Parallel Retrieval Quality Comparison

**Date:** 2026-05-14T10:41:03.320613
**Baseline:** nomic-embed-text (table: content_embeddings, 14788 docs)
**Candidate:** qwen3-embedding:8b (table: content_embeddings_qwen3_test, 1000 docs)
**Queries:** 40 | **Top-K:** 10
**Production changed:** False | **Routing changed:** False

## Aggregate Metrics

| Metric | Baseline | Candidate | Delta |
|--------|----------|-----------|-------|
| Avg Similarity | 0.6128 | 0.6087 | -0.0041 |
| Avg Latency (ms) | 28 | 321 | +293 |
| Avg Diversity | 1.43 | 2.08 | +0.65 |
| Avg Top-5 Overlap | 0.0056 | -- | -- |
| Avg Top-10 Overlap | 0.0135 | -- | -- |
| Empty Queries | 0 | 0 | -- |

## Verdict: **HYBRID_RECOMMENDED**

Models retrieve substantially different documents with similar quality. A hybrid approach may capture broader relevant content.

## Per-Query Results (first 10)

### Q1: Show current portfolio composition and allocation

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6527 | Candidate avg sim: 0.5791
- Baseline diversity: 1 | Candidate diversity: 2
- Baseline latency: 22ms | Candidate latency: 1495ms

**Baseline top-3:**
  1. [agent_result:572863603] score=0.6768 — XLB steph: HOLD
  2. [agent_result:459282179] score=0.6712 — GLXG steph: TRIM
  3. [agent_result:1008374104] score=0.6669 — ETOR steph: RESEARCH_MORE

**Candidate top-3:**
  1. [agent_result:136733750] score=0.6281 — LQD risk_agent: NO_RECOMMENDATION
  2. [agent_result:1945515383] score=0.6054 — XLI risk_agent: SKIP_DUE_TO_STALE_DATA
  3. [agent_result:1744313560] score=0.5765 — ALAI risk_agent: HOLD

### Q2: What are the largest positions by market value?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6136 | Candidate avg sim: 0.5153
- Baseline diversity: 1 | Candidate diversity: 2
- Baseline latency: 353ms | Candidate latency: 405ms

**Baseline top-3:**
  1. [agent_result:1606140095] score=0.6473 — KBR steph: SELL
  2. [agent_result:1051353832] score=0.6248 — LMT maria_research: TRIM
  3. [agent_result:1628040969] score=0.6216 — NEE steph: HOLD

**Candidate top-3:**
  1. [agent_result:136733750] score=0.5304 — LQD risk_agent: NO_RECOMMENDATION
  2. [agent_result:1945515383] score=0.5303 — XLI risk_agent: SKIP_DUE_TO_STALE_DATA
  3. [fused_signal:890] score=0.5275 — XLK signal:

### Q3: Find recent analysis for AVAV

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6458 | Candidate avg sim: 0.5015
- Baseline diversity: 1 | Candidate diversity: 2
- Baseline latency: 13ms | Candidate latency: 176ms

**Baseline top-3:**
  1. [agent_result:892102685] score=0.6583 — GLOB maria: HOLD
  2. [agent_result:12698751] score=0.6564 — ITGR maria: HOLD
  3. [agent_result:492522555] score=0.6507 — BZ risk_agent: NONE

**Candidate top-3:**
  1. [agent_result:1082930466] score=0.5879 — AVAV risk_agent: HOLD
  2. [fused_signal:972] score=0.5310 — AVNW signal:
  3. [fused_signal:990] score=0.5292 — ABVX signal:

### Q4: What is the current watchlist thesis for RKLB?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5980 | Candidate avg sim: 0.5446
- Baseline diversity: 1 | Candidate diversity: 1
- Baseline latency: 19ms | Candidate latency: 380ms

**Baseline top-3:**
  1. [agent_result:726386754] score=0.6317 — AJG maria: HOLD
  2. [agent_result:773647803] score=0.5981 — CORT risk_agent: HOLD
  3. [agent_result:250113488] score=0.5974 — NPK maria: HOLD

**Candidate top-3:**
  1. [agent_result:684793092] score=0.5774 — RKLB risk_agent: TRIM
  2. [agent_result:613034086] score=0.5751 — XLB risk_agent: HOLD
  3. [agent_result:2088560067] score=0.5751 — XLB risk_agent: HOLD

### Q5: Find recovery watch evidence for TDG

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5801 | Candidate avg sim: 0.6133
- Baseline diversity: 2 | Candidate diversity: 2
- Baseline latency: 13ms | Candidate latency: 188ms

**Baseline top-3:**
  1. [agent_result:1689694993] score=0.5957 — LITE risk_agent: HOLD
  2. [agent_result:492522555] score=0.5926 — BZ risk_agent: NONE
  3. [agent_result:169737314] score=0.5886 — DOX risk_agent: SKIP

**Candidate top-3:**
  1. [agent_result:1644490938] score=0.6383 — TDG steph: TRIM
  2. [agent_result:2035351515] score=0.6272 — TDG maria: HOLD
  3. [agent_result:1931408375] score=0.6272 — TDG maria: HOLD

### Q6: What changed in RTX after stop-out?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.6196 | Candidate avg sim: 0.6446
- Baseline diversity: 1 | Candidate diversity: 3
- Baseline latency: 22ms | Candidate latency: 466ms

**Baseline top-3:**
  1. [agent_result:220443609] score=0.6421 — KBR maria: AVOID
  2. [agent_result:1213992893] score=0.6404 — LDOS maria: AVOID
  3. [agent_result:1006034360] score=0.6373 — NOC maria: HOLD

**Candidate top-3:**
  1. [agent_result:684609361] score=0.6891 — RTX risk_agent: TRIM
  2. [agent_result:2103814302] score=0.6724 — RTX maria: HOLD
  3. [agent_result:795421258] score=0.6449 — MLTX risk_agent: AVOID

### Q7: Show recent closed trades with bad exits

- Top-5 overlap: 0.00 | Top-10 overlap: 0.05
- Baseline avg sim: 0.6698 | Candidate avg sim: 0.5977
- Baseline diversity: 3 | Candidate diversity: 4
- Baseline latency: 22ms | Candidate latency: 194ms

**Baseline top-3:**
  1. [agent_result:867901237] score=0.7036 — KBR risk_agent: SELL
  2. [agent_result:638451197] score=0.6938 — EYE risk_agent: HOLD
  3. [trade_review:32] score=0.6777 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)

**Candidate top-3:**
  1. [trade_outcome:19] score=0.6349 — FLYW trade outcome: UNKNOWN  (momentum_scalp)
  2. [trade_outcome:12] score=0.6259 — FLYW trade outcome: loss (swing_trade)
  3. [agent_result:1945515383] score=0.5990 — XLI risk_agent: SKIP_DUE_TO_STALE_DATA

### Q8: Find failed breakout trades in the journal

- Top-5 overlap: 0.11 | Top-10 overlap: 0.11
- Baseline avg sim: 0.6480 | Candidate avg sim: 0.5716
- Baseline diversity: 3 | Candidate diversity: 4
- Baseline latency: 21ms | Candidate latency: 218ms

**Baseline top-3:**
  1. [trade_review:32] score=0.7541 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [trade_review:132] score=0.7151 — INFU overnight review: WIN $+67.83 (swing_breakout)
  3. [trade_review:222] score=0.6470 — GCTS overnight review: LOSS $-12.38 (momentum_scalp)

**Candidate top-3:**
  1. [trade_review:32] score=0.6092 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [fused_signal:1054] score=0.6044 — BRKR signal:
  3. [trade_outcome:19] score=0.6002 — FLYW trade outcome: UNKNOWN  (momentum_scalp)

### Q9: What patterns exist in automated journal entries?

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5024 | Candidate avg sim: 0.5431
- Baseline diversity: 2 | Candidate diversity: 2
- Baseline latency: 27ms | Candidate latency: 530ms

**Baseline top-3:**
  1. [trade_review:32] score=0.5197 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [agent_result:773647803] score=0.5104 — CORT risk_agent: HOLD
  3. [trade_review:202] score=0.5089 — GCTS overnight review: LOSS $-9.38 (momentum_scalp)

**Candidate top-3:**
  1. [agent_result:1945515383] score=0.5673 — XLI risk_agent: SKIP_DUE_TO_STALE_DATA
  2. [agent_result:1824404147] score=0.5648 — ABUS risk_agent: LOW_CONFIDENCE_SKIP
  3. [fused_signal:1252] score=0.5447 — AMJB signal:

### Q10: Show journal evidence for early exits

- Top-5 overlap: 0.00 | Top-10 overlap: 0.00
- Baseline avg sim: 0.5985 | Candidate avg sim: 0.5944
- Baseline diversity: 2 | Candidate diversity: 2
- Baseline latency: 13ms | Candidate latency: 168ms

**Baseline top-3:**
  1. [trade_review:32] score=0.6482 — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [trade_review:132] score=0.6101 — INFU overnight review: WIN $+67.83 (swing_breakout)
  3. [trade_review:202] score=0.6049 — GCTS overnight review: LOSS $-9.38 (momentum_scalp)

**Candidate top-3:**
  1. [fused_signal:1168] score=0.6169 — EXK signal:
  2. [fused_signal:1225] score=0.6017 — ED signal:
  3. [agent_result:1936826020] score=0.5984 — BRCB steph: LOW_CONFIDENCE_SKIP

---
*Generated by compare_phase2b_parallel_retrieval.py*