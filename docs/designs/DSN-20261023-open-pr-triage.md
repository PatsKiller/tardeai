---
id: DSN-20261023-open-pr-triage
title: Open PRs with no program owner (triage)
status: IN_PROGRESS
approval: not needed (triage); merges follow approval A or the operator
source: gh pr list --state open (46 open on 2026-10-23 14:10 ET)
summary: Every open PR not covered by another design gets a task here, so nothing open is invisible on the Work board.
phases:
- id: DSN-20261023-open-pr-triage-P1
  title: Stale since 09-28 / 10-15 (conflicting)
  status: PROPOSED
  tasks:
  - id: DSN-20261023-open-pr-triage-P1-T1
    title: 'Triage #1350 / #1351 (09-28 audit docs, conflicting): close as superseded or rebase'
    status: PROPOSED
    areas:
    - docs/trade-ai-memory-and-system-live-audit-20260928.md
  - id: DSN-20261023-open-pr-triage-P1-T2
    title: 'Triage #1599 n8n relay env allowlist (conflicting; packet n8n-relay-env-allowlist-20261021 DRAFT)'
    status: PROPOSED
    areas:
    - scripts/n8n_run_relay.py
  - id: DSN-20261023-open-pr-triage-P1-T3
    title: 'Triage #1628 release-grant SHA binding (conflicting)'
    status: PROPOSED
    areas:
    - scripts/lib/release_grant_binding.py
  - id: DSN-20261023-open-pr-triage-P1-T4
    title: 'Triage the F09 broker-read onboarding stack #1795/#1796/#1798/#1799/#1801/#1802 against AGENTS 19.0.0 §27 (conflicting)'
    status: PROPOSED
    areas:
    - config/n8n_effect_keys.json
  - id: DSN-20261023-open-pr-triage-P1-T5
    title: 'Triage the LLM bridge routes stack #1804-#1807 (conflicting; packet n8n-llm-bridge-routes-20261021 DRAFT)'
    status: PROPOSED
    areas:
    - config/llm_process_registry.json
- id: DSN-20261023-open-pr-triage-P2
  title: Green and mergeable, not yet batched
  status: PROPOSED
  tasks:
  - id: DSN-20261023-open-pr-triage-P2-T1
    title: 'Batch #1879 / #1880 / #1881 (n8n maturity + health retry + recovery budget fixes; green, mergeable)'
    status: PROPOSED
    areas:
    - config/self_healing_mechanisms.json
- id: DSN-20261023-open-pr-triage-P3
  title: Red
  status: PROPOSED
  tasks:
  - id: DSN-20261023-open-pr-triage-P3-T1
    title: 'Fix #1940 desk truth lanes v2 (red, conflicting)'
    status: PROPOSED
    areas:
    - config/ci_gates/n8n_desk_truth_lanes_20261022.json
  - id: DSN-20261023-open-pr-triage-P3-T2
    title: 'Fix #1943 cio-hardening fast shards (red)'
    status: PROPOSED
    areas:
    - .github/workflows/cio-production-hardening-ci.yml
---

Backfill 2026-10-23. Every other open PR belongs to a design: #1935 #1936 #1937 #1939 #1942 (release train),
#1953 #1955 #1958 #1960 #1996 #2000 #2001 (CIO prospect store), #1957 (momentum alerts), #1970 #1972 (Ops Controls),
#1976 (data domains), #1991 (AT alignment), #1997 (premarket), #2004 #2010 (merged via batch 9, close), #2005 #2006
#2011 (Ask the CIO), #2016 (JSONL retention), #2017 (site validation), #2020 (account labels), #2021 (Work pipeline).
