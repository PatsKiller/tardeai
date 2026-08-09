# CIO Run Budgets

**Document ID:** CIO-BUDGET-001  
**Version:** 1.0.0  
**Owner:** Trade AI CIO Agent  
**Date:** 2026-08-08

## 1. Global Cap

**Daily global cap: $0.25** — all runs combined must not exceed this.

## 2. Per-Workload Budgets

### daily_brief
- max_provider_calls: 4
- max_cost_usd: $0.02
- max_specialist_calls: 2
- max_hermes_challenges: 1 (budget floor; worker enforces 0 for non-material)
- max_wall_time_minutes: 5

### weekly_review
- max_provider_calls: 8
- max_cost_usd: $0.05
- max_specialist_calls: 4
- max_hermes_challenges: 2
- max_wall_time_minutes: 10

### monthly_review
- max_provider_calls: 12
- max_cost_usd: $0.08
- max_specialist_calls: 4
- max_hermes_challenges: 2
- max_wall_time_minutes: 15

### action_followup
- max_provider_calls: 4
- max_cost_usd: $0.02
- max_specialist_calls: 2
- max_hermes_challenges: 1
- max_wall_time_minutes: 5

### material_event
- max_provider_calls: 6
- max_cost_usd: $0.03
- max_specialist_calls: 3
- max_hermes_challenges: 2
- max_wall_time_minutes: 8

### operator_request
- max_provider_calls: 8
- max_cost_usd: $0.05
- max_specialist_calls: 4
- max_hermes_challenges: 2
- max_wall_time_minutes: 10

### default (fallback)
- max_provider_calls: 4
- max_cost_usd: $0.02
- max_specialist_calls: 2
- max_hermes_challenges: 0
- max_wall_time_minutes: 5

## 3. Hard Caps (server-side, cannot be exceeded)

- max_provider_calls: 20
- max_cost_usd: $0.25
- max_wall_time_minutes: 60
- max_specialist_calls: 10
- max_hermes_challenges: 5

## 4. Budget Enforcement

- Budget checked before every state transition
- BUDGET_EXCEEDED status set when limit reached
- Budget-deferred runs marked as BUDGET_DEFERRED
- No fallback to bypass budget limits

## 5. Cost Tracking

- Every model call recorded with cost
- Cumulative cost tracked per run
- Day-level cost aggregation from run store
