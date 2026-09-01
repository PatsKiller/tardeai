# Scalp Multi-Setup Taxonomy — Implementation Closeout (2026-07-27)

Status:      HISTORICAL
as_of:       2026-07-27T23:45:01-04:00
Measured at: efcc51365 / not measured

```
START_MAIN:          21366635ce6e2a8610e0ea1ea716036016df299b
BRANCH:              agent/scalp-multi-setup-taxonomy-v1
PR:                  (opened at merge gate — see below)
MERGE_SHA:           OPERATOR_MERGE_COMMAND_REQUIRED (classifier blocks gh pr merge for the agent)

SETUP_REGISTRY:      config/scalp_setup_registry.yaml (scalp-setup-registry-v1)
SETUP_IDS:           SCALP_IGNITION_BREAKOUT_V1, SCALP_L2_MOMENTUM_V1, SCALP_VWAP_PULLBACK_V1,
                     SCALP_VWAP_REVERSION_V1, SCALP_ORB_15_BREAKOUT_V1, SCALP_MICRO_PULLBACK_V1,
                     SCALP_PREMARKET_MOMENTUM_V1
PREMARKET_WINDOW:    07:00–09:29 ET (default; active start configurable to 06:00, no code change)
ACTIVE_FIRE_WINDOW:  07:00–12:00 ET (context collection from 06:00)
NOON_CUTOFF:         12:00 ET — no NEW FIRED state after; management/journaling continue
MIGRATIONS:          migrations/2026-07-28_scalp_setup_taxonomy.sql (additive; IF NOT EXISTS)
API_ENDPOINTS:       GET /api/v3/active-trader/scalp/setups, GET /api/v3/active-trader/scalp/setup-events
ACTIVE_TRADER_MODAL: SETUPS & STRATEGY RULES (registry-driven, a11y, responsive, read-only) on Trading→Scalp
SCALP_LABELS:        IGNITION BREAKOUT · L2 MOMENTUM · VWAP PULLBACK · VWAP REVERSION · 15M ORB ·
                     MICRO PULLBACK · PREMARKET MOMENTUM · MULTI-SETUP
ALERT_LABELS:        primary + matched setup labels + market session + "MANUAL PAPER ONLY — NOT AN ORDER"
JOURNAL_LABELS:      setup-events API filters by primary setup + session (+ date)

TESTS:               ~130 focused (registry, session, detectors, confirmations+gate, API, alerts,
                     isolation AST guard); Playwright spec e2e/scalp-strategy-modal.spec.ts (desktop+narrow)
CI:                  (release-readiness runs on the PR)
STATIC_DEPLOY:       deferred to gated rollout (build exact merged ref → canonical convergence installer)
MIGRATION_APPLIED:   deferred to gated rollout (additive)
SCHEDULE_CHANGED:    deferred — only the approved shadow-logger window (context 06:00–12:00 / active 07:00–12:00)
SERVICE_RESTARTS:    0 so far (all work isolated on the branch)
ROLLBACK_POINTS:     branch is additive; migration is IF NOT EXISTS; static deploy uses the convergence
                     installer's bound backup+manifest; logger wiring is fail-safe

AUTO_PAPER_PRESENT:              NO
AUTOMATIC_PAPER_ORDER_QUEUED:    NO
AUTOMATIC_PAPER_ORDER_SUBMITTED: NO
MANUAL_PAPER_ORDER_SUBMITTED:    NO
LIVE_ORDER_QUEUED:               NO
LIVE_ORDER_SUBMITTED:            NO
LIVE_2FA_REQUESTED:              NO
LIVE_CREDENTIAL_READ:            NO
LLM_FINANCIAL_AUTHORITY:         NONE

FIRST_BLOCKER:       none technical — awaiting operator merge (protected merge is agent-blocked)
NEXT_SAFE_ACTION:    operator merges the PR; then gated rollout (migration → build/deploy → schedule window)
FINAL_STATUS:        BRANCH_COMPLETE_TESTED_AWAITING_MERGE
```

## What was built (branch commits)

- `a29bd4b1` — Layer 1: registry + session clock + additive migration
- `610717ff` — Layer A: 7 deterministic detectors + shadow-logger wiring (FSM reused, not duplicated)
- `05eb10af` — Layer B+C: confirmation overlays + universal execution gate
- `abf8cfb0` — API endpoints + Active Trader strategy modal + signal chips
- (this commit) — alert setup labels, Playwright spec, docs

## Extends, does not fork

All detectors operate on the existing engine's inputs; MICRO/IGNITION reuse `scalp_trigger_engine`; the
event table gains additive columns (lane preserved); the logger wiring is fail-safe. The AST isolation
guard (`tests/test_scalp_engine_isolation.py`) covers every new module — no proposal/order import.

## Deferred / gated (operator)

Static deploy, migration apply, and the logger schedule/window change happen at **gated rollout after the
merge is on origin/main** — not during this implementation. The first paper order is the human operator's
in a later interactive session; nothing here submits any order.
