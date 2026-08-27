# Closing the CIO learning loop — implementation record

**Date:** 2026-08-27
**Releases:** `5b9738fd` → `2cf31a8e`, each promoted and verified live
**Companion:** `PERSISTENCE_WIRING_2026-08-27.md` (identity, lineage, memory, evidence gate)

The pipeline's lower half was four segments that each worked internally and never handed off. This records closing them, and — more importantly — the two places where the obvious fix would have written false data into the learning loop.

Every figure was measured against live production state.

---

## The chain, resolving for the first time

```
LESSON      e38856b4febcafbf8b25 [PROVISIONAL]  SCHD / TRIM
  -> OUTCOME cc06af712aff1dc88af18b7e | decision dec_c1cec3c99d978b9d | 1_session
     realized  SCHD 35.03 -> 35.14 (+0.314%)
     sources   ticker_prices:SCHD:2026-08-26, ticker_prices:SCHD:2026-08-27
  -> CHECKPOINT ea1d37bb6589425b9c20 | RESOLVED
     due_at 2026-08-27T01:53:28Z | resolved_at 2026-08-27T20:14:04Z
```

Before today every link in that chain was absent.

---

## What was broken

| break | state before | now |
|---|---|---|
| research arc ↔ CIO arc | envelope overlap **0**; neither arc could complete | each arc finishes its own record (#560) |
| checkpoint → outcome | **183 checkpoints, 50 overdue, 0 ever resolved** | resolver shipped (#561) |
| outcome → lesson | **1,617 lessons, 0 referencing an outcome** | linked (#563) |
| causal trigger | `HERMES_RESOLVED` **0 occurrences** | not a missing wire — see below |

### The trigger was never missing

`HERMES_CHALLENGE_RESOLVED → HERMES_RESOLVED` is fully wired in `cio_wake_dispatcher._map_wake_to_run_trigger`, and `cio_hermes_challenge_worker` enqueues it. It never fired because it only fires for a run in `WAITING_FOR_HERMES`, and:

```
every run ever recorded:  QUEUED -> HEALTH_CHECK -> BLOCKED
```

No run had ever advanced past the evidence gate, so none reached that state. The trigger was a **symptom** of the gate, not an independent gap. It becomes reachable only now that runs can pass.

---

## The two traps

Both would have produced confident, wrong data that is indistinguishable from real data downstream. Both were found by running the code against production and reading the output, not by reasoning about it.

### 1. A cash decision priced against a company called CASH

The first working resolver processed **43 of 50** due checkpoints and looked like a clean success. **37 of those 43 were `HOLD_CASH` decisions about the portfolio's cash sleeve — being priced against `CASH`, the ticker.**

`CASH` is Pathward Financial, CUSIP `59100U108`, 268 rows in `ticker_prices`, and it resolves in the identity registry as a **CONFIRMED security**. Neither the symbol string nor the identity spine can tell the cash sleeve from the equity. **Only the recommendation can.**

`price_resolvable()` now refuses a checkpoint whose recommendation is a cash action, whose `entity_type` is a portfolio type, or whose subject is not a ticker-shaped registered security — each with its reason recorded.

```
due                    50
resolved                6   real securities (SCHD/TRIM)
not_price_resolvable   44   38 hold_cash · 5 no_security_subject
                             1 entity_type_portfolio_cash
```

**Six is the honest number. Forty-three was not.**

`NOT_PRICE_RESOLVABLE` is a distinct status from `OUTCOME_PENDING_DATA`: no future run will make a cash decision price-comparable, so leaving it "pending" would churn it forever.

### 2. One event counted as five samples

`lesson_candidate_v2` decides status from `len(supporting_outcome_ids)`, and `MIN_LESSON_SAMPLES` is **5**.

The first five outcomes were five distinct `decision_id`s that were **all SCHD / TRIM / decided 2026-08-26 / 1_session / +0.314%** — one event measured five times. Passing them all would have hit the threshold exactly and stamped the lesson **SUPPORTED** at n=5, where the effective n is **1**.

The epistemics function was **not changed**. It is fed correct input instead: observations group by `(subject, recommendation, decision date, horizon)`, each group contributes **one** representative, and the uncounted siblings are kept as `correlated_outcome_ids` with `independent_samples` and `total_observations` both recorded.

Result: `PROVISIONAL`, *"independent samples 1 of 5 observations"*.

**Direction is read relative to the recommendation.** A TRIM followed by a price *rise* is the decision looking wrong, not a favourable move — the first version described it as favourable, which inverts the lesson. Recommendations with no implied direction (`HOLD`, `WAIT`, `HOLD_CASH`) produce **no lesson** rather than a guess.

---

## Two snapshot defects found on the way

**The fallback was lying about causes.** A blanket pass overwrote the registry loop's `gap_reason`, so a collector that raised `TypeError` reported `not_yet_collected_by_snapshot_builder` — pointing at the wrong thing. Checking only `gap_reason` was still not enough, because `add_error` records `error_detail`; the fallback now skips **any** recorded domain.

**That revealed a systemic one.** `cio_portfolio` imports `DomainEvidence` from `lib.cio_domain_evidence`; the snapshot imports it from `scripts.lib.cio_domain_evidence`. Both succeed and they are **two distinct class objects**, so `isinstance` was False for every collector returning one — **8 of 18** — each dying with *"Unexpected collector return type: DomainEvidence"* and then being relabelled "not yet collected". Now duck-typed on `quality_state`.

```
usable domains  14 -> 19
cash_buying_power PARTIAL · income PARTIAL · retirement AVAILABLE · reentry AVAILABLE
```

All four were previously dead.

---

## Evidence gate: from 54/55 blocked to four purposes passing

```
SCHEDULED_CIO_BRIEF          PASS
WATCH_OR_CATALYST_REVIEW     PASS
OPERATOR_REQUEST             PASS
PORTFOLIO_ALLOCATION_REVIEW  BLOCK  holdings_detail (STALE)
RISK_OR_STOP_EVENT           BLOCK  defense_stops_protection
```

The gate itself is unchanged throughout, and tests assert that. Every fix in this record is to a **producer**.

---

## Schedule: the brain was market-hours-only

The CIO wake dispatcher ran `*/5 9-16 * * 1-5`. Ingestion largely does not stop — 47 research and catalyst jobs already run 24/7 — but the component that turns evidence into a run did. A catalyst landing Thursday 20:00, or a filing on Saturday, created a wake that sat unprocessed until Monday morning.

Now `*/5 * * * *`. Still session-relative, and defensibly so: the catalyst premarket/swing bands, the high-frequency news bridge, and the premarket/EOD research cycles.

---

## What remains

1. **`holdings_detail` is STALE and `positions_built_at` reads 2026-07-17.** Repricing refreshes prices, not the position list; `_canonical_reconcile` is 12 days behind. This is a real data problem, not wiring.
2. **`defense_stops_protection`** blocks `RISK_OR_STOP_EVENT`.
3. **`reentry` has no zero-argument collector** — the last member of the `_EXTERNAL_ADAPTER_FUNCTIONS` defect family, named in a guard test rather than silently skipped.
4. **The evidence base is one PROVISIONAL lesson from one event.** Real learning needs runs completing over days. The passing gate and the 24/7 dispatcher are what make that possible; they do not substitute for it.
5. **Most CIO decisions are portfolio-level, not security-level.** 44 of 50 due checkpoints were not price-resolvable. The checkpoint schema only knows how to score securities, so the learning loop currently cannot evaluate the majority of what the CIO actually decides. That is a design question, not a bug.

---

## The pattern, again

Every capability here already existed. `process_due_checkpoint`, `persist_observation`, `lesson_candidate_v2`, `finalize_notification_required`, the `HERMES_RESOLVED` trigger — all written, tested, and never called. The work was wiring joints and refusing to let the obvious wiring write false data.
