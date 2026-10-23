---
id: DSN-20261023-server-memory
title: Portfolio-server memory kills
status: IN_PROGRESS
approval: approved (memory fix in approve-all; AGENTS 20.1.0 rule 'approved' ~11:05 ET 2026-10-23)
source: docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md
summary: 'Root cause 10-23: agent crawls and vite previews against :7777 plus unbounded routes (1.2 GB per load vs MemoryHigh
  1.5 GB).'
phases:
- id: DSN-20261023-server-memory-P1
  title: 'Health remediation memory bound (69 watchdog SIGKILLs 10-22) — #1963'
  status: LIVE
- id: DSN-20261023-server-memory-P2
  title: 'Client-side amplifiers — #1974, #1984'
  status: LIVE
- id: DSN-20261023-server-memory-P3
  title: 'Server read bounds — #2012'
  status: DONE
  tasks:
  - id: DSN-20261023-server-memory-P3-T1
    title: Server memory kills fix PR — board task T-20261023-fc7872
    status: DONE
    areas:
    - scripts/api_v2.py
    board_task: T-20261023-fc7872
  - id: DSN-20261023-server-memory-P3-T2
    title: Verify no portfolio-server SIGKILL in the first full session after the batch 9 release (journal read, no :7777
      traffic in-window)
    status: PROPOSED
    areas:
    - docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md
    depends_on:
    - DSN-20261023-agent-ops-P1-T2
- id: DSN-20261023-server-memory-P4
  title: AGENTS 20.1.0 §28.8 — no agent traffic to the live server in market hours
  status: DONE
- id: DSN-20261023-server-memory-P5
  title: 'Next candidates: portfolio.shared-symbol-context.v1 pref; minute-aligned :53-:58 trigger check'
  status: PROPOSED
  tasks:
  - id: DSN-20261023-server-memory-P5-T1
    title: Check crontab/timers against the kill seconds (:53-:58) and bound the shared-symbol-context pref route
    status: PROPOSED
    areas:
    - scripts/api_v2.py
---

Backfill 2026-10-23. #1963 LIVE 0f5bf2453; #1974/#1984 LIVE 80e93c99f; #2012 merged in batch 9 (98bef2794);
#2019 (20.1.0) merged d42fa803d.
