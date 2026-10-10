# 00 — N8N Maturity Acceleration: program index

**Status:** CURRENT — index of the in-repo program artifacts

**Date:** 2026-10-09

**Owner:** Agent A (program supervisor)

AGENTS.md §23 (4.1.0, ACTIVE 2026-10-09) names this file as the program's home. It is an index only: the
rules live in AGENTS.md, the designs in the numbered docs below, and the scores in the scorer receipt. Day-to-day
status (PR board, reviews, operator decisions) is kept outside the repo on the program board and is not
mirrored here, so this file does not go stale with it.

## Rules

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
