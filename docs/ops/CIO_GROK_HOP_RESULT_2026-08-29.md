# Grok critique hop — executed, verdict REJECT (2026-08-29)

Status:      HISTORICAL
as_of:       2026-08-29T16:11:51-04:00
Measured at: efcc51365 / not measured

    plan_477c33c065ec (SPCX) / res_557cfaab8c34
    lane grok · process maria_research_critique · model grok-3
    verdict REJECT · attachable false · ATTACHED: NO
    cost_usd 0.00 (free_oauth) · calls 1 · retryable false
    telegram_sent false · would_channel none

Global spend 2.0451 → 2.0451. `provider_cost` delta 0 — the grok lane is
`free_oauth`, so a call is ledgered by the consumption gate without a metered
provider cost row.

## Unblocking it

The registry change alone did nothing: `should_call` reads
`llm_process_config.allowed_lanes` in **Postgres**, and
`sync_process_policies_from_registry()` reads `REGISTRY_PATH` relative to the
**running release**. So the sequence had to be **merge → promote → sync → hop**,
not merge → sync. After promote:

    allowed_lanes ['fast','deepseek-v4-flash','grok']
    should_call   {'allow': True}

One process changed, cost cap untouched at $0.30, 56 → 56 processes.

## The verdict, and why it matters

Grok returned **REJECT** with four reasons:

1. the requested `question_ids` **are** addressed (via internal q1/q2/q3
   mapping) and complete — the earlier mismatch has narrowed
2. no internal contradictions; findings, `CONFIRMS` and `HOLD` are consistent
3. **execution-tainted**: `desk_implications` contains direct instruction —
   *"Maintain small tracking position with hard invalidation; do not add until
   price action confirms forward-looking signals"* — and the recommendation
   section directs the reader on stance, size and waiting criteria
4. **not attachable**, as that language violates the READ_ONLY_ADVISORY boundary

## The finding: our own matcher misses this

Checked directly against the stored artifact:

    find_imperative(desk_implications)  -> NO MATCH
    find_imperative(recommendation)     -> NO MATCH
    find_imperative(whole artifact)     -> NO MATCH

The shared matcher's verb set is
`buy|sell|trim|flatten|liquidate|submit|place|execute|exit|short|cover`. It has
no **position-directive** verbs — *maintain*, *add*, *keep*, *hold*. So
"Maintain small tracking position … do not add until …" reads as clean prose to
the gate that exists to catch exactly that.

**I did not widen the verb list.** The operator's Decision 1 was explicit — *"Do
not ban the words trim / sell / half. That is what would torch the 466."* Adding
`hold` or `maintain` is riskier still: `hold_with_thesis` is a legitimate stance
label used throughout the book, and `maintain` appears in ordinary descriptive
text. A careless addition would fail-closed a large fraction of stored research.

The honest position: **a real gap, with a fix that needs a decision.** Options,
none taken:

1. add position-directive verbs with the existing object requirement — narrower
   than it sounds, since `_OBJECT` already demands "the position"/"shares"/a size
2. treat `desk_implications.notes` and `recommendation` as instruction-shaped
   *fields* and lint them more strictly than free prose
3. leave the matcher and rely on critique for this class — accepting that it is
   only caught when a paid critique runs

## A smaller bug fixed on the way

The failure path reported the module-default lane rather than the one passed, so
a refused **grok** call recorded as **deepseek**. Fixed; the lane and process now
follow the actual call on every path.

Also observed: the model set `verdict: REJECT` while leaving its
`execution_language` boolean false, though its prose says execution-tainted. The
code trusts the verdict for the outcome — so the artifact is recorded `FAIL` and
unattached either way — but the structured flag disagreed with the model's own
reasoning, which is worth knowing before anyone keys logic off that boolean.

## Recorded

`SpecialistArtifact` `provider=grok_critique outcome=FAIL cost=0.0`, plus a
`DeliveryReceipt` with `would_channel: none`, `would_send: false`. **Nothing
attached.** No CASE_SUMMARY minted.

## Pins

`telegram_sent` false, INTERDICT on, `CIO_SITUATION_NOTIFY` 0, MBI 0, ROTATE
advisory-only, no second process widened, no cap raise (`$2.25` was
run-scoped and operator-authorised earlier today; `.env` still reads `0.50`),
no Flash-critique, no `grok_execution_review`, no escalation.
