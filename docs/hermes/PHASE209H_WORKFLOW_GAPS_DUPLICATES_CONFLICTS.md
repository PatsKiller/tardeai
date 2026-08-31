# Phase 209H — Workflow Gaps, Duplicates, Conflicts (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:29:04-04:00
Measured at: efcc51365 / not measured

| Finding | Class | Note |
|---------|-------|------|
| Coordinator kill-switch references retired hermes_sidecar/.hermes/DISABLED (stale path) | P1 | repoint to live path (operator-approved) — carried from 208J/R3 |
| hermes_research_backlog dedicated table not created (backlog = tagged rows) | P2 | documented design note; /research-backlog surfaces tagged rows |
| serverops carries broad tools while unconfigured (incl terminal/code_execution) | P1/HOLD | harden before configuring (208J/R2) |
| tradeai12b purpose was unclear to operator | P2 (now resolved) | 209E matrix: experimental, manual-only, not used by automation |
| hermes_alerts table empty (0 rows) | P2 | confirm alert producers wired or intentionally idle |
| Disabled hermes-gateway.service unit still has sidecar ExecStart | P2 | inert (disabled); repoint/remove later |
| Naming: Hermes (chat profiles) vs Hermes (research fleet) vs retired sidecar | P2 (mitigated) | /v3/hermes relabeled "Research Agent Graph"; System→Hermes = profiles |
| Embedding/Promotion share one script (hermes_embedding_promotion_reviewer.py) | P2 | single owner for two graph nodes — by design, not a conflict |

## Classification summary
- **P0 breakage: 0.** No workflow without an owner; no graph node without a backing job; no active job
  calling retired wrappers/gateway; no duplicate conflicting owners.
- P1: 2 (kill-switch repoint, serverops hardening) — both operator-gated.
- P2: documentation/cleanup items.
