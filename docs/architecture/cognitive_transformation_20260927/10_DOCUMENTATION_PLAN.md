# 10 · Documentation Plan — affected, new, obsolete; diffs; sequencing

```
Status:      PROPOSED
as_of:       2026-09-27T18:00:00-04:00
Measured at: 8f2a178d5 (origin/main) / served 8f2a178d5-main-exact-phase2-20260927-171004.
Authority:   READ_ONLY_ADVISORY. Documentation obligations only.
Package:     cognitive_transformation_20260927 — read 00 first.
Answers:     operator brief §11 (documentation requirements: affected, new, obsolete, diffs,
             dependencies, migration sequencing — documentation is part of the implementation plan).
```

## 1. Rules this plan obeys (AGENTS.md §14, §20 `[CODE]`)

- Every document carries `Status / as_of / Measured at`. Superseded documents say so in the header;
  nothing is deleted. Rewrites are diffed against the original and the diff is reported.
- The index is generated (`scripts/report_docs_inventory.py --write-index`), never hand-edited;
  `--check-index` is the CI drift check (it fails today on one pre-existing row,
  `RELEASE_MANIFEST_LATEST.md` `[VERIFIED: survey run 2026-09-27]` — reported, not fixed by this PR).
- `PROJECT_DOC_INDEX.md` and `DOCUMENTATION_INDEX.md` remain the hand-maintained "what is current"
  narratives and get one row each for this package.
- A rule change to AGENTS.md is a normal PR outside §0/§2/§17 (§20), but this package **proposes** the
  text (§5) and does not edit AGENTS.md — the operator sees it first.
- Docx and generated binaries stay out of the repo (`#1277` tripwires) — the emailed `.docx` lives in
  the session scratchpad and Drive, not in `docs/`.

## 2. Affected documents — header-level diffs applied by this PR

Each diff is one or two header lines added inside the existing header block. Body text is untouched
in this PR; body integration happens in the wave that changes the behaviour (§4).

| Document | Diff (verbatim lines added) | Why |
|---|---|---|
| `docs/architecture/PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md` | `Extended by:  cognitive_transformation_20260927/ (memory enforcement, GIR, retrieval-first, supervision, governance; roadmap 09 supersedes §12 waves 1–5 as the active plan; §12 stays the baseline)` | its roadmap is re-planned |
| `docs/architecture/MATURITY_PLAN_4_TO_8.5_2026-09-21_ENHANCED.md` | `Amended by:   cognitive_transformation_20260927/09_MATURITY_GAP_AND_ROADMAP.md — phases P4 (memory join) and P6 (gate honesty) are re-planned there; P1–P3, P5 unchanged` | memory/gates re-planned; alert phases stay |
| `docs/architecture/TRADE_AI_INSTITUTIONAL_MEMORY_AND_AUTONOMOUS_AGENT_ARCHITECTURE_2026-08-24.md` | `Amended by:   cognitive_transformation_20260927/01 (enforcement), 04 (layer transitions), 08 (influence path); the seven-plane taxonomy stands` | design kept, obligations added |
| `docs/architecture/TRADE_AI_MEMORY_RETRIEVAL_AND_INDEX_STRATEGY_2026-08-24.md` | `Amended by:   cognitive_transformation_20260927/03 — retrieval modes become ladder steps 1–7; index type resolved to pgvector (installed on prod, measured 2026-09-27)` | index decision made |
| `docs/architecture/M2_PRODUCTION_SHADOW_MIGRATION_DESIGN_2026-08-24.md` | `Amended by:   cognitive_transformation_20260927/02 §5 — the GIR projection reuses this projector pattern; prod cutover remains gated (12)` | reuse stated |
| `docs/architecture/TRADE_AI_FUTURE_STATE_2026-09-14.md` | `Amended by:   cognitive_transformation_20260927/00 for the memory, agent, research, worker and governance domains` | future state extended |
| `docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md` | `Amended by:   cognitive_transformation_20260927/04 (checkpoints), 08 (MBI_COGNITION ladder); MBI_BEHAVIOR = 0 unchanged` | its four additions get a path |
| `docs/architecture/AEC_PARALLEL_AGENTS_AND_MEMORY.md` | `Amended by:   cognitive_transformation_20260927/01 — the four spines are read through the façade; "not yet built" items are W1–W3` | spines absorbed |
| `docs/architecture/TICKER_KNOWLEDGE_GRAPH_GUID_LINEAGE.md` | `Amended by:   cognitive_transformation_20260927/07 — ticker_guid is an alias; edges move to intelligence.gir_edge` | partly stale |
| `docs/architecture/DECISION_PROVENANCE_MATRIX.md` | `Amended by:   cognitive_transformation_20260927/07 §3 — provenance becomes USED edges emitted by the façade` | census → mechanism |
| `docs/architecture/AGENT_SERVICE_MAP_2026-09-25.md` | `Amended by:   cognitive_transformation_20260927/06 — every component gains an SLA row and a heartbeat; registry-vs-host drift is a 05 detector` | map → governed roster |
| `docs/architecture/ARCHITECTURE_INDEX.md` | seven new rows (question → registry → checker): memory architecture → 01/02; worker contract → 06 + supervisor tables; model routing → 09-27 §9 + 03 gating; SLA/health → 06; knowledge graph → 07; governance → 05; roadmap → 09 | 5 of these 7 questions answer NONE today `[DOC-CLAIM: survey]` |
| `docs/architecture/V3_3_IMPLEMENTATION_STATUS_2026-09-27.md` | one bullet under "Live and not named in v3.3" becomes a pointer: `Cognitive transformation package (PROPOSED): cognitive_transformation_20260927/` | annex stays the v3.3 truth |
| `docs/project/PROJECT_DOC_INDEX.md`, `docs/DOCUMENTATION_INDEX.md` | one dated section / row for the package | hand-maintained "current" lists |
| `docs/INDEX.md` | regenerated | generated |

