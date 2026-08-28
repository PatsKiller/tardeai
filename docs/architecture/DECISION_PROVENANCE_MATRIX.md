# Decision provenance matrix — 2026-08-28

Answers one question: **which parts of what the operator reads are the system's own
view, and which are rules?**

`[VERIFIED]` = a command was run against live state and its output is quoted.
`[CODE]` = read from source in the live release. `[DOC-CLAIM]` = a document asserts it.

Posture: `READ_ONLY_ADVISORY`, `MBI 0`. This census changed no code.

Live release measured: `9783395a-main-exact-phase2-20260828-082142`.

## Provenance of this document

The draft exists as an operator-held document; it is **not in this repository**, at that
path or any other, in the working tree or anywhere in git history `[VERIFIED]`. The
operator supplied it on 2026-08-28, after the first census pass. Its vocabulary and the
Phase 9 brief's agree, so the classifications below are unaffected. The reconciliation
against the draft is the final section of this document, and it resolves the one row the
draft marked unresolved.

## Vocabulary

| tag | meaning |
|-----|---------|
| **D** | deterministic — computed from state by fixed rules |
| **T** | template — fixed prose, possibly with values interpolated |
| **M** | model-assisted and gated |
| **A** | agent-originated judgment |
| **S** | snapshot-derived — a value copied from a stored snapshot |

---

## THE THREE COUNTS

### 1. Fields classified **A** (agent-originated): **0**

No operator-facing field on any surface carries agent-originated judgment.

### 2. Fields classified **M** (model-assisted, gated): **1 in code, 0 delivered**

`Overnight Risk Analysis` in the Aegis morning brief, sourced from
`risk_synthesis_results.top_risks->0->>'action'` and commented in source as "from deep
LLM window" `[CODE aegis_morning_brief_delivery.py:277-290]`.

It has delivered nothing in 97 days `[VERIFIED]`:

```
risk_synthesis_results  total rows                     3
                        most recent generated_at       2026-05-23 23:08:05-04:00
                        eligible for the brief now     0     (needs < 18h old)
```

The query is guarded by `except Exception: pass`, so its absence is silent. The brief
renders without the section and looks complete.

### 3. Fields **T** or **D** rendered in a register implying **A**: **9**

This is the defect list. Each is honest computation presented in the voice of a view.

| # | field | surface | actual class | why it reads as judgment |
|---|-------|---------|--------------|--------------------------|
| 1 | `portfolio_implication` | CIO product, evening packet | **T, unconditional constant** | "Preserve quality growth exposure, keep cash for dislocations, and do not force lower-quality replacements." Identical text every run, no branch, no input `[CODE cio_investment_product.py:502-506]`. Reads as portfolio guidance; is a literal. **The strongest member of this list.** |
| 2 | "Nothing requires action today" | Telegram, `executive_summary` | **D** | Emitted when `action_book.DO_NOW` is empty. Reads as a considered all-clear. |
| 3 | `executive_summary` (the label) | Command Center, packet | **T** | The name asserts synthesis. The value is `brief["summary"]`, an f-string `[CODE cio_operator_product.py:205]`. |
| 4 | `RISK ON TREND — SELECTIVE RISK` | every surface | **D** | `f"{label.upper()} — SELECTIVE RISK"` from a regime label `[CODE cio_investment_product.py:501]`. The em-dash and "SELECTIVE" imply a stance; the suffix is a constant. |
| 5 | `temperament.narrative` | CIO product | **T** | f-string over four counters `[CODE :519-522]`. "Temperament" implies disposition. |
| 6 | `action_now` | Command Center, product | **D** | A filter on `urgency == "NOW"` `[CODE cio_operator_product.py:239]`. See the legibility note below. |
| 7 | "Closest re-entries: ATAI +3.0% vs exit …" | Telegram | **D** | Ranked by `abs(pct_above_exit)`. Reads as a shortlist someone chose. |
| 8 | `next_reviews` | Command Center | **T** | "next material generation or next session — standing cadence, not a decision" repeated per entry. |
| 9 | `instructions` | evening packet | **T** | Five fixed lines telling a downstream agent how to behave. Reads as tasking. |

