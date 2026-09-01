Status:      ACTIVE
as_of:       2026-08-30
Measured at: not measured — extension spec against AS-IS + FUTURE
Canonical repo path: docs/architecture/PROJECT_THE_DESK_V2.md
Authority:   how to extend existing types; no new subsystem
Supersedes:  PROJECT_THE_DESK.md (v1)
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md
             docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md
             AGENTS.md §13.4 §13.5 §19

# PROJECT · THE DESK — an autonomous CIO, built as extensions to the existing spec

**Supersedes** `PROJECT_THE_DESK.md` (v1), which proposed four new types where three already
exist. This version is written against `CIO_ASIS_VS_SPEC_2026-08-30.md` and
`CIO_FUTURE_STATE_FULL_MATURITY.md`.

**Governing constraint: nothing here is a new subsystem.** Every capability is an extension of a
node already in the pipeline, a field on `InstrumentRecord@v1`, or a producer for a type already
registered in `CanonicalStoreRegistry@v1` and currently unproduced.

---

# 0 · What v1 got wrong, so it is not repeated

| v1 proposed | Already specified | Correct construction |
|---|---|---|
| `OperatorTurn@v1` | `operator_turns[]` on the record; `operator_turn_id` registered | **extend the existing field** |
| `InterestDeclaration@v1` | `WATCH:SYM` subject_key + `notify_priority` + `next_eligible_at` | **a record state, not a type** |
| an attachment graph | `GRAPH IMPACT` — 1-hop, held non-dust only, marked PARTIAL | **widen that stage** |
| a research-priority scorer | `MATERIALITY S1–S7` → `notify_priority` | **an input to S1–S7** |
| price monitors | `OutcomeCheckpoint@v1`, `plan_id` bound at creation | **a checkpoint with a price condition** |
| unprompted surfacing | `notify_priority crossed a bar` → `NOTIFICATION POLICY` | **use the existing bar** |
| **`AdvisoryProposal@v1`** | **`AGENT_COMMITMENT@v1`** — claim, confidence, horizon, falsifier, `checkpoint_id` | **the same object.** A sized proposal is a commitment with an instrument attached |

**Genuinely new: two things.** The `THEME:` / `INDUSTRY:` / `EVENT:` subject_key prefixes, and the
sizing/instrument fields on a commitment. Everything else extends.

**And one prerequisite that outranks all of it:** `AGENTS.md` does not contain the type vocabulary —
not the subject_key namespace, not the eleven registered id types, not `AgentView@v1` or
`AGENT_COMMITMENT@v1`. An agent reading `AGENTS.md` before building cannot know `operator_turns[]`
exists. **That gap is why v1 was written wrong, and it will produce the same error in Cursor, Grok
and Codex.** §9 addresses it, and it ships first.

---

# 1 · The target, stated against the spec

The desk performs sixteen CIO functions. The spec already routes fourteen of them; two need new
fields. The reason none of them work is not architecture — it is that **three nodes are dark and
one is barred.**

```
✗ LLM only if still unresolved        no model on the CIO path
✗ OUTCOME                             the edge is dark
░ load-by-subject on every wake       built, correct, called by nothing
▓ MBI_COGNITION = 1                   enforced, but the delta is barred from action
```

**Fix those four and most of the CIO function follows from the spec as written.** The rest of this
document is the extensions on top.

---

# 2 · Subject-key namespace — extend, registry-declared

Current: `HELD:SYM` · `EXIT:SYM` · `WATCH:SYM` · `SECTOR:name` · `SLEEVE:CASH`

**Add three prefixes**, each a first-class `InstrumentRecord` with the same lifecycle, the same
`operator_turns[]`, the same `next_eligible_at`, the same cognition rules:

```
INDUSTRY:cybersecurity     Finviz-derived taxonomy, machine-known
THEME:ai_security          operator-derived, learned from what the operator says
EVENT:falcon_2026          dated, expiring, watchable
EVENT:crwd_earnings_2026-09-04
```

**Why these are records and not tags.** A tag has no `next_eligible_at`, no `operator_turns[]`, no
`lessons[]`, and cannot be woken. A theme the operator declared is a subject the desk should
research on a cadence, hold a thesis about, and form a view on. `SECTOR:` is already precedent —
this is the same construction at two more granularities.