The v3.3 master architecture itself is **not edited**: it is a blueprint with its own supersession
rules (§1) and an annex mechanism already in use; a v3.4 that integrates 01–08 is a Wave 5 deliverable
after the designs have been proved, not before.

## 3. New documents

| Document | Status at creation | Owner | Becomes ACTIVE when |
|---|---|---|---|
| `cognitive_transformation_20260927/00_…13_*.md` (this package) | PROPOSED | platform | operator approves the package (11) |
| `docs/architecture/adr/ADR-006-memory-as-platform-dependency.md` … `ADR-010-approval-packages.md` | PROPOSED | platform | the wave that implements each |
| `docs/briefs/WAVE_COGX_cognitive_maturity_4_7.md` | recovered verbatim | operator | on commit (a brief is the operator's text) |
| `docs/architecture/cognitive_transformation_20260927/AGENTS_13_AMENDMENT_DRAFT.md` (§5) | DRAFT | platform | merged into AGENTS.md by its own PR after operator review |
| Wave closeouts `docs/ops/COGX_WAVE_<n>_CLOSEOUT_<date>.md` | per wave | wave lead | at wave exit |
| Runbooks `docs/ops/SUPERVISOR_LADDER_RUNBOOK.md`, `docs/ops/APPROVAL_PACKAGE_RUNBOOK.md` | W2 / W1 | platform | when the lane is live |
| Contracts `docs/contracts/MemoryContext_v1.md`, `RetrievalReceipt_v1.md`, `IntelligenceEnvelope_v1.md`, `ApprovalPackage_v1.md`, `Breach_v1.md`, `CognitiveCheckpoint_v1.md` | W1–W3 | platform | with the code that emits them (same PR) |
| `config/contract_manifest.json` (hashes for drift, 05 §5) | W1 | platform | with the first contract |

## 4. Obsolete documents (marked, never deleted)

| Document | Action | Reason |
|---|---|---|
| `CIO_AS_IS/FUTURE/GAP_2026-09-19-*` and `2026-09-20-*` series (27 files) | already `archive_superseded` in the generated index; no change | superseded snapshots |
| `HONEST_MATURITY_ASSESSMENT_2026-09-20-*` (3 files) | already superseded by the 09-21 assessment | superseded |
| `agent-contracts.md` | already `SUPERSEDED BY @v2`; add `See also: 01 §3` | receipts now written by the façade |
| `MATURITY_PLAN_4_TO_8.5_2026-09-21.md` (non-enhanced) | already replaced by ENHANCED; no change | superseded |
| `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_0/1/2.md` | superseded by v3.3 (09-27 PR #1279); no change | superseded |

## 5. Proposed AGENTS.md §13 amendment (draft text, not applied)

> **§13.8 · Memory-first and retrieval-first are architectural standards** `[PROPOSED 2026-09-27]`
> 1. No process that decides, advises, researches, curates or monitors may run without opening a
>    `MemoryContext@v1` through `intelligence_client` before it acts and committing after it acts.
>    Decisions and advice fail closed (`HOLD_MEMORY_UNAVAILABLE`); monitors run degraded and say so.
> 2. No research-class LLM call may be made without a `RetrievalReceipt@v1` showing the seven-step
>    ladder was attempted. A receipt with an empty ladder is a defect.
> 3. Memory reaches cognition and advice by the per-surface mode ladder in `config/memory_influence_policy.json`
>    (operator-approved rows). It never reaches `BEHAVIOR_FIELDS`; §0 rule 1 and the unconditional
>    raise at `cio_instrument_record.py:390` are unchanged.
> 4. Every lane has an SLA row and a heartbeat. Exit 0 without the lane's output signal is a `NO_OUTPUT`
>    breach, not a success.
> 5. Silo conformance (`PlatformConformance@v1`) gates promotion once Wave 5 turns the gate on; until
>    then it warns and is published daily.
> **Why (the failures behind the rule):** 0 of 22,392 wake decisions changed by memory; research produced
> seven times; 128k contradictions unresolved; weekly/monthly reports failing for months under "skipped
> (non-fatal)"; the wake dispatcher killed 436 times unnoticed. (Sources: 09-27 due diligence §1–§5; 09-26 audit.)

Change class: MINOR (adds obligations, weakens nothing; §0/§2/§17 untouched) → rides the existing
ratification per the version policy; the operator decides.

## 6. Migration sequencing (which docs change in which wave PR)

| Wave | Documentation delivered in the same PRs as the code |
|---|---|
| **This PR** | package 00–13, ADR-006..010, brief, header diffs (§2), index regenerated, `PROJECT_DOC_INDEX` row |
| **W1** | contracts for `MemoryContext@v1`, `RetrievalReceipt@v1`, `IntelligenceEnvelope@v1`, `ApprovalPackage@v1`; `APPROVAL_PACKAGE_RUNBOOK`; `contract_manifest.json`; 01/02/03 status → ACTIVE (shadow); `ARCHITECTURE_INDEX` rows verified against code; W1 closeout |
| **W2** | `Breach@v1`, `RecoveryReceipt@v1`; `SUPERVISOR_LADDER_RUNBOOK`; `gateway-enforcement.md` gains the memory chokepoint; 09-27 report body §11 integrated (single write path live); AGENTS.md §13.8 PR (if approved); W2 closeout |
| **W3** | `CognitiveCheckpoint@v1`, `Procedure@v1`; 04 → ACTIVE; `CIO_FUTURE_STATE_FULL_MATURITY` body integration (judgment/commitment/scoring/self-repair mapped to 04/06); W3 closeout |
| **W4** | worker contract doc (the 09-27 §5 contract becomes `docs/architecture/WORKER_CONTRACT.md`); model routing architecture doc (`MODEL_ROUTING.md`, from 09-27 §9 + chooser); one agent registry doc; `AGENT_SERVICE_MAP` re-measured (not re-dated); W4 closeout |
| **W5** | v3.4 master architecture integrating 01–08 (diffed against v3.3, omissions listed); 09 re-scored by the independent lane; the package status → ACTIVE or SUPERSEDED BY v3.4; final closeout with the shorter operator-only list |

## 7. Dependencies between documents

00 depends on 01–13 (summary). 02 depends on 01 (façade) and 07 (edges). 03 depends on 01, 02. 04
depends on 01, 02. 05 depends on 01 §6, 03 §7, 06. 06 depends on 05 (classes A/B/C) and 13 (L4/L5).
08 depends on 01, 03, 05. 09 depends on all. 11/12/13 depend on 09 (what each wave needs). A change to
a contract in W1 propagates: 01 → 02/03/04 → 05/06 → 08 → 09; the drift detector (05 §5) hashes the
contracts so the propagation is checked, not remembered.
