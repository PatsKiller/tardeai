# Material change → due-diligence questions

**Status:** proposed, not implemented. **Authority:** advisory only — never sizes, orders,
stops, or writes to a broker.

## The gap, stated precisely

On 2026-09-05 three watchlist names were up 15–40% on the homepage movers board and
nothing told the operator. The data was all present. Nothing was watching it.

Two distinct absences, and they need different fixes:

1. **Nothing is change-triggered.** Every research job on this box is schedule-triggered
   — `*/30 4-9`, `30 9-15`, `0 18,22`. They sweep a universe on a clock. A sweep cannot
   notice that *this* name is behaving unlike itself, because it treats every name the
   same on every pass.
2. **Nothing ever asks what to ask.** Questions come from templates
   (`hermes_research_prompt.py`) and topic lists. No component reads the corpus we
   already hold on a subject and proposes the *next* question. Research is therefore
   only ever as good as the question someone thought of in advance.

The second is the one the operator asked for, and it is the harder one.

## What already exists (this is mostly wiring, not new machinery)

| piece | where | state |
|---|---|---|
| evidence corpus | `news_articles` 115,378 · `catalyst_events` 136,052 · `hermes_external_research` 48,456 · `research_insights` 46,717 | live |
| identity spine | `document_mentions.subject_guid` — **91,949 / 91,949**, 3,412 subjects | live, complete |
| evidence assembly | `hybrid_rag_context_adapter.py`, `rag_retrieval.py` | live |
| prompt discipline | `hermes_research_prompt.py` — fact/inference separation, advisory framing | live |
| research lanes | free OAuth → `deepseek-flash` → **ask the operator** (`LlmEscalation@v1`) | live |
| spend governance | `cio_governed_model_bridge` — four caps, reservations | live |
| answer quality | `hermes_external_research.usefulness_score` | being backfilled |

**Nothing new is needed for detection inputs.** `ticker_prices` carries only
`close_price` — no high/low, so ATR cannot be derived there — but ATR already exists in
`indicator_confluence_cache.atr` and `aegis_symbol_snapshot_nightly.atr`. Use those.
Do not recompute, and do not add an OHLC ingest for this.

## Stage 0 — the spine must reach the corpus first (prerequisite, not polish)

A dossier keyed on `subject_guid` can only see what carries one. Measured 2026-09-06:

| source | on the spine? | rows |
|---|---|---|
| `document_mentions` | yes — 99,854 / 99,854 | complete |
| `news_articles` | **partial — 27,263 / 115,378** | 88,115 invisible |
| `hermes_research_intelligence` | **partial — 16,594 / 33,336** | 16,742 invisible |
| `catalyst_events` | **no column at all** | 136,052 invisible |
| `hermes_external_research` | **no column at all** | 48,456 invisible |
| `research_insights` | **no column at all** | 46,717 invisible |

**About 336,000 rows cannot be joined to a subject.** Two thirds of the corpus is
unreachable by identity. Building the dossier before fixing this produces a layer that
looks like it is reading everything and is in fact reading a third — the most dangerous
possible failure here, because it fails silently and *plausibly*.

So stage 0 is: add `subject_guid` + `issuer_guid` to the three tables that lack them, and
finish the backfill on the two that are partial. The machinery already exists —
`document_mentions.extract()`, `subject_from_symbol()`, and the resolver in
`cio_subject_guid.py`. This is backfill, not new inference.

Rank is one-way, as everywhere else on the spine: `CONFIRMED > CANDIDATE > UNRESOLVED`,
and a backfill may raise a row's status but never lower it.

## Every artifact this layer creates is addressable

The operator's requirement: *the question needs a unique ID, and it has to carry the
other IDs related to the subject — we don't want to lose anything.*

GUIDs are minted the way the rest of the spine mints them — `security_identity.py:30`,
`uuid5(NAMESPACE_URL, "tradeai:{namespace}:{value}")`. `uuid5` is a pure function, so the
same inputs always produce the same id. That property is doing real work here:

```
question_guid = uuid5("tradeai:question:{subject_guid}|{trigger_guid}|{normalized_text}")
```

- The **same** question, about the same subject, from the same trigger → **same id**.
  It dedupes instead of accumulating. This is the fix for the class of bug where a
  detector re-emits the same finding forever and nobody can tell how many real ones
  there are.
