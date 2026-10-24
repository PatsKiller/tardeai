---
id: DSN-20261023-nvda-false-alert
title: NVDA phantom STOP HIT (0.133 promo share)
status: IN_PROGRESS
approval: approved (P1 fix, operator 2026-10-23)
source: branch fix/nvda-phantom-stop-alert-20261023 (worklog worklogs/claude-nvda-alert-20261023.worklog.md)
summary: The $213 stop was a system watchlist ENTRY plan stop (watchlist_entry_planner.py) that notify_material_change paired
  with a moomoo promo share.
phases:
- id: DSN-20261023-nvda-false-alert-P1
  title: Investigation (read-only)
  status: DONE
- id: DSN-20261023-nvda-false-alert-P2
  title: 'Fix PR: account tags, promo/de-minimis exclusion, stop provenance, fresh chart (local 3a735b4f1, depends on #2020)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-nvda-false-alert-P2-T1
    title: Push + PR for fix/nvda-phantom-stop-alert-20261023 (INDEX row, CI green, no merge)
    status: PROPOSED
    areas:
    - scripts/lib/held_position_alerts.py
    - config/held_position_alerts.json
---

Backfill 2026-10-23. Held by claims 20261023T174000Z-claude-550a5f7f / ...c321de18 / ...c0d3f8ad (session
2e7e1d01-nvda); the board task's areas overlap them, so only that session can take it.
