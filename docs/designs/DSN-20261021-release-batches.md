---
id: DSN-20261021-release-batches
title: Releases and integration batches (manual path, 2026-10-21..23)
status: IN_PROGRESS
approval: 'approved (per-release grants; approve-all A/B 2026-10-22; maintenance period: release when merged)'
source: docs/ops/packets/release-train-20261021/README.md
summary: 'The manual release path the train falls back to. One phase per release. Served build on disk: portfolio-server/CURRENT
  -> 80e93c99f (2026-10-23 12:06 ET).'
phases:
- id: DSN-20261021-release-batches-P1
  title: 'Release 1 — #1909 d55da84d0 (release-train phases 0-1)'
  status: LIVE
- id: DSN-20261021-release-batches-P2
  title: 'Release 2 — #1910 4104effb9 (release-train phases 1-4, CI fixes 5-6)'
  status: LIVE
- id: DSN-20261021-release-batches-P3
  title: 'Release 3 — #1913 c81eb463c (arming fixes, FRED macro calendar, forced canary; guard patches #1912, AGENTS 16.0.0)'
  status: LIVE
- id: DSN-20261021-release-batches-P4
  title: 'Release 4 — 82180caba (finviz #1915, AGENTS 17.0.0 #1914, H.0 shadow-enable #1918)'
  status: LIVE
- id: DSN-20261021-release-batches-P5
  title: 'Batch 5 — #1959 ee38621b1 (Home Do-now, Watch, Trading tabs/Open Trades, Releases & Schedules, Ops Controls inert)'
  status: LIVE
- id: DSN-20261021-release-batches-P6
  title: 'Batch 6 — #1961 + AGENTS 19.0.0 #1962, served f7c1e96cb'
  status: LIVE
- id: DSN-20261021-release-batches-P7
  title: 'Release 7 + batch 7 — #1963 0f5bf2453 (memory fix), #1982 53aa1b619'
  status: LIVE
- id: DSN-20261021-release-batches-P8
  title: 'Batch 8 — #2002 b42f37435 + AGENTS 20.0.0 #2013, served 80e93c99f'
  status: LIVE
- id: DSN-20261021-release-batches-P9
  title: 'Batch 9 — #2018 98bef2794 (memory fix #2012, claim/work board, Trade AI P1s, Watch lists, site-validation fixes)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261021-release-batches-P9-T1
    title: Release batch 9 and verify the served SHA — board task DSN-20261023-agent-ops-P1-T2
    status: PROPOSED
    areas:
    - docs/designs
    board_task: DSN-20261023-agent-ops-P1-T2
  - id: DSN-20261021-release-batches-P9-T2
    title: 'Close #2004 and #2010: their heads are in main via batch 9 (278a90ec9, 41847187d) but the PRs are still open'
    status: PROPOSED
    areas:
    - operator/prs/close-2004-2010
- id: DSN-20261021-release-batches-P10
  title: Batch 10 — integration in progress (board task T-20261023-9ad805)
  status: IN_PROGRESS
---

Backfill 2026-10-23. Evidence: `gh pr list --state merged --search "merged:>=2026-10-22"`, release directories under
`~/trade-ai-releases/portfolio-server/` (82180caba 10-22 11:08, ee38621b1 18:57, f7c1e96cb 20:32, 0f5bf2453 10-23
08:52, 53aa1b619 09:39, 80e93c99f 12:04), the guard ledger (one release-write grant per release; campaign grant
46e85e0d since 10-23 09:38). Batch 9 is merged (98bef2794) and not yet served: CURRENT still points at 80e93c99f.

Batch 10 candidates (coordinator plan): #1972, #1996, #2000, #2001, #1999 (already in 9), #2005, #2011, #1953, #1955,
#1957, #1958, #1960, #1970, #1976, #1879-#1881, #2017, #2020.
