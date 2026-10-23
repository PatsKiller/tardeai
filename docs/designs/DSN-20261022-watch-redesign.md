---
id: DSN-20261022-watch-redesign
title: Watch redesign (prospect lanes, My Watchlist / System Suggests)
status: IN_PROGRESS
approval: approved (Watch mockup as-is 2026-10-22 ~15:35; My Watchlist/Suggests 2026-10-23)
source: docs/ops/WATCH_LISTS_PAGE_2026-10-23.md
summary: Watch reads the one CIO record; held flag from the broker store; NAVN shown formerly-held with P/L and re-entry.
phases:
- id: DSN-20261022-watch-redesign-P1
  title: 'Accuracy fixes — #1926'
  status: LIVE
- id: DSN-20261022-watch-redesign-P2
  title: 'Prospect lanes redesign (Gate 3 mockup) — #1945'
  status: LIVE
- id: DSN-20261022-watch-redesign-P3
  title: 'My Watchlist (104 operator names) + System Suggests (top 20-30) + NAVN formerly held + filters + 502 banner — #2008'
  status: DONE
  tasks:
  - id: DSN-20261022-watch-redesign-P3-T1
    title: Watch lists build — board task T-20261023-37ca39
    status: DONE
    areas:
    - apps/command-center-v3/src/pages/Watch
    board_task: T-20261023-37ca39
- id: DSN-20261022-watch-redesign-P4
  title: 'Curator held flag (positions reader batch #4) — operator decision in DSN-20261022-cio-prospect-store P3-T4'
  status: PROPOSED
---

Backfill 2026-10-23. #1926 and #1945 LIVE batch 5 (ee38621b1); #2008 merged in batch 9 (98bef2794), live with the
batch 9 release.
