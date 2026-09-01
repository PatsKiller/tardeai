Status:      ACTIVE
as_of:       2026-08-30
Measured at: audit programme snapshot — re-measure before quoting node status
Canonical repo path: docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md
Authority:   dated reading of LIVE / PARTIAL / UNWIRED / DARK — not a behaviour spec
Supersedes:  none
See also:    docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md
             docs/architecture/PROJECT_THE_DESK_V2.md
             AGENTS.md §13.4 §15 §19

# CIO Agent — AS-IS vs SPEC

**Snapshot as_of 2026-08-30.** Every status below was measured at some point in the audit
programme; several moved during it. Treat the annotations as a dated reading, not a fixed
truth — re-measure before quoting any of them.

```
LEGEND
  █  LIVE       runs on schedule, produces durable output, verified at runtime
  ▓  PARTIAL    runs, but incomplete, degraded, or its consumer is unproven
  ░  UNWIRED    the code exists and is correct; nothing calls it or consumes it
  ✗  DARK       never executed, or produces nothing, in recorded history
```

---

```
                        REAL TRADE AI EVENT
                                  │
          ┌───────────────────────┼────────────────────────┐
          │                       │                        │
    █ Security/Ticker      █ Sector/Industry        ▓ Catalyst
                                                     family completion ~1.5%
          └───────────────────────┼────────────────────────┘   extraction writes
                                  │                            non-symbols into
                                  ▼                            a symbol column
                       ▓ OPERATOR  (also an event)
              question · ack · defer · reject · /cio
              turn lands on the record and is read back
              BUT no scheduled wake proven to consume it
                                  │
                                  ▼
                     ▓ S0_OPERATOR_CONVERSE
                       mechanism real · loop unproven under cron
                                  │
                                  ▼
                    █ CANONICAL ENTITY / IDENTITY
                      registry live · guard correctly refuses
                      unrecognised symbols · the noise is upstream
                                  │
                                  ▼
                         █ MATERIALITY   S1–S7
                                  │
                                  ▼
                         ▓ GRAPH IMPACT
                           thin — barely a stage in practice
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│              ▓ INSTRUMENT RECORD @v1   (persistent unit)            │
│                                                                     │
│   █ subject_key · thesis · cc_narrative                             │
│   █ research[] / artifact_ids                                       │
│   █ operator_turns[]        turn written and read back              │
│   ▓ lessons[]               337 candidates — ALL research-fed       │
│   █ next_eligible_at · notify_priority                              │
│                                                                     │
│   ░ load-by-subject on every wake                                   │
│        the mechanism is built and correct.                          │
│        NO SCHEDULED WAKE CONSUMES IT.  ← this is proof M5,          │
│        and it is the single highest-value unwired thing here        │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                        █ RESEARCH GAP
                                  │
                                  ▼
                ┌──── FREE-FIRST RESEARCH ─────┐
                │                              │
    █ Persistent cognition          ▓ Hermes / RAG / FRED
      lessons · thesis                 ░ librarian: grade / stale-out
      █ CASE_SUMMARY 337                 index file DOES NOT EXIST
                │                        — a fully tested law
                │                          governing nothing
                └──────────────┬───────────────┘
                               │
                    ▓ residual web research
                      lane live · engine pool DEGRADED
                      (several search engines CAPTCHA-suspended)
                               │
                               ▼
              ✗ LLM only if still unresolved
                 ── the paid lane failed closed for ~5 weeks
                    on a missing cost-cap env var
                 ── the overnight judgment window was RETIRED in June
                 ── MODEL_CALL_RECORDED fires for inference
                    that never happens: a receipt with no call
                               │
                               ▼
                    ▓ SPECIALIST DISPATCHER
                      N=100 sample exit gate FAILED
                               │
                               ▼
                  ░ SpecialistArtifact@v1-lite
                    no formal type — informal dict convention
                               │
                               ▼
                   █ CIOCouncilSynthesis@v1
                     deterministic · DISPUTED stands
                     ← correct by design. no model is called here,
                       and that is intended
                               │
                               ▼
              ▓ WRITE BACK TO INSTRUMENT RECORD
                cc_narrative · next_question · priority
                cognition enforced: CognitionNoOp raises
                on a write that moves nothing
                               │
                               ▼
                   █ CIOOperatorProduct@v1
                     DETERMINISTIC_PRODUCT · $0.00
                     ▓ but: a field whose value depends on a
                       three-way branch reads as a total;
                       most payload blocks — including every
                       cash number — carry no as_of of their own
                               │
                               ▼
                    █ NOTIFICATION POLICY
       ┌───────────────────────┼───────────────────────┐
       │                       │                       │
   █ IMMEDIATE            █ DIGEST         █ COMMAND_CENTER_ONLY
       └───────────────────────┼───────────────────────┘
                               │
                       █ or SUPPRESSED
                               │
                               ▼
               █ DELIVERY RECEIPT / DEDUPE
                 content-keyed, windowed
                               │
                               ▼
                  ▓ OutcomeCheckpoint@v1
                    ~791 checkpoints exist
                    only a handful RESOLVED
                    a large block sits OUTCOME_PENDING_DATA
                    — nobody has asked what data is pending
                               │
                               ▼
                          ✗ OUTCOME
                            the edge is dark
                               │
                    ┌─────────┴──────────┐
                    │                    │
              ✗ from outcome      ▓ from research  ← 337 lessons
                    │                    │            arrive HERE,
                    └─────────┬──────────┘            bypassing outcome
                              ▼
                    ▓ LESSON / HYPOTHESIS
                      the system learns from WHAT IT READ,
                      not from WHAT HAPPENED
                              │
                              ▼
                       ░ REVIEW_READY
                         next wake LOADS THE RECORD
                         — unproven under cron
                              │
                  █ MBI_BEHAVIOR  = 0   enforced for the agent
                  ▓ MBI_COGNITION = 1   enforced, but the delta
                                        it may carry is barred
                                        from changing any action

┌────────────────────────────────────────────────────────────────────┐
│              █ CanonicalStoreRegistry@v1                           │
│                █ GOOD_PERSISTENT_ROOT                              │
│                ▓ four confirmed checkout-relative splits:          │
│                  release-local logs · two holdings copies ·        │
│                  risk state · evening packet                       │
│                  (each found while looking for something else —    │
│                   the true count is unknown)                       │
└────────────────────────────────────────────────────────────────────┘
```