**`THEME:` is the one that matters.** "AI security" is not a Finviz industry. The system did not
have it until the operator said it. **A theme is how a desk actually thinks**, and it is the only
node here the machine cannot derive on its own.

**Registered in `CanonicalStoreRegistry@v1`** alongside `instrument_record_id`. No new store.

---

# 3 · `GRAPH IMPACT` — widen the stage that is already there

Spec: *1-hop · held non-dust only*. As-is: **PARTIAL, "barely a stage in practice."**

That constraint is correct for a market event — a move in a held name should not fan out
arbitrarily. **It is wrong for an operator event**, which is the case the spec added at the top of
the pipeline and this stage never accounted for.

**Widen by event class:**

| event class | hop policy |
|---|---|
| market / catalyst | 1-hop, held non-dust — **unchanged** |
| **operator inquiry** | 1-hop across `SECURITY → INDUSTRY → THEME → SECTOR → EVENT → EXPOSURE`, **held or not** |

An operator asking about CRWD propagates to `INDUSTRY:cybersecurity`, any declared `THEME:` it
matches, `SECTOR:Technology`, the two live `EVENT:` records, and an **exposure gap** — the operator
holds zero direct cybersecurity.

**Edge strength is explicit and per-edge.** Direct security interest is strong and persistent.
Sector is weak and expires. Theme, once declared, persists until revoked.

**This is the attachment graph v1 proposed, built where the spec already put it.**

---

# 4 · `operator_turns[]` — extend the field

Already on the record, already written, already read back. **Extend its shape; do not create a
type.**

```
operator_turns[] entry
  turn_id                       registered id type, exists
  asked_at
  verbatim                      what was said, not a summary        ← new
  subject_keys[]                every node GRAPH IMPACT reached     ← new
  intent_classified             with confidence and alternates      ← new
  agent_answered                sources and as_of per field         ← new
  gaps_named                    what could not be reached           ← new
  offer_made[] · offer_response the options and the choice          ← new
  led_to                        commitment_id · research_id · checkpoint_id  ← new
```

**`verbatim` is load-bearing.** "AI security" is a theme the system did not have until the operator
said it. A summary loses the thing that created the record.

**Every exchange writes, whether or not an offer is accepted.** A declined offer is information
about what the operator does not want.

---

# 5 · Interest — a record state, not a new type

**No new type.** Interest is expressed in fields that already exist:

- `subject_key` prefix `WATCH:` — the record's existence *is* the interest
- **`interest_level`** — new field: `WATCHING · CONSIDERING · ACTIVE · POSITION · DIVESTING`
- **`interest_intent`** — new field: `long · short · swing · income · hedge · undecided`
- **`interest_declared_at` / `interest_revoked_at`** — new fields
- `next_eligible_at` — already the cadence control
- `notify_priority` — already the surfacing control

**Persistent until revoked.** No decay. The operator states the level; the agent asks once rather
than guessing, and never silently promotes an inferred `WATCHING` to `CONSIDERING`.

## Interest feeds `MATERIALITY S1–S7` — it does not compete with it

**No second scorer.** `interest_level` becomes an input term:

```
S1–S7 materiality  +  interest_weight        WATCHING 2 · CONSIDERING 5 · ACTIVE 8
                   +  recency_of_mention     refreshed by any turn touching the subject
                   +  exposure_gap           interested and holds none, or overweight and worried
                   +  event_proximity        an EVENT: record inside the horizon
                   −  recently_researched
                   →  notify_priority
```

**The spec's own rule then handles surfacing unchanged:** *notification only if
`record.notify_priority` crossed a bar.* Nothing new is required for unprompted delivery — the bar
already exists and the agent was never given a reason to cross it.

---

# 6 · Tools — the free-first layer, where the spec puts them

The spec's `FREE-FIRST RESEARCH` node already reads persistent cognition, RAG, FRED and a Fed URL,
and only then reaches residual web. **Tools are readers inside that node, not a new layer.**

Market data · fundamentals with peer comparables · news and the **event radar** (conferences,
earnings, Fed, rebalances — this is what `EVENT:` records are for) · options chain from the desk
that already produces edge · portfolio with corrected look-through · tax lots, rebuilt nightly and
consulted by nothing · macro.