#### The legibility case, in one product `[VERIFIED]`

```
executive_summary : "RISK ON TREND — SELECTIVE RISK. Nothing requires action today. …"
action_now        : 8 entries — AXTI, IRDM, ARKG, FJSCX, MNTS, ELAB, … all decision=AVOID, urgency=NOW
action_book.DO_NOW: 0
```

These are not contradictory. `AVOID` at `urgency=NOW` means *do not buy this now* — a
thing not to do. `DO_NOW` counts things to do, and is genuinely 0.

But an operator reading a field named `action_now` holding eight rows, beside a sentence
saying nothing requires action, cannot reconcile them without knowing that one counts
actions and the other counts urgent non-actions. **Both are D. Neither is wrong. The
surface is illegible.** This is the census's central finding in miniature.

---

## THE MATRIX

Cadence is when the value can change, not when it is displayed.

### Surface 1 — CIO run-complete Telegram (the only producer that delivered in 24h)

`[VERIFIED]` outbox, last 24h: 6 `NOTIFICATION_ENQUEUED`, 6 `DELIVERY_CONFIRMED`, sole
actor `cio_run_worker`. 148 modules can send to Telegram; one did.

| field | tag | producer | cadence | distinguishable? |
|-------|-----|----------|---------|------------------|
| subject `CIO Run Complete — <run_id>` | D | `cio_run_worker._emit_notifications` | per run | yes — it is plainly an id |
| posture clause | D | `cio_investment_product.build_temperament` | per brief | **no** |
| "Nothing requires action today" | D | `cio_investment_product._summary` | per brief | **no** |
| closest re-entries + distances | D | `cio_investment_product._nearest_reentries` | per brief | **no** |
| tracking counts | D | `_summary` over `reentry_book.counts` | per brief | yes — plainly counts |
| change-since-last | D | `cio_investment_product._changed_since` | per brief | yes |
| "Advisory only — no orders placed" | T | `_summary` | fixed | yes — explicit disclaimer |

### Surface 2 — Command Center `/v3/cio` → operator product

25 `REQUIRED_SECTIONS` `[VERIFIED]`. The served page is a shell; substance comes from
`cio_operator_product.build_operator_product`, rebuilt on demand (`persist=False`).

| section | tag | producer | cadence | distinguishable? |
|---------|-----|----------|---------|------------------|
| `product_id`, `generation_id`, `as_of` | D | `build_operator_product` | per build | yes |
| `executive_summary` | T | `cio_investment_product._summary` via `brief["summary"]` | per brief | **no** |
| `action_now` | D | filter `urgency == "NOW"` | per brief | **no** — see above |
| `decisions` (25 live) | D | `entries` from governed verdicts | per brief | yes |
| `standing_decisions` (9 live) | D | filter on decision ∈ HOLD/WATCH/WAIT/NO_ACTION | per brief | yes |
| `portfolio`, `cash`, `data_quality` | S | `_holdings_sections` ← `portfolio.holdings.current` | per reprice | yes |
| `risk` | D | `brief["risk"]`, else a fixed note | per brief | partly |
| `watch`, `reentry` | D | `opportunity_book` / `reentry_book` | per brief | yes |
| `sector`, `industry`, `catalysts` | S | `canonical_cognition_bind.bind_market_context` | per bind | yes |
| `themes`, `earnings`, `macro` | S | `brief` passthrough | per brief | yes |
| `research_changes` | D | `symbol_thesis_review.daily_thesis_changes` | daily | yes |
| `research_gaps` | D | `brief` passthrough | per brief | yes |
| `specialist_disagreements` | D | `brief` passthrough — **live value `[]`** | per brief | yes |
| `outcomes_learning` | D | `cio.outcomes` counters | per resolution | yes |
| `policy_gaps` | D | `_ops_degradation` | per build | yes |
| `next_reviews` | T | fixed string per entry | per brief | **no** |
| `completeness` | D | `cio_operator_product.completeness` | per build | yes |

