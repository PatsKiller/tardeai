# Phase 2C: Hybrid RAG Retrieval Pilot Report

**Date:** 2026-05-14T11:02:14.913531
**Nomic table:** content_embeddings (14791 docs)
**Qwen3 table:** content_embeddings_qwen3_test (1000 docs)
**Queries:** 40 | **Top-K baseline:** 10 | **Top-K candidate:** 10 | **Final-K:** 10
**Production changed:** False | **Routing changed:** False

---

## Summary Table

| Metric | Value |
|--------|-------|
| Queries tested | 40 |
| Avg source diversity | 1.88 |
| Avg hybrid score | 0.6988 |
| Consensus items (both models) | 10 |
| Nomic-only items | 164 |
| Qwen3-only items | 226 |
| Both-model items | 10 |
| Avg nomic embed latency | 20ms |
| Avg qwen3 embed latency | 314ms |
| Avg hybrid total latency | 1713ms |
| Empty result queries | 0/40 |
| Empty result rate | 0.0% |

### Model Source Distribution (across all final results)

| Source | Count | Pct |
|--------|-------|-----|
| nomic-only | 164 | 41.0% |
| qwen3-only | 226 | 56.5% |
| both | 10 | 2.5% |

---

## Per-Query Results (first 10)

### Q1: Show current portfolio composition and allocation

- Source diversity: 1 unique types
- Nomic latency: 20ms | Qwen3 latency: 211ms
- Consensus items: 0
- Model distribution: nomic=10 qwen3=0 both=0

**Hybrid top-5:**
  1. [agent_result:572863603] hybrid=0.7193 sim=0.6768 model=nomic — XLB steph: HOLD
  2. [agent_result:459282179] hybrid=0.7101 sim=0.6712 model=nomic — GLXG steph: TRIM
  3. [agent_result:1008374104] hybrid=0.7070 sim=0.6669 model=nomic — ETOR steph: RESEARCH_MORE
  4. [agent_result:189583865] hybrid=0.7037 sim=0.6625 model=nomic — CSWC steph: HOLD
  5. [agent_result:763472831] hybrid=0.7025 sim=0.6609 model=nomic — BND steph: HOLD

### Q2: What are the largest positions by market value?

- Source diversity: 1 unique types
- Nomic latency: 28ms | Qwen3 latency: 544ms
- Consensus items: 0
- Model distribution: nomic=10 qwen3=0 both=0

**Hybrid top-5:**
  1. [agent_result:1606140095] hybrid=0.7193 sim=0.6473 model=nomic — KBR steph: SELL
  2. [agent_result:1051353832] hybrid=0.6969 sim=0.6248 model=nomic — LMT maria_research: TRIM
  3. [agent_result:1628040969] hybrid=0.6944 sim=0.6216 model=nomic — NEE steph: HOLD
  4. [agent_result:502272627] hybrid=0.6918 sim=0.6182 model=nomic — ENPH risk_agent: TRIM
  5. [agent_result:1567973970] hybrid=0.6867 sim=0.6116 model=nomic — SCHD risk_agent: HOLD

### Q3: Find recent analysis for AVAV

- Source diversity: 1 unique types
- Nomic latency: 13ms | Qwen3 latency: 164ms
- Consensus items: 0
- Model distribution: nomic=10 qwen3=0 both=0

**Hybrid top-5:**
  1. [agent_result:892102685] hybrid=0.7193 sim=0.6583 model=nomic — GLOB maria: HOLD
  2. [agent_result:12698751] hybrid=0.7128 sim=0.6564 model=nomic — ITGR maria: HOLD
  3. [agent_result:492522555] hybrid=0.7085 sim=0.6507 model=nomic — BZ risk_agent: NONE
  4. [agent_result:1239192047] hybrid=0.7059 sim=0.6472 model=nomic — SHV maria: HOLD
  5. [agent_result:1670043008] hybrid=0.7049 sim=0.6460 model=nomic — FPS risk_agent: HOLD

### Q4: What is the current watchlist thesis for RKLB?

- Source diversity: 1 unique types
- Nomic latency: 22ms | Qwen3 latency: 456ms
- Consensus items: 0
- Model distribution: nomic=10 qwen3=0 both=0

**Hybrid top-5:**
  1. [agent_result:726386754] hybrid=0.7193 sim=0.6317 model=nomic — AJG maria: HOLD
  2. [agent_result:250113488] hybrid=0.6871 sim=0.5974 model=nomic — NPK maria: HOLD
  3. [agent_result:1061582367] hybrid=0.6860 sim=0.5959 model=nomic — PEW maria: HOLD
  4. [agent_result:1506857466] hybrid=0.6855 sim=0.5954 model=nomic — LI maria: HOLD
  5. [agent_result:1880044713] hybrid=0.6854 sim=0.5952 model=nomic — CCK maria: HOLD

### Q5: Find recovery watch evidence for TDG

- Source diversity: 2 unique types
- Nomic latency: 13ms | Qwen3 latency: 234ms
- Consensus items: 0
- Model distribution: nomic=1 qwen3=9 both=0

