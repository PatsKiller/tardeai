# Is the CIO pipeline diagram the true state? — measured verification

**Date:** 2026-08-27
**Verified against:** live release `395db177` (= `origin/main`), live stores under `GOOD_PERSISTENT_ROOT`
**Question asked:** does the operator's end-to-end diagram describe what actually runs?
**Answer:** accurate for the contracts and the upper pipeline; **not** accurate for the lower half. The loop it draws does not close, and has never closed.

Companion: [`EXTERNAL_DIAGRAM_TYPE_MAPPING.md`](../architecture/cio/EXTERNAL_DIAGRAM_TYPE_MAPPING.md) mapped the diagram's *names* to code (audit finding L7). This doc measures whether the *flow* executes. The mapping could not answer that, because nobody had measured completion.

---

## Verified real

| Diagram element | Evidence |
|---|---|
| `CanonicalStoreRegistry@v1` | exact literal; 29 stores; present in the hub since M10 closed 2026-08-27 |
| `CIOOperatorProduct@v1` | exact literal, 5 files |
| `OutcomeCheckpoint@v1` | exact literal, 4 files (added 2026-08-26) |
| `GOOD_PERSISTENT_ROOT` | real, and is the root the live server reads |
| **`MBI remains 0`** | true and enforced — in env *and* stamped on every lineage record |
| `READ_ONLY_ADVISORY` | stamped on every record |
| Notification policy | `IMMEDIATE` / `DIGEST` / `COMMAND_CENTER_ONLY` / `SUPPRESSED` all exist |
| Materiality · Research gap · Persistent cognition · Free-first | real code (58 / 62 / 9 files, plus `free_first_refresh.py`) |

Research, lineage, theses and product stores were all written **within the hour** at verification time. The upper pipeline genuinely runs.

## Not true as drawn

| Diagram element | Reality |
|---|---|
| `CIOCouncilSynthesis@v1` | **0 files.** Real equivalent is `InvestmentDecision@v1`; its store `cio.decisions` **does not exist on disk** |
| `SpecialistArtifact@v2` | **0 files.** Informal dict convention only |
| `CANONICAL ENTITY / IDENTITY` | **0 files** by that name; `identity.registry` store **missing**; `entity_type` is `UNRESOLVED` on every record |
| `LESSON / HYPOTHESIS` | `learning.weekly` store **missing** |
| `GRAPH IMPACT` | 1 file — not a stage in practice |
| `notifications.outbox` | **missing** |

---

## The loop does not close

Measured over the live lineage, folded to the latest envelope per workflow:

```
workflows                94
complete_to_checkpoint   0   (0.0%)
with checkpoint_id       29
arcs                     {'research_checkpoint': 29, 'cio_notification': 29}
first open stage         {'research': 65, 'cio': 29}
```

Everything from `OutcomeCheckpoint@v1` downward — OUTCOME → LESSON/HYPOTHESIS → REVIEW_READY, and the feedback edge into the next cycle — has **never executed**. Consistent with `cio.outcomes` ~19h stale, `cio.feedback` ~12 days stale, and `learning.weekly` absent.

### Root cause: identity fragmentation, not a failing stage

Two arcs write lineage under **two different identifier systems** and never join:

| | Arc A | Arc B |
|---|---|---|
| stages completed | research · specialist · checkpoint | cio · notification |
| `workflow_id` | `wf_<digest>` — content digest | the CIO **run UUID**, passed straight through |
| `subject_id` | real tickers (17 distinct) | `None` on all 29 |
| ids present | research/specialist/checkpoint | generation/notification |
| **`subject_id` overlap between arcs** | **0** | |

`is_complete_to_checkpoint` requires, on **one** envelope: `checkpoint == COMPLETED`, a non-blank `checkpoint_id`, **and** a settled notification stage. Arc A has the first two. Arc B has the third. `event_id` and `context_id` — the fields that would bridge them — are `None` in both.

**So the predicate is not merely false; it is structurally unsatisfiable.** No retry, backfill, or stage fix can produce a completion while the halves carry different ids.

This is exactly the gap the diagram's own `CANONICAL ENTITY / IDENTITY` node describes — and that node has no implementation and no store. The missing identity resolution *is* why the loop is open.

### Why nothing noticed

The stores were fresh, the logs were clean, and every stage reported success for its own arc. "The pipeline is running" and "the pipeline completes" were never distinguished, because `is_complete_to_checkpoint` was computed on every write and **read by nothing**. Same family as the incident in [`HEALTH_AGENT_MATURITY_PLAN_2026-08-27.md`](../ops/HEALTH_AGENT_MATURITY_PLAN_2026-08-27.md): a component reporting success is not evidence that it did anything.

---

## What shipped with this doc