### Surface 3 — Aegis morning brief (Telegram + `.md` export)

| field | tag | producer | cadence | distinguishable? |
|-------|-----|----------|---------|------------------|
| summary line | S | `brief["summary"]` upstream | daily | **no** |
| top sections / items | S | `brief["sections"]` | daily | yes |
| Steph Queue counts | D | `_get_steph_queue` ← `aegis_steph_escalations` | daily | yes |
| **Overnight Risk Analysis** | **M** | `risk_synthesis_results` (LLM) | **dormant since 2026-05-23** | **no** — absent, not marked absent |
| Event Intelligence | D | `_get_event_digest` | 24h | yes |
| Watch Directives | D | `_get_watch_directives_brief` | daily | yes |
| Gain Guardian | D | `_get_gain_guardian_brief` | daily | yes |
| Pipeline health | D | `_get_pipeline_health_for_brief` | 12h | yes — fixed in #573 |
| Provenance footer `model=aegis` | T | fixed string | fixed | **misleading — see below** |

The export footer reads `Provenance: model=aegis` `[CODE :521]`. No model produces this
brief. The one model-derived field it can carry has been empty for 97 days.

### Surface 4 — Aegis evening packet (JSON, consumed by an isolated agent session)

| field | tag | producer | cadence | distinguishable? |
|-------|-----|----------|---------|------------------|
| `cio.desk` | T | same `_summary` string | per brief | **no** |
| `cio.operator_product` | D | `build_operator_product(persist=False)`, truncated | per build | yes |
| `cio.reentry` | D | `reentry_book`, truncated | per brief | yes |
| `health.*` | D | health agent counters | per cycle | yes |
| `holdings_protection.*` | S | holdings store | per reprice | yes |
| `advisory.body` | D | `advisory.current`, truncated | per build | yes |
| `instructions` | T | five fixed lines | fixed | **no** |

---

## What this says about the operator's question

**Nothing the operator reads is the system's own view.** Count A is zero, and the single
M-class field has been silent since May. Every sentence that sounds like judgment is a
rule, a filter, or a constant.

The system is not *pretending* — no field is falsified, and several carry explicit
disclaimers. The gap is one of register: nine fields are written in the voice of an
analyst and produced by an `if` statement. `portfolio_implication` is the clearest case,
because it is literally the same paragraph of advice every single run.

Two structural observations follow, both for the operator:

1. **The register is fixable without new capability.** Marking each field with its class
   at the point of display costs nothing and would answer the question permanently.
2. **Whether there *should* be an A-class field is a scoping decision, not a defect.**
   Where the model output currently goes is the subject of P9.1 and is deliberately not
   answered here.

---

# Reconciliation against the operator's draft (2026-08-28)

The draft was supplied after the first census pass. Its vocabulary matches, so no
classification changed. Six rows are affected.

## 1. The one row the draft marked unresolved — **RESOLVED**

> *"Item 8, self-tagged `(INFERENCE)` — **M or A — unresolved** — the only
> non-deterministic sentence emitted in 24h; subject was a `ModuleNotFoundError`"*

**It is A. Genuinely agent-originated — and produced entirely outside this system**
`[VERIFIED]`.

The evening packet is not a report. **It is a prompt.** `aegis_evening_packet.py:186-198`
builds it:

```
FRESH SESSION. Do not inherit prior conversation.
Read ONLY this bounded packet file and reply with 'Aegis Evening Scan'.
Rules:
- Maximum 8 findings.
- Sections: protection / CIO-reentry / research-news / runtime / freshness.
```

Three facts fix the identification beyond doubt:

- the live packet carries `max_findings: 8` `[VERIFIED]`, matching "Items 1–7 … Item 8"
  exactly;
