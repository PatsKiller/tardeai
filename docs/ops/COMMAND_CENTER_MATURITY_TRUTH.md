# Command Center maturity truth (live runtime)

**Lane T** replaces the control-plane maturity *served body* with live evidence.

## What changed

- `GET /api/v3/control-plane/maturity` is now a **computed** domain.
- Generator: `scripts/lib/campaign_maturity_truth.py` → `CampaignMaturityTruth@v1`.
- Envelope `freshness` / `evidence_class`: `LIVE_RUNTIME` (not `CURRENT_SMOKE`).
- Historical file `data/runtime/maturity_score_latest.json` (generated_at **2026-06-28**)  
  remains on disk as **SUPERSEDED_NOT_DELETED** and is no longer the served collection body.

## Dimension evidence classes

Each item carries: `evidence_class`, `count`, `explicit_zero`, `served_sha` (envelope),  
`evidence_timestamp`, `source_store`, `staleness_hours`, `proof_refs`, `limiting_factor`,  
`next_proof`.

Classes used: implemented, configured, scheduled, attempted, consumed, delivered,  
settled, outcome_observed, behavior_changing, fixture, controlled_canary, organic, absent.

## Hard rules encoded

- CANARY **configuration** ≠ gateway **delivery ownership** (separate dimensions + note).
- Controlled canary wakes ≠ organic.
- `behavior_changing` is an **explicit zero** under MBI_BEHAVIOR=0.
- No certification score (`overall_is_not_a_certification=true`, `computes_maturity=false`).
