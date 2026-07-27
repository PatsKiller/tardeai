# Operator TODO — after Stage 1

**Run ID:** 20260722-01 · **Date:** 2026-07-22

## Required BEFORE Stage 2
1. **Create the Bitwarden lab machine account** (`trade-ai-lab-codex`) — the recorded
   Stage 1 deviation. Steps in `BITWARDEN_LAB_PROVISIONING.md`. Until done, the
   lab-token isolation test remains BLOCKED and lab writes ride the org write token.

## Carried forward (unchanged from Stage 0 unless noted)
2. Wedged production checkout: ruling says QUARANTINED, not blocking — resolve at leisure,
   never as part of this program.
3. Litmus BF-1 (Moomoo disconnect-surviving broker-resident protection): evidence needed
   before Stage 14; recommended to gather during Stage 2 capability-probe design.
4. ~~Test database~~ DONE (separate lab cluster; see TEST_DATABASE_PROVISIONING.md).
5. ~~Gmail send path~~ DONE (ruling: gog gmail send → john@jwwhiting.com).
6. ~~Email/Drive values~~ CONFIRMED by ruling.
7. Hygiene items from Stage 0 (pilot_caps 9999-vs-5 mismatch, GATES_REMOVED posture
   confirmation, OPERATIONS.md service-scope mismatch, DEFAULT_PAPER_ACCOUNT label
   discrepancy, snaptrade_accounts.json absence, pgvector absence, future-dated
   migration filenames) — untouched by Stage 1, still open, none blocking.

## Notes for the Stage 2 authorization prompt
- Stage 2 = broker account discovery + capability registry probes (read-only broker API
  calls will occur for the first time — the prompt should say which brokers/accounts may
  be probed and confirm rate/scope).
- The blocked Bitwarden isolation test should be re-run at Stage 2 start once item 1 lands.
