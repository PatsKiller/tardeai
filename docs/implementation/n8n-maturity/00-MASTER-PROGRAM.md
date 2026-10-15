# 00 — N8N Maturity Acceleration: program index

**Status:** CURRENT — index of the in-repo program artifacts

**Date:** 2026-10-09 (index amended 2026-10-10: configuration reference, onboarding and monitoring standards, health contracts)

**Owner:** Agent A (program supervisor)

AGENTS.md §23 (4.1.0, ACTIVE 2026-10-09) names this file as the program's home. It is an index only: the
rules live in AGENTS.md, the designs in the numbered docs below, and the scores in the scorer receipt. Day-to-day
status (PR board, reviews, operator decisions) is kept outside the repo on the program board and is not
mirrored here, so this file does not go stale with it.

## Program status 2026-10-15 02:35Z (served 5aa61048d; AGENTS.md 10.0.0 ACTIVE)

The day-to-day board stays outside the repo. This one dated pointer exists because 10.0.0 changed what the
program measures:

- **Tracker:** [`PROGRAM_TRACKER_20261015.md`](PROGRAM_TRACKER_20261015.md), "what's done / what's left", one
  row per item with status, evidence, owner and next action.
- **Success metric (§23.23 (2)):** business processes owned by n8n, and orchestration owners retired. **Lanes
  moved do not count.** Processes owned today: **0**. The first is hermes learning, PR-OPEN #1746.
- **Timer-only cutover freeze (§23.23 (1)):** all three exit conditions are met: Run Lane LIVE, the run-outcome
  callback LIVE, and 10.0.0 ACTIVE. The freeze stays in force until the operator lifts it.
- **Fabric primitives (Build 1, #1739) LIVE:** Run Lane + error workflow published. P1 passed 01:15Z, P2 passed
  01:37Z. 18 active workflows.
- **Governed `/v1/llm_step` (Build 2, #1738) LIVE:** grok + chatgpt. DeepSeek is unproven (upstream degraded).
- **Framework compliance (§23.24, PROPOSED 11.0.0):** 40% (18 workflows; none compliant).
- **Migration state doc:** `MIGRATION_STATE_20261014.md` exists only on PR #1727 (open, AGENTS 8.0.0). It is
  not on main, and this tracker supersedes its status lines.

## Start here — configuration and procedures (2026-10-10)

| Doc | What |
|---|---|
| `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` | **Entry point.** How n8n is configured on ms01-openclaw: container, host relay / gateway / executor, workflows, governance, change log, open items |
| `docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` | **Mandatory** procedure for adding any lane, workflow, relay path or executor setting to n8n (AGENTS.md §23 pointer) |
| `docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md` | Per-lane monitoring, SIEM, Telegram routing, LLM auto-remediation, R6 validation, workflow health contracts |
| `config/n8n_health_contracts.json` | Workflow health contracts (gate `scripts/check_n8n_health_contracts.py`) |
| `docs/implementation/n8n-maturity/PROGRAM_TRACKER_20261015.md` | **2026-10-15 program tracker**: done / left, status label + evidence + owner + next action per item |
| `docs/incidents/INCIDENT_20261014_SPCX_RESTING_STOPS.md` | Incident record INC-20261014-SPCX (timeline, root cause, containment, fixes, open items) |
| `docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md` | **2026-10-14 final gap assessment**: current vs target, per-workflow framework compliance matrix (18 workflows × 6 areas, re-scored 2026-10-15), maturity scores, next actions |
| `N8N_CONFIGURATION.md` §0 | n8n operational standards and the mandatory workflow framework (AGENTS.md §23.24, PROPOSED 11.0.0) |

## Rules

- `AGENTS.md` (4.4.0) §23.18 R1 classes and the 4.4.0 cron-row shape at shadow/canary.
- `AGENTS.md` §23.11 registry-driven dispatch, §23.12 wave ladder, §23.13 program window (push budget,
  standing 48 h merge approval), §23.14 lanes never dispatcher-eligible
  (`tests/test_agents_policy_4_1_0_amendment.py`). §23.3 keeps `trade-ai-scalp-live` as the single named
  exception.
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