- its `instructions` name the five sections the operator saw;
- **no `(FACT)` / `(INFERENCE)` line tagging exists anywhere in this codebase**
  `[VERIFIED]` — grepping every script returns only unrelated matches (entity-type
  inference, options positioning, financial-senses source types).

The items are written by the OpenClaw Aegis session that reads the packet. This repository
composes the prompt and never sees the reply.

### What that does to the headline count

The census counted **A = 0**, and that stands *for fields this system produces*. The
reconciled statement is sharper and worse:

> **A = 0 inside the pipeline. A = 1 arriving from outside it, ungated.**

The single piece of genuine judgment the operator receives each day is produced by a
component that none of this system's provenance, gating, persistence, or lineage
machinery covers. It is not validated by a schema, not recorded in the run store, not
counted in `MODEL_CALL_RECORDED`, and not reproducible from anything stored here. That
is why P9.1 found no model call and this matrix found no A field, while the operator
correctly observed one non-deterministic sentence: **both are true, and they are about
different components.**

It also explains the subject of that sentence. An external agent given a bounded packet
and told to find at most 8 things will report what is visibly wrong in the packet — and
what was visibly wrong was a `ModuleNotFoundError`. The judgment is real; the material it
was given to judge was runtime diagnostics.

## 2. `(FACT)` / `(INFERENCE)` self-tagging — worth generalising, but there is nothing yet to tag

The draft calls this *"the closest thing the system has to this matrix, and worth
generalising rather than replacing."* Agreed, with one correction: **the tagging is not
the system's.** It is the external agent's convention, applied to its own output.

Generalising it into the pipeline means adopting the vocabulary — which is what this
matrix does. But a pipeline-side `(INFERENCE)` tag would currently have nothing to mark:
every pipeline field is D, T, or S.

## 3. Command Center `/v3/cio` — no longer unclassified

The draft says *"Not yet classified. P9.0 deliverable."* It is classified above: 25
`REQUIRED_SECTIONS`, each with a named producer.

## 4. Position `as_of` lag — larger than the draft records

The draft: *"`as_of` lagged the last reprice by ~3.3h at time of send."* Measured
`[VERIFIED]`:

```
holdings.json   as_of         2026-08-26
                generated_at  2026-08-28 06:15:01 ET
position-level  as_of         2026-08-03, 2026-08-04, 2026-08-26
```

Two days at document level, up to **25 days** at position level. The 3.3h figure was
`holdings_age_hours` from the packet's health block — a different quantity, and the more
flattering one.

## 5. Cross-surface disagreement — answered in P9.3

The draft's open question is resolved: **two independent computations**, proven by two
separate `build_reentry_book` definitions with disjoint signatures. But they compute
*different quantities* under one name — see `docs/audits/P93_TWO_SURFACES_ONE_BOOK_2026-08-28.md`.

## 6. Capability boundaries — deferred to P9.5, one correction

The draft's four candidate boundaries are the right shape. One is already contradicted by
evidence gathered in P9.2: the system **does** initiate research on names outside a
schedule — 184 `S3_REENTRY_CANDIDATE` and 162 `S1_POSITION_LIFECYCLE` situations raised
it. What it does not do is let that research change an action
(`POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION`). The distinction matters for scoping:
the lane exists and runs; it is barred at the last step.

The full sort into built-and-broken / built-and-unwired / never-built is P9.5.

## 7. The maintenance proposal is feasible

> *"A new operator-facing field without a row here should fail CI, in the same shape as
> the dark-contract gate."*

The dark-contract gate (#567) is the working precedent, and the shape transfers: enumerate
fields from the known producers, diff against the rows here, fail on an unexplained new
one, and seed today's set as inherited. The honest caveat is that "operator-facing field"
is harder to detect statically than "versioned schema literal" — the gate would need an
explicit producer registry rather than a regex. That is a real cost and should be scoped,
not assumed.

## 🛑 Census complete — held for operator review before P9.1.
