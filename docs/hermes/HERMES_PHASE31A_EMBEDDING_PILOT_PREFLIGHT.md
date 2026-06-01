# Hermes Phase 31A — Embedding Pilot Preflight

**Date:** 2026-06-01
**Status:** COMPLETE

## Source Record Verification

| ID | Symbol | Type | Status | Confidence | Summary |
|----|--------|------|--------|------------|---------|
| 12 | SCHD | source_discovery | staged | 0.50 | SA upgrades SCHD to Buy, resilience amid rising yields |
| 13 | TRX | source_discovery | staged | 0.50 | Yahoo Finance TRX Q2 2026 earnings, record production |

## Pre-Embedding Checks

| Check | Result |
|-------|--------|
| id=12 exists and is SCHD | YES |
| id=13 exists and is TRX | YES |
| Neither already embedded | YES (0 rows in content_embeddings) |
| Content non-empty | YES (both have summary + thesis) |
| source_type = hermes_research | YES |
| Embedding model = nomic-embed-text | YES (available in Ollama) |
| Existing Hermes embeddings | 7 (ids 1–7 from Phase 2A/2C) |
| Rollback targets exact rows | YES — DELETE WHERE source_id IN (12,13) |

## Rollback File

`docs/hermes/HERMES_PHASE31_EMBEDDING_PILOT_ROLLBACK.sql`
