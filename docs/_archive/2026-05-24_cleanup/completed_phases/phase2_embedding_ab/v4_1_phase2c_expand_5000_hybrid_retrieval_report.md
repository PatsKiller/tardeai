# Phase 2C: Hybrid RAG Retrieval Pilot Report

**Date:** 2026-05-14T12:01:38.900878
**Nomic table:** content_embeddings (14797 docs)
**Qwen3 table:** content_embeddings_qwen3_test (4897 docs)
**Queries:** 40 | **Top-K baseline:** 10 | **Top-K candidate:** 10 | **Final-K:** 10
**Production changed:** False | **Routing changed:** False

---

## Summary Table

| Metric | Value |
|--------|-------|
| Queries tested | 40 |
| Avg source diversity | 2.73 |
| Avg hybrid score | 0.7042 |
| Consensus items (both models) | 2 |
| Nomic-only items | 112 |
| Qwen3-only items | 286 |
| Both-model items | 2 |
| Avg nomic embed latency | 28ms |
| Avg qwen3 embed latency | 275ms |
| Avg hybrid total latency | 6881ms |
| Empty result queries | 0/40 |
| Empty result rate | 0.0% |

### Model Source Distribution (across all final results)

| Source | Count | Pct |
|--------|-------|-----|
| nomic-only | 112 | 28.0% |
| qwen3-only | 286 | 71.5% |
| both | 2 | 0.5% |

---

## Per-Query Results (first 10)

### Q1: Show current portfolio composition and allocation

- Source diversity: 3 unique types
- Nomic latency: 18ms | Qwen3 latency: 1524ms
- Consensus items: 0
- Model distribution: nomic=5 qwen3=5 both=0

**Hybrid top-5:**
  1. [youtube:842] hybrid=0.7050 sim=0.7207 model=qwen3 — Puzzle Wealth Streamline Your Deals with Expert Operations
  2. [news:4041] hybrid=0.6921 sim=0.7022 model=qwen3 — My Portfolio Is At An ALL-TIME HIGH | Portfolio Update May 2026
  3. [agent_result:572863603] hybrid=0.6888 sim=0.6768 model=nomic — XLB steph: HOLD
  4. [youtube:962] hybrid=0.6871 sim=0.7022 model=qwen3 — My Portfolio Is At An ALL-TIME HIGH | Portfolio Update May 2026
  5. [agent_result:459282179] hybrid=0.6799 sim=0.6712 model=nomic — GLXG steph: TRIM

### Q2: What are the largest positions by market value?

- Source diversity: 1 unique types
- Nomic latency: 354ms | Qwen3 latency: 410ms
- Consensus items: 0
- Model distribution: nomic=10 qwen3=0 both=0

**Hybrid top-5:**
  1. [agent_result:1606140095] hybrid=0.7193 sim=0.6473 model=nomic — KBR steph: SELL
  2. [agent_result:1051353832] hybrid=0.6969 sim=0.6248 model=nomic — LMT maria_research: TRIM
  3. [agent_result:1628040969] hybrid=0.6944 sim=0.6216 model=nomic — NEE steph: HOLD
  4. [agent_result:502272627] hybrid=0.6918 sim=0.6182 model=nomic — ENPH risk_agent: TRIM
  5. [agent_result:1567973970] hybrid=0.6867 sim=0.6116 model=nomic — SCHD risk_agent: HOLD

### Q3: Find recent analysis for AVAV

- Source diversity: 2 unique types
- Nomic latency: 13ms | Qwen3 latency: 178ms
- Consensus items: 0
- Model distribution: nomic=7 qwen3=3 both=0

**Hybrid top-5:**
  1. [agent_result:892102685] hybrid=0.7193 sim=0.6583 model=nomic — GLOB maria: HOLD
  2. [decision_outcome:490] hybrid=0.7143 sim=0.5577 model=qwen3 — AVEM outcome: RESEARCH_MORE
  3. [agent_result:492522555] hybrid=0.7085 sim=0.6507 model=nomic — BZ risk_agent: NONE
  4. [agent_result:1239192047] hybrid=0.7059 sim=0.6472 model=nomic — SHV maria: HOLD
  5. [decision_outcome:511] hybrid=0.7052 sim=0.5524 model=qwen3 — AVUV outcome: RESEARCH_MORE

### Q4: What is the current watchlist thesis for RKLB?

- Source diversity: 4 unique types
- Nomic latency: 22ms | Qwen3 latency: 394ms
- Consensus items: 0
- Model distribution: nomic=1 qwen3=9 both=0

**Hybrid top-5:**
  1. [cio_decision:991979655] hybrid=0.7479 sim=0.6489 model=qwen3 — RKLB CIO: HOLD
  2. [cio_decision:1781388000] hybrid=0.7429 sim=0.6489 model=qwen3 — RKLB CIO: HOLD
  3. [cio_decision:136128104] hybrid=0.7429 sim=0.6489 model=qwen3 — RKLB CIO: HOLD
  4. [cio_decision:2137526963] hybrid=0.7429 sim=0.6489 model=qwen3 — RKLB CIO: HOLD
  5. [cio_decision:180617163] hybrid=0.7429 sim=0.6489 model=qwen3 — RKLB CIO: HOLD

### Q5: Find recovery watch evidence for TDG

- Source diversity: 2 unique types
- Nomic latency: 12ms | Qwen3 latency: 179ms
- Consensus items: 0
- Model distribution: nomic=0 qwen3=10 both=0

