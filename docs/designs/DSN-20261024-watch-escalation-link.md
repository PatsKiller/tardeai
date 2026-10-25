---
id: DSN-20261024-watch-escalation-link
title: Correct the escalation My Watchlist link
owner: codex-watch-escalation-link-20261024
status: IN_PROGRESS
phases:
  - id: DSN-20261024-watch-escalation-link-P1
    title: Construct the current encoded Watch destination at the escalation writer
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261024-watch-escalation-link-P1-T1
        title: Fix and verify the escalation link without running or sending the job
        status: IN_PROGRESS
---

# Escalation My Watchlist link

This implements item 9 of the operator's Ask CIO quality request. Entry is accepted main `d635873e1063efb8a9ff8e8ce542654ed2ef7654`, including SITE PR #2076. The actual escalation writer is claimed separately from the Ask frontend/backend packages.

Acceptance: the sender uses the central URL builder with current `my-watchlist` tab and encoded symbol; the final normalized URL has one query separator, retains the symbol and cannot inject a second query or fragment. Existing synthesis, confidence, reasons and notification priority remain. Tests exercise the actual sender expression with a recording fake, never importing/running its job. Hidden-driver checks, no-new guards and documentation must pass before one local publication command. Coordinator/operator owns rollout.