- The **same** question after a **new** trigger → **new id**. Correct: "is the thesis
  still intact?" asked after an earnings miss is genuinely a different question from the
  same words asked last month.

Every artifact carries the same lineage envelope `document_mentions` already defines —
`source_table`, `source_id`, `subject_guid`, `issuer_guid`, `identity_status`, `role`,
`role_source`, `role_confidence`, `matched_via`, `schema_version`, `authority` — plus the
edges that make it traversable in both directions:

| edge | from a question you can reach | why it must not be lost |
|---|---|---|
| `subject_guid`, `issuer_guid` | the company, and everything else about it | the join that makes a dossier possible at all |
| `trigger_guid` | the `MaterialChange` that prompted it | "why are we asking this now" |
| `narrative_guid` | the state description it was drawn from | the reasoning, not just the conclusion |
| `cited_ids[]` | every dossier row the model used | ungrounded questions are dropped; this is the proof |
| `answer_ids[]` | research that answered it, and its `usefulness_score` | closes the loop and re-ranks the next dossier |
| `supersedes_guid` | the question this one replaces | **nothing is deleted** — a refined question points back |
| `run_guid`, `lane`, `model` | which run, lane and model produced it | attribution, not just a count |

**Append-only.** A question is never overwritten or removed; a better one supersedes it
and the chain stays walkable. That is the same bitemporal discipline as `MemoryFact@v2`,
and it is what "we don't want to lose anything" means in practice — not "keep the rows"
but "keep the *edges*", because a row whose links are gone is not recoverable knowledge,
it is orphaned text.

Questions also land in the same shape as `inbound_operator_questions`, which already
carries `subject_guid`/`issuer_guid`. So a question the operator asks and a question the
system proposes are the same kind of object on the same spine, and can be ranked,
answered and scored by the same machinery.

## Shape

Six stages, and **exactly one of them uses a model** — stages 3 and 4 are two outputs
of a single call. That is the whole design principle. The operator's own framing was
"we have the deterministic information, it's just not being analyzed and processed
intelligently": identity, detection and assembly stay deterministic so they are cheap,
testable and explainable, and the model is spent only where judgement is genuinely
required — describing what this looks like, and deciding what is worth asking next.

```
  [0] spine            [1] detect          [2] assemble         [3] characterize
  backfill guids       deterministic       deterministic        ONE llm call
  ~336k rows        →  MaterialChange@v1 → SubjectDossier@v1 →  StateNarrative@v1
                            │                                          │
                            │                                          ▼
                            │                              [4] interrogate
                            │                              SAME llm call, second output
                            │                              DueDiligenceQuestion@v1
                            │                                          │
                            └── notify operator ───────────────────────┤
                                (narrative + top questions)            ▼
                                                              [5] route to lanes
                                                              answers → usefulness_score
                                                              re-ranks the next dossier
```

### 1. Detect — `MaterialChange@v1`

A new producer, `material_change_detector.py`, run every 15 minutes against tracked
subjects only (watchlist + holdings — not the whole universe).

Change kinds, each deterministic and each carrying its own magnitude:

| kind | test | why not a fixed % |
|---|---|---|
| `price_excursion` | `abs(move) / atr >= K` | 8% is noise in one name and a five-sigma event in another. Normalising by the name's own ATR is the only threshold that means the same thing twice. |
| `catalyst_new` | unseen `catalyst_events` row for the subject | — |
| `news_burst` | article count over baseline for that subject | baseline per subject, same reason as above |
| `mention_spike` | `document_mentions` rate over baseline | — |
| `thesis_contradiction` | new evidence opposing a stored thesis | the highest-value kind, and the one a sweep can never find |

Every row records `subject_guid`, `kind`, `magnitude`, `observed_at`, and the row ids of
the evidence that fired it. **Attribution, not just a count** — a change nobody can trace
back to its evidence is not actionable, and this session spent a day on exactly that
failure mode.

### 2. Assemble — `SubjectDossier@v1`

Deterministic. Keyed on `subject_guid`, not ticker: the identity spine already resolves
name and CUSIP, and a dossier keyed on a symbol silently splits when a symbol changes
hands.

Bounded and *ranked*, not "everything":

