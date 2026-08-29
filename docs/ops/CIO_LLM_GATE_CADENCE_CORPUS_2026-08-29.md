# CIO LLM gate + cadence + institutional corpus (2026-08-29)

Implements the diagram law that was missing in code: **free-first → residual →
LLM only if unresolved AND material**, outcomes changing the *next* gate, and
not everything running every day.

Companion: `docs/ops/CIO_INSTITUTIONAL_CORPUS_MAP_2026-08-29.md`.

## Headline

On CURRENT, over the real open plan book:

    445 open researchable plans  ->  8 eligible model calls

    skip   437     flash 8
      not_material                353
      event_driven_kind_no_event   38
      duplicate_subject_same_day   35
      kind_never_uses_llm          11

Zero paid calls made producing that report. Default backend is a stub.

## What was added

| module | role |
|---|---|
| `scripts/lib/cio_research_gate.py` | `ResearchNeedDecision@v2` — routing gate + cadence + ops surface |
| `scripts/lib/cio_corpus_index.py` | read-only adapter over the corpus that already exists |
| `scripts/lib/cio_research_templates.py` | versioned per-gate prompt skeletons |
| `scripts/lib/cio_source_discovery.py` | bounded search-for-new; CANDIDATE refs only |
| `scripts/cio_research_gate_report.py` | dry report CLI; makes no model calls |

`research_need_decision.py` (v1) is **unchanged**. It answers *how much*
research a symbol needs; v2 answers *what should run now*. Its existing callers
(`closed_loop_maturity`, `symbol_thesis_research`) are untouched.

## The routing law

    not material                  -> skip
    cost cap hit                  -> skip until next_eligible_at   (NOT a bug)
    prior execution_language      -> skip, fail closed, no next paid gate
    cadence not due               -> skip
    source-hash gate says fresh   -> reuse
    VALID row inside TTL          -> reuse
    corpus closes the dimension   -> corpus_hit                    (no call)
    unreviewed paid artifact      -> grok_critique                 (before attach)
    flash PARTIAL/truncated       -> pro                           (same research_id)
    pro unresolved + material     -> openai
    otherwise                     -> flash

Ordering is load-bearing and pinned by tests: a cost cap is read *before*
escalation, so a capped day cannot still buy a bigger model; execution language
fails closed *before* any escalation at all.

## One freshness law, not two

`research_source_index.decide()` already owned "is this source stale or
unchanged", with class SLAs in `freshness_days_for`. v2 **delegates** to it
rather than keeping a second opinion.

This was deliberate. A second freshness law over the same question is the exact
shape of the `total_cash` bug closed earlier today (#634/#635): two writers, one
field, drift invisible until someone diffs them by hand. The local TTL table is
only a fallback for callers that supply no `source_id`, and a fired event
overrides a source-index skip so a real catalyst is never swallowed by an
unchanged hash.

## Cadence TTLs

| kind | TTL | notes |
|---|---|---|
| `held_core_thesis` | 7d | unless a material event fires |
| `new_position_if` | 7d | or first-seen |
| `watch_block` | **never** | watch BLOCK gets no LLM at any materiality |
| `s6_concentration` | event only | threshold cross / operator defer expiry |
| `earnings_calendar` | event only | `days_to_event <= 5` |
| `corpus_refresh` | 7d | weekly max |
| default | 3d | |

Plus **same-day subject collapse**: one model class per `research_id` per
calendar day, falling back to `(kind, symbol)` when a plan has no research_id.
That single rule took the eligible set from 43 to 8 — 36 open S5 cash plans are
36 rows asking one question, and giving each its own Flash call is the grind
this gate exists to stop.

A peek that finds nothing eligible is healthy. `claimed=0` is not a failed run.

## Corpus — and a constraint worth naming

Verdict on the 20–30 publication set: **`CORPUS_UNLOCATED`**. What exists is
`cio_research_library.library_facts()` — 11 facts over 7 families, defined in
code. Only `seasonality` has depth (5 facts); every other family holds a single
placeholder.

More importantly, the corpus carries **its own application law** in
`evidence_grade`, and it is stricter than "the almanac answered it":

| grade | registry wording | may close a gap |
|---|---|---|
| A / B | independently reproduced — *risk-modifier only*, max 10% conviction, never a standalone sell | **yes**, context dimensions only |
| C | "challenge-prompt / context only" | no |
| D | "must not be treated as a Trade AI fact" | no |
| X | reproduction contradicts the claim — do not apply | no, and flagged |

So `corpus_hit` is narrower than the brief implied: only a reproduced A/B fact,
only for a context-level dimension. Entity-level questions (`bear_case`,
`structural_drivers`, `what_is_priced_in`) can never be closed by an
entity-agnostic corpus, and that list is explicit in code so a future family
cannot quietly acquire authority over a name-level question. Letting a grade-D
citation close a gap would launder an unreproduced claim into a resolved
question and skip the research that would have caught it.

A `corpus_hit` carries the ceiling forward: `max_influence_pct`,
`standalone_sell: False`, `creates_trim: False`.

## Templates

Four versioned skeletons — Flash classifies and asks but never answers; Pro
answers only the supplied `question_ids` with citations; OpenAI takes only the
residual and returns schema; Grok critiques and never performs the research.
Carried across every hop: `question_ids`, `artifact_id`, prior outcome, corpus
refs, prior critique.

Every template names the forbidden constructions in its system prompt (buy /
sell / trim / flatten / liquidate / place / submit / execute directed at the
reader, prices-as-facts, notify copy) — belt and braces next to the output lint,
which remains the enforcement. Corpus refs travel *with their grade* so a
grade-D citation cannot read as settled.

## Search-for-new (bounded)

Dry by default. `--apply` stores CANDIDATE refs only — never facts, never with
an evidence grade. Cap 3 per entity per week, deduped against the existing
library. No download, no scrape, no new dependency. A candidate becomes a fact
only via a separate critique pass.

## Verification

- 57 gate/corpus/template tests, including the full decision matrix, cadence
  re-entry, ordering precedence, and the delegation guard
- existing rails re-run green: `test_cio_wave2c_301_308_locks` (cio_run stays
  `DETERMINISTIC_PRODUCT`), `test_cio_wave2c_161_190_research`,
  `test_cio_pipeline_step1_research_attach` — 25 passed
- host dry report on CURRENT: 445 considered, 8 eligible, **0 live paid calls**

`tests/test_research_skip_gate.py::test_run_apply_skip_gate_blocks_metered`
fails, but it also fails on clean `origin/main` — pre-existing, in the recorded
baseline, not from this change.

## Not done, deliberately

No cap raised. No notify, no Telegram producer. No second cron. No model called
from `cio_run`. Hermes worker not replaced. No web scraped. Wave 3 not started.
