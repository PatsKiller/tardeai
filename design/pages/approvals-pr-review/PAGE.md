# Approvals: PR review (Merges)

- **Page id:** `approvals-pr-review`
- **Route:** `/v3/approvals?tab=MERGE` (list), `/v3/approvals/pr:<N>` (review sheet; `?head=<sha9>` from the digest link)
- **Nav group:** Approvals (a new "Merges" tab on the existing Approvals Center; nothing removed)
- **Component (to build):** `apps/command-center-v3/src/pages/ApprovalsHub.tsx` (tab) + a new review sheet component
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** none
- **Current (verified) version:** none

## Purpose

Let the operator read an independent, head-bound review of every ready PR and decide Approve / Hold / Ask in one
full-screen sheet. That works on a phone, where GitHub diffs cannot be reviewed.

## Data sources (proposed, not built)

- `PrReview@v1` store `data/coordination/pr_reviews/` (domain `pr_reviews`, proposed)
- Operator decisions ledger `data/governance/operator_decisions.jsonl` (kind `MERGE`; store activation pending)
- `pr_merge_digest` digests and `PrMergeHeadBinding@v1`

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v001 | PROPOSED | — | Merges tab + review sheet; synthetic mockup at 390/412/1440 (private) |

Full spec: `docs/ops/PR_REVIEW_MODAL_SPEC.md`. How to change this page: propose a new version; never edit an approved one.
