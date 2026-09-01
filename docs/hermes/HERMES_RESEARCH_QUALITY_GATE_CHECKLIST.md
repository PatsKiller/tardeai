# Hermes Research Quality Gate Checklist

Status:      ACTIVE
as_of:       2026-05-30T20:20:52-04:00
Measured at: efcc51365 / not measured

Reusable checklist for validating Hermes research before ingestion, embedding, or promotion.

---

## Pre-Ingestion Gate

- [ ] `source` = 'hermes'
- [ ] `status` = 'staged'
- [ ] `research_type` is a valid allowed type
- [ ] `symbol` or `topic` is populated
- [ ] `hermes_agent_name` identifies the agent
- [ ] `model_used` is a local model (gemma3:12b, gemma3:4b)
- [ ] `confidence_score` is 0.0–1.0 and varies by task (not always 0.6)
- [ ] `freshness_date` is today or recent
- [ ] `evidence_json` has at least 3 substantive keys
- [ ] `limitations` array is present and non-empty
- [ ] `source_views` lists which safe views were used
- [ ] `summary` is 50+ words
- [ ] `thesis` is 30+ words
- [ ] No forbidden keywords (place_order, execute_trade, approve_proposal, etc.)
- [ ] No broker instructions or execution language
- [ ] No sensitive data (credentials, account IDs, chat IDs)
- [ ] challenge_points are findings, not questions (no "Analyze...", "Evaluate...", "Assess...")

## Post-Ingestion Verification

- [ ] Row inserted with correct id
- [ ] `source` = 'hermes' confirmed in DB
- [ ] `status` = 'staged' confirmed
- [ ] Production tables unchanged
- [ ] content_embeddings unchanged
- [ ] No other hermes_* tables changed unexpectedly

## Pre-Embedding Gate

- [ ] All pre-ingestion checks pass
- [ ] Evidence quality score >= 4/5
- [ ] Trading usefulness score >= 3/5
- [ ] Actionability score >= 3/5
- [ ] No question-style challenge_points
- [ ] Operator has reviewed the row

## Pre-Dashboard Gate

- [ ] All pre-embedding checks pass
- [ ] Summary is clear enough for operator dashboard display
- [ ] No misleading claims or overclaims
- [ ] Limitations are visible alongside the research note

## Pre-Promotion Gate

- [ ] All pre-dashboard checks pass
- [ ] Multiple similar-quality rows exist (not a one-off)
- [ ] Promotion script dry-run reviewed
- [ ] Operator explicitly approves promotion
- [ ] Rollback SQL exists for the promoted rows