- prior research, **ranked by `usefulness_score`** — the backfill currently running is
  what makes this possible; without it, the dossier is ordered by recency, which
  reliably surfaces the most recent noise instead of the most useful prior work
- open questions previously asked and **never answered**
- questions previously asked and **answered** — so the model does not re-ask them
- stored theses and their outcomes
- the triggering evidence

### 3. Characterize — `SubjectStateNarrative@v1`

*"Something needs to say, in sentences, what this looks like."*

Before asking what to ask, the layer states what it sees: a short, plain description of
the subject's current situation, drawn only from the dossier.

This is a separate artifact from the questions, and it needs its own `narrative_guid`,
for three reasons:

- **The question cites it.** "Why are we asking this now" is only answerable if the
  reasoning that produced the question is itself addressable. Storing only the question
  keeps the conclusion and discards the thinking.
- **It is the thing the operator actually reads.** A Telegram alert carrying five
  questions and no orientation is a puzzle. One carrying *"up 4.1× its normal daily
  range on no filing; last thesis (July) assumed flat margins; two analyst notes since
  contradict that"* is intelligence.
- **It is independently checkable.** A narrative can be wrong in ways a question cannot
  be — it makes claims. Every sentence carries the `cited_ids` behind it, so a false
  claim is traceable to the row that produced it rather than to "the model said so."

Hard rules, each from a defect this system has already paid for:

- **Every claim cites a dossier row.** Uncited sentences are dropped, not softened.
  This is the no-invented-structure rule from the Maria fabrication fix, and it is the
  reason this stage can be trusted at all.
- **Absence is stated, never inferred.** "No filing found since 2026-07-12" is a claim
  about the corpus, not about the world, and must read that way. A layer that quietly
  turns "we have nothing" into "there is nothing" manufactures false confidence — and
  after stage 0 there will still be rows the spine has not reached.
- **A narrative is never a recommendation.** It describes; it does not advise, size, or
  direct. Advisory-only, like everything else in this layer.

The narrative and the questions come from **one** model call with two outputs, not two
calls. They are the same act of reading — splitting them doubles the spend and lets the
question drift from the description it is supposed to follow from.

### 4. Interrogate — `DueDiligenceQuestionSet@v1`

The second output of the same model call. Input: the change, the dossier, and the narrative just written. Output: ranked questions,
each with

- **why now** — which dossier item or trigger makes this newly worth asking
- **what would settle it** — the observation that would answer it either way
- **which lane** should answer it (free OAuth, paid, or operator judgement)

Three rules, each paid for by a specific past failure:

- **Every question must cite a dossier item id.** A question citing nothing is dropped,
  not surfaced. This is the no-invented-structure rule from the Maria fabrication fix.
- **"No new question" is a valid, recorded answer.** It must be distinguishable from
  "did not run" — `questions_produced` is `null` when unmeasured and `0` when genuinely
  none. Two states cannot express "no input"; that defect cost five false alarms and
  three thousand real rows this week.
- **Lane order is the standing policy:** free OAuth → `deepseek-flash` → **ask the
  operator before any further paid lane**. A cap refusal is a `429`, not a fault, and it
  stops the run rather than being retried.

### 5. Route and close the loop

Questions go to the existing research lanes. Answers land in
`hermes_external_research`, get scored for usefulness, and that score re-ranks the next
dossier. The loop closes on itself, which is the only part of this that compounds.

## The full lifecycle — a question is not done when it is answered

The operator's requirement: *follow the whole life cycle — research goes out, the answer
comes back, it gets analysed again, and it cycles.*

Most of the state already exists on `hermes_external_research`: `status`, `lane_used`,
`budget_tier`, `budget_decision`, `research_expires_at`, `research_reason`,
`operator_action`, `downstream_outcome`, `usefulness_score`. The loop is not new
machinery; it is those fields being read by something that closes on itself.

| state | meaning | what moves it on |
|---|---|---|
| `ASKED` | question minted, not yet routed | lane selection |
| `ROUTED` | sent to a lane | an answer, or a lane refusal |
| `ANSWERED` | answer stored, cited back to `question_guid` | usefulness scoring |
| `SCORED` | `usefulness_score` set | re-ranks the next dossier |
| `EXPIRED` | past `research_expires_at`, never answered | re-ask, or retire with reason |
| `SUPERSEDED` | a later question replaced it | `supersedes_guid` chain |
| `RETIRED` | answered and no longer load-bearing | librarian retention |

