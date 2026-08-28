# P9.2 — has a research round trip ever closed?

**No. 0 of 456.** And the reason is written into the system as a policy, not a bug.

READ ONLY. Nothing was fixed. `[VERIFIED]` = command run against live state, output
quoted. `[CODE]` = read from source in `9783395a-main-exact-phase2-20260828-082142`.

---

## The three conditions

The brief asked for one research request that (a) the system initiated rather than a
schedule, (b) completed, and (c) changed something downstream.

**(a) and (b) are satisfied many times over. (c) has never happened.**

### (a) System-initiated — yes, hundreds `[VERIFIED]`

`hermes_research_requests.jsonl`, 4,244 events. Requests are raised by situations, not
by a clock:

```
reason
  situation.raised:S3_REENTRY_CANDIDATE              184
  situation.raised:S1_POSITION_LIFECYCLE             162
  situation.raised:S6_CONCENTRATION_OR_DISPOSITION    25
  Evidence refresh required: no_approved_primary…     25

operator_forced   False 733 · True 3
```

Only 3 requests in the entire store were operator-forced. This lane is genuinely
self-starting.

### (b) Completed — yes, 456 `[VERIFIED]`

```
HERMES_RESEARCH_COMPLETED   459
HERMES_LOOP_COMPLETED       456
critique_verdict   VALID 378 · PARTIAL 66
```

The research is not merely finishing; it is being judged good by the system's own critic.

### (c) Changed something downstream — **zero** `[VERIFIED]`

Across all 456 completed loops:

```
enriched           True 436 · False  20     <- enrichment RAN
material_changed   False 436 · None  20     <- and changed nothing, every time
notified           False 456                <- no operator was ever told
reassessment_ok    True 433
memory_ok          True 397                 <- stored as RESEARCH_REFERENCE
```

`material_changed` is not an inert field. It is a real comparison
`[CODE hermes_research_loop.py:567]`:

```python
after_fp = _material_fingerprint(plan)
material_changed = after_fp != before_fp
```

over five substantive fields — `recommendation`, `summary`, `fire_reasons`, `material`,
`hermes_result_id` `[CODE :433-441]`. Four of the five are populated on live plans
(781 / 781 / 770 / 277 of 781), so the fingerprint is not vacuous.

The fifth is the tell: **`hermes_result_id` is set on 0 of 781 plans** `[VERIFIED]`. The
research result is never attached to the plan it was raised for.

So: enrichment runs, the plan is reloaded, and its material content is byte-identical
before and after. 436 times out of 436.

---

## Is the research corpus write-only with respect to decisions?

**No — and this is the part that would be wrong to state simply.**

Research *is* consumed at decision time by `ThesisDecisionGate@v1`, on both sides
`[VERIFIED]`, across the 67 live re-entry names:

```
reason_codes
  INCOMPLETE_RESEARCH_BLOCKS_UNGOVERNED_HIGH_CONVICTION   29
  NO_MATERIAL_THESIS_RESTRICTION                          27
  POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION        11

delta_classification   CONFIRMS 9 · STRENGTHENS 3 · NO_NEW_INFO 1 · None 54
positive_delta_created_promotion   False 67
delta_freshness        UNKNOWN 67
```

So thirteen real research deltas exist and are read. Nine **confirm** a thesis, three
**strengthen** one. The gate sees them.

And then the third reason code says what happens next, in the system's own words:

> `POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION`

**A positive research delta may raise completeness. It may never raise action.** That is
not a defect; it is an encoded rule, and it is the reason (c) is zero. Research can close
a gap. It cannot change a decision. `positive_delta_created_promotion` is False on all 67
because it is designed to be.

The asymmetry is worth stating plainly:

| direction | effect | count |
|-----------|--------|-------|
| research **absent** | blocks promotion of an ungoverned high-conviction name | 29 |
| research **present and positive** | raises completeness, changes no action | 13 |

Research is therefore load-bearing in exactly one direction — its absence restrains — and
inert in the other.

One loose thread, unresolved: `delta_freshness` is `UNKNOWN` on all 67. Even the deltas
that are consumed have no established age.

---

## The honest answer to the brief's question

There is no example to trace, so none is constructed. The count is **0 of 456**.

The lane is not broken in the way "0" suggests. Every stage works:

```
situation raised → request enqueued → claimed → completed → critique VALID
    → enriched into the plan → accepted into memory
        → and then nothing
```

Two independent policies close the loop off at the last step, and both are deliberate:

1. `POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION` — research may not change an action.
2. Memory admits research as `RESEARCH_REFERENCE`, which governance never promotes to
   ACTIVE (established in P8.1) — so the memory path cannot carry it into influence
   either.

The research corpus is read, judged, stored, and prevented from mattering. Whether that
is right is a scoping decision for the operator; it is not something to "fix" by
loosening either rule. Loosening the first would let unreviewed research move positions.
Loosening the second was explicitly rejected in P8.1 — a lane that admits everything is
worse than one that admits nothing, because it looks healthy.

## What this composes with

- **P9.1**: nothing in the CIO run path generates judgment. **P9.2**: the one lane that
  produces genuinely new information is barred from acting on it. Together these explain
  P9.0's `A = 0` completely — not as an oversight, but as the sum of two working gates.
- **P8.1**: `AGENT_COMMITMENT` and `CASE_SUMMARY` have no producers. A completed research
  loop with `critique_verdict: VALID` is the most plausible source for a `CASE_SUMMARY`
  that exists today — 378 of them — and it is currently discarded at exactly that point.
