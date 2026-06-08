# Hermes Source — Core Activation (operator-approved, 2026-06-08)

Operator approved hermes for CORE — the operator-gated promotion the vetting ladder reserved.

## What changed
- `research_sources` (hermes): **active=false → true**, credibility_score 0.5 → 0.85,
  notes += {operator_core_approved:true, core_approved_at, core_approved_by:operator}.
- `source_maturity.py`: now honors `operator_core_approved` in research_sources.notes → pins tier=**core**
  (override; auto-core formula needs score≥70, hermes is 62.8 — operator override is the intended gate).
- Effect: tiers now core:1 / trusted:3 / probationary:6 / candidate:135 / demoted:3.
- Catalyst classifier: hermes-sourced catalysts get the **core confidence multiplier (×1.15)** — verified
  confidence 0.66 (trusted) → 0.69 (core). hermes removed from the operator-action queue.

## Why hermes
Top source by precision: go-rate 0.4474 (34/76 surfaced symbols became GO/WAIT) — far above any feed; it's
the internal research lane, not a firehose. Activation makes it a vetted core research source.

## Reversibility / safety
Reversible: set active=false + remove operator_core_approved in research_sources.notes, re-run source_maturity.
Advisory only — core status raises catalyst confidence weighting; it does NOT change GO/WAIT or strategy
scoring. No trades/holdings touched.
