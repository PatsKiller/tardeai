# R5–R8 Build Baseline

Isolated additive workstream on top of merged R1–R4.

- worktree: `/home/johnclaw/tradeai-wt-research-r5plus`
- branch: `feature/research-r5-r8`
- BASE_SHA: `08be8976c049c11584a80f7fc631d2463fe1af0f`
- REMOTE_MAIN_AT_START: `08be8976c049c11584a80f7fc631d2463fe1af0f`
- R1_MERGE_SHA: `c005551a1e5da5a8d3f46d9e3018bff9bd516e7c`
- R2_MERGE_SHA: `f1cc17e50e0eec657aa47f8f9bdeb0b455bdb08e`
- R3_R4_MERGE_SHA: `08be8976c049c11584a80f7fc631d2463fe1af0f`

Authority: `READ_ONLY_ADVISORY`

```text
R5 — CPCV PATH CONSTRUCTION        R5A-1   (AFML Ch.12 deferred from R1)
R6 — APPEND-ONLY GOVERNANCE STORE  R6A-1   (durable persistence deferred from R1)
R7 — POLICY + BEHAVIORAL           R7A-1   (unimplemented evidence types)
R8 — EMPIRICAL FACTOR / STRATEGY   R8A-1   (fixture family, no winner-only)
```

Not in this PR: live Alex/CIO report rewrite, Telegram, RELEASE_MANIFEST,
deploy, rag_retrieval, Hermes, kb_lessons, production DB, broker/order/stop.
Does not create `scripts/lib/research_governance/live_alex.py`.
