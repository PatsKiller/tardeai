---
id: DSN-20261024-tradeinview-history
title: TradeInView package C Holding history
owner: CIO/TradeInView; codex-tradeinview-c-20261024 source worker
status: IN_PROGRESS
approval: 'Source implementation delegated from tradeinview-build-request.md and approved handoff SPEC; no runtime or policy approval is implied.'
phases:
  - id: DSN-20261024-tradeinview-history-P1
    title: Source frontend and producer-backed proof
    status: IN_PROGRESS
    goal: Render the approved Holding history layout using only server financial truth.
    entry_criteria: Own frontend task/claim; API_CONTRACT_V1 agreed with backend A and shell B.
    acceptance:
      - Server ordering/statistics, URL symbol/sort, named accounts and source clocks retained.
      - Six statistics, account timelines, all trip rows, provenance and actual gap reasons.
      - Pinned actual producer COPY AXTI plus basis/Fidelity fixture states1440/412.
      - Model/browser/build/nopg/ratchets/completeness proof and one publication handoff.
    gates:
      - No backend, broker, order, stop, provider or live server calls.
      - Actual backend producer fixture required before final delivery; no mockup financial values.
    tasks:
      - id: DSN-20261024-tradeinview-history-P1-T1
        title: Implement Holding history frontend and verify source truth
        status: IN_PROGRESS
        areas:
          - apps/command-center-v3/src/components/tradeinview/HoldingHistory.tsx
          - apps/command-center-v3/src/lib/holdingHistoryModel.ts
          - docs/ops/TRADEINVIEW_HOLDING_HISTORY_20261024.md
  - id: DSN-20261024-tradeinview-history-P2
    title: Coordinator integration and exact served acceptance
    status: HELD
    goal: Integrate backend A, shell B and frontend C, then prove served readback.
    entry_criteria: All source packages published, required checks green and coordinator release authorized.
    acceptance:
      - Real history endpoint schema and source-backed AXTI/V/SCHD/SCHG/SPCX/NFLX accounts verified on production COPY by A.
      - Shell imports real HoldingHistory and Replay navigation works with exact trade ID.
      - Exact served identity/readback evidence, separately from fixture proof.
    gates:
      - Coordinator owns merges and releases; worker never pushes or declares runtime acceptance.
    tasks:
      - id: DSN-20261024-tradeinview-history-P2-T1
        title: Integrate and verify the accepted TradeInView packages
        status: HELD
        areas:
          - coordinator-only/tradeinview-integration
---

# Holding history source and evidence

See [package C report](../ops/TRADEINVIEW_HOLDING_HISTORY_20261024.md). Backend A owns source normalization,
all financial aggregation and the global lineage report. Shell B owns tabs, Journeys and Replay navigation.