Two rules make this a cycle rather than a queue:

- **An answer is an input, not an ending.** A stored answer changes the dossier, which
  changes what the next material change is worth asking about. That is the only part of
  this design that compounds — and the reason `usefulness_score` matters more than it
  looks: it is what stops the loop re-amplifying its own noise.
- **An unanswered question is evidence too.** A question that expires unanswered is a
  standing gap, and it belongs in the next dossier as one. Silently dropping it would
  make the system look better informed than it is.

**Nothing is deleted.** Expired and superseded questions keep their edges — the
`supersedes_guid` chain stays walkable, so "what did we think in July, and what changed"
is answerable from the graph rather than reconstructed from memory.

## Lane policy — free first, always

Standing operator policy, unchanged from `LlmEscalation@v1`:

1. **Free OAuth lanes first** (Grok, ChatGPT). Today they carry ~500 calls/day at $0.00.
2. **`deepseek-flash`** when the free lanes fail or are exhausted. Measured on the
   usefulness backfill at **$0.000133/row**.
3. **Ask the operator before any further paid lane.** This is a hard STOP, not a
   preference: `run_with_escalation()` notifies and stops rather than escalating on its
   own, and a failed notification is never treated as permission to spend.

Stage 0 spends nothing at all — identity resolution is a registry lookup, a pure function
of the symbol, with no model on any row. Stages 1–2 also spend nothing. The first cost
in this design is stage 3/4's single call per material change, which is bounded by how
many things actually moved, not by the size of the universe.

Governance is the existing bridge: four caps, reservations, and a cap refusal that
returns `429` and **stops** rather than being retried — so a budget ceiling can never
again look like an outage, and can never consume a queue.

## Notification — the operator's actual ask

A `MaterialChange` above the material threshold on a **watchlist or held** name sends
Telegram immediately, carrying the change, its magnitude in ATR units, and the top
questions. That is the Friday case: not "AAPL moved 15%", but "AAPL moved 4.1× its
normal daily range; here is what we already knew, and here is what we should now be
asking."

Signal discipline: **notify on the change, not on the sweep.** A detector that fires
every fifteen minutes trains the operator to ignore it, and a muted alarm is worse than
no alarm — this system has already lost detectors that way.

## Guard rails, each one already paid for

- `rows_produced` / `questions_produced`: `null` = unmeasured, `0` = measured zero.
- Attribution on every row — which detector fired, which lane answered, which model.
- Governance refusals are `429` and terminal; they stop a run, never consume the queue.
- No runtime state in tracked config.
- Retention: question sets follow the mentions policy — operator-referenced subjects
  held 365 days and confirmed before deletion.
- **Advisory only.** This layer proposes questions. It never sizes, orders, or stops.

## Build order

0. **Extend the spine** — `subject_guid`/`issuer_guid` onto `catalyst_events`,
   `hermes_external_research`, `research_insights`; finish `news_articles` and
   `hermes_research_intelligence`. Nothing downstream is trustworthy until this lands,
   because a dossier reading a third of the corpus fails silently and plausibly.
1. `material_change_detector.py` + `MaterialChange@v1` — deterministic, testable with no
   model. **Ship and watch it alone first.** If the thresholds are wrong, everything
   downstream is noise, and that is far cheaper to discover here.
2. Telegram on material change. Delivers the operator's original ask at zero model spend.
3. `SubjectDossier@v1` assembly over the existing RAG adapter, ranked by
   `usefulness_score`.
4. `SubjectStateNarrative@v1` + `DueDiligenceQuestion@v1` — one model call, two outputs,
   shadow-first: generate and store, do not surface, until the narratives have been read
   and judged worth surfacing.
5. Route to lanes; answers re-rank the next dossier via `usefulness_score`.

Stages 0–2 answer the original complaint on their own. Stages 3–5 are what make it
compound.

## Open questions for the operator

- **`K` for `price_excursion`.** Suggest starting at 3× ATR and tuning against the
  2026-09-05 movers, which are a known-good labelled case.
- **Universe.** Watchlist + holdings only, or also names with open theses?
- **Notification hours.** Market hours only, or pre/post-market too?
