# Stage 1 Closeout — Additive Schema, Contracts, Flags, and Checkpointing

**Run ID:** 20260722-01 · **Date:** 2026-07-22
**Branch:** feat/active-trader-next · **Start HEAD:** a7c9376b · PR: #150 (draft)

## Result: GREEN (one recorded deviation)

**Deviation (architecture-owner approved in-session):** Bitwarden machine account
`trade-ai-lab-codex` is vault-UI-only and was not created; Stage 1 lab secret operations
used the org write token, and the "production Bitwarden access unavailable from lab
token" test is BLOCKED. Required operator steps are in BITWARDEN_LAB_PROVISIONING.md and
stage-01/OPERATOR_TODO.md item 1 — complete before Stage 2.

## Delivered
- Draft PR #150 body corrected (Step 1).
- Isolated test database: separate user-owned PG17 lab cluster (:5433), `trade_ai_test`
  / `trade_ai_lab`, DSN only in Bitwarden `trade-ai-lab`; 4/4 isolation proofs (Step 2).
- Bitwarden: `trade-ai-lab` project + `ACTIVE_TRADER_TEST_DATABASE_DSN` secret (Step 3,
  with the deviation above).
- Root `AGENTS.md` (Step 4).
- Stage 1 implementation (Step 5): 5 paired up/down migrations → all 14 Active Trader
  tables + tracking table; guarded migration runner; typed contracts (sessions/
  authorizations/accounts, order intents, broker capability + normalized rejection,
  22-flag registry all-OFF defaults, owner-approved rate policy PLACE 15/12/3 +
  MODIFY_CANCEL 20/16/4 per 30 s, run checkpoint, drive manifest, §16J.3 litmus schema);
  46 tests (34 pure + 12 lab-DB) all green.

## Environment discipline delivered
SHADOW/SIMULATION/LIVE explicit everywhere; no defaults; DB CHECKs enforce
LIVE⇒session-authorization+hash, SHADOW⇒no write states; idempotency keys globally
unique (no sim/live reuse); drafts, flags, journal append-only via triggers.

## Checkpoint
```yaml
run_id: 20260722-01
architecture_version: v3.3
program_version: v1.1
base_sha: 87c2fa09fa95a8a69233959b04b1144e1297b923
branch: feat/active-trader-next
current_stage: 1
state: GREEN_CLOSED
last_green_stage: 1
stage_commits: [d7691f93, a7c9376b, <stage-1 commit — recorded in stage-01-changes.txt>]
drive_artifacts: stage-00 (13 verified) + stage-01 (see stage-01-drive-manifest.json)
pending_operator_actions: [bitwarden trade-ai-lab-codex machine account (pre-Stage-2)]
test_summary: 46/46 new tests PASS; 1 BLOCKED isolation test; validators 16/17 (1 pre-existing)
failure: none
updated_at: 2026-07-22
```

## Mandatory safety assertions
```text
REAL ORDER QUEUED: NO · SUBMITTED: NO · MODIFIED: NO · CANCELLED: NO
REAL POSITION CLOSED: NO · REAL 2FA REQUESTED: NO
MOOMOO INSTALLED: NO · MOOMOO LIVE UNLOCKED: NO
PRODUCTION SECRET READ: NO · WRITTEN: NO
PRODUCTION PACKAGE UPGRADED: NO · DATABASE MIGRATED: NO · SERVICE CHANGED: NO
PRODUCTION FEATURE FLAG CHANGED: NO · GUARDRAIL CHANGED: NO
EXISTING APPROVAL SERVICE CHANGED: NO · EXISTING PER-ORDER 2FA CHANGED: NO
/V3 ROUTE REMOVED OR REPLACED: NO · PRODUCTION CHECKOUT TOUCHED: NO
MAIN BRANCH MODIFIED: NO · NEXT STAGE STARTED: NO
```

## Stop
Stage 1 complete. Stage 2 requires a separate architecture-owner authorization prompt
(and operator TODO item 1 first).
