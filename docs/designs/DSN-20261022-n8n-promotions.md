---
id: DSN-20261022-n8n-promotions
title: n8n promotion batch A-F (2026-10-23)
status: PROPOSED
approval: awaiting operator ("Reply with the letters you approve"); each letter -> its own registry PR; cron letters need
  one cron grant
source: 'docs/ops/N8N_PROMOTION_READINESS_2026-10-22.md (PR #1972)'
summary: Ordered lowest to highest risk. Nothing moves without the letter, the dry run quoted, lane tests under TRADE_AI_CI=1
  and a forced or natural fire.
phases:
- id: DSN-20261022-n8n-promotions-P1
  title: A — stage label canary->cutover, 4 lanes (no cron line)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-n8n-promotions-P1-T1
    title: 'OPERATOR: approve or decline promotion letter A'
    status: PROPOSED
    areas:
    - operator/n8n-promotions/a
    owner: OPERATOR
- id: DSN-20261022-n8n-promotions-P2
  title: 'B — retire cron line, tier 1: job-coverage-monitor, classify-instruments'
  status: PROPOSED
  tasks:
  - id: DSN-20261022-n8n-promotions-P2-T1
    title: 'OPERATOR: approve or decline promotion letter B'
    status: PROPOSED
    areas:
    - operator/n8n-promotions/b
    owner: OPERATOR
- id: DSN-20261022-n8n-promotions-P3
  title: C — retire cron line, tier 2, 13 lanes (C1 first 7, C2 other 6)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-n8n-promotions-P3-T1
    title: 'OPERATOR: approve or decline promotion letter C'
    status: PROPOSED
    areas:
    - operator/n8n-promotions/c
    owner: OPERATOR
- id: DSN-20261022-n8n-promotions-P4
  title: D — as C, 2 lanes with an earlier exit_1 (daily-incubator-refresh, instrument-belief-writer)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-n8n-promotions-P4-T1
    title: 'OPERATOR: approve or decline promotion letter D'
    status: PROPOSED
    areas:
    - operator/n8n-promotions/d
    owner: OPERATOR
- id: DSN-20261022-n8n-promotions-P5
  title: E — shadow->canary, tier 1, 3 lanes
  status: PROPOSED
  tasks:
  - id: DSN-20261022-n8n-promotions-P5-T1
    title: 'OPERATOR: approve or decline promotion letter E'
    status: PROPOSED
    areas:
    - operator/n8n-promotions/e
    owner: OPERATOR
- id: DSN-20261022-n8n-promotions-P6
  title: F — shadow->canary, tier 2, indicator-engine + hermes-discovery-yield-on-learning
  status: PROPOSED
  tasks:
  - id: DSN-20261022-n8n-promotions-P6-T1
    title: 'OPERATOR: approve or decline promotion letter F'
    status: PROPOSED
    areas:
    - operator/n8n-promotions/f
    owner: OPERATOR
- id: DSN-20261022-n8n-promotions-P7
  title: 'Cutover factory: parse effect_claim_cron.sh wrapper; 4 canary rows with commented cron (board task T-20261023-f7771f)'
  status: IN_PROGRESS
---

Backfill 2026-10-23. Every letter is in the operator approval list (board task T-20261023-240510 and
DSN-20261022-operator-approvals P23). Unblocking work: owner REVIEW of 19 DRAFT health contracts.