**Street ships gated and says so.** 689,349 rows, zero directional; both known divergences are a
1-vs-1 tie broken by `LIMIT 1`; `ABX` is a ticker collision. Until a sample floor, a staleness gate
and exchange disambiguation exist it returns *"unreliable — here is why."* **A fabricated consensus
in front of a real decision is the worst thing this system could ship.**

**The librarian's grading law already exists, fully tested, with no index file.** Populate it —
these tools are exactly the sources it was written to grade.

---

# 7 · Sizing — fields on `AGENT_COMMITMENT@v1`

**No `AdvisoryProposal@v1`.** The spec's commitment type is the proposal, and it has had zero
producers for the life of this programme.

```
AGENT_COMMITMENT@v1
  subject_key · claim · confidence · horizon      spec
  falsifier                                       spec — no falsifier, no commitment
  checkpoint_id      bound at creation            spec

  kind               entry | add | trim | exit | hedge | income | tax     ← new
  sizing             shares · notional · %book · %sector · binding_limit  ← new
  entry_plan         tranches, levels, triggers                           ← new
  instrument         common | CSP | covered_call | spread | collar        ← new
  risk               stop, max loss, correlation, beta contribution       ← new
  tax                lot method, wash window, LT/ST distance              ← new
  provenance         class A                                             spec
```

## Why this does not touch `MBI_BEHAVIOR`

`BehaviorWriteRefused` raises on `shares`, `size_usd`, `qty`, `recommended_delta_usd`,
`target_weight_pct` **on the InstrumentRecord cognition path** — so a lesson can never silently
move a position size. That rail is correct and stays exactly as written.

**A commitment is a different object with a different lifecycle.** The spec already says so:
*"MBI_BEHAVIOR stays 0. A commitment is a belief, never an order."* Sizing on a commitment is the
belief's content, not a cognition write. Nothing renders into `InstrumentRecord` behaviour fields;
nothing reaches the broker path; `record.commitments[]` holds ids, not sizes.

**Gate:** `COMMITMENT_SIZING_ENABLED`, default off, first ten reviewed. Not because the design is
unsafe — because a new producer's first outputs should be read before they arrive unannounced.

## The binding constraint is always named

*"Fifty shares — correlation-limited, not conviction-limited. You hold Technology at 6.5% and this
correlates 0.7 with SCHG."* **A size with no named binding limit is a guess.**

## Entry ladders are checkpoints

Each level is an `OutcomeCheckpoint@v1` with a price condition, `plan_id`-bound at creation exactly
as the spec requires. When it fires it writes back to the record — so the agent knows it told the
operator, and what the operator did. **No monitor subsystem. The checkpoint type already does this.**

---

# 8 · The two-way loop — `◆ AGENT ASKS TOO`, from the future-state spec

The future state already has it: *when confidence is low or evidence conflicts, the agent raises a
question TO the operator and blocks on it.*

**That node is the interaction model.** *"Long, short or swing? What size are you thinking? Where
would you add?"* is a low-confidence block, and the answer completes the commitment. One question,
not five.

**And a desk disagrees.** When stated intent conflicts with the book: *"500 shares is 16% against
your 12% name limit and takes Technology to 12.9%. I would do 200 and add on weakness. If you want
500, tell me what changes about the limit."* Reasoning, then the operator's call — never obstruction.

The commitment records **what the agent would have concluded without the operator turn**, which is
`#715`'s open work and the mechanism that makes M3 provable.

---

# 9 · Prerequisites — these ship before any of the above

**P0 · `AGENTS.md` gains the type vocabulary.** The subject_key namespace, the eleven registered id
types, `AgentView@v1`, `AGENT_COMMITMENT@v1`, `SpecialistArtifact@v1-lite`, `OutcomeCheckpoint@v1`,
and the rule: **a new `@v1` type must be justified against the existing set in the PR body.** This
gap produced v1 of this document and it will produce the same error in every other agent.

**P1 · `load-by-subject` on every scheduled wake.** `░` today — built, correct, called by nothing.
**Nothing in this project functions without it.** No record load, no interest, no memory, no M5.

