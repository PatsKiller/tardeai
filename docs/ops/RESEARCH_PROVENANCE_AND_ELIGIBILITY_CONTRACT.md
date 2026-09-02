# Research Provenance and Eligibility Contract

Status: ACTIVE  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0  
Schema: ResearchObservation@v1  
As of: 2026-09-02  
Campaign: cc-remediation-v1-20260902T224409Z  

## Purpose

Additive research observation / provenance envelope and fail-closed eligibility
policy for Command Center and downstream agent consumers. Reuses existing
research products and stores via adapters. Does **not** rewrite the research
platform, authorize orders, change schedulers, or mutate production data.

Backend lane owns portfolio/overview `canonical_observation`. This contract is
the **research-boundary** counterpart: wrap research records at the edge;
do not edit leased backend paths.

## Architecture rules (v3.3)

- Research **display** may fail open only with an explicit degraded label after
  deterministic checks.
- **Proposal eligibility** and any financial decision using required
  stale/unknown evidence **fail closed**.
- No LLM is a source of arithmetic, market, broker, account, position,
  eligibility, or execution truth.
- No research/agent path may connect to live broker-write authority.

## Envelope fields

Every research record exposed to Command Center or downstream agents must carry:

| Field | Meaning |
|-------|---------|
| `source_identity` | Product / artifact class id |
| `provider` | Producer system |
| `provider_at` | Provider timestamp |
| `observed_at` / `received_at` / `normalized_at` | Observation timeline |
| `business_date` / `session` | Where relevant |
| `freshness_status` / `freshness_age_seconds` | Freshness |
| `quality_status` | Quality |
| `entitlement_status` | Licensing / entitlement |
| `sequence_or_version` | Sequence or version |
| `source_hash` | Integrity hash of normalized non-secret payload |
| `calculation_or_model_version` | Calc / model version |
| `fallback_state` | Fallback visibility |
| `trace_id` / `run_id` | Correlation |
| `raw_evidence_ref` | Opaque evidence handle (no secrets / restricted body) |
| `durable_output_present` / `log_success_claimed` | Join proof |

## Freshness statuses

`NO_DATA` · `GAP` · `STALE` · `PARTIAL` · `INELIGIBLE` · `ERROR` · `FRESH`

A gap or missing durable output must **never** be relabeled `FRESH`.

## Join rule

Job logs, durable output, and Command Center status share one `run_id` /
correlation id. A successful log **without** durable output is **not** success
(`LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT` → `ERROR`).

## Eligibility gates (fail closed)

Missing provenance, stale data, failed/unknown quality, unknown entitlement,
wrong run id, wrong source hash, silent fallback, clock regression, future
skew, or schema-version mismatch → `INELIGIBLE` with explicit reasons.

Display consumers may accept `DISPLAY_ONLY` when a `degraded_label` is present.
Proposal and agent consumers accept `ELIGIBLE` only.

## Module map

| Path | Role |
|------|------|
| `scripts/lib/research_observation/contract.py` | Envelope |
| `scripts/lib/research_observation/statuses.py` | Vocabularies |
| `scripts/lib/research_observation/eligibility.py` | Policy |
| `scripts/lib/research_observation/join.py` | Log↔artifact↔CC join |
| `scripts/lib/research_observation/adapters.py` | Wrap existing products |
| `scripts/lib/research_observation/consumer_gate.py` | Downstream gate |
| `fixtures/research_observation/` | Fixture controls only |
| `tests/test_research_observation_*.py` / `test_research_eligibility_policy.py` / `test_research_consumer_gate.py` | Mandatory cases |

## Non-goals

- No live trading behavior change.
- No model order placement authority.
- No edits to paths leased by backend/frontend/runtime lanes.
- No production store rewrites.
