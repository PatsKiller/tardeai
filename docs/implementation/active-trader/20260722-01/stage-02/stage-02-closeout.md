# Stage 2 Closeout — Broker Account Discovery and Capability Registry

**Run ID:** 20260722-01 · **Date:** 2026-07-22
**Branch:** feat/active-trader-next · **Start HEAD:** 42f0c2cb · PR #150 (draft)

## Result: GREEN

The operator created `trade-ai-lab-codex` before this stage; the full lab-isolation gate
passed (lab read/write PASS, production enumeration/read/write DENIED, temp sentinel
removed, org token unused) — closing the Stage 1 deviation. Discovery, capability
registry, projection, probe runner, and 23 new tests landed additively; a bounded live
read-only probe discovered 6 accounts across alpaca/schwab (moomoo recorded
NOT_INSTALLED) with 0 write methods proposed or invoked and 94 capability rows
persisted to the lab database only.

## Highlights
- Real finding: Alpaca **taxable live read credentials are active and healthy**
  (***4834) — reads OK, execution remains UNSUPPORTED by policy.
- Real finding: the two-sided alpaca label discrepancy (`tradeai_automated` vs
  `alpaca_paper`) predicted by Stage 0 is now live-confirmed by the projection.
- Schwab all 3 accounts read via the managed-token transport (deliberately avoiding
  the self-refreshing adapter's token-race hazard); write capabilities graded
  RESTRICTED/UNKNOWN strictly from existing fences.
- Capability discipline: SUPPORTED only with evidence; UNKNOWN is the default for
  everything a write would be needed to prove; probe evidence expires in 24 h.

## Checkpoint
```yaml
run_id: 20260722-01
architecture_version: v3.3
program_version: v1.1
base_sha: 87c2fa09fa95a8a69233959b04b1144e1297b923
branch: feat/active-trader-next
current_stage: 2
state: GREEN_CLOSED
last_green_stage: 2
stage_commits: [d7691f93, a7c9376b, 2bb60f4a, 42f0c2cb, <stage-2 commit in stage-02-changes.txt>]
drive_artifacts: stage-00 (13 verified) + stage-01 (11 verified) + stage-02 (see manifest)
pending_operator_actions: label-mismatch decision + market-hours look (non-blocking)
test_summary: 69 local tests PASS; isolation gate ALL PASS; live probe clean; validators 16/17 (pre-existing)
failure: none
updated_at: 2026-07-22
```

## Mandatory safety assertions
```text
REAL ORDER QUEUED: NO · SUBMITTED: NO · MODIFIED: NO · CANCELLED: NO
REAL POSITION CLOSED: NO · REAL 2FA REQUESTED: NO
MOOMOO INSTALLED: NO · MOOMOO LIVE UNLOCKED: NO
PRODUCTION SECRET VALUE DISPLAYED: NO · PRODUCTION SECRET WRITTEN: NO
PRODUCTION PACKAGE UPGRADED: NO · PRODUCTION DATABASE MIGRATED: NO
PRODUCTION SERVICE CHANGED: NO · PRODUCTION FEATURE FLAG CHANGED: NO
PRODUCTION GUARDRAIL CHANGED: NO · EXISTING WRITE FENCES CHANGED: NO
EXISTING APPROVAL SERVICE CHANGED: NO · EXISTING PER-ORDER 2FA CHANGED: NO
/V3 ROUTE REMOVED OR REPLACED: NO · PRODUCTION CHECKOUT TOUCHED: NO
MAIN BRANCH MODIFIED: NO · NEXT STAGE STARTED: NO
```

## Stop
Stage 2 complete. Stage 3 requires a separate architecture-owner authorization prompt.
