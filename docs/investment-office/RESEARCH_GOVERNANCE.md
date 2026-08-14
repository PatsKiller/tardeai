# Research Governance — PR-R1 Foundation

Parallel workstream: book/research knowledge infusion. Isolated from the
production-hardening CIO remediation agent.

- branch: `feature/research-governance-v1`
- worktree: `/home/johnclaw/tradeai-wt-research-governance`
- base: see `RESEARCH_GOVERNANCE_BUILD_BASELINE.md`
- authority: `READ_ONLY_ADVISORY` — nothing here grants broker/order/stop authority.

## Purpose

Govern the promotion of research knowledge (books, primary papers, reproduced
factors, seasonality) into Trade AI cognition so that a weak finding cannot be
promoted merely because its source "sounds right". The methodology books (Aronson,
López de Prado, White, Harvey/Liu/Zhu) have the authority to **block** weak
research promotion; they can never generate a trade.

## Core invariants

```text
NO CONFIRMATORY RESULT WITHOUT A FROZEN HYPOTHESIS FAMILY
NO FROZEN FAMILY WITHOUT A COMPLETE TRIAL REGISTRY
NO COMPLETE TRIAL REGISTRY THAT RECORDS ONLY SELECTED/WINNING VARIANTS
```

Once a confirmatory OOS segment is examined and then used to alter parameters,
that segment is **consumed** (`oos_consumed_at`). It cannot remain untouched OOS
evidence; a later iteration needs a new segment or must be labelled
`POST_OOS_TUNED` rather than `OOS_SUPPORTED`.

## Three orthogonal schema dimensions

Never collapse into one field:

- `evidence_type` — what kind of knowledge (SOURCE_NARRATIVE, DETERMINISTIC_MECHANICS,
  EMPIRICAL_STRATEGY, EMPIRICAL_FACTOR, SEASONALITY, VALUATION_MODEL, ...).
- `research_status` — lifecycle position (SOURCE_CLAIM → ... → OOS_SUPPORTED).
- `evidence_grade` — type-aware quality grade (A/B/C/D/X).

## Statistical governance (applicability-driven)

- **DSR** (`deflated_sharpe.py`) — requires the trial-Sharpe distribution and a
  known trial count; otherwise UNAVAILABLE.
- **PBO/CSCV** (`pbo.py`) — requires >= 2 configurations; otherwise NOT_APPLICABLE.
- **White Reality Check / STW** (`bootstrap_reality_check.py`) — one family test;
  a calendar family is evaluated as a named family, not a lone best variant.
- **Multiple testing** (`multiple_testing.py`) — Bonferroni, Holm, BH-FDR.
- **Purged/embargoed CV + CPCV** (`cv.py`) — López de Prado label-leakage discipline.

## Promotion ladder (RG-0 .. RG-11)

`promotion_gate.py` defines the asymmetric ladder. Methodology may block;
mechanics may establish conditional facts; risk may veto/size down; valuation may
alter ranges; portfolio-construction may change sizing; seasonality may modify
staging/timing. None independently creates trade authority.

## Subsystem acceptance (RGA-1 .. RGA-16)

`acceptance.py` defines phase-aware acceptance with `PASS / FAIL / NOT_IN_SCOPE`.
`NOT_IN_SCOPE` never counts as PASS. R1 requires RGA-1..10, 13, 14; RGA-11/12 are
contract-only; RGA-15/16 are not in scope until R3/R4.

## Scope guard

`pr_scope_guard.py` enforces the R1 allowlist against
`git diff --name-only BASE_SHA...HEAD`. Off-limits CIO/retrieval/release files
fail the guard.

## Authority boundary

Every promotion terminates in READ_ONLY_ADVISORY. No provider calls, no broker
calls, no production DB writes, no change to live Alex behavior in R1.
