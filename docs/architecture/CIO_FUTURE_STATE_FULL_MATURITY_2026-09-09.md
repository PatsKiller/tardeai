Status:      ACTIVE
as_of:       2026-09-09
Measured at: not measured — target spec, not runtime
Canonical repo path: docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY_2026-09-09.md
Authority:   full-maturity target (judgment, commitment, scoring, self-repair) — refreshed to today, bar unchanged
Supersedes:  docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md (delta + build-order status refreshed)
Superseded-by: docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY_2026-09-09-ceiling.md (live-ceiling build-order status)
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-09-09.md
             docs/architecture/CIO_ASIS_VS_FUTURE_GAP_2026-09-09.md
             docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md (2026-08-30 target, historical)
             AGENTS.md §13.4 §15 §19

# CIO Agent — FULL MATURITY TARGET (2026-09-09)

What "self-thinking, self-learning, self-fixing" means concretely. **The maturity bar is
unchanged** from the 2026-08-30 target; this dated refresh restates it and annotates what has
moved underneath the bar since then. The four additions are the same; the near-term build
priority is sharpened by what the 09-01/02 audits and the 09-08/09 canary run proved.

```
THE FOUR ADDITIONS (unchanged)

  ①  JUDGMENT        the agent forms a view of its own, gated and costed
  ②  COMMITMENT      it stakes that view as a falsifiable claim, with a deadline
  ③  SCORING         outcomes settle the claim and move its priors
  ④  SELF-REPAIR     it detects and fixes its own broken plumbing, and reports what it can't

Everything below marked ◆ is new. Everything else exists today in some form.
```

---

## Delta vs the 2026-08-30 target (what moved underneath, without lowering the bar)

| target step | 08-30 | 09-09 | consequence for the build order |
|---|---|---|---|
| 1. every wake loads the record | UNWIRED | **M5_CANDIDATE** | step 1 is now *mostly done* — finish the durability proof |
| 2. outcomes resolve | DARK | **PARTIAL** (158 RESOLVED; hourly settler) | step 2 has a working spine — next: bind to commitments |
| 3. judgment layer | DARK | DARK (phantom receipt fixed) | still the first genuine cost decision |
| 4. commitments + falsifiers | absent | specified, no producer | unchanged, net-new |
| 5. scoring moves priors | absent | absent (n=1 outcome lesson) | unchanged, net-new |
| 6. self-repair | absent | not FUTURE-shaped | unchanged, net-new |

