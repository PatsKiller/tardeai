# Phase 2B Expansion — Coverage Gap Analysis

**Date:** 2026-05-14

## Production Source Mix (14,796 rows)

| Source Type | Production Count | % of Total |
|-------------|-----------------|------------|
| agent_result | 4,830 | 32.6% |
| news | 3,339 | 22.6% |
| social_post | 2,245 | 15.2% |
| fused_signal | 1,264 | 8.5% |
| decision_outcome | 860 | 5.8% |
| youtube | 818 | 5.5% |
| agent_synthesis | 780 | 5.3% |
| cio_decision | 446 | 3.0% |
| sec_form4 | 166 | 1.1% |
| fred_series | 28 | 0.2% |
| trade_review | 11 | 0.1% |
| trade_outcome | 7 | 0.05% |
| brave_cache | 1 | <0.01% |
| test | 1 | <0.01% |

## Current Qwen3 Index (1,000 rows) — Before Expansion

| Source Type | Qwen3 Count | Coverage % |
|-------------|-------------|------------|
| agent_result | 576 | 11.9% |
| fused_signal | 399 | 31.6% |
| trade_review | 11 | 100% |
| news | 8 | 0.24% |
| trade_outcome | 6 | 85.7% |
| **8 source types** | **0** | **0%** |

**Critical gaps:** news (0.24%), social_post (0%), decision_outcome (0%), youtube (0%), agent_synthesis (0%), cio_decision (0%), sec_form4 (0%), fred_series (0%)

## Proposed 5,000-Doc Source Mix

| Source Type | Target | Actual Fetched | Notes |
|-------------|--------|---------------|-------|
| agent_result | 1,500 | 1,500 | Core analysis content |
| fused_signal | 900 | 900 | Signal fusion outputs |
| news | 600 | 600 | News articles |
| decision_outcome | 500 | 500 | CIO decision outcomes |
| agent_synthesis | 400 | 400 | Agent synthesis narratives |
| cio_decision | 400 | 400 | CIO decisions |
| youtube | 250 | 250 | YouTube transcripts |
| social_post | 200 | 200 | Social/scalp content |
| sec_form4 | 100 | 100 | SEC insider filings |
| trade_review | 50 | 11 | All available |
| trade_outcome | 50 | 7 | All available |
| fred_series | 28 | 28 | All available |
| brave_cache | 10 | 1 | All available |
| **Total** | **4,988** | **4,897** | |

## Expected Coverage Improvement

| Metric | Before (1K) | After (5K) |
|--------|------------|------------|
| Source types covered | 5 of 14 | 13 of 14 |
| Production coverage | 6.8% | ~33% |
| news coverage | 0.24% | ~18% |
| decision_outcome coverage | 0% | ~58% |
| youtube coverage | 0% | ~31% |
| agent_synthesis coverage | 0% | ~51% |
| cio_decision coverage | 0% | ~90% |
| sec_form4 coverage | 0% | ~60% |

This should substantially improve hybrid consensus, since qwen3 will now be able to find the same document types that nomic finds.
