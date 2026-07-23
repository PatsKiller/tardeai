# Stage 1 Plan — Additive Schema, Contracts, Flags, and Checkpointing

**Run ID:** 20260722-01 · **Start HEAD:** a7c9376bbae172877d1c1b482f062b015861285c
**Branch:** feat/active-trader-next · **Worktree:** /home/johnclaw/worktrees/active-trader-next
**Authorization:** architecture-owner Stage 1 launcher (2026-07-22), which also recorded the
BF-2 rate-policy ruling, broker scope (alpaca/moomoo/schwab), gog email lane, Drive root,
quarantined production checkout, and §16J.3-canonical litmus schema.

## Steps
1. Update stale draft-PR #150 body (Stage 0 evidence corrections).
2. Provision isolated test database: separate user-owned PostgreSQL 17 lab cluster
   (~/tradeai-lab/pg17, port 5433) with `trade_ai_test` owned by LOGIN-only role
   `trade_ai_lab`; DSN stored ONLY in Bitwarden `trade-ai-lab` as
   `ACTIVE_TRADER_TEST_DATABASE_DSN`; prove reachability, migration rights, production
   denial, and production schema-hash stability.
3. Provision Bitwarden lab isolation: `trade-ai-lab` project; machine account
   `trade-ai-lab-codex` (vault-UI-only — operator deviation recorded: proceed with org
   write token; machine account remains a pre-Stage-2 operator TODO).
4. Create root `AGENTS.md` (worktree rule, prohibitions, stage discipline, test commands).
5. Implement Stage 1: 5 paired up/down migrations creating the 14 Active Trader tables +
   tracking table; guarded runner (`scripts/active_trader/migrate.py`) that refuses
   production targets; typed contracts (`scripts/active_trader/contracts.py`) for
   sessions/authorizations/accounts, order intents, broker capabilities/rejections,
   feature flags (22-flag registry, all defaults OFF), owner-approved rate policy
   (PLACE 15/12/3, MODIFY_CANCEL 20/16/4 per 30 s, separate budgets, reserve protected),
   run checkpoint (optimistic versioning, FAILED cannot silently advance,
   GREEN_CLOSED requires verified Drive artifacts), drive-manifest entry, and the
   §16J.3 litmus schema; test suites (pure + lab-DB-only).
6. Proof set: additive-only diff; /v3 build green; production schema hash unchanged;
   strict-lint failure reproduces at base and head; validators 16/17 with the same
   single pre-existing failure; Moomoo still absent.
7. Evidence artifacts, commit (`feat(active-trader): add Stage 1 schema contracts and
   controls`), push, PR update, Drive sync + SHA-256 verification, checkpoint update,
   operator email, stop before Stage 2.

## Explicit non-goals (deferred by program)
2FA implementation; Moomoo SDK/OpenD; broker discovery/probes (Stage 2); rejection
classifier runtime (Stage 3); read API (Stage 4); rate-governor runtime (Stage 5);
any UI; Drive sync worker; any production change.
