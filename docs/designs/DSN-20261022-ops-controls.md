---
id: DSN-20261022-ops-controls
title: Ops -> Controls (passkey, sudo window, dashboards)
status: IN_PROGRESS
approval: 'approved (AGENTS 19.0.0 §27 ratified #1962; passkey ''yes on passkey''; ''approve sudo window'' 2026-10-22)'
source: AGENTS.md §27, §28.5
summary: 'Operator: "all of these configurations I want hands-on keyboard for nothing that has to edit files." One governed
  host applier; safe direction one click, risky direction passkey + typed phrase.'
phases:
- id: DSN-20261022-ops-controls-P1
  title: 'Controls surface + governed host applier — #1941'
  status: LIVE
- id: DSN-20261022-ops-controls-P2
  title: 'AGENTS 19.0.0 (n8n broker reads + Controls) ratified #1962; first passkey registered 2026-10-22 21:26'
  status: LIVE
  tasks:
  - id: DSN-20261022-ops-controls-P2-T1
    title: 'OPERATOR: rename the passkey named "804607" (add a new passkey, revoke the old one)'
    status: PROPOSED
    areas:
    - operator/ops-controls/passkey-rename
    owner: OPERATOR
- id: DSN-20261022-ops-controls-P3
  title: Releases & schedules page (#1938) + Jobs & schedules readable (#1964)
  status: LIVE
- id: DSN-20261022-ops-controls-P4
  title: 'n8n lanes dashboard + promotion readiness — #1972 (green, conflicting)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-ops-controls-P4-T1
    title: 'Rebase #1972 onto main and land it in batch 10 (security-flagged: review its actions first)'
    status: PROPOSED
    areas:
    - apps/command-center-v3/src/lib/opsControlsN8n.ts
- id: DSN-20261022-ops-controls-P5
  title: 'Sudo window — #1970 (inert until AGENTS >= 20.0.0, now met)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-ops-controls-P5-T1
    title: 'Rebase #1970 (conflicting) and land it'
    status: PROPOSED
    areas:
    - apps/command-center-v3/src/components/OpsControlsSudo.tsx
  - id: DSN-20261022-ops-controls-P5-T2
    title: 'OPERATOR: set ops_controls.sudo_window_enabled after #1970 is LIVE'
    status: PROPOSED
    areas:
    - operator/ops-controls/sudo-enable
    owner: OPERATOR
    depends_on:
    - DSN-20261022-ops-controls-P5-T1
---

Backfill 2026-10-23. #1941 LIVE batch 5 (ee38621b1); #1962 LIVE f7c1e96cb; #1938 LIVE batch 5; #1964 LIVE batch 7.
Ops Controls went live with a passkey on 2026-10-22 (coordinator worklog, Done). Data approvals view #1976 is in
DSN-20261022-data-domains P6; Tier 2 approval actions are DSN-20261023-work-pipeline P2.
