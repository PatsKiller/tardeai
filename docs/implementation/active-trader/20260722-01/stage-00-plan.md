# Stage 0 Plan — Baseline and Read-Only Architect Litmus Review

**Run ID:** 20260722-01
**Date:** 2026-07-22
**Branch:** feat/active-trader-next
**Base SHA:** 87c2fa09fa95a8a69233959b04b1144e1297b923 (origin/main, verified)
**Worktree:** /home/johnclaw/worktrees/active-trader-next (separate worktree; production checkout untouched)
**Controlling documents (SHA-256):**

| Document | SHA-256 |
|---|---|
| docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md | e2649ec30f531d72635e9b255ff4c4a1e57725241a50b2dfb312ea19b9609da8 |
| docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md | 6293b5502ad3c6e421dcb75c2824583dc7113b3a2c9b8854696d32fcc57f8604 |
| docs/prompts/ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md | 0c7b5d2d31a11dee3699843fd0515ff8acdec4660191540f367df45915d90eb5 |

## Deviation from the original bootstrap (architecture-owner authorized)

The bootstrap required the checked-out main SHA to equal 87c2fa09. The local production
checkout at /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild was behind (2b25ad8f,
a strict ancestor) with an unresolved two-file merge-conflict index state. The architecture
owner explicitly authorized Option 1 on 2026-07-22: create feat/active-trader-next from the
fetched origin/main commit in a separate git worktree and leave the production checkout
completely untouched. This plan executes that authorization.

## Scope (Stage 0 only)

1. Inventory and preserve all unrelated local modifications in the production checkout (no changes).
2. Baseline audit: /v3 frontend, backend /api/v2 + /api/v3 ownership, DB migrations/schema,
   feature flags, approval/2FA/execution rails, broker adapters and accounts, notification
   workflows, Moomoo/OpenD state, runtime versions, tests, deploy/rollback commands.
3. Read-only architect litmus review per ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.
   Reviewer runs as a tool-restricted read-only agent (no Write/Edit/commit capability) and
   returns report text only; the controller writes ACTIVE_TRADER_LITMUS_REVIEW.md verbatim.
4. Non-destructive external prerequisite checks: GitHub, Google Drive, Gmail, Bitwarden
   Secrets Manager, test database.
5. Produce all required Stage 0 artifacts under docs/implementation/active-trader/20260722-01/.
6. Commit evidence to feat/active-trader-next, push, open one draft PR, sync artifacts to
   Drive (Trade_AI_Docs_v2/implementation/active-trader/20260722-01/stage-00/), verify SHA-256
   hashes, update checkpoint, notify operator, stop before Stage 1.

## Method

- Repository facts are gathered from the worktree at the exact base SHA (read-only agents).
- Runtime facts (services, versions, database) are gathered from the live host read-only.
- Database access uses the application's own configured credentials; no secret value is
  printed, stored, or committed — only key NAMES and non-secret facts appear in artifacts.
- Anything not provable is marked UNVERIFIED and added to OPERATOR_TODO.md.

## Explicit non-actions

No application behavior change; no /v3 change; no /v3-next product code; no production DB
table creation; no service/package/feature-flag/guardrail change; no 2FA request; no Moomoo
unlock; no live trading API call; no order of any kind; no merge to main.
