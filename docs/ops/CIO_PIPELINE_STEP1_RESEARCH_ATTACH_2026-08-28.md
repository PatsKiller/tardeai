# CIO Pipeline Step 1 — research attach + honest synthesis provenance

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MEMORY_BEHAVIOR_INFLUENCE: 0
Promotion ceiling: REVIEW_READY

## What this slice did

Two last-mile lies:

1. Hermes completed (HERMES_LOOP_COMPLETED hundreds of times) but the originating plan never carried `hermes_result_id`. Fingerprint compared a field that was always empty. Downstream readers could not find the artifact.
2. CIO run synthesis (deterministic `build_investment_product_synthesis_fn` / dict-literal fallback) stamped `CIO_RUN_MODEL_CALL_RECORDED` with hardcoded `cost_usd=0.001` even though no model ran.

This PR attaches a successful result id onto the plan (forward-only + optional dry-run backfill) and stops recording a model call when none is made.

## What this slice did not do

- Action / ThesisDecisionGate unchanged. Research still cannot create promotion or an order.
- Notify unchanged. `CIO_SITUATION_NOTIFY` / Telegram interdict left as found. `material_changed` is still a substantive field compare (rec / summary / fire / material). Joining `hermes_result_id` does not flip it.
- No SpecialistArtifact@v2. No InvestmentDecision rename. No new LLM call in `cio_run_worker` synthesis.
- Stop management / 2FA / quote freshness untouched.
- Two reentry books (#584) not merged.

## Before (CURRENT measure 2026-08-28, production plan fold via `CIOPlanStore`)

| Metric | Value |
|---|---|
| plans (folded) | 787 |
| plans_with_hermes_result_id | 0 |
| plans_with_hermes_research_id | 425 |
| HERMES_RESEARCH_COMPLETED | 460 |
| HERMES_LOOP_COMPLETED | 457 |
| CIO_RUN_MODEL_CALL_RECORDED | 45 |
| distinct cost_usd on those receipts | `{0.001: 45}` |

Root cause A: `CIOPlanStore.update_plan` allowed `hermes_research_id` but not `hermes_result_id`, so `_merge_evidence_on_plan_id` could never persist the join.

Root cause B: `_cio_synthesis` always called `record_model_call(..., 0.001)` after the injected deterministic `synthesis_fn` and after the dict-literal fallback.

## After (fill at promote)

| Metric | After promote |
|---|---|
| UI / SOURCE | *(filled live)* |
| plans_with_hermes_result_id | *(filled live — forward-only until backfill --apply)* |
| new CIO_RUN_MODEL_CALL_RECORDED with cost 0.001 from deterministic synthesis | should be 0 going forward |

Historical 45 receipts of $0.001 remain in the append-only ledger. We do not rewrite them.

## Attach rules

- Stamp `hermes_result_id` / `research_id` / `completed_ts` only when critique is VALID or PARTIAL and the job is not failed/truncated/cost-capped.
- Same research_id + result_id updates in place. No new plan fork.
- Attach throw: lineage stall note (`logs/lineage_stalls.jsonl`); research result already persisted; worker success path does not raise.
- Optional backfill: `scripts/cio_attach_research_backfill.py` (dry-run default; `--apply` appends PLAN_UPDATED only).

## Step 2 (not this PR)

Specialist join onto the same plan **or** an honest A-class operator-surface field (agent-originated count > 0 on a real desk). Not notify. Not a model in synthesis. Not council type invention.
