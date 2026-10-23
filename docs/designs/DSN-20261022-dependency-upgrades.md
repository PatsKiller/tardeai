---
id: DSN-20261022-dependency-upgrades
title: Dependency upgrades (approval M)
status: APPROVED
approval: 'approved (operator: "if we get through everything else, you can do all of the upgrades. And have a rollback plan
  just in case something breaks.")'
source: board task T-20261023-948210
summary: Vite 8, esbuild, react-router (+ npm audit fix) go last, in a separate release, with a rollback plan; hold until
  the Command Center PRs merge.
phases:
- id: DSN-20261022-dependency-upgrades-P1
  title: Rollback plan + upgrade PR — board task T-20261023-948210
  status: APPROVED
- id: DSN-20261022-dependency-upgrades-P2
  title: Separate release with rollback rehearsed
  status: PROPOSED
---

Backfill 2026-10-23.
