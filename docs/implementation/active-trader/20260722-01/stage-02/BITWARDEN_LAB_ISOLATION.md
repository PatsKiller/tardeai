# Bitwarden Lab Isolation — Stage 2 Gate Results

**Run ID:** 20260722-01 · **Date:** 2026-07-22 · Token: `~/.openclaw/credentials/bws_lab_token`

## Preflight verification (no values revealed)
- Token file exists, owner `johnclaw`, mode `0600` ✔
- Token authenticates and sees exactly one project: `trade-ai-lab` ✔ (machine account
  `trade-ai-lab-codex`, created by the operator in the vault after Stage 1)

## Gate results
```text
LAB READ: PASS                    (lists trade-ai-lab; sees ACTIVE_TRADER_TEST_DATABASE_DSN by name)
LAB WRITE: PASS                   (created + edited temp secret STAGE2_ISOLATION_TEMP with sentinel values)
PRODUCTION ENUMERATION: DENIED    (trade-ai-prod project invisible; secret list returns empty)
PRODUCTION READ: DENIED           (no prod secret id reachable/readable)
PRODUCTION WRITE: DENIED          (create in trade-ai-prod → 404 Resource not found)
TEMP SENTINEL REMOVED: YES        (deleted; lab project back to exactly ACTIVE_TRADER_TEST_DATABASE_DSN)
ORG-WIDE TOKEN USED: NO           (bws_write_token untouched for the entire stage)
```

## Effect on the Stage 1 deviation
Stage 1's BLOCKED test — "production Bitwarden access is unavailable from the lab token" —
is now EXECUTED and PASSED. The Stage 1 deviation is closed. All Stage 2 secret reads
(lab DSN for tests, persistence, and the live probe) used the lab token exclusively.
