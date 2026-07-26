# Watch quality projection v2 — source-unit correction

Date: 2026-07-25

Status: **DRAFT / UNDEPLOYED / READ-ONLY EVIDENCE ONLY**

## Evidence received

The exact-ref validator at `11d69ea08155147afccb9a86649dca2b1a61c020` completed with:

- 61 focused Python tests passing;
- TypeScript passing;
- production Vite build passing;
- `watch-quality-admission-v1` present;
- `watch-quality-projection-v1` present;
- `research-due-diligence-v1` present for PROPOSAL, DEFENSE, SECTOR, INDUSTRY and WATCH;
- no live dist change, database write, packet rebuild, model/provider call, paid-lane call, schedule change, service restart or external action;
- `PASS_WATCH_QUALITY_GOVERNANCE_VALIDATION`.

The forced-read-only top-200 v1 projection reported:

- 20 projected `ADMITTED`;
- 81 projected `RESEARCH_ONLY`;
- 99 projected `QUARANTINED`;
- 20 projected new-entry allowed;
- 2 projected management-only;
- all 200 existing packets still `UNASSESSED` under the new persisted policy.

These counts are preserved as diagnostic evidence but are **not rollout-authoritative**.

## Why v1 is superseded

The v1 projection applied one conversion to two fields with different source contracts:

1. the legacy Finviz enrichment cache uses the historical key `market_cap_b`, but the stored number is already USD millions; the canonical packet producer documents that `67674.87` means approximately `$67.7B`;
2. `valuation_supplement_cache.json`, introduced by PR #170, uses `market_cap_b` literally as USD billions.

Projection v1 multiplied either source by 1,000. That made many Finviz micro/small-cap issuers appear as companies worth hundreds of billions or trillions and weakened the market-cap quality gate.

The v1 output also exposed physically implausible cached percentage values, including multi-thousand-percent margins. Those values must not silently determine pre-profit classification, deterministic thesis state or P/S admission treatment.

## Projection v2 contract

`scripts/watch_quality_projection_v2.py` supersedes v1 for rollout evidence and keeps the same forced-read-only census implementation while replacing evidence assembly.

It:

- treats Finviz `market_cap_b` as mislabeled USD millions;
- treats supplement `market_cap_b` as true USD billions and converts it to millions;
- prefers the current Watch database observation for price, float and RVOL over stale packet copies;
- preserves packet OHLC-derived ATR and absolute SMA evidence where available;
- applies fail-closed sanity bands without clipping or repairing values;
- rejects market-cap values that materially conflict with `price × shares outstanding`;
- records field-level source, rejected field and rejection reason;
- withholds rejected evidence so missing/conflicted evidence becomes `RESEARCH_ONLY` rather than an invented pass;
- performs no cache, packet, database, provider, model, schedule, service or external mutation.

Contract: `watch-quality-projection-v2`.

Projection v1 status: `SUPERSEDED_SOURCE_UNIT_CONFLICT`.

## Required next evidence

1. Run the exact-ref validator at the latest branch head and require:
   - `quality_projection_contract|watch-quality-projection-v2`;
   - `projection_v1_status|SUPERSEDED_SOURCE_UNIT_CONFLICT`;
   - `final_status|PASS_WATCH_QUALITY_GOVERNANCE_VALIDATION`.
2. Run a fresh forced-read-only top-200 census using `watch_quality_projection_v2.py`.
3. Preserve and review:
   - projected admission counts;
   - new-entry and management-only counts;
   - field coverage;
   - rejected-field counts and representative provenance;
   - top policy reasons;
   - admitted-symbol list.
4. Do not rebuild packets, deploy the UI or modify a scheduler until the v2 result is reviewed.

## Authority boundary

No broker, order, trade, approval or 2FA action is authorized. No model lane, OAuth lane, paid lane, OpenClaw service, Hermes service, production database write, packet rebuild, deployment or schedule change is authorized by this evidence step.
