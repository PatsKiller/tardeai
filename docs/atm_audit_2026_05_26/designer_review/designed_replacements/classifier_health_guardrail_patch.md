# Designer Replacement: classifier_health_guardrail_patch

**Status:** READY TO APPLY  
**Git Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Created:** 2026-05-26  

## Problem

`config/atm_config.yaml` line 21 has `min_classifier_health: 0.0` with a comment saying
"TEMPORARY: lowered from 0.50 to 0.0 during DRY_RUN cold-start." This effectively
disables the classifier health gate entirely. There is no visibility into when this
threshold is being bypassed, and no automatic reminder to restore it.

The `atm_classifier_health.py` score returns 0.0 when fewer than 3 closed trades exist
per strategy, which means the gate legitimately blocks during cold-start. But with the
threshold at 0.0, the block is silently bypassed.

## Design Principle

Do NOT change the threshold value (that is a strategy logic decision for the operator).
Instead, add **visibility** so the operator can see:
1. That the guardrail is currently relaxed
2. Which strategies are below the production threshold (0.50)
3. When enough data exists to restore the production threshold

## Changes

### 1. Add `_guardrail_note` field to `config/atm_config.yaml`

Add a comment-only reminder. No code reads this — it's for human operators:

```yaml
  strategy_filter:
    # GUARDRAIL STATUS: min_classifier_health is at 0.0 (cold-start bypass).
    # Production target: 0.50. Restore when >= 3 paper trades close per active strategy.
    # P0.5 patch adds API/dashboard visibility for this status.
    min_classifier_health: 0.0
```

### 2. Add classifier guardrail status to `/api/v2/atm/status` response

In `scripts/api_v2.py`, in the ATM status endpoint handler, add a `classifier_guardrail`
block to the response:

```python
# In the atm_status endpoint handler, after loading atm_config:
min_health = atm_config.get("defaults", {}).get("strategy_filter", {}).get("min_classifier_health", 0.5)
production_threshold = 0.50
guardrail_relaxed = min_health < production_threshold

# For each active strategy, compute health
from atm_classifier_health import get_health_detail
active_strategies = [s for s in strategy_ids_in_use]  # already available in endpoint
strategy_health_details = {}
for sid in active_strategies:
    detail = get_health_detail(sid)
    strategy_health_details[sid] = {
        "score": detail["score"],
        "closed_trades": detail["closed_trades"],
        "has_baseline": detail["has_baseline"],
        "would_pass_production": detail["score"] >= production_threshold,
    }

strategies_ready = sum(1 for d in strategy_health_details.values() if d["would_pass_production"])
strategies_total = len(strategy_health_details)

# Add to response:
response["classifier_guardrail"] = {
    "current_threshold": min_health,
    "production_threshold": production_threshold,
    "guardrail_relaxed": guardrail_relaxed,
    "strategies_ready_for_production": strategies_ready,
    "strategies_total": strategies_total,
    "strategy_details": strategy_health_details,
    "recommendation": "READY_TO_RESTORE" if strategies_ready >= strategies_total * 0.6 else "KEEP_RELAXED",
}
```

### 3. Add classifier guardrail banner to AutomatedTradeMode.tsx

In the ATM dashboard, add a visible banner when `classifier_guardrail.guardrail_relaxed` is true:

```tsx
{atmStatus?.classifier_guardrail?.guardrail_relaxed && (
  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
    <div className="flex items-center gap-2">
      <span className="text-amber-600 font-medium">Classifier Health Guardrail Relaxed</span>
      <span className="text-sm text-amber-500">
        Threshold: {atmStatus.classifier_guardrail.current_threshold} 
        (production: {atmStatus.classifier_guardrail.production_threshold})
      </span>
    </div>
    <div className="text-sm text-amber-700 mt-1">
      {atmStatus.classifier_guardrail.strategies_ready_for_production} of{' '}
      {atmStatus.classifier_guardrail.strategies_total} strategies ready for production threshold.
      {atmStatus.classifier_guardrail.recommendation === 'READY_TO_RESTORE' && (
        <span className="font-medium"> Consider restoring to 0.50.</span>
      )}
    </div>
  </div>
)}
```

## What This Does NOT Do

- Does NOT change `min_classifier_health` value
- Does NOT auto-restore the threshold
- Does NOT block any proposals
- Does NOT change trading logic

## Testing

1. Load `/api/v2/atm/status` — verify `classifier_guardrail` block appears
2. Check `guardrail_relaxed: true` since threshold is 0.0
3. Check each strategy shows `closed_trades` and `would_pass_production`
4. Verify ATM dashboard shows amber banner
5. Confirm no proposals are rejected differently than before
