---
id: DSN-20261022-site-validation
title: Command Center site validation (Playwright) + P3 cosmetics
status: IN_PROGRESS
approval: 'approved (operator 2026-10-22 ~22:15: "use playwright overnight to go through all of the pages on the site and
  validate everything."; P3 UI fixes approved 2026-10-23)'
source: docs/ops/SITE_VALIDATION_2026-10-23_53aa1b619.md
summary: ~290 views per build, no regressions. Live :7777 crawling stopped 09:31 ET 10-23 (AGENTS 20.1.0 §28.8).
phases:
- id: DSN-20261022-site-validation-P1
  title: 'Crawl + P1/P2 fix PRs (#1974 #1975 #1984-#1987 #1998 #2003 #2007 #2009 #2014) + report #2015'
  status: DONE
  tasks:
  - id: DSN-20261022-site-validation-P1-T1
    title: Site validation P1/P2 fixes + P3 mockups — board task T-20261023-b92fe2
    status: DONE
    areas:
    - apps/command-center-v3
    board_task: T-20261023-b92fe2
- id: DSN-20261022-site-validation-P2
  title: 'P3 cosmetics — #2017 (green, conflicting vs MetricStrip from batch 9)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-site-validation-P2-T1
    title: 'Rebase #2017 onto main; add its Playwright spec to cc-surface-agreement-ci.yml; review the adapted rotationRetainedError
      guard test'
    status: PROPOSED
    areas:
    - apps/command-center-v3/src/components/MetricStrip.tsx
- id: DSN-20261022-site-validation-P3
  title: Live validation of /retirement .. /control-plane after 16:15 ET (GET only, <=1 req/s)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-site-validation-P3-T1
    title: After-close live smoke of the replay-only pages with TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1 (never inside 04:00-16:15
      ET)
    status: PROPOSED
    areas:
    - scripts/crawl_v3_dashboard.py
    depends_on:
    - DSN-20261023-agent-ops-P1-T2
- id: DSN-20261022-site-validation-P4
  title: Not fixed (owner decisions)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-site-validation-P4-T1
    title: 'OPERATOR: portfolio valuation-clock decision (holdings reprice vs overview snapshot, report #17)'
    status: PROPOSED
    areas:
    - operator/decisions/valuation-clock
    owner: OPERATOR
  - id: DSN-20261022-site-validation-P4-T2
    title: Strategy Live R root cause in paper_trade_monitor.py (needs an execution-engineering grant + owner)
    status: HELD
    areas:
    - scripts/paper_trade_monitor.py
---

Backfill 2026-10-23. P1/P2 fixes merged in batch 8 (#1974 #1984-#1987, LIVE 80e93c99f) and batch 9 (#1975 #1998 #2003
#2007 #2009 #2014 #2015). P3 mockups sent to the operator (~/.cache/rtc/site-crawl/mockups/P3_MOCKUPS.html).