**Hybrid top-5:**
  1. [fused_signal:1200] hybrid=0.7225 sim=0.6242 model=qwen3 — TTD signal:
  2. [agent_result:1644490938] hybrid=0.7143 sim=0.6383 model=qwen3 — TDG steph: TRIM
  3. [agent_result:1931408375] hybrid=0.7056 sim=0.6272 model=qwen3 — TDG maria: HOLD
  4. [agent_result:2035351515] hybrid=0.7056 sim=0.6272 model=qwen3 — TDG maria: HOLD
  5. [agent_result:152406386] hybrid=0.6977 sim=0.6171 model=qwen3 — CCLD risk_agent: WAIT

### Q6: What changed in RTX after stop-out?

- Source diversity: 2 unique types
- Nomic latency: 23ms | Qwen3 latency: 394ms
- Consensus items: 0
- Model distribution: nomic=2 qwen3=8 both=0

**Hybrid top-5:**
  1. [agent_result:684609361] hybrid=0.7143 sim=0.6891 model=qwen3 — RTX risk_agent: TRIM
  2. [agent_result:2103814302] hybrid=0.7022 sim=0.6724 model=qwen3 — RTX maria: HOLD
  3. [fused_signal:1185] hybrid=0.6993 sim=0.6418 model=qwen3 — BTG signal:
  4. [fused_signal:894] hybrid=0.6917 sim=0.6382 model=qwen3 — DGX signal:
  5. [fused_signal:1056] hybrid=0.6889 sim=0.6344 model=qwen3 — CBT signal:

### Q7: Show recent closed trades with bad exits

- Source diversity: 3 unique types
- Nomic latency: 23ms | Qwen3 latency: 208ms
- Consensus items: 1
- Model distribution: nomic=5 qwen3=4 both=1

**Hybrid top-5:**
  1. [trade_outcome:22] hybrid=0.7794 sim=0.6605 model=both — GCTS trade outcome: LOSS -0.1R (momentum_scalp)
  2. [trade_outcome:19] hybrid=0.7512 sim=0.6349 model=qwen3 — FLYW trade outcome: UNKNOWN  (momentum_scalp)
  3. [trade_outcome:12] hybrid=0.7448 sim=0.6259 model=qwen3 — FLYW trade outcome: loss (swing_trade)
  4. [trade_outcome:16] hybrid=0.7249 sim=0.5979 model=qwen3 — BLBD trade outcome: UNKNOWN  (earnings_catalyst)
  5. [agent_result:867901237] hybrid=0.7193 sim=0.7036 model=nomic — KBR risk_agent: SELL

### Q8: Find failed breakout trades in the journal

- Source diversity: 4 unique types
- Nomic latency: 28ms | Qwen3 latency: 287ms
- Consensus items: 2
- Model distribution: nomic=3 qwen3=5 both=2

**Hybrid top-5:**
  1. [trade_outcome:22] hybrid=0.7219 sim=0.6212 model=both — GCTS trade outcome: LOSS -0.1R (momentum_scalp)
  2. [trade_review:32] hybrid=0.7100 sim=0.7541 model=both — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  3. [trade_outcome:19] hybrid=0.6980 sim=0.6002 model=qwen3 — FLYW trade outcome: UNKNOWN  (momentum_scalp)
  4. [trade_outcome:12] hybrid=0.6859 sim=0.5820 model=qwen3 — FLYW trade outcome: loss (swing_trade)
  5. [trade_review:132] hybrid=0.6742 sim=0.7151 model=nomic — INFU overnight review: WIN $+67.83 (swing_breakout)

### Q9: What patterns exist in automated journal entries?

- Source diversity: 2 unique types
- Nomic latency: 28ms | Qwen3 latency: 551ms
- Consensus items: 0
- Model distribution: nomic=0 qwen3=10 both=0

**Hybrid top-5:**
  1. [agent_result:1945515383] hybrid=0.7143 sim=0.5673 model=qwen3 — XLI risk_agent: SKIP_DUE_TO_STALE_DATA
  2. [fused_signal:1252] hybrid=0.7136 sim=0.5447 model=qwen3 — AMJB signal:
  3. [agent_result:1824404147] hybrid=0.7121 sim=0.5648 model=qwen3 — ABUS risk_agent: LOW_CONFIDENCE_SKIP
  4. [fused_signal:937] hybrid=0.7076 sim=0.5436 model=qwen3 — ABEO signal:
  5. [fused_signal:1247] hybrid=0.7036 sim=0.5390 model=qwen3 — AGMI signal:

### Q10: Show journal evidence for early exits

- Source diversity: 3 unique types
- Nomic latency: 14ms | Qwen3 latency: 196ms
- Consensus items: 0
- Model distribution: nomic=3 qwen3=7 both=0

**Hybrid top-5:**
  1. [fused_signal:1168] hybrid=0.7094 sim=0.6169 model=qwen3 — EXK signal:
  2. [trade_review:32] hybrid=0.7050 sim=0.6482 model=nomic — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  3. [fused_signal:1225] hybrid=0.6927 sim=0.6017 model=qwen3 — ED signal:
  4. [fused_signal:921] hybrid=0.6868 sim=0.5941 model=qwen3 — EDBL signal:
  5. [fused_signal:1240] hybrid=0.6851 sim=0.5918 model=qwen3 — EOSE signal:

---

## Verdict: **HYBRID_MARGINAL**

Hybrid retrieval shows some benefit but the improvement over nomic-only is modest. Consider targeted hybrid routing for specific query contexts (journal review, deep overnight) rather than blanket hybrid.

---
*Generated by hybrid_rag_retrieval_pilot.py*