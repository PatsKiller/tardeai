# Hermes Phase 4A — Promotion Dry-Run Report

**Date:** 2026-05-31
**Status:** DRY-RUN ONLY — zero DB writes

## Candidates

| ID | Symbol | Type | Confidence | Eligible | Target Section |
|----|--------|------|------------|----------|----------------|
| 1 | FLYW | ticker_thesis_challenge | 0.6 | YES | hermes_ticker_thesis_challenge_FLYW |
| 2 | SPRC | ticker_thesis_challenge | 0.6 | YES | hermes_ticker_thesis_challenge_SPRC |
| 3 | SCHD | news_research_reframe | 0.6 | YES | hermes_news_research_reframe_SCHD |
| 4 | APPS | trade_reflection | 0.7 | YES | hermes_trade_reflection_APPS |
| 5 | INFU | ticker_thesis_challenge | 0.7 | YES | hermes_ticker_thesis_challenge_INFU |
| 6 | ASPN | trade_reflection | 0.6 | YES | hermes_trade_reflection_ASPN |
| 7 | — | pipeline_quality_validation | 0.6 | YES | hermes_pipeline_quality_validation_system |
| 8 | FJSCX | ticker_thesis_challenge | 0.6 | YES | hermes_ticker_thesis_challenge_FJSCX |
| 9 | TELO | ticker_thesis_challenge | 0.2 | **NO** | — |
| 10 | APAM | ticker_thesis_challenge | 0.6 | YES | hermes_ticker_thesis_challenge_APAM |
| 11 | TRX | ticker_thesis_challenge | 0.6 | YES | hermes_ticker_thesis_challenge_TRX |

**Selected: 10 | Rejected: 1 (TELO — confidence 0.2)**

## Rejection Detail

| ID | Symbol | Reason |
|----|--------|--------|
| 9 | TELO | confidence_score 0.2 below 0.3 threshold |

## Safety Checks

| Check | Result |
|-------|--------|
| DB writes | **ZERO** |
| Production mutations | **ZERO** |
| Promotion audit rows | **ZERO** |
| Status changes | **ZERO** |
| Files only | YES — docs/hermes/phase4a_dryrun/ |

## Recommendation

Proceed to Phase 4B with capped first promotion (≤3 rows) into llm_intelligence_cache. Requires separate operator approval.
