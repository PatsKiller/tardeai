# Stage 13 — Inactive Dual-Operation Readiness — Plan

**Run:** 20260722-01 · **Branch:** feat/active-trader-next · **HEAD:** 4e4176ba
**Controller:** Corrected Stage 12/13 v1.1 §4 · **Date:** 2026-07-23

## Objective
Prove classic /v3 and new /v3-next can coexist and be switched/rolled back operationally **without
enabling production traffic**. No production deployment change authorized. Terminal state:
GREEN_CLOSED_PROMOTION_BLOCKED.

## Method
1. Static collision analysis (routes, assets, services, ports) from configs.
2. Local fixture-only dual-run drill on loopback, nonproduction ports: concurrent serve, route isolation,
   rollback motion, full teardown with 0-leftover proof.
3. Parity matrix with the six categories (MATCH / INTENTIONALLY_NEW / NOT_APPLICABLE / FIXTURE_ONLY /
   LIVE_DATA_PENDING / PREMARKET_VALIDATION_PENDING); do not label fixture parity as live parity.
4. Switch + rollback runbooks (production-inactive; not executed).
5. Live-flag/service report; promotion gate matrix; Stage 14 blockers.
6. Commit/push/Drive/email.

## Boundaries
Loopback-only local processes; no broker network; no production route/proxy/firewall/DB/service/flag
change; PR stays draft; no Stage 14.

## Artifacts
DUAL_OPERATION_READINESS · V3_V3NEXT_PARITY_MATRIX · SWITCH_RUNBOOK · ROLLBACK_RUNBOOK ·
LOCAL_DUAL_RUN_REPORT · ROUTE_ASSET_COLLISION_REPORT · LIVE_FLAG_AND_SERVICE_REPORT ·
PROMOTION_GATE_MATRIX · STAGE14_BLOCKERS · stage-13-tests · stage-13-changes · stage-13-closeout ·
stage-13-drive-manifest · OPERATOR_TODO.
