# R16.1 — Live institutional learning closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Canary:** unset · **Cash:** unconfirmed / `POLICY_GAP`  
**R17:** not started

## Pins (do not confuse)

| | SHA |
|---|---|
| PR #510 (docs-only R15.2) | `ce105e65cbaca23f839f95a7540f93f8033745ae` |
| PR #511 merge | `55520666b4a742b9ed893c3231b414d089312363` |
| repository_head after #511 | `55520666b4a742b9ed893c3231b414d089312363` |
| runtime_source (CURRENT) | `55520666b4a742b9ed893c3231b414d089312363` |
| exact_runtime_release | `55520666-main-exact-phase2-20260825-125124` |
| rollback | `d72ecdd1-main-exact-phase2-20260825-120222` |

`SOURCE_COMMIT == BUILD_SHA == GIT_SHA == loaded_pin`. Pin match true after promote and after restart.

Unlike #510, #511 contained runtime code. Exact-main prepare/promote was required before live maturity credit. Feature branch was **not** deployed.

## What moved from source to live

R16 contracts now run on CURRENT:

- Learning cockpit `/api/v3/cio/brain/learning-cockpit` (and brain snapshot)
- `OutcomeObservation@v1` append-only store at `data/cio/outcome_observations.jsonl`
- Observational checkpoints at `data/cio/outcome_checkpoints.jsonl`
- Promotion ceiling `REVIEW_READY`; GUI cannot self-promote
- Identity-safe subject: SCHD TRIM joined to canonical TRS `security_guid`; cash/re-entry rows left unresolved; **no GUID minted from ticker text**

## Natural proof on the same pin (`55520666`)

**Material scan** (`tradeai-cio-material-scan.timer`, not `systemctl start`):

- 16:58:08Z first post-promote fire; 17:08:11Z second fire
- receipt path is the `55520666` release on both
- `intelligence_fabric` present, `paid_dispatch=0`, `llm_calls=0`
- HOLD_CASH + WAIT suppressed as `unchanged_replay`; TRIM SCHD DIGEST then SUPPRESSED (`DATA_CONFLICT` / unchanged)
- `policy_status=POLICY_GAP`; canary still false
- R16 did not change materiality, free-first zero-cost invariant, or notification safety
- Observational checkpoints: 18 unique (second scan TRIM duplicates rejected; new cash/wait IDs scheduled)

**Free-first** (`tradeai-free-first-circulation.timer`, not started by hand):

- `as_of=2026-08-25T17:27:06Z` on `55520666`
- 120 names: Hermes 117, RAG 2, structured 1, SearXNG 0
- `fresh_no_change=120`, `paid_dispatch_entered=0`
- Zero-cost invariant unchanged by R16

**Restart:** `portfolio-server` restarted; health ok; pin match; checkpoints + observations survived.

## Historical validation (not longitudinal)

- 38 inventory rows: **PARTIAL 38 / FULLY_TRACEABLE 0 / UNRESOLVED 0**
- 25 `OUTCOME_RECORDED` events linked by `cio_action_id`; original decision hashes unchanged after outcome append
- 11 canonical identity joins (including live SCHD TRIM); 17 TRS symbols still have no `security_guid`
- `NATURAL_LONGITUDINAL=0`. Future due_at values were scheduled, not fabricated as elapsed.

## Learning loop (deployed, not auto-promoting)

- Lessons: 1 PROVISIONAL (one free-first cycle ≠ methodology), 1 SUPPORTED (bounded, counterexample-searched)
- Hypotheses: 1 preregistered; frozen primary metric hash unchanged after results
- Shadow experiments: positive, negative, inconclusive — no operator side effect
- Unauthorized promotion / registry mutation / feedback injection: DENIED
- Registry hashes unchanged: model `3f76b564…` process `1a699bbc…`

## Tests

**1939 passed, 0 failed** (R11–R16 + brain + envelope + notification + identity).  
Lookahead: 75 goldens + 8 adversarial dated-future cases, **0 leaks**.  
Named-key gap (not a dated leak): `future_research` / `future_specialist_artifact` as top-level keys are not in `FORBIDDEN_FUTURE_KEYS`; evidence timestamps are rejected.

## Maturity

**86 → 88.** **89 not awarded. 90 not awarded.**

87 is the deploy/smoke/linkage/lookahead gate. 88 is the integrated learning loop. 89 still needs auto-schedule on new material decisions, cockpit binding to jsonl counts, and naturally elapsed due observations. 90 remains reserved for real longitudinal improvement.

Do not treat historical replay as 90.

## Safety

Broker / orders / stops / risk / 2FA / production SQL / Telegram canary / cash policy: unchanged.  
PR #505 remains open and separate. Default 20–25% cash band is still **not** operator policy.
