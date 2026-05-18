# B-1C Daily Momentum Scalp Boundary Design

## Current State

No confirmed leakage found. The Trade AI `momentum_scalp` YAML strategy is a
valid system strategy, distinct from any separate operator daily scalp workflow.
All momentum_scalp proposals come from standard pipeline sources
(auto_proposal_generator, incubator_promoter, telegram_manual, system).

## Boundary Rules

### 1. Naming/Namespace
- Trade AI strategy: `momentum_scalp` (YAML-backed, SAME_DAY bucket)
- External scalp: any source containing `daily_momentum_scalp`, `tradeai_daily_scalp`, `external_scalp`
- The two must never be conflated

### 2. DB Filtering
- paper_trade_proposals: exclude where strategy_id IN daily scalp indicators
- strategy_setup_matches: exclude daily scalp strategy_id from route audit
- A-5/SP reports: exclude daily scalp source_system if column exists

### 3. API Filtering
- GET /api/v2/paper-proposals: exclude source_system='daily_momentum_scalp' if present
- Trust audit: mark daily scalp source as out_of_scope

### 4. Route Audit Exclusion
- Do not evaluate daily scalp strategies in multi_setup_router
- If daily scalp records enter proposals, mark as out_of_scope blocker

### 5. Future Integration
- If operator wants daily scalps in paper proposals, require explicit approval
- Create a dedicated source_system flag
- Add to A-5/SP only after explicit inclusion decision

### 6. What NOT To Do
- Do NOT disable Trade AI `momentum_scalp` YAML strategy
- Do NOT filter out valid momentum_scalp proposals
- Do NOT conflate "momentum_scalp strategy" with "daily scalp workflow"
