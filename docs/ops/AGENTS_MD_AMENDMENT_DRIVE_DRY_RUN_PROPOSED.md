# PROPOSED amendment to AGENTS.md — Drive / gog dry-run honesty

**Status:** PROPOSED (not applied)  
**Effective-Date:** PENDING operator approval  
**Author:** Lane T / campaign m2-canary-20260907  
**Does not edit AGENTS.md in this change set.**

## Proposed addition (under dry-run / evidence rules)

> **Drive / `gog` exception (tool-version specific).**  
> For the observed `gog` CLI (v0.12.x), `gog drive upload -n` / `--dry-run` and  
> `gog drive delete|rm|trash -n` must **not** be cited as dry-run proof. Treat those  
> invocations as mutating or untrusted. Use a separate read-only plan that does not  
> invoke `gog`, and require explicit target identity plus pre/post hash verification  
> for execute. Prefer `scripts/gog_drive_safe.py`.

## Rationale

Independent maturity validation and Lane T tooling found that operators and scripts  
may treat `-n` as a safe dry run. The safer rule wins when a tool’s dry-run claim is  
not independently proven for Drive mutations.

## Approval

Operator must approve and merge into AGENTS.md (Policy-Version bump) before this  
text becomes ACTIVE. Until then, campaign ops docs (`DRIVE_MUTATION_SAFETY.md`) govern.
