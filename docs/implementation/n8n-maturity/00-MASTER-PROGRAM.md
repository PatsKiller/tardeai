# 00 — N8N Maturity Acceleration: program index

**Status:** CURRENT — index of the in-repo program artifacts

**Date:** 2026-10-09 (index amended 2026-10-10: configuration reference, onboarding and monitoring standards, health contracts;
amended 2026-10-14: governing AGENTS.md version, cutover standard, migration state, architecture and cutover runbook)

**Owner:** Agent A (program supervisor)

AGENTS.md §23.13 (4.1.0, ratified 2026-10-09) names this file as the program's home. It is an index only: the
rules live in AGENTS.md, the designs in the numbered docs below, and the scores in the scorer receipt. Day-to-day
status (PR board, reviews, operator decisions) is kept outside the repo on the program board and is not
mirrored here, so this file does not go stale with it.

## Governing policy — as of 2026-10-14

| AGENTS.md version | State (measured 2026-10-14 ~11:40 ET: `git show origin/main:AGENTS.md`, `gh pr view`) |
|---|---|
| **5.1.0** | last **ACTIVE** version (ratified `APPROVE_AGENTS_POLICY_5_1_0 1689 b0f0c6eeb`); the n8n rules in force are §23 as amended through 4.5.0 plus 5.1.0 |
| 5.2.0 | merged on main as **PROPOSED** (§8.1 validate now: tests, dry run, forced run); not ratified |
| 6.0.0 | PROPOSED, PR #1697 (onboarding step 8 accepts a forced shadow fire) — subsumed by 8.0.0 §23.21 criterion 2 |
| 7.0.0 | PROPOSED, PR #1725 (§23.20 advisory market-data lanes); operator approval `APPROVE_AGENTS_POLICY_7_0_0 1725 73eebc5c1` posted 2026-10-14T14:54:21Z; not yet merged |
| 8.0.0 | PROPOSED, branch `docs/n8n-migration-state-20261014` (§23.21 cutover standard — the operator ruling of 2026-10-14 ~11:05 ET: defect fixed, n8n dry run passes, lane regression tests pass, ≥ 1 successful live n8n run with cron present under the shared lock; multi-day soaks removed) |

The §23.13 program window (push budget, 48 h standing merge approval) ended 2026-10-12T23:59:59-04:00; every
`AGENTS.md` merge needs the operator's per-PR word.

## Current state, architecture and cutover procedure (2026-10-14)

| Doc | What |
|---|---|
| `docs/implementation/n8n-maturity/MIGRATION_STATE_20261014.md` | counts, buckets, canary wave, cutover list, never-eligible justification, evidence paths |
| `docs/implementation/n8n-maturity/N8N_RUNTIME_ARCHITECTURE.md` | diagram: cron vs dispatcher → relay → gateway → executor → lane; locks, ledger, heartbeat-watch, incident fan-in |
| `docs/implementation/n8n-maturity/RUNBOOK_CUTOVER_ROLLBACK.md` | the standard cutover and per-line rollback; evidence to record; who approves |

## Start here — configuration and procedures (2026-10-10)

| Doc | What |
|---|---|
| `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` | **Entry point.** How n8n is configured on ms01-openclaw: container, host relay / gateway / executor, workflows, governance, change log, open items |
| `docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` | **Mandatory** procedure for adding any lane, workflow, relay path or executor setting to n8n (AGENTS.md §23 pointer) |
| `docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md` | Per-lane monitoring, SIEM, Telegram routing, LLM auto-remediation, R6 validation, workflow health contracts |
| `config/n8n_health_contracts.json` | Workflow health contracts (gate `scripts/check_n8n_health_contracts.py`) |

## Rules

- `AGENTS.md` (4.4.0) §23.18 R1 classes and the 4.4.0 cron-row shape at shadow/canary.
- `AGENTS.md` §23.11 registry-driven dispatch, §23.12 wave ladder, §23.13 program window (push budget,
  standing 48 h merge approval — both expired), §23.14 lanes never dispatcher-eligible
  (`tests/test_agents_policy_4_1_0_amendment.py`). §23.3 keeps `trade-ai-scalp-live` as the single named
  live exception among ingest writers and senders; 7.0.0 (PROPOSED) adds the §23.20 advisory market-data class.
- `AGENTS.md` §23.19 (4.5.0): every n8n addition follows `N8N_ONBOARDING_STANDARD.md` and has a health contract.
- `AGENTS.md` §23.21 (8.0.0, PROPOSED): the cutover standard. Until ratified, ACTIVE §23.3 / §23.14 still state the
  `trade-ai-scalp-live` three-market-day fallback.
- `docs/architecture/n8n/ADR_COORDINATION_SECRETS.md` — secrets, relay bearer, credential boundaries.

## Workstream designs

| Doc | Workstream |
|---|---|
| `docs/implementation/n8n-maturity/01-registry-reconciliation.md` | B1 — lane registry reconciled against the live scheduler inventory |
| `docs/implementation/n8n-maturity/02-six-workflow-architecture.md` | B5 — six generic workflows, `coordination/due`, executor v2 |
| `docs/implementation/n8n-maturity/03-momentum-scalp-lanes.md` | B4 — momentum scalp lanes |

Generated workflow files: `docs/implementation/n8n-maturity/workflows/` (built by
`scripts/n8n_workflow_templates.py build-generic`, inactive until activated under one `cron` grant).
Schemas: `docs/implementation/n8n-maturity/schemas/`. Evidence data: `docs/implementation/n8n-maturity/data/`.

## Measuring maturity

- Scorer: `scripts/n8n_platform_maturity.py` (N8nPlatformMaturity@v1; collectors in `scripts/lib/n8n_maturity/`).
- Thresholds and the 12 dimensions: `config/n8n_platform_maturity.json` (target overall 8.0, stretch 9.5;
  a dimension whose gate is not met is capped at 7.9).
- Self-healing mechanisms the scorer looks for evidence of: `config/self_healing_mechanisms.json`.

```bash
python3 scripts/n8n_platform_maturity.py --dry-run      # scorecard, writes nothing
python3 scripts/n8n_platform_maturity.py --markdown     # scorecard section for the program master doc
```

A score is only a live score when it is computed against the promoted release and the production state root.
A dimension whose evidence could not be read is UNVERIFIED, never a pass.
