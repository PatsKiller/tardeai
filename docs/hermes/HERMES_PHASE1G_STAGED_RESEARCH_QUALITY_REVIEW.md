# Hermes Phase 1G — Staged Research Quality Review

**Date:** 2026-05-30
**Status:** PASS (all 4 rows pass with notes)

---

## 1. Verification

| Check | Result |
|-------|--------|
| Gateway | active (running), port 18790 |
| hermes_research_intelligence | 4 rows (ids 1-4) |
| hermes_memory_events | 1 row (Phase 1B smoke) |
| Other hermes_* tables | 0 rows each |
| Hermes embeddings | 0 |
| Production tables | Unchanged (38 trades, 145 proposals) |

---

## 2. Per-Row Quality Review

### Row 1: FLYW Thesis Challenge (Phase 1E)

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| Schema compliance | 5 | source=hermes, status=staged, research_type valid, evidence_json rich, confidence=0.6, model=gemma3:12b, limitations present, source_views listed |
| Evidence quality | 4 | Cites all 3 trades + 4 proposals from context. Correctly identifies D grade vs +15.5% month discrepancy. Distinguishes fact from inference. Minor: doesn't note that trade_1 was actually profitable ($27.36) despite "stop_hit" exit. |
| Trading usefulness | 5 | Clear insight: strategy mismatch (dividend_growth_compounder on volatile small-cap), stop placement too tight, cancelled trades indicate system issues. Directly useful for operator review. |
| Safety/compliance | 5 | No broker instructions, no execution language, no sensitive data. Advisory only. |
| Actionability | 4 | Identifies problems clearly. Could be stronger with specific "next step" recommendation (e.g., "remove FLYW from swing strategies"). |

**Overall: PASS**
**Disposition:** keep_staged, candidate_for_dashboard_later, candidate_for_embedding_later

---

### Row 2: SPRC Thesis Challenge (Phase 1F)

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| Schema compliance | 5 | All fields correct. Evidence includes RSI (77.47), beta (2.46), SMA50 (+115%), trade PnL percentages. |
| Evidence quality | 3 | Correctly identifies extreme technicals (RSI 77, beta 2.46, SMA50 +115%). However, challenge_points are questions ("Analyze...", "Evaluate...") rather than findings. Less assertive than Row 1. |
| Trading usefulness | 3 | Identifies that SPRC is high-risk/high-reward with extreme momentum. But doesn't give a clear thesis verdict — more of a "needs more research" note. |
| Safety/compliance | 5 | No execution language, no sensitive data. |
| Actionability | 3 | Lists questions to investigate rather than conclusions. Useful as a research prompt but not a standalone insight. |

**Overall: PASS (with notes)**
**Disposition:** keep_staged, revise_required for future prompt improvement — challenge_points should be findings, not questions

---

### Row 3: SCHD News Reframe (Phase 1F)

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| Schema compliance | 5 | All fields correct. Evidence cites specific article titles and dates from safe views. |
| Evidence quality | 4 | Correctly cites 3 specific articles with dates. Identifies SCHD's positioning as income/retirement ETF. Notes limitations (10-article sample, missing sentiment scores). Honest about coverage gaps. |
| Trading usefulness | 4 | Useful for understanding SCHD sentiment landscape. Identifies that coverage is consistently positive/income-focused. Notes risk discussions exist but are about peers (SPHD), not SCHD directly. |
| Safety/compliance | 5 | No execution language. Advisory framing throughout. |
| Actionability | 4 | Clear that SCHD coverage is income-themed. Useful for income strategy alignment. Could add "compare against actual SCHD performance" as next step. |

**Overall: PASS**
**Disposition:** keep_staged, candidate_for_embedding_later, candidate_for_dashboard_later

---

### Row 4: APPS Trade Reflection (Phase 1F)

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| Schema compliance | 5 | All fields correct. Confidence=0.7 (highest of the batch — appropriate for a factual trade review). |
| Evidence quality | 3 | Correctly cites entry (6.5356), exit (7.16), PnL ($159.98). But very thin — only 3 data points. Doesn't analyze the trade deeply. Identifies "Alpaca exit" as a mechanism but doesn't explain what position_closed_in_alpaca means. |
| Trading usefulness | 3 | States the trade was profitable but offers minimal insight beyond restating the numbers. Challenge_points are questions ("Analyze...", "Evaluate...") not findings. |
| Safety/compliance | 5 | No execution language. Advisory only. |
| Actionability | 2 | Weak. "The trade was profitable" is not a useful reflection. Missing: entry timing analysis, stop placement, whether target was hit, strategy classification, what could be repeated. |

