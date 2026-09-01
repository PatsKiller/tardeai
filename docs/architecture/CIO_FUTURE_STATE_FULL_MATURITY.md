Status:      ACTIVE
as_of:       2026-08-30
Measured at: not measured — target spec, not runtime
Canonical repo path: docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md
Authority:   full-maturity target (judgment, commitment, scoring, self-repair)
Supersedes:  none
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md
             docs/architecture/PROJECT_THE_DESK_V2.md
             AGENTS.md §13.4 §15 §19

# CIO Agent — FULL MATURITY TARGET

What "self-thinking, self-learning, self-fixing" means concretely, drawn as a system rather than
as adjectives. Four things are added to the current spec; everything else is the spec you
already have, working.

```
THE FOUR ADDITIONS

  ①  JUDGMENT        the agent forms a view of its own, gated and costed
  ②  COMMITMENT      it stakes that view as a falsifiable claim, with a deadline
  ③  SCORING         outcomes settle the claim and move its priors
  ④  SELF-REPAIR     it detects and fixes its own broken plumbing, and reports what it can't

Everything below marked ◆ is new. Everything else exists today in some form.
```

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
                    ◆ AGENT ASKS TOO
                      when confidence is low or evidence conflicts,
                      the agent raises a question TO the operator
                      and blocks on it. two-way, not one-way.
                                  │
                                  ▼
                       S0_OPERATOR_CONVERSE
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
│                                                                     │
│   thesis · cc_narrative · research[] · operator_turns[]             │
│   next_eligible_at · notify_priority                                │
│                                                                     │
│   ◆ commitments[]     views the agent staked, with deadlines        │
│   ◆ priors            what it currently believes and how strongly   │
│   ◆ scored_lessons[]  lessons that CHANGED a prior, with the        │
│                       outcome that earned the change                │
│                                                                     │
│   ★ EVERY WAKE LOADS THIS RECORD FIRST — enforced, scheduled,       │
│     and proven unattended. no wake acts before it reads.            │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                          RESEARCH GAP
                    (gap vs THIS record AND its priors)
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
│  ◆ ①  JUDGMENT LAYER                                                │
│                                                                     │
│    invoked only when free-first leaves a material question open     │
│                                                                     │
│    in:   the record, its priors, the evidence, the open question    │
│    out:  a VIEW — a claim, its reasoning, its confidence,           │
│          and what would falsify it                                  │
│                                                                     │
│    gated:   daily cap arithmetic done BEFORE the lane runs          │
│    costed:  every call recorded with a REAL cost, never a literal   │
│    graded:  critique pass — the view is challenged before it        │
│             is allowed to persist                                   │
│    typed:   AgentView@v1, provenance class A, marked as opinion     │
│             everywhere it is displayed                              │
│                                                                     │
│    if the lane is unavailable, the system SAYS SO on the surface.   │
│    silence is never allowed to look like "nothing to say."          │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                     SPECIALIST DISPATCHER
                        (formal artifact type)
                               │
                               ▼
                     CIOCouncilSynthesis@v1
                   deterministic · DISPUTED stands
                   ◆ carries the agent's view alongside the
                     deterministic product, never blended into it
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ②  COMMITMENT                                                    │
│                                                                     │
│    the agent stakes the view as a falsifiable claim:                │
│                                                                     │
│      AGENT_COMMITMENT@v1                                            │
│        subject_key · claim · confidence · horizon                   │
│        falsifier      what would prove this wrong                   │
│        checkpoint_id  bound at creation, not after                  │
│                                                                     │
│    a view with no falsifier is not a commitment — it is a           │
│    sentence, and it does not enter the store.                       │
│                                                                     │
│    MBI_BEHAVIOR stays 0. a commitment is a belief, never an order.  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                      CIOOperatorProduct@v1
              deterministic product  +  agent view, labelled
              every field carries its provenance class and its as_of
                               │
                               ▼
                       NOTIFICATION POLICY
       ┌───────────────────────┼───────────────────────┐
   IMMEDIATE                 DIGEST          COMMAND_CENTER_ONLY
       └───────────────────────┼───────────────────────┘
                               │
                  ◆ DAILY AGENT BRIEF
                    what I looked at · what came back ·
                    what I now think that I didn't yesterday ·
                    what changed · what I couldn't do
                    ("nothing changed today" is a valid brief)
                               │
                               ▼
                     DELIVERY RECEIPT / DEDUPE
                               │
                               ▼
                     OutcomeCheckpoint@v1
                 bound to a commitment at creation
                               │
                               ▼
                            OUTCOME
              ★ the edge that is dark today. resolution runs,
                pending-data states are chased, and every
                commitment eventually settles or expires.
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ③  SCORING                                                       │
│                                                                     │
│    outcome settles the commitment:  CONFIRMED · REFUTED · EXPIRED   │
│                                                                     │
│    a REFUTED commitment is the most valuable object in the system.  │
│    it is not hidden, softened, or averaged away.                    │
│                                                                     │
│    the score moves the PRIOR — not the position, not the size.      │
│    calibration is tracked openly: when the agent says 70%,          │
│    how often is it right?                                           │
│                                                                     │
│    LESSON provenance is explicit and never blurred:                 │
│      OUTCOME_DERIVED   earned — changes a prior                     │
│      RESEARCH_DERIVED  read — informs the next question only        │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                         REVIEW_READY
                next wake LOADS THE RECORD — with its
                updated priors and its settled commitments
                               │
                    MBI_BEHAVIOR  = 0
                    MBI_COGNITION = 1
                      cognition may move: next question,
                      narrative, priority, and PRIORS
                      cognition may never move: size, weight,
                      order, stop — refused, never filtered