`scripts/lib/cio_lineage_health.py` + `scripts/cio_lineage_completion_report.py` — read-only completion metrics, folded per workflow, with an explicit `identity_fork_suspected` signal that distinguishes *this* fault from an ordinary stage failure.

```bash
python scripts/cio_lineage_completion_report.py            # human summary
python scripts/cio_lineage_completion_report.py --json     # machine readable
python scripts/cio_lineage_completion_report.py --fail-on-finding   # cron/CI gate
```

It writes nothing and mints no identity. **Diagnosing a fork is not authority to merge one.**

This is the first concrete instance of the Health Agent plan's Phase 1 (consistency invariants) and is the natural thing to wire in there.

## Update — identity node implemented (option 2 chosen)

`scripts/lib/cio_canonical_identity.py` implements the diagram's `CANONICAL ENTITY / IDENTITY` node. Both arcs now stamp a canonical `event_id`, derived rather than minted-and-stored, so each computes the same value independently with no shared state, no lookup race and no ordering requirement:

```
arc A  {"symbol": "SCHD",     "occurred_at": "…T15:05:00Z"}  → evt_51966048b852f76be4d9
arc B  {"subject_id": "schd", "created_at":  "…T15:52:41Z"}  → evt_51966048b852f76be4d9
```

Proven end-to-end: when both arcs carry one event, the envelope accumulates all five stages and `complete_to_checkpoint` reads **1/1 (100%)**. The loop closes.

Design points worth keeping:

- **`None`, never a shared placeholder,** for an unresolvable entity. A common "unknown" id would join every unresolved event to every other one and manufacture completions that never happened.
- **A missing timestamp does not mean "key on now."** That would rehash the same event on every call and break the join silently; it buckets to a stable sentinel instead.
- **A ticker is never promoted to a `security_guid`**, matching `identity_from_payload`'s existing guarantee.
- **`identity_fields()` never sets `workflow_id`.** Rewriting it changes how every downstream consumer keys lineage, so that stays an explicit caller decision. Stamping is purely additive and safe to merge into a live envelope.

### But identity alone does not close the production loop

Two further blockers, both found while implementing this, and neither fixable by identity:

**1. The two arcs are about genuinely different entities.** Production CIO runs are not security events — 42 of 49 carry `trigger_type: SYSTEM` with `trigger_ref: wake_goal_goal_<id>_<hour>`. They are portfolio-level goal wakes. Research is security-driven. The trigger types that *would* link them, `HERMES_RESOLVED` and `SPECIALIST_COMPLETION`, exist in `VALID_TRIGGER_TYPES` and have **zero occurrences**. The arcs are not merely mis-keyed, they are causally unwired.

So `_run_identity` types a goal wake as `entity_type: GOAL` rather than pretending it is a security. Two arcs about different entities then correctly *fail* to join, instead of colliding on a placeholder and reporting a completion that did not happen.

**2. Nearly every CIO run is evidence-blocked before synthesis.** 46 of 49 runs block at `HEALTH_CHECK`:

```
EVIDENCE_GAP: missing_required: health_data_quality, watch_intelligence, operator_profile
              stale_required:   portfolio
```

The gate is fail-closed and behaving correctly — the required domains genuinely are unavailable. But a run that blocks at HEALTH_CHECK never reaches synthesis, so arc B produces no checkpoint regardless of identity.

**Ordering follows from that:** identity (done) → wire the causal trigger → resolve the evidence gaps. Doing them in any other order produces no measurable change in completion.

## What is still open — needs an operator decision

Closing the loop requires deciding **which identity wins**, and that changes how every downstream consumer keys lineage. Two coherent options:

1. **CIO run adopts the research workflow id.** `cio_run_worker.py` passes `run_id` as `workflow_id` (`record_cio_generation(str(run_id), ...)`); it would instead carry the `wf_<digest>` of the research that triggered it. Correct-shaped — one real-world event, one workflow — but requires the run to know its originating research request, which it does not today.
2. **Mint an `event_id` upstream and join on it.** Implement the diagram's `CANONICAL ENTITY / IDENTITY` node for real: resolve the entity once, mint one id, thread it through both arcs. Larger, and the option the diagram actually describes.

Option 2 is the diagram's own design. Option 1 is the smaller step and may be a viable staging point. **Neither should be applied unilaterally** — this is a live advisory pipeline, and picking an identity scheme silently is how you get two more years of unjoinable history.

### A methodology note worth keeping

The first pass at this analysis counted **raw lineage rows** rather than folding to the latest envelope per workflow, which inflated the population 315 → 94 and mixed early snapshots with final state. A second error read values through `str()` in the display path and misreported the on-disk types as stringified. Both were wrong and both looked convincing. `latest_envelopes()` exists so the fold is done once, correctly, in one place.