---

## What the spec says and the system does not do

| Spec node | Reality |
|---|---|
| `LLM only if still unresolved AND materially useful` | No model is called on the CIO path. The receipt fires anyway. |
| `lessons[] cognition only → next question` | Lessons exist in volume but are **research-derived**. The outcome edge feeding them is dark. |
| `load-by-subject on every wake` | Built, correct, tested — and no scheduled wake consumes it. |
| `librarian: grade / stale-out` | Fully tested law, index file absent, governs nothing. |
| `SpecialistArtifact@v1-lite` | No formal type; the dispatcher's own sample gate failed. |
| `Telegram reply is the next S0` | The turn lands. Nothing scheduled reads it back. |
| `MBI_COGNITION = 1` | Enforced — but a validated positive research delta is barred by policy from changing any action, so cognition has nowhere to land. |

## The one-sentence version

**The nervous system is built and running; the cortex was never wired.** Everything from event
intake through notification works at scale. Everything that would constitute a view of its own —
a model call, an outcome-fed lesson, a committed position — is dark, unwired, or barred.

## The count that matters

**Agent-originated fields reaching any operator surface: zero.** Every sentence the operator
reads is a rule, a threshold, a template, or a constant. The one genuinely non-deterministic
sentence delivered per day is produced by an external session reading a packet this system
composes — outside every provenance, gating and lineage mechanism described above.
