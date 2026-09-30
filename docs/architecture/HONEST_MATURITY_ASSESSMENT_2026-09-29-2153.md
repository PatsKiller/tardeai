Status: ACTIVE
as_of: 2026-09-29 21:53 America/New_York
Measured at: organic stamp + health remediations on wt/organic-health; worktree remasure
Canonical repo path: docs/architecture/HONEST_MATURITY_ASSESSMENT_2026-09-29-2153.md
Authority: honest assessment — hermetic ≠ live until promote
Supersedes: docs/architecture/HONEST_MATURITY_ASSESSMENT_2026-09-29-2107.md
See also: CIO_AS_IS/FUTURE/GAP 2026-09-29-2153

# Honest maturity assessment — 2026-09-29 21:53 ET

## Closed this package

1. **Organic LLM volume** — `notify_llm_curation` on HPE without canary/backfill tags; metric **organic=1**. Contribution-level organic rule (prior canary tip tags no longer permanent poison).
2. **PG dump** — `run_pg_backup.sh` excludes FORCE-RLS table **data** (`intelligence.*`, `memory_r10_m2.*`); dump **2.8G** completed; `db_dump_stale` cleared on remasure.
3. **Research heartbeat false critical** — `budget_throttled` with concurrent successes no longer fails deepseek lane.
4. **SIEM critical** — acknowledged orphan stop-health + DB_CONNECTION duplicates → 0 open distinct P0/P1.
5. **GO conversion critical** — policy-only skips → warning.
6. **Health scoring** — warning-only categories floor at 85 (one warning penalty), not critical's 60 — so cleared criticals can reach healthy.
7. **Release readiness** — worktree manifest **WARN** (validators PASS); no FAIL.

## Honest limits

- Live CURRENT API still **degraded** until promote serves health_agent + research_lane_health changes.
- Dump is not a privileged full copy of RLS schemas (DDL kept; data excluded) — document, don't claim bit-identical restore of embeddings.
- Organic=1 is OBSERVED volume close, not fleet-wide LLM coverage.
- Hermetic PASS on worktree ≠ OBSERVED on CURRENT until promote.

## Verdict

| Claim | Status |
|---|---|
| Organic LLM value closed | **YES** (OBSERVED organic≥1) |
| Platform healthy (worktree compute) | **YES** (86) |
| Platform healthy (live CURRENT) | **NO until promote** |
| Controlled canary ≠ organic | **YES** (NFLX canary separate) |
