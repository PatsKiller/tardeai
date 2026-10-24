---
id: DSN-20261024-ask-cio-readable
title: Ask CIO canonical readable answers and live completion
owner: codex-ask-cio-readable-20261024
status: IN_PROGRESS
phases:
  - id: DSN-20261024-ask-cio-readable-P1
    title: Render canonical answers and refresh matching open threads
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261024-ask-cio-readable-P1-T1
        title: Shared readable answer presentation and completion refresh
        status: IN_PROGRESS
---

# Ask CIO canonical answers and completion

This is frontend items 4 and 6 of the operator's Ask CIO quality request. Accepted base: `9228634873392073f5849aaa77ec9b9121eb6094`.

The backend owns canonical plain answer text, sources, quote identity, actual spend and research-memory writes. The frontend preserves that text verbatim, shares one readable renderer, collapses only its structured sources and refreshes the matching thread/ask/version without a document reload.

Acceptance requires the actual copied-ledger question and backend-generated quick/deep responses, byte-for-byte equality with Telegram text, delayed completion and wrong-identity browser cases at 1440/412, native/house guards, hidden-driver checks and repository ratchets. A local source checkpoint is not publication or runtime acceptance. Coordinator/operator owns rollout.
