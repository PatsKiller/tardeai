Status:      ACTIVE
as_of:       2026-09-02T09:15:00-04:00
run_id:      sop-1.2.0-20260902
base_sha:    4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9
Canonical repo path: docs/implementation/maturity-program/sop-1.2.0-20260902/STAGE_01_PR_COLLISION.md
Authority:   READ_ONLY recommendations. No PR mutated.

# Stage 1 · Open-PR collision / convergence inventory

Open PRs: **34**. Machine inventory: `OPEN_PR_COLLISION_INVENTORY.json`.

## Hot files (≥3 open PRs) — serialize; integrator owns shared governance

| degree | file | PRs |
|---:|---|---|
| 7 | `scripts/api_v2.py` | #126, #141, #168, #170, #257, #296, #417 |
| 5 | `apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx` | #200, #201, #202, #204, #296 |
| 4 | `apps/command-center-v3/src/pages/PortfolioHub.tsx` | #172, #196, #197, #257 |
| 3 | `apps/command-center-v3/src/components/DecisionPacketBand.tsx` | #151, #172, #296 |
| 3 | `scripts/active_trader/read_http.py` | #247, #249, #251 |
| 3 | `apps/command-center-v3/src/components/WatchlistCard.tsx` | #126, #141, #171 |
| 3 | `apps/command-center-v3/src/components/WatchlistCardV4.tsx` | #126, #141, #171 |

**Designated integrator for hot governance/API surfaces:** this SOP tranche integrator (Grok session). UI component hot files remain with their feature owners; do not edit them in this tranche.

## Per-PR disposition (recommendation only)

| PR | draft | age_d | files | disposition | note |
|---:|---|---:|---:|---|---|
| #126 | False | 58 | 18 | REBASE_REQUIRED | long-lived open PR; expect main drift |
| #133 | False | 56 | 1 | REBASE_REQUIRED | long-lived open PR; expect main drift |
| #140 | False | 55 | 7 | REBASE_REQUIRED | long-lived open PR; expect main drift |
| #141 | False | 55 | 25 | REBASE_REQUIRED | long-lived open PR; expect main drift |
| #150 | True | 41 | 100 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #151 | False | 40 | 8 | REBASE_REQUIRED | CI failures on head — rebase/fix before merge consideration |
| #162 | True | 40 | 5 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #165 | False | 40 | 13 | REBASE_REQUIRED | CI failures on head — rebase/fix before merge consideration |
| #166 | True | 39 | 22 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #167 | True | 39 | 40 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #168 | True | 39 | 9 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #169 | True | 39 | 1 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #170 | True | 39 | 2 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #171 | True | 39 | 4 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #172 | True | 39 | 66 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #196 | True | 37 | 1 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #197 | False | 37 | 2 | ACTIVE | open; no auto disposition |
| #200 | False | 37 | 1 | ACTIVE | open; no auto disposition |
| #201 | False | 37 | 2 | ACTIVE | open; no auto disposition |
| #202 | False | 37 | 3 | ACTIVE | open; no auto disposition |
| #204 | False | 37 | 1 | ACTIVE | open; no auto disposition |
| #210 | False | 37 | 2 | ACTIVE | open; no auto disposition |
| #247 | True | 35 | 31 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #249 | True | 35 | 32 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #251 | True | 35 | 19 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #255 | False | 34 | 5 | ACTIVE | open; no auto disposition |
| #257 | True | 34 | 100 | SUPERSEDED_CANDIDATE | stale draft >30d; verify before close |
| #296 | False | 27 | 81 | REBASE_REQUIRED | CI failures on head — rebase/fix before merge consideration |
| #328 | False | 18 | 2 | REBASE_REQUIRED | CI failures on head — rebase/fix before merge consideration |
| #393 | True | 14 | 2 | ACTIVE | open; no auto disposition |
| #417 | False | 12 | 22 | REBASE_REQUIRED | CI failures on head — rebase/fix before merge consideration |
| #473 | True | 9 | 22 | ACTIVE | open; no auto disposition |
| #507 | False | 7 | 6 | ACTIVE | open; no auto disposition |
| #777 | False | 1 | 11 | NEEDS_OPERATOR_DECISION | cash as-of freshness; conflicts historically; do not auto-merge |

## Convergence order (minimize rework)

1. Do **not** land stale UI/defense/moomoo DRAFTs until owners rebase onto `4bcba2cf7`.
2. Serialize `scripts/api_v2.py` touchers (#126/#141/#168/#170/#257/#296/#417) — one integrator queue.
3. Keep #777 as operator decision; this SOP tranche must not edit cash_letter / capital_plan freshness.
4. Governance SOP files claim disjoint paths under `docs/implementation/maturity-program/sop-1.2.0-20260902/`, `config/agent_clients.yaml`, session/lease/worktree/CI — avoid `apps/command-center-v3/**` and ActiveTrader paths.

## Acceptance

- every open PR represented: YES
- overlap reproducible from JSON: YES
- no PR mutated: YES
- evidence vs recommendation distinguished: YES

## Checkpoint

| field | value |
|---|---|
| base/head | `4bcba2cf7` / `4bcba2cf7` |
| money/orders/schedulers/guardrails | unchanged |
| next | Stage 2 agent-client registry (local); stop before remote |
