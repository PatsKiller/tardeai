---
id: DSN-20261023-ask-the-cio
title: Ask the CIO (Phases 8-11)
status: IN_PROGRESS
approval: approved (operator 2026-10-23, after the release-train phases); option B advisory sizing needs AGENTS 21.0.0
source: 'docs/ops/ASK_THE_CIO_RESEARCH.md (PR #2005); scripts/lib/cio_ask_contract.py (PR #2011)'
summary: Phases keep the operator's numbering (P8-P11). size_suggestion stays omitted until AGENTS 21.0.0 is ACTIVE. Every
  question/answer/source lands in CIO memory keyed by security_guid.
phases:
- id: DSN-20261023-ask-the-cio-P8
  title: Ask bar + "My questions" + Telegram quick path (shared contract)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-ask-the-cio-P8-T1
    title: 'Land #2011 (Phases 8/10/11; CI red, conflicting) — board task T-20261023-6aa6e1'
    status: PROPOSED
    areas:
    - scripts/lib/cio_ask_core.py
    board_task: T-20261023-6aa6e1
  - id: DSN-20261023-ask-the-cio-P8-T2
    title: 'OPERATOR: third push for #2011 (push budget)'
    status: PROPOSED
    areas:
    - operator/push/2011
    owner: OPERATOR
  - id: DSN-20261023-ask-the-cio-P8-T3
    title: Wire advisory size_suggestion into cio_ask_contract.py once AGENTS 21.0.0 is ACTIVE
    status: PROPOSED
    areas:
    - scripts/lib/cio_ask_contract.py
    depends_on:
    - DSN-20261023-agent-ops-P1-T6
- id: DSN-20261023-ask-the-cio-P9
  title: Deep research pipeline (Brave/SEC/news/street targets, LLM panel, prospectus); lane at SHADOW
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-ask-the-cio-P9-T1
    title: 'OPERATOR: third push for #2006 (local commit 9d4fd4d04, env_names sort fix)'
    status: PROPOSED
    areas:
    - operator/push/2006
    owner: OPERATOR
  - id: DSN-20261023-ask-the-cio-P9-T2
    title: 'OPERATOR: review the cio-ask-research lane contract (DRAFT -> REVIEWED) on #2006'
    status: PROPOSED
    areas:
    - operator/contracts/cio-ask-research
    owner: OPERATOR
  - id: DSN-20261023-ask-the-cio-P9-T3
    title: 'OPERATOR: decide the cio_ask_deep_research spend cap ($5/day proposed vs $2/day global cap)'
    status: PROPOSED
    areas:
    - operator/decisions/ask-cio-cap
    owner: OPERATOR
- id: DSN-20261023-ask-the-cio-P10
  title: Auto-tracking / persistent memory
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-ask-the-cio-P10-T1
    title: 'OPERATOR: approve the questions/answers store row (§26), the positions_store reader cio_ask and the memory apply
      flag'
    status: PROPOSED
    areas:
    - operator/decisions/ask-cio-store
    owner: OPERATOR
- id: DSN-20261023-ask-the-cio-P11
  title: Re-answer on material change
  status: IN_PROGRESS
---

Seeded 2026-10-23 from the contract header (branch only) and docs/ops/ASK_THE_CIO_RESEARCH.md:4 (Phase 9 branch).

Backfill 2026-10-23: PRs #2011 (P8/P10/P11, red + conflicting), #2005 (P9 pipeline, green, conflicting after batch 9),
#2006 (P9 lane at SHADOW, red by design until the contract is REVIEWED). Operator, verbatim: "the key is the
persistent memory. Across the CIO system." Option B (advisory sizing) chosen 2026-10-23 -> AGENTS 21.0.0.