**Hybrid top-5:**
  1. [decision_outcome:648] hybrid=0.7805 sim=0.6260 model=qwen3 — GBTG outcome: IGNORE
  2. [agent_result:544054387] hybrid=0.7143 sim=0.6390 model=qwen3 — TDG steph: HOLD
  3. [agent_result:1644490938] hybrid=0.7137 sim=0.6383 model=qwen3 — TDG steph: TRIM
  4. [agent_result:1653173325] hybrid=0.7137 sim=0.6383 model=qwen3 — TDG steph: TRIM
  5. [agent_result:1159152436] hybrid=0.7137 sim=0.6383 model=qwen3 — TDG steph: TRIM

### Q6: What changed in RTX after stop-out?

- Source diversity: 1 unique types
- Nomic latency: 21ms | Qwen3 latency: 401ms
- Consensus items: 0
- Model distribution: nomic=0 qwen3=10 both=0

**Hybrid top-5:**
  1. [agent_result:181123528] hybrid=0.7143 sim=0.7222 model=qwen3 — RTX risk_agent: SELL
  2. [agent_result:1652813326] hybrid=0.7143 sim=0.7222 model=qwen3 — RTX risk_agent: SELL
  3. [agent_result:22831146] hybrid=0.7143 sim=0.7222 model=qwen3 — RTX risk_agent: SELL
  4. [agent_result:107427294] hybrid=0.7143 sim=0.7222 model=qwen3 — RTX risk_agent: SELL
  5. [agent_result:677874799] hybrid=0.7143 sim=0.7222 model=qwen3 — RTX risk_agent: SELL

### Q7: Show recent closed trades with bad exits

- Source diversity: 3 unique types
- Nomic latency: 21ms | Qwen3 latency: 191ms
- Consensus items: 0
- Model distribution: nomic=7 qwen3=3 both=0

**Hybrid top-5:**
  1. [trade_outcome:19] hybrid=0.7562 sim=0.6349 model=qwen3 — FLYW trade outcome: UNKNOWN  (momentum_scalp)
  2. [trade_outcome:12] hybrid=0.7448 sim=0.6259 model=qwen3 — FLYW trade outcome: loss (swing_trade)
  3. [trade_outcome:16] hybrid=0.7249 sim=0.5979 model=qwen3 — BLBD trade outcome: UNKNOWN  (earnings_catalyst)
  4. [agent_result:867901237] hybrid=0.7193 sim=0.7036 model=nomic — KBR risk_agent: SELL
  5. [agent_result:638451197] hybrid=0.7073 sim=0.6938 model=nomic — EYE risk_agent: HOLD

### Q8: Find failed breakout trades in the journal

- Source diversity: 5 unique types
- Nomic latency: 22ms | Qwen3 latency: 192ms
- Consensus items: 1
- Model distribution: nomic=5 qwen3=4 both=1

**Hybrid top-5:**
  1. [trade_review:32] hybrid=0.7100 sim=0.7541 model=both — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  2. [trade_outcome:19] hybrid=0.7030 sim=0.6002 model=qwen3 — FLYW trade outcome: UNKNOWN  (momentum_scalp)
  3. [decision_outcome:717] hybrid=0.6914 sim=0.6043 model=qwen3 — BRKR outcome: RESEARCH_MORE
  4. [trade_outcome:12] hybrid=0.6859 sim=0.5820 model=qwen3 — FLYW trade outcome: loss (swing_trade)
  5. [trade_review:132] hybrid=0.6742 sim=0.7151 model=nomic — INFU overnight review: WIN $+67.83 (swing_breakout)

### Q9: What patterns exist in automated journal entries?

- Source diversity: 4 unique types
- Nomic latency: 18ms | Qwen3 latency: 375ms
- Consensus items: 0
- Model distribution: nomic=0 qwen3=10 both=0

**Hybrid top-5:**
  1. [news:3729] hybrid=0.7050 sim=0.6240 model=qwen3 — Behavioral Patterns of JEPI and Institutional Flows - Stock Traders Daily
  2. [cio_decision:2072136410] hybrid=0.6988 sim=0.5628 model=qwen3 — AB-DISC-Z CIO: HUMAN_REVIEW
  3. [youtube:842] hybrid=0.6969 sim=0.6138 model=qwen3 — Puzzle Wealth Streamline Your Deals with Expert Operations
  4. [cio_decision:1649239434] hybrid=0.6938 sim=0.5628 model=qwen3 — AB-DISC-Z CIO: HUMAN_REVIEW
  5. [agent_result:1945515383] hybrid=0.6689 sim=0.5673 model=qwen3 — XLI risk_agent: SKIP_DUE_TO_STALE_DATA

### Q10: Show journal evidence for early exits

- Source diversity: 3 unique types
- Nomic latency: 12ms | Qwen3 latency: 170ms
- Consensus items: 0
- Model distribution: nomic=1 qwen3=9 both=0

**Hybrid top-5:**
  1. [decision_outcome:654] hybrid=0.7499 sim=0.5952 model=qwen3 — ETD outcome: IGNORE
  2. [fused_signal:1168] hybrid=0.7094 sim=0.6169 model=qwen3 — EXK signal:
  3. [trade_review:32] hybrid=0.7050 sim=0.6482 model=nomic — XMTR overnight review: BREAKEVEN $+0.00 (swing_breakout)
  4. [fused_signal:659] hybrid=0.6978 sim=0.6083 model=qwen3 — WENT signal:
  5. [fused_signal:540] hybrid=0.6940 sim=0.6033 model=qwen3 — JUST signal:

---

## Verdict: **HYBRID_MARGINAL**

Hybrid retrieval shows some benefit but the improvement over nomic-only is modest. Consider targeted hybrid routing for specific query contexts (journal review, deep overnight) rather than blanket hybrid.

---
*Generated by hybrid_rag_retrieval_pilot.py*