```

---

```
┌─────────────────────────────────────────────────────────────────────┐
│  ◆ ④  SELF-REPAIR   — runs continuously, beside the main loop       │
│                                                                     │
│    DETECTS                          then                            │
│      unscheduled scripts              opens a PR with the fix        │
│      dark contracts                   for reversible, additive work  │
│      stale or split stores                                          │
│      metrics with no producer         ESCALATES, never fixes:        │
│      producers wired to nothing         divergent authoritative      │
│      gates that never execute            stores · gate strengthening │
│      lanes producing nothing            · anything on a money        │
│      remediations that don't work         surface · anything         │
│                                           irreversible               │
│                                                                     │
│    VERIFIES BY EFFECT, NEVER BY EXIT CODE                           │
│      CLEARED · INEFFECTIVE · FAILED · WORSENED · UNVERIFIED         │
│      WORSENED escalates on first observation                        │
│                                                                     │
│    KNOWS ITS OWN SHAPE                                              │
│      every operator field's provenance, kept current by CI          │
│      every metric's producer and as_of                              │
│      one authoritative gauge per question, not three                │
│      a new unlabelled field, or a new dark contract,                │
│      fails the build                                                │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                  CanonicalStoreRegistry@v1                          │
│   + agent_view_id · commitment_id · prior_id · score_id             │
│                    GOOD_PERSISTENT_ROOT                             │
│   ◆ one writer per store, declared. no checkout-relative writes.    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## What makes this different from what exists

Today the loop is: **read → compute → display → checkpoint → (dark)**.

At maturity it is: **read → think → commit → display → observe → score → believe differently
→ read again.**

The pivot is ②. A system that produces lessons without ever staking a claim is summarising, not
learning — and that is precisely what 337 research-derived lessons and a handful of resolved
checkpoints describes today. **Learning requires something to be wrong about.**

## How you would know it works, without asking anyone

1. The daily brief says something today that it did not say yesterday, and names why.
2. A commitment made two weeks ago settles this week, and the settlement is visible whether it
   was right or wrong.
3. The agent asks you a question you weren't expecting, because its evidence conflicted.
4. A calibration line exists: when it says 70%, here is how often it has been right.
5. Something broke overnight, it fixed it, and told you what it fixed — or told you it couldn't
   and why.

None of those five can be faked by a template, and none requires you to read a scoreboard.

## The order it has to be built in

```
  1. every wake loads the record          ← without this, nothing persists into behaviour
  2. outcomes resolve                     ← without this, there is nothing to learn from
  3. judgment layer                       ← the model call, gated and costed
  4. commitments with falsifiers          ← the view becomes stakeable
  5. scoring moves priors                 ← the loop closes
  6. self-repair                          ← extends what already half-exists
```

Steps 1 and 2 are plumbing you have most of. Step 3 is a decision about cost and a lane that was
switched off, not new architecture. Steps 4 and 5 are genuinely new and are where the agent stops
being a very good reporter and starts being an analyst who can be wrong.