**Overall: PASS (with notes)**
**Disposition:** keep_staged, revise_required — trade reflections need deeper prompting with strategy context and MFE/MAE data

---

## 3. Rejected Task Analysis (Phase 1F)

| Task | Type | Rejection Reason | Category | Fix |
|------|------|-----------------|----------|-----|
| phase1f_task_04 | pipeline_quality_validation | Empty evidence_json | Model output issue | System tasks need explicit "extract specific metrics" prompt. Pipeline context needs failure counts, error patterns, not raw status tables. |
| phase1f_task_05 | pipeline_quality_validation | Empty evidence_json | Context insufficiency | Agent confidence data was provided but the model couldn't structure findings. Needs example output in prompt. |

---

## 4. Batch-Level Quality Assessment

| Metric | Value |
|--------|-------|
| Rows reviewed | 4 |
| PASS | 4 (2 with notes) |
| NEEDS_REVIEW | 0 |
| REJECT | 0 |
| Average schema compliance | 5.0/5 |
| Average evidence quality | 3.5/5 |
| Average trading usefulness | 3.75/5 |
| Average safety | 5.0/5 |
| Average actionability | 3.25/5 |
| **Overall batch quality** | **PASS — schema and safety strong, evidence and actionability need improvement** |

### Key Findings

1. **Schema discipline is excellent.** All rows have correct source, status, model, evidence, limitations, source_views. The ingestion script enforcement works.

2. **Safety is perfect.** No execution language, no broker instructions, no sensitive data leakage, no production mutation recommendations. The system prompt guardrails work.

3. **Evidence quality varies.** Row 1 (FLYW) is strong — specific trade references, identified patterns, clear challenge. Rows 2 and 4 are weaker — list questions rather than findings.

4. **Actionability needs improvement.** Rows 2 (SPRC) and 4 (APPS) produce "analyze this" and "evaluate that" rather than clear conclusions. The prompt needs to say "state your findings, not your questions."

5. **Trade reflections need richer context.** Row 4 (APPS) only had trade + ticker data. Adding strategy_id, proposal history, MFE/MAE data, and market regime would produce much stronger reflections.

---

## 5. Validator Improvement Recommendations

| # | Improvement | Priority |
|---|------------|----------|
| 1 | Reject challenge_points that are questions (contain "Analyze", "Evaluate", "Assess", "Determine") — require findings | HIGH |
| 2 | Require minimum evidence_json depth (at least 3 substantive keys beyond metadata) | MEDIUM |
| 3 | Add word-count minimum for summary (50+ words) and thesis (30+ words) | LOW |
| 4 | Validate that confidence_score varies by task (not always 0.6) | LOW |

## 6. Prompt Improvement Recommendations

| # | Improvement | Priority |
|---|------------|----------|
| 1 | Add to prompt: "State your findings and conclusions, not questions to investigate. Be assertive." | HIGH |
| 2 | For trade reflections: include strategy_id, proposal history, hold duration, MFE/MAE in context | HIGH |
| 3 | For system tasks: provide explicit example output structure with real metric extractions | MEDIUM |
| 4 | Add: "Include a clear 'recommended next step for the operator' in every response" | MEDIUM |

---

## 7. Recommendations

| Decision | Recommendation | Reason |
|----------|---------------|--------|
| More ingestion? | **YES (limited)** — after prompt improvements | Schema and safety are proven. Evidence quality needs prompt fixes first. |
| Embeddings? | **NOT YET** — wait for improved evidence quality | Current evidence_json is adequate but thin for some rows. Embedding low-quality content pollutes RAG. |
| Dashboard display? | **NOT YET** — wait for prompt hardening | Rows 2 and 4 are too question-oriented for operator dashboard display. |
| Production promotion? | **NO** — premature | Need higher evidence quality and more rows before promotion makes sense. |

---

## 8. Risks

| Risk | Severity |
|------|----------|
| Challenge_points as questions reduce usefulness | MEDIUM |
| Trade reflections lack strategy context | MEDIUM |
| System tasks fail validation entirely | LOW (known, fixable) |
| Confidence scores cluster at 0.6 (poor calibration) | LOW |

---

## 9. Next Recommended Gate

**Phase 1H — prompt hardening + limited additional ingestion**

Scope:
1. Apply prompt improvements (assertive findings, richer trade context)
2. Apply validator improvements (reject question-style challenge_points)
3. Run 5 more tasks with improved prompts
4. Compare quality scores against Phase 1E+1F baseline
5. No embeddings, no promotion, no dashboard until quality improves
