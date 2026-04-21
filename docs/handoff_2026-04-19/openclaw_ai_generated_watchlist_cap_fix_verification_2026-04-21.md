# AI-Generated Watchlist Cap Fix — Verification Report

**Date:** 2026-04-21
**Verifier:** Claude Opus 4.6
**File changed:** `scripts/portfolio_orchestrator.py`

---

## 1. Root Cause

The first two pipeline runs created 3 + 3 = 6 AI-generated items because the cap logic was added AFTER the second run. The cap code itself was correct but the overflow from pre-cap runs needed reconciliation.

## 2. Fix Applied

Added reconciliation block that runs BEFORE candidate generation:
```python
if _ai_active_count > 5:
    _ai_wl_exec(
        """UPDATE watchlist_items SET status = 'expired', updated_at = now()
           WHERE id IN (
               SELECT id FROM watchlist_items
               WHERE source_type = 'ai_generated' AND status = 'active'
               ORDER BY confidence ASC, created_at ASC
               LIMIT %s
           )""",
        (_ai_active_count - 5,)
    )
```

Expires the lowest-confidence items first until active count = 5.

## 3. Before/After

| Metric | Before | After |
|--------|:---:|:---:|
| Active AI-generated | 6 | **5** |
| Expired AI-generated | 0 | **1** (DARE, conf 0.66) |
| User active | 12 | **12** (unchanged) |

## 4. State After Fix

```sql
SELECT symbol, confidence, status FROM watchlist_items WHERE source_type='ai_generated' ORDER BY status, confidence DESC;

 KURA  | 0.84 | active
 ACHV  | 0.76 | active
 EVTL  | 0.74 | active
 ALGS  | 0.70 | active
 VANI  | 0.66 | active
 DARE  | 0.66 | expired  ← lowest confidence, expired by reconciliation
```

## 5. Cap Verification

Subsequent pipeline run: 0 new AI items added. Active count remains 5.

## 6. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Active AI-generated count never exceeds 5 | **PASS** |
| Per-run additions capped at 3 | **PASS** |
| Existing overflow reconciled safely | **PASS** (DARE expired, lowest confidence) |
| User/analyst-curated entries untouched | **PASS** (12 user active, unchanged) |
| Implementation remains deterministic and bounded | **PASS** |