Plumbing that moved: pre-claim record consult + `decide_after_load` + cognition persist on the
scheduled wake; formal `SpecialistArtifact` type; hourly `resolve_due_checkpoints --apply`;
`delivery_owner` stamp (PR #926). None of these *is* the cortex; all of them are prerequisites
now in place.

---

```
                        REAL TRADE AI EVENT
                                  │
          ┌───────────────────────┼────────────────────────┐
      Security/Ticker        Sector/Industry            Catalyst
          └───────────────────────┼────────────────────────┘
                                  │
                                  ▼
                         OPERATOR  (also an event)
              question · ack · defer · reject · /cio
                                  │
                    ◆ AGENT ASKS TOO   (still dark — see AS-IS)
                                  │
                                  ▼
                       S0_OPERATOR_CONVERSE   (✗ no input today)
                                  │
                                  ▼
                      CANONICAL ENTITY / IDENTITY
                                  │
                                  ▼
                           MATERIALITY  ·  GRAPH IMPACT
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  INSTRUMENT RECORD @v1                              │
│   thesis · cc_narrative · research[] · operator_turns[]             │
│   next_eligible_at · notify_priority                                │
│   ◆ commitments[]     views the agent staked, with deadlines        │
│   ◆ priors            what it currently believes and how strongly   │
│   ◆ scored_lessons[]  lessons that CHANGED a prior                  │
│   ★ EVERY WAKE LOADS THIS RECORD FIRST — M5_CANDIDATE today         │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                          RESEARCH GAP
                    (gap vs this record AND its priors)
                                  │
                                  ▼
                ┌──── FREE-FIRST RESEARCH ─────┐
       Persistent cognition            Hermes / RAG / FRED
       lessons · thesis · priors       librarian: grading LIVE
                └──────────────┬───────────────┘
                               │
                       residual web research
                    healthy engine pool, state visible
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ①  JUDGMENT LAYER        (DARK today; lane + cost gate exist)    │
│    invoked only when free-first leaves a material question open     │
│    in: the record, priors, evidence, open question                  │
│    out: AgentView@v1 — claim, reasoning, confidence, falsifier      │
│    gated: daily cap arithmetic BEFORE the lane runs                 │
│    costed: real cost, never a literal                               │
│    graded: critique pass before it persists                         │
│    silence is never allowed to look like "nothing to say"           │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                     SPECIALIST DISPATCHER  (formal type now exists)
                               │
                               ▼
                     CIOCouncilSynthesis@v1
                   deterministic · ◆ agent view beside it
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ②  COMMITMENT            (specified; zero producers today)       │
│      AGENT_COMMITMENT@v1                                            │
│        subject_key · claim · confidence · horizon                   │
│        falsifier · checkpoint_id (bound at creation)                │
│    a view with no falsifier is not a commitment                     │
│    MBI_BEHAVIOR stays 0                                             │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                      CIOOperatorProduct@v1
              deterministic product  +  agent view, labelled
              every field carries provenance class and as_of
                               │
                               ▼
                       NOTIFICATION POLICY
   IMMEDIATE · DIGEST · COMMAND_CENTER_ONLY · SUPPRESSED
                  ◆ DAILY AGENT BRIEF
                    what I looked at · what came back ·
                    what I now think that I didn't yesterday ·
                    what changed · what I couldn't do
                               │
                               ▼
                     DELIVERY RECEIPT / DEDUPE
                               │
                               ▼
                     OutcomeCheckpoint@v1
                 bound to a commitment at creation
                               │
                               ▼
                            OUTCOME   (now PARTIAL — settling)
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ③  SCORING             (priors absent today; n=1 outcome lesson) │
│    CONFIRMED · REFUTED · EXPIRED → move the PRIOR                   │
│    REFUTED is the most valuable object — never hidden                │
│    calibration tracked: 70% claim → how often right?               │
│    LESSON provenance explicit:                                       │
│      OUTCOME_DERIVED   earned — changes a prior                     │
│      RESEARCH_DERIVED  read   — informs the next question only      │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                         REVIEW_READY
                next wake LOADS THE RECORD with updated priors
                    MBI_BEHAVIOR = 0
                    MBI_COGNITION = 1  (may move question/narrative/priority/priors)
```

```
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ④  SELF-REPAIR   — continuous, beside the main loop             │
│    DETECTS                          then                            │
│      unscheduled scripts              opens a PR (reversible, additive)
│      dark contracts                   ESCALATES (divergent stores,   │
│      stale/split stores               money surfaces, irreversible)  │
│      metrics with no producer                                        │
│    VERIFIES BY EFFECT: CLEARED · INEFFECTIVE · FAILED · WORSENED     │
│    KNOWS ITS OWN SHAPE: provenance current in CI;                    │
│      a new dark contract fails the build                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## The order it has to be built in (with current status)

```
  1. every wake loads the record          ← M5_CANDIDATE — finish the days-earlier proof
  2. outcomes resolve                     ← PARTIAL — next: bind to commitments
  3. judgment layer                       ← the model call, gated and costed (decision)
  4. commitments with falsifiers          ← the view becomes stakeable
  5. scoring moves priors                 ← the loop closes
  6. self-repair                          ← extends what already half-exists
```

## What we should add now that we know (near-term, dated 2026-09-09)

1. **Close M5 → OBSERVED.** Let the 09-04 deferrals expire unattended and capture a
   days-earlier `cadence_not_due` on a served pin, no hand-run. Also fix the writer stamp
   (`cc_narrative.writer = migration:deterministic` on live wake writes) — open PR #836.
2. **Bind outcomes to commitments.** `due_at` on 871 of 875 `SCHEDULED` checkpoints is null
   (`event-relative` horizon); `plan_id` binding is 0 of 1,125. Without a horizon-derived
   `due_at` and a commitment, scoring has nothing to score against.
3. **Wire the operators that exist.** The recurring defect is a correct module whose only caller
   is an unscheduled report script (council synthesis, `NotificationPolicy@v1`,
   `DeliveryReceipt@v1`, `build_catalyst_graph`). Schedule them or delete the claim.
4. **Resolve the dual-write root.** `legacy_read_only:false` + 266 PROJ-rooted cron lines produce
   315 divergent files and 779 stranded per-release copies. This is the operator's deploy-boundary
   decision, and it gates self-repair's ability to trust any store.
5. **Make the true send gate observable.** `_interdicted()` returns silently; a firing leaves no
   trace. Log it before self-repair can verify-by-effect.
6. **Judgment lane.** The cost gate (`LLM_GLOBAL_DAILY_USD_CAP`) is set; the lane is off. This is
   a cost decision, not new architecture.
7. **Drive / AGENTS honesty.** Promulgate the two proposed AGENTS amendments (delivery_owner stamp,
   Drive year-path exclusion) and settle the ops-mirror allowlist so dated campaign evidence
   reaches Drive without a manual mirror.

## How you would know it works, without asking anyone (unchanged)

1. The daily brief says something today it did not say yesterday, and names why.
2. A commitment made two weeks ago settles this week, visible whether right or wrong.
3. The agent asks you a question you weren't expecting, because its evidence conflicted.
4. A calibration line exists: when it says 70%, here is how often it has been right.
5. Something broke overnight, it fixed it, and told you what it fixed — or told you it couldn't.

None of the five can be faked by a template.

## Non-goals / hard rails (unchanged)

- `MBI_BEHAVIOR` stays 0; a commitment is a belief, never an order.
- The agent view is never blended into the deterministic product — it sits beside it, labelled.
- `OUTCOME_DERIVED` vs `RESEARCH_DERIVED` provenance is never blurred.
- Extend `InstrumentRecord@v1` / `CanonicalStoreRegistry@v1`; do not mint subsystems.

## Falsifiers for the target itself

- A "commitment" with no falsifier, or a lesson labelled outcome-derived that cites no `outcome_id`.
- A maturity "pass" produced by a template, a scoreboard edit, or a hand-run, with no unattended
  durable artifact.
- A prior that moves without a settled, referenced outcome.

## Open dependencies (prerequisites, not the maturity body)

- Cost gate exported into every cron lane (not just present in the env file).
- Librarian index file actually written (`research_source_index.json`).
- One writer per store, declared and honoured.
- Operator turn path (Telegram reply → `operator_turns[]`) — currently absent.
