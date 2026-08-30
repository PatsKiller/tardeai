# P1-WS1 — Failure-point inventory (per stage)

**Date:** 2026-08-30  
**Pin:** `852ecd47`  
**Authority:** READ_ONLY_ADVISORY · MBI=0  
**Companion:** `P1_WS1_AS_BUILT_ARCHITECTURE_2026-08-30.md`

Failure classes used below:
- **Crash** — exception / unit fail / hard stop
- **Silent skip** — continues without recording the miss
- **Dual-write** — two stores/schemas for one concept
- **Id fork** — same real-world event keyed differently so joins fail
- **Stale success** — stage reports OK on outdated inputs
- **Authority bypass** — parallel path ignores CIO gate

---

## Event intake

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Crash | `cio_reactive_cycle` / detector exception | unit journal; reactive timer retries | No end-to-end drop census (P1-WS2) |
| Silent skip | Backlog policy expires/cancels PENDING wakes (`cio_wake_backlog_policy`) | wake job status fields | Easy to misread as “no events” |
| Id fork | Goal wakes (`trigger_type=SYSTEM`) vs security research digests | lineage health `identity_fork_suspected` | Documented 2026-08-27; still structural |
| Dual-write | Legacy orchestrator alerts vs CIO material events | separate logs | G-AUTH-01 adjacent |

## Operator interface

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Crash | Telegram bot / converse core | `tradeai-cio-telegram` unit | Restart mid-turn not battery-tested (P1-WS3) |
| Silent skip | S0 mint with empty `symbols` (historical) | S0 module now extracts symbols | Regression risk if bypass converse_core |
| Stale success | CC home serves last product while books drift | product `as_of` | Operator may treat home as real-time |
| Dual-write | Operator turns jsonl vs plan symbols | — | Attach/rehydrate miss → “desk only knows SCHD” class bugs |

## Identity

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Id fork | Arc A `wf_<digest>` vs arc B run UUID without shared `event_id` | `cio_lineage_completion_report` | Partially mitigated by `cio_canonical_identity`; completions 54% not 100% |
| Silent skip | `subject_guid` LOOKUP_FAILED collapsed into UNRESOLVED (historical) | `identity_lookup` enum in `cio_subject_guid` | Outage must not look like “no entity” |
| Crash | Registry unreadable | LOOKUP_FAILED | G-ID-01 |
| Dual-write | Ticker-as-security-GUID temptation | code refuses mint from ticker | Continuous gate needed |

## Materiality

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Silent skip | First material scan baseline does not treat all holdings as POSITION_OPENED | module docstring | Correct by design; can look like “missed opens” |
| Stale success | Freshness gate not consulted by parallel rebalancer | rebalancer path | G-AUTH-01 |
| Crash | `--live` material scan with office load failure | unit fail | Timer will retry |
| Dual-write | Material decisions vs portfolio_alerts drift alerts | separate channels | Operator hears two authorities |

## Graph impact

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Silent skip | Graph not invoked → no neighbour risk on product | absence | Stage optional; diagram overstates |
| Stale success | `catalyst_graph_latest.json` old while pipeline “green” | mtime | Not wired as gate |
| Crash | Sector map missing for symbol | returns empty neighbours | Low |

## Research

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Silent skip | Gate `skip` / `reuse` / `corpus_hit` without paid hop | ResearchNeedDecision | Correct; still a “no new research” miss for operator expectation |
| Crash | Hermes drain failure | hermes worker journal | Bounded `--max 2` |
| Dual-write | Free-first circulation vs Hermes curation vs IR hashes | multiple stores | Contamination risk → G-SPEC / research hygiene |
| Id fork | research_id day collapse vs residual hop budget | residual_web + gate | Wave 3D; not proven every research_id |
| Stale success | Evidence HEALTH_CHECK blocks synthesis while research arc completes | lineage first_open_stage | Seen historically; keeps loop open |

