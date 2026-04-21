# Recommendation Refinement — Article-Backed Draft Rationale Verification

**Date:** 2026-04-21
**Verifier:** Claude Opus 4.6
**Files changed:** `scripts/portfolio_orchestrator.py`

---

## 1. Change Summary

Added bounded article-context lookup to the recommendation draft generation block:
- Queries `article_index` for 7-day article counts, categories, and top titles per symbol
- Enriches `rationale` with a short article-context clause when coverage exists
- Enriches `evidence_summary` with `article_context` block

## 2. Draft Comparison

### Before (no article context)
```
V concentration at 15.7% exceeds 15% threshold. Yahoo analyst context: 35 analysts,
mean target $393, consensus: strong_buy. Pending review (severity 2).
```

### After (with article context)
```
V concentration at 15.8% exceeds 15% threshold. Yahoo analyst context: 35 analysts,
mean target $393, consensus: strong_buy. Recent coverage includes analyst, sector
articles (36 in 7d). Pending review (severity 2).
```

### STOP_REVIEW (portfolio-level, no symbol-specific articles)
```
1 stop(s) currently triggered. Pending review (severity 1).
```
Unchanged — no article context for portfolio-level drafts (correct).

## 3. Evidence Summary (V)

```json
{
  "trigger_rule": "concentration_above_15",
  "severity": 2,
  "yahoo_analyst": {
    "current_price": "313.94",
    "target_mean_price": "393.43",
    "recommendation_key": "strong_buy",
    "number_of_analyst_opinions": 35
  },
  "article_context": {
    "article_count_7d": 36,
    "analyst_article_count": 2,
    "categories": ["analyst", "noise", "sector"],
    "most_recent_article_at": "2026-04-21 07:31:51",
    "top_titles": [
      {"title": "3 Reasons Investors Love Visa (V)", "source": "Yahoo", "category": "noise"},
      ...
    ]
  },
  "escalation_summary": "V concentration at 15.8% exceeds 15% threshold"
}
```

## 4. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Article evidence incorporated when available | **PASS** — V draft cites "36 articles in 7d" |
| No duplicate drafts | **PASS** — count=2 after re-run |
| Drafts remain status='draft' only | **PASS** |
| No notification/action logic added | **PASS** |
| Rationale remains conservative | **PASS** — "Recent coverage includes..." not "you must act because of articles" |

## 5. Explicit Statements

| Question | Answer |
|----------|--------|
| Is article evidence optional and non-blocking? | **YES** — STOP_REVIEW has no article context and works fine |
| Does rationale remain conservative? | **YES** — "Recent coverage includes..." is observational, not directive |
| Is article presence treated as supporting context, not decision authority? | **YES** — articles enrich evidence, they don't change the action type or confidence |
