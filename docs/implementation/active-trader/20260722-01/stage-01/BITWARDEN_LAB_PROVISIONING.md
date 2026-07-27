# Bitwarden Lab Provisioning — Stage 1

**Run ID:** 20260722-01 · **Date:** 2026-07-22

## Completed
- Project **trade-ai-lab** created (id `1b0a478d-87a3-4e2d-85f6-b4900015afa0`) alongside
  `trade-ai-prod` (id `9ab21606-...`), using the existing org write token.
- Lab secret **ACTIVE_TRADER_TEST_DATABASE_DSN** created in `trade-ai-lab` (value never
  displayed). Sentinel convention `UNSET__OPERATOR_REQUIRED` implemented and rejected at
  runtime (`contracts.reject_sentinel`, migration runner, tests).
- No production secret was read, copied, or modified. No secret value appears in any
  artifact, commit, Drive upload, or email.

## DEVIATION (architecture-owner approved 2026-07-22, in-session)
Machine account **trade-ai-lab-codex** could NOT be created from this host: Bitwarden
Secrets Manager machine accounts are created only in the web vault UI (no bws CLI or
public-API path), and the operator elected **"Proceed with deviation"** after two
attempts to complete the vault step.

Consequences, all recorded:
- Stage 1 lab secret operations used the existing **org write token** lane
  (`~/.openclaw/credentials/bws_write_token`) instead of a lab-scoped token.
- The required isolation test "production Bitwarden access is unavailable (from the lab
  token)" is **BLOCKED — NOT RUN** (no lab token exists to test).
- The DSN was NOT stored anywhere other than the `trade-ai-lab` project (no weakening).

## Required operator steps before Stage 2
1. vault.bitwarden.com → Secrets Manager → **Machine accounts → New** → `trade-ai-lab-codex`.
2. In the machine account → **Projects** → add `trade-ai-lab` with **Can read, write**.
   Do NOT grant `trade-ai-prod`.
3. **Access tokens** → create token; store on ms01:
   `umask 077; printf '%s' 'TOKEN' > ~/.openclaw/credentials/bws_lab_token; chmod 600 ~/.openclaw/credentials/bws_lab_token`
4. Tell the Stage 2 controller to re-run the blocked isolation test
   (lab token lists `trade-ai-lab` secrets; access to `trade-ai-prod` project fails).
