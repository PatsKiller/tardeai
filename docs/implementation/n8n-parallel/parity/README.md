# n8n guardrail parity tables

Status:      ACTIVE
as_of:       2026-10-09
Authority:   READ_ONLY_ADVISORY

This directory holds one guardrail parity table per lane, as AGENTS.md §23 requires before a lane or
capability moves into n8n. Each tranche PR that moves a lane adds its table here and updates the three
baseline audits:

- `docs/implementation/n8n-parallel/audits/guardrail-audit-a-config-20261009.md` (config, audit A)
- `docs/implementation/n8n-parallel/audits/guardrail-audit-b-code-20261009.md` (code, audit B)
- `docs/implementation/n8n-parallel/audits/guardrail-audit-c-policy-n8n-20261009.md` (policy and n8n side, audit C)

Each row lists the guardrail, where it executes today, its source (code, JSON, policy), its kind
(technical, procedural, policy), how n8n enforces it, how that is validated, and how it is monitored.
A gap blocks the move until it has a remediation and an owner.

As of 2026-10-09 no per-lane table has been committed here yet.