**P2 · The outcome edge.** `✗` today. Without settled outcomes there is no scoring, no priors, and
a commitment is a claim nobody ever grades.

**P3 · The judgment layer.** `✗` today. Without it every "view" is deterministic and class A stays
at zero.

**P4 · The research→action bar.** `POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION` — cognition is
enforced and has nowhere to land. **Default: a research-backed positive delta may raise
`notify_priority`, change `cc_narrative`, and set `next_research_question`. It may never touch size,
weight, order or stop.** That is `MBI_COGNITION = 1` inside its existing definition.

---

# 10 · Build order, with anti-dark acceptance

**Every phase names its consumer before it is built, and acceptance proves the write is read by
something scheduled.** This system has `load-by-subject` built and called by nothing,
`store_consistency` built and never wired, a liveness monitor built and never scheduled. **Not
again.**

**Phase 0 — P0 and P1.** Type vocabulary into `AGENTS.md`; `load-by-subject` wired.
*Acceptance:* a scheduled wake loads a record and returns `skip / cadence_not_due` on a
days-old disposition, **unattended**. That is M5.

**Phase 1 — answer, and the graph.** Tools in free-first; `operator_turns[]` extended; `GRAPH
IMPACT` widened for operator events; `INDUSTRY:` and `THEME:` prefixes.
*Acceptance:* ask about an unheld symbol, get a real answer with `as_of` per field, **and find the
turn on `SECURITY:CRWD`, `INDUSTRY:cybersecurity` and `THEME:ai_security` — with `INDUSTRY:`
created by the question.**

**Phase 2 — interest into materiality.** `interest_level`, `interest_intent`, the S1–S7 term.
*Acceptance:* declare interest, then find the subject **ranked above an equivalent one nobody
mentioned, in the next scheduled materiality cycle, unattended.** The consumer is S1–S7 and it must
be shown reading the term.

**Phase 3 — ask, plan, checkpoint.** The `◆ AGENT ASKS TOO` node; entry ladders as checkpoints.
*Acceptance:* state an intent, get a ladder, **and have a level checkpoint fire and write back.**

**Phase 4 — commitment with sizing.** The new fields; the options desk wired in; gated.
*Acceptance:* a commitment created with a falsifier and a bound `checkpoint_id`, rendered on the
operator product **labelled class A and visibly separate from the deterministic product.**

**Phase 5 — autonomy.** `EVENT:` radar, thesis drift, theme matching, all through the existing
`notify_priority` bar.
*Acceptance:* **a surfacing the operator did not ask for, that the operator agrees was worth the
interruption.** Subjective by design, and the only test that matters.

**Phase 6 — portfolio.** Cash deployment plan, hedging, tax-aware selection, correlation-aware
construction.

**Phase 7 — scoring.** Outcomes settle commitments; priors move; calibration tracked openly. **When
it says 70%, how often is it right.**

---

# 11 · What must not happen

- **No new type without justification against the registry** in the PR body.
- **No parallel memory.** `Star` writes membership rather than the spine and Watch Intelligence is
  rich-but-parallel with no `InstrumentRecord` — **do not add a third.**
- **No second scorer, no second monitor, no second graph.** Extend `MATERIALITY`,
  `OutcomeCheckpoint`, `GRAPH IMPACT`.
- **No behaviour write.** `BehaviorWriteRefused` untouched.
- **No order, no stop, no broker write.** That subsystem is separate and stays separate.
- **No fabricated number.** A tool that cannot answer says so.
- **No new data vendor.** Phases 0–6 need nothing that is not already paid for.
- **No alarm without a firing test.**
- **No phase built on an unproven phase.**

---

# 12 · How you will know it is real

1. Ask about any symbol — real answer, cited, dated, gaps named.
2. Declare a theme — **a name never mentioned surfaces because it matches.**
3. Set a level — it fires, and the record shows it fired.
4. A week later the brief mentions a symbol **because it was asked about.**
5. It tells you something unasked **and you are glad it did.**
6. It disagrees, with reasoning, and one of you changes.
7. A commitment made a month ago settles — visibly, right or wrong.

**Five and seven are the desk.** Everything before them is a very good tool.
