---
id: DSN-20261024-ask-tracking
title: Ask-CIO canonical tracking truth
owner: codex-ask-tracking-20261024
status: IN_PROGRESS
phases:
  - id: DSN-20261024-ask-tracking-P1
    title: Existing canonical writer and verified consumer readback
    status: IN_PROGRESS
    goal: Auto-track into the same My Watchlist source or return an explicit unverified failure.
    entry_criteria: Own tracking-only claim; accepted-main source; no live writes.
    acceptance:
      - Actual canonical command and membership reader with confirmed GUID binding.
      - Identity refusals stop later writes; partial/readback failures never verify.
      - Shared membership survives question untrack; no legacy default store.
      - Isolated producer/consumer proof, affected whole suites and ratchets, one PUSH_NEEDED.
    tasks:
      - id: DSN-20261024-ask-tracking-P1-T1
        title: Implement canonical tracking backend and honest receipts
        status: IN_PROGRESS
        areas:
          - scripts/lib/cio_ask_tracking.py
          - tests/test_cio_ask_tracking_canonical_20261024.py
          - docs/ops/ASK_CIO_TRACKING_CANONICAL_20261024.md
  - id: DSN-20261024-ask-tracking-P2
    title: Integrated Ask presentation and served acceptance
    status: HELD
    goal: Show only verified target claims with the Ask-quality/mobile companion.
    entry_criteria: Coordinator integrates and releases green source; exact runtime authority.
    acceptance:
      - Exact source and canonical runtime consumer readback.
      - Ask UI phone tap/Back/focus/viewport proof in its companion, not invented by backend tests.
    tasks:
      - id: DSN-20261024-ask-tracking-P2-T1
        title: Integrate and prove runtime tracking and mobile presentation
        status: HELD
        areas:
          - coordinator-only/ask-tracking-integration
---

# Canonical tracking truth

See [source report](../ops/ASK_CIO_TRACKING_CANONICAL_20261024.md). No new source of truth or live operation is introduced.
