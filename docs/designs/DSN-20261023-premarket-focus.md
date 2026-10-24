---
id: DSN-20261023-premarket-focus
title: Premarket 1-minute cadence + scalp focus list
status: IN_PROGRESS
approval: approved for build (operator 10-23); merge, cron install and live flip are operator acts
source: 'PR #1997 (docs/ops/packets/premarket-1min-20261023 on its branch)'
summary: 1-minute candles, threaded lifecycle, top-20 focus list with rotation, state threading; shadow first. EE grant 423dbe39
  covers premarket_watch.py.
phases:
- id: DSN-20261023-premarket-focus-P1
  title: 'Build — #1997 (green, conflicting; classifier denied the agent merge)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-premarket-focus-P1-T1
    title: 'Operator merge decision for #1997 — board task T-20261023-e06794'
    status: PROPOSED
    areas:
    - scripts/active_trader/premarket_watch.py
    board_task: T-20261023-e06794
- id: DSN-20261023-premarket-focus-P2
  title: Cron packet (install.sh outside 05:55-09:35, with an inventory row)
  status: PROPOSED
  tasks:
  - id: DSN-20261023-premarket-focus-P2-T1
    title: 'OPERATOR: run docs/ops/packets/premarket-1min-20261023/install.sh outside 05:55-09:35 ET, add the inventory row'
    status: PROPOSED
    areas:
    - operator/packets/premarket-1min
    owner: OPERATOR
- id: DSN-20261023-premarket-focus-P3
  title: Flip cadence_mode to live
  status: PROPOSED
  tasks:
  - id: DSN-20261023-premarket-focus-P3-T1
    title: 'OPERATOR: flip premarket cadence_mode to live after a clean shadow session'
    status: PROPOSED
    areas:
    - operator/flags/premarket-cadence
    owner: OPERATOR
    depends_on:
    - DSN-20261023-premarket-focus-P2-T1
---

Backfill 2026-10-23 from the coordinator worklog (operator to-dos; 10:20 ET entry: "#1997 held: the classifier
denied the merge, so it waits for the operator").