## Specialists

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Dual-write | `SpecialistArtifact@v1-lite` (2 rows) **and** `SpecialistArtifact@v2` informal jsonl (36) **and** handoff advisories | three shapes | G-SPEC-01 |
| Silent skip | `should_wait` then never resumed | run store WAITING_FOR_SPECIALISTS | Needs N=100 sample (P5) |
| Id fork | artifact without `workflow_id` (live v1-lite rows) | store inspection | Cannot join council/product cleanly |
| Crash | Unknown provider raises in `build()` | tests | Good fail-closed for ledger |

## Council

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Dual-write | Wave3B join module vs older on-disk committee-shaped `cio_council_synthesis.json` | schema same literal, keys differ | Shape drift / stale file (Aug 26) |
| Silent skip | `NO_VALID_ARTIFACTS` state | council block | Product may render empty thesis |
| Crash | Model call accidentally introduced | tests assert no provider client | Keep regression |
| Authority bypass | InvestmentDecision not consumed by daily rebalancer | grep / slice 14 | G-AUTH-01 |

## Product

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Stale success | Persist refused for UNAVAILABLE but UI may show prior | `persist_operator_product_if_available` | Last-good honesty |
| Dual-write | `cio.operator_product.*` vs `cio.product.*` (brief) | registry | Two “product” surfaces |
| Silent skip | Book section missing → availability reason | product_availability | |
| Merge failure | Surface A/B accidentally combined | `merged` flag + tests | G-DUAL-01 |

## Notify

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Silent skip | SUPPRESSED / COMMAND_CENTER_ONLY under quiet defaults | notification metrics | Alert miss vs fatigue (G-NOTIFY-01) |
| Crash | Delivery worker exception | timer | |
| Dual-write | CIO delivery path vs `portfolio_alerts` Telegram from orchestrator | two producers historically | Authority + fatigue |
| Missing store | `notifications.outbox` absent | registry resolve | Replay/outbox semantics incomplete |
| Interdict drift | Host INTERDICT left as found; policy reads env | delivery_mode | Do not “fix” by enabling notify in diligence PRs |

## Outcome

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Id fork | Checkpoint on arc A without notification settle on same envelope | completion 54% | G-LOOP-01 |
| Silent skip | Unbound checkpoint → lesson_bind skip (no lesson_id) | lesson_bind rules | By design; loop stays open |
| Missing store | `cio.lesson_binds` | registry | |
| Crash | Checkpoint enrich failure | lineage writer | |

## Cognition

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Crash / refuse | `apply_cognition` with sizing / delta fields | raises MBI_BEHAVIOR=0 | Good |
| Silent skip | Lesson that moves no cognition field → failed persist | explicit error | Prevents fake “applied” |
| Missing store | `learning.weekly` | registry | Diagram LESSON/HYPOTHESIS weak |
| Stale success | Reflection candidates without IR bind | nightly reflection | |

## Persistence

| Mode | Mechanism | Detection today | Gap / note |
|------|-----------|-----------------|------------|
| Crash | Disk full / lock | atomic_json_store / jsonl locks | |
| Dual-write | Overlay vs persistent-state confusion | GOOD_PERSISTENT_ROOT / production_state_root | Deploy pin vs state root must stay paired |
| Silent skip | Registry lists store that does not exist (`cio.decisions`, `learning.weekly`, `notifications.outbox`, `cio.lesson_binds`) | resolve_store exists=false | Orphan/registry work → P9 |
| Corruption | Price outliers in history | Aug 27 C3 / G-PRICE-01 | Quarantine ≠ DELETE |

---

## Cross-stage “loop open” summary

Most dangerous combination observed historically and still partially true:

1. **Id fork** (research workflow vs CIO run) +  
2. **Causal unwiring** (goal wakes ≠ security events) +  
3. **Evidence block** before synthesis +  
4. **Authority bypass** on the daily rebalance recommendation surface  

Lineage completion **54%** is improvement over 0%, not a closed loop. Do not advertise 99.99% until P1-WS2 baseline + P9 path exist.
