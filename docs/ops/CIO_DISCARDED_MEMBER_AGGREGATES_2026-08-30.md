# Aggregates that discard their members — system inventory

Date: 2026-08-30 · `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0`
Scope: read-only inventory + three recomputations. **Nothing was rewritten or remediated.**

Companion to `docs/ops/CIO_CATALYST_SKIP_COMPOSITION_2026-08-30.md`, which proved
the principle on one tally. This paper asks the follow-on question: **where else
does the system keep a count and throw away the rows behind it?**

Tags: `[VERIFIED]` = command run, output quoted · `[CODE]` = source read ·
`[DOC-CLAIM]` = a document asserts it.

---

## The principle

**An aggregate that discards its members is a hypothesis, not a measurement.**
It can be quoted but never audited. The catalyst case showed the cost: 35,928
"unregistered symbols" was really 374 directive slugs + 1,071 English words +
**149 real tickers**. A 149-name cleanup read as a structural identity failure
because nobody could get from the number back to the rows.

A tally qualifies for this inventory if **a reader cannot get from the number
back to the rows.** Severity then splits three ways, and the split matters more
than the headcount:

| class | meaning | remedy cost |
|---|---|---|
| **A — irrecoverable** | source rows gone, overwritten, or never materialized; the number can never be decomposed | high; requires re-instrumenting the producer |
| **B — recoverable, not retained** | members droppable-but-rederivable from a live source | low; retain a list, or document the recompute |
| **C — partial** | some members named, the rest silently dropped | medium; the truncation is undeclared |

Class B is the common case and the cheap fix. **The catalyst exemplar is class A** —
which is why it did real damage.

---

## Corrections to the brief that commissioned this work

Five things in my tasking did not survive contact with the repo. Recording each,
because every one would mislead the next reader.

1. **The companion write-up is not merged.** It lives on branch
   `docs/catalyst-skip-composition` (commit `0663e09a`). `origin/main` at
   `6bae6529` contains no such file.
   `[VERIFIED]` `git ls-tree origin/main -- docs/ops/ | grep -i catalyst` → empty.
2. **`data/cio/` is not in the canonical rebuild tree.** The live store is
   `/home/johnclaw/trade-ai-releases/persistent-state/data/cio/`, reached by symlink
   from `CURRENT/data/cio`. `catalyst_graph_latest.json` exists **only** there; a
   sweep of `trade-ai-v12-rebuild/data/cio/*.json` finds nothing. `[VERIFIED]`
3. **The census is unrunnable in the served release**, so "verify against CURRENT,
   not a checkout" could not be followed literally — see the box below.
4. **No tally in this class is wired to a gate.** The brief asked me to prioritise
   gate-bearing numbers; there are none. `[VERIFIED]` grep for threshold/assert
   comparisons on `completion_rate`, `complete_to_checkpoint`,
   `weighted_full_lifecycle_pct`, `coverage_pct_material` and `insufficient_data`
   across `scripts/` returns only unit-test assertions, never a production gate.
   `P1_WS1_FAILURE_POINT_INVENTORY_2026-08-30.md:59` says the same of the catalyst
   artifact: *"Not wired as gate"*. **Blast radius is documents and product JSON,
   not enforcement.** That is good news, and it should lower this whole class
   relative to anything that does gate.
5. **The frontend is clean.** `[CODE]` No persisted-tally pattern exists on the TS
   side. Every `suppressedCount` in `apps/command-center-v3/src/components/reentry/`
   is a render-time derivation over an in-memory array that is itself displayed.
   Nothing is written. This is a backend-only problem.

> ### The census cannot run in the release it describes
> `[VERIFIED]` Running `scripts/cio_event_lifecycle_census.py` under `CURRENT`
> (`66f97259`, deployed 11:21 today) fails at import:
> ```
> File ".../66f97259.../scripts/cio_event_lifecycle_census.py", line 26
>     from __future__ import annotations
> SyntaxError: from __future__ imports must occur at the beginning of the file
> ```
> Cause `[CODE]`: a `NO_CONSUMER_REASON = (...)` assignment sits **above** the
> shebang and module docstring. PR #705 (`6bae6529`, *"two scripts could not
> compile; the census was unrunnable for 10 hours"*) fixes this on `main`, but
> **the fix is merged and not deployed.** The recomputations below therefore run
> the fixed `main` copy with `--root CURRENT` — same data, compilable code.

---

## Inventory — file-backed stores

All values `[VERIFIED]` by direct read on 2026-08-30. "Members?" = are the
identifiers behind the count retained anywhere in the artifact.

### Class A — irrecoverable

| # | Store | Field | Value | Members? | As-of |
|---|---|---|---:|---|---|
| A1 | `persistent-state/data/cio/catalyst_graph_latest.json` | `skipped.symbol_not_registered` | **35,928** | **NO** | `generated_at` 2026-08-27T17:57:02Z (**3d stale**) |
| A2 | same | `skipped.entity_has_no_issuer` | **2,962** | **NO** | same |
| A3 | `persistent-state/data/runtime/health_inspector_growth_memory.json` | `seen.portfolio_validator_error.count` | **8,306** | **NO** — only `first_seen`/`last_seen`/`last_message` | mtime 2026-08-26 |
| A4 | same | `seen.journal_stale_display.count` | **5,255** | **NO** | mtime 2026-08-26 |
| A5 | `persistent-state/data/runtime/llm_retry_health.json` | `last_7d.by_error.HTTP503` | **6,945** | **NO** — no request/lane ids | `updated_at` 2026-08-26 |
| A6 | `persistent-state/data/runtime/advisory_notif_broker/metrics.json` | `suppressed_dupes` | **2,422** | **NO** | `ts` 2026-08-30T16:00Z |
| A7 | `data/runtime/scalp_lifecycle_funnel_latest.json` | `reject_deferred_reasons[].count` | 332/283/175/156/132/63 | **NO** — elements are `{decision,count}` | `generated_at` **2026-06-28** (2 months) |
| A8 | `docs/ops/CIO_WAVE2_SCOREBOARD.json` | `LLM_GATE.live.skipped_not_material` | **353** | **NO** | none |

A3–A6 are runtime health counters, and they carry a specific ambiguity: they are
monotonic accumulators across restarts. 8,306 `portfolio_validator_error`
occurrences with one retained `last_message` cannot distinguish **8,306 distinct
faults from one fault looping 8,306 times** — the same ambiguity the catalyst
tally had, and recompute 2 below shows it is not hypothetical.

### Class B — recoverable from a live source, but not retained

| # | Store | Field | Value | Members? | As-of |
|---|---|---|---:|---|---|
| B1 | `persistent-state/data/cio/cio_investment_brief.json` | `thesis_universe.insufficient_data` | **4,782** | **NO** | `as_of` 2026-08-30T16:11:52Z (live) |
| B2 | same | `thesis_universe.role_unknown` | **64** | **NO** | same |
| B3 | census `lineage_overlay` (`scripts/lib/cio_lineage_health.py`) | `stalled_at.research` | **640** pub / **685** now | **NO** | see recompute 2 |
| B4 | same | `stalled_at.cio` | **112** pub / **118** now | **NO** | " |
| B5 | `persistent-state/data/cio/transferson_universe_latest.json` | `unresolved_identity_n` | **2,635** | **NO — self-declared** | `as_of` 2026-08-25 |
| B6 | `persistent-state/data/runtime/hermes_governance_cache.json` | `stale.stale_gt30d` | **1,397** | **NO** | `_cached_at` 2026-08-26 |
| B7 | `persistent-state/data/runtime/research_lane_health.json` | `lanes.drive-sync.skipped` / `.failed` | **1,762** / **1,230** | **NO** — members only in an external `result_path` | `as_of` 2026-08-22 |
| B8 | `CURRENT/data/portfolios/state/brave_search_budget.json` | `skipped_budget` | **46** | **NO** | mtime 2026-08-10 |
| B9 | `persistent-state/data/cio/office_state_latest.json` | `freshness_counts.DATA_CONFLICT` | **19** | **NO** | mtime 2026-08-30 |

**B5 is the honest one and deserves credit.** `transferson_universe_latest.json`
sets `"securities_omitted_in_latest": true` and notes *"Counts are observations."*
It discards its members **and says so**, so no reader can mistake the count for an
auditable set. That is the minimum acceptable behaviour for a class-B tally.

### Class C — partial retention, undeclared truncation

| # | Store | Field | Value | Members? |
|---|---|---|---:|---|
| C1 | `persistent-state/data/runtime/shadow_batch_status.json` | `deferred_by_cap` | **4,530** | **PARTIAL** — `members` (100) + `next_100` (100); **4,330 unnamed** |
| C2 | `docs/ops/COST_CAP_SKIPPED_2026-08-22.json` | `n_error_rows` | **441** | **PARTIAL** — sibling `symbols_by_tier` |
| C3 | census `drop_reasons`, all families `[CODE]` | `dict(drops.most_common(40))` | — | **NO**, and **truncated to 40** |
| C4 | `data/runtime/source_auto_approval_latest.json` `[CODE]` | `skipped[:20]` | — | **PARTIAL, and the file carries no total** — a reader cannot tell it was truncated |

C3 is doubly lossy: it drops members *and* silently caps the reason vocabulary at
40 (`cio_event_lifecycle_census.py:794`). C4 is the worst shape in the inventory:
20 members, no count, no truncation flag.

---

## Inventory — code-backed and DB-backed tallies

The brief asked specifically about DB projection tables. `[CODE]` These write
counts into durable tables with no member join available:

| Write call | Table | Count fields | Members? |
|---|---|---|---|
| `scripts/lib/memory_shadow_projector.py:343-353` | `tradeai_memory_shadow.shadow_run_receipt` | `unresolved`, `excluded`, `failed` | **NO.** `counts` is a bare int dict (`:188`) bumped at 8 sites; no fact/identity id is ever appended. Excluded rows are never projected into the shadow tables, so **there is no row to join back to** — class A. |
| `scripts/pipeline_controller.py:291-296` | `pipeline_runs.summary` | `skipped`, `failed`, `degraded` | **Recoverable, not in-payload.** `statuses = list(stage_results.values())` (`:273`) discards the stage keys; mitigated only because per-stage rows are separately inserted into `pipeline_stage_runs`. |
| `scripts/strategy_signal_sync.py:682-697` | `signal_flow_audit` | `skipped_count`, `error_count` | **PARTIAL.** `details` keeps `symbol:status`, but the **skip reason** is logged only (`:636`) and never persisted. |

Further count-only emitters worth noting `[CODE]`:
`report_journal_lesson_quality.py:60-64` (`by_category` = `{k: len(v)}`, discarding
member lists it had just built); `two_way_curation.py:518`; `cio_wave3b_report.py:79`
(`most_common(10)` — doubly lossy); `analyst_report_builder.py:382`
(`suppressed_count`); `watchlist_proposal_bridge.py:577`, whose
`skipped += max(0, len(new_eligible) - cap) * len(lanes)` counts over-cap
candidates and records none of their symbols.

**A telling asymmetry, in one file, in one write** `[CODE]`
`scripts/shadow_batch_generator.py:316` writes `regenerate_reasons` as a full
`symbol → reason` map (~100 named symbols with their causes) and, in the same
payload, `already_fresh_skipped: len(fresh)` — a bare integer over a `set` that is
then discarded (`:339`, `:378`). The author clearly knew how to retain members.
The two buckets differ only in which one someone expected to be asked about.

---

## The pattern to copy — already in this repo

`cio_investment_brief.json` → `identity_coverage.surfaces[*]` gets it right, and
it is written **by the same producer, in the same file, at the same timestamp** as
B1/B2 `[VERIFIED]`:

```json
{"surface": "reentry_book", "n": 70, "resolvable_n": 70,
 "unresolved_symbols": [], "unresolved_truncated": false, "class": "D"}
```

A count, **the members**, and an explicit boolean saying whether the member list
was truncated. Any tally above could adopt this shape unchanged.

**The strongest pattern in the repo is better still** `[CODE]`:
`scripts/research_skip_gate_report.py:57` does not store a tally at all — it
derives `by_code` counts on demand **from** a durable member ledger,
`data/cio/research_skip_ledger.jsonl`. A count computed from retained members
cannot drift from them and cannot be quoted without them. That is the shape to
prefer wherever a ledger already exists.

Other clean in-repo examples: `cio_graph_impact_held.py:95-103`
(`skipped` list + `by_skip_reason`), `holdings_universe.py:266`
(`unresolved_cusips` beside `unresolved_cusip_n`), `r17_checkpoint_binding.py:229`,
`atm_position_reconciler.py:452` (**every** item inserted into
`atm_position_reconciliation_items`, so the DB count always has a join).

`thesis_universe` also does one thing genuinely well that is worth keeping:
`percentage_definitions` names numerator, denominator, `membership_scope` and
`formula` for every percentage. It documents *how* the number is built while still
discarding *what* it is built from — precisely the gap this paper is about. The
two practices are complementary, not substitutes.

---

## Recomputations

Chosen by blast radius: 1 and 2 are quoted as **bolded headline figures** in
`docs/audits/diligence/P1_WS2_EVENT_LIFECYCLE_BASELINE_2026-08-30.md`; 3 is the
largest live tally in a served product JSON.

### 1 — Census `catalyst_earnings` and the 2.17% headline · AGREES · and that is the problem

Published (`evidence/P1_WS2_event_lifecycle_census_2026-08-30.json`, as-of
2026-08-30T04:45:56Z) vs recomputed (as-of **2026-08-30T16:13:53Z**, 11.5 h later):

| headline field | published | recomputed | |
|---|---:|---:|---|
| `accepted_total` | 39,752 | 39,752 | SAME |
| `weighted_full_lifecycle_pct` | **2.17** | **2.17** | SAME |
| `weighted_processed_pct` | 2.10 | 2.10 | SAME |
| `min_full_lifecycle_pct` | **1.49** | **1.49** | SAME |
| `recoverable_total` | 862 | 862 | SAME |

Every field identical. **The agreement is not reassurance — it is the finding.**

The census folds the class-A catalyst tally straight into its own denominator.
Its own note admits it `[VERIFIED]`:

> `catalyst_graph_skipped_aggregate=38890 (counted in stages via aggregate, not per-row materialization)`

`[CODE]` `cio_event_lifecycle_census.py`: `fam["sample_n"] = len(events) + skip_total`.
So `accepted = 588 + 38,890 = 39,478` `[VERIFIED]` — **98.5% of the catalyst
family's denominator, and 97.8% of the whole census's `accepted_total`, is a
single integer copied from a file frozen on 2026-08-27.**

A frozen count reproduces perfectly forever. This number will agree with itself on
every future run while the world moves underneath it — reproducibility
masquerading as validity. It is the exact failure mode the principle predicts, and
it is why "we re-ran it and got the same answer" must never be accepted as
validation of a tally whose members are gone.

**What the headline becomes under the companion paper's composition.** That paper
recomputed the 35,928 as 374 directive slugs + 1,071 words + 149 real tickers
behind **2,512** events. Substituting only the real names:

| | published | using recomputed composition |
|---|---:|---:|
| catalyst_earnings `accepted` | 39,478 | 3,100 |
| catalyst_earnings `full_lifecycle_pct` | **1.49%** | **18.97%** |
| **event-weighted `full_lifecycle_pct`** | **2.17%** | **≈25.55%** |

**The bolded 2.17% baseline understates itself by roughly 11.8x.**

This is an illustrative bound, not a corrected figure — it grafts one paper's
recomputation onto another's denominator, and the 2,512 events are not the same
population as the census's 588 materialized ones. **I have not rewritten the
store, and the published number stands as published.** The point is only that a
headline resting 97.8% on a discarded tally cannot be defended at either value.

### 2 — Lineage completion · DISAGREES

Same script, same single invocation as recompute 1 — but this half reads a live
append-only JSONL (`cio_workflow_lineage.jsonl`, mtime 2026-08-30 12:06):

| field | published 04:45Z | recomputed 16:13Z | |
|---|---:|---:|---|
| `workflows` | 752 | **803** | +51 |
| `complete_to_checkpoint` | 406 | **448** | +42 |
| `completion_pct` | **53.99** | **55.79** | +1.80 |
| `with_checkpoint_id` | 436 | 478 | +42 |
| `stalled_at.research` | 640 | **685** | +45 |
| `stalled_at.cio` | 112 | **118** | +6 |

**One run of one script: the frozen-input half is byte-identical, the live-input
half moved.** That contrast is the cleanest available evidence for the principle —
nothing differed except whether the input still had its members.

`[CODE]` `completion_report()` returns `arcs`, `stalled_at` and `entity_types` as
bare `dict(Counter)` — no workflow ids. Note the writer sits in a helper
**imported locally inside a `try:`** (`census_lineage_overlay`), the trap the brief
warned about; a filename grep would have missed it.

**Materializing what `stalled_at` drops** `[VERIFIED]`:

| bucket | count | distinct `workflow_id` | distinct `event_id` | inflation |
|---|---:|---:|---:|---:|
| `research` | 685 | 685 | **334** | 2.1x |
| `cio` | 118 | 118 | **18** | **6.6x** |

**"118 stalled CIO workflows" is 18 actual events**, each carrying ~6.5 duplicate
envelopes. The tally invites you to read 118 problems; there are 18. Same shape as
the catalyst case — a small real issue wearing a large multiplier of duplication.
This is the class A3–A6 ambiguity made concrete: a count of occurrences is not a
count of things. Research-bucket entity types: `GOAL` 312, `UNRESOLVED` 187,
`SECURITY` 186 — the 187 `UNRESOLVED` are the identity gap surfacing again, and
they are nameable.

### 3 — `thesis_universe.insufficient_data` = 4,782 · AGREES · benign

Recomputed against `--root CURRENT`:

| field | published (`as_of` 16:11:52Z) | recomputed | |
|---|---:|---:|---|
| `universe_union` | 5,153 | 5,153 | SAME |
| `material` | 128 | 128 | SAME |
| `insufficient_data` | **4,782** | **4,782** | SAME |
| `role_unknown` | 64 | 64 | SAME |
| `coverage_pct_material` | 60.9 | 60.9 | SAME |

**Materialized** `[VERIFIED]`: 4,782 rows, **4,782 distinct symbols**, all
`memberships: {WATCHLIST: 4782}`, **none material**. Composition: 4,772
ticker-shaped (`A`, `AA`, `AAA`, `AAAA`, `AAAC`, `AAAP`, `AAAU`, …) + 10
fund/share-class identifiers (`FID-CONTRA-F`, `JPM-LGCG`, `VANG-FTSE-SOC`).

**This one is benign, and saying so is part of the job.** The alphabetical run
shows a bulk-loaded watchlist; "no thesis on 4,782 bulk watchlist names" is the
expected state, not a coverage failure. It is class B: I recovered every member in
one call. Not every large discarded tally hides a problem — but you only learn
that by materializing it, which is the whole argument.

The residual risk is presentational. `insufficient_data: 4782` sits beside
`coverage_pct_material: 60.9` in a served product JSON, and `[CODE]`
`insufficient_data` is counted over **all rows** while every percentage beside it
is computed over **`material` only** (`symbol_thesis_attach.py:276`). A reader
comparing the two is comparing different populations. `[VERIFIED]` the frontend
does not render it and no gate reads it, so this is latent rather than active.

---

## Two traps this audit walked into

Both are recorded because the brief warned about them and they still nearly
produced false findings.

**A 41x false divergence.** My first recompute of #3 returned `universe_union`
**124** against a published 5,153, and `insufficient_data` **0** against 4,782.
That is not a divergence: `_load()` → `reconcile_universe()` reads Postgres, and I
had run without the environment, so most sources came back empty. With `DB_*`
loaded the recompute matched exactly. **A collector that under-populates looks
identical to a store that is wrong.** Any recomputation in this class must prove
its inputs were populated before it may allege divergence.

**A plausible cross-producer bug that dissolved on reading two lines up.** The
code sweep flagged `cio_wave2_census.py:181`,
`[s.get("symbol") for s in (graph.get("skipped") or [])]`, as expecting a list of
dicts that `catalyst_graph.py:187`'s counts-only `dict(skipped)` cannot satisfy —
an appealing latent `AttributeError`. `[VERIFIED]` It is wrong:
`cio_wave2_census.py:168` sets `graph = home.get("graph_impact")`, whose producer
`cio_graph_impact_held.py:95` **does** emit a full list of `{symbol, skip_reason}`.
The reader is correctly shaped for its own producer. Two artifacts sharing the
field name `skipped` are not the same artifact.

---

## What this changes

1. **The catalyst tally is not an isolated defect.** 21 file-backed tallies plus
   three DB tables keep counts and drop members, across `data/cio/`,
   `data/runtime/`, `docs/ops/*.json` and two in-memory census collectors. Nine
   are class A.
2. **Most are cheap to fix and low-stakes.** Class B is the bulk; none of the 24
   gates anything; the frontend is clean. The correct response is a retention
   convention, not an incident.
3. **One has already done damage.** The catalyst tally propagated into a diligence
   baseline headline (**2.17%**) that is 97.8% composed of it, and that headline
   reproduces exactly on re-run because its input is frozen.
4. **Counts of occurrences are being read as counts of things.** Recompute 2 shows
   a 6.6x inflation already present in a published figure. A3–A6 have the same
   shape and have not been checked.
5. **The convention already exists in-repo** — `unresolved_symbols` +
   `unresolved_truncated`, in the same file as two of the offenders; and better,
   `research_skip_gate_report.py` deriving counts from a durable ledger.

Suggested rule, offered for review and **not applied here**: any field counting
rows that were skipped, dropped or excluded should ship a member list, or an
explicit `*_truncated` / `*_omitted` boolean when it cannot — the
`transferson_universe_latest.json` minimum. A count with neither should not be
quoted as evidence.

The single highest-value follow-up is not on this list: **redeploy the census
fix.** The artifact that carries the worst tally is currently described by a
script that cannot run in the release it describes.

---

## Provenance

- Branch `docs/a3-discarded-member-aggregates`, off `origin/main` `6bae6529`.
- Release under test: `CURRENT` → `66f97259-main-exact-phase2-20260830-112142`.
- Live store root: `/home/johnclaw/trade-ai-releases/persistent-state`.
- Census recomputation: fixed `main` copy, `--root CURRENT`, as-of `2026-08-30T16:13:53Z`.
- Published census compared against
  `docs/audits/diligence/evidence/P1_WS2_event_lifecycle_census_2026-08-30.json`,
  as-of `2026-08-30T04:45:56Z`.
- `READ_ONLY_ADVISORY`, `MBI_BEHAVIOR=0`. No store was written, corrected or
  remediated. No promote, merge, deploy, Telegram or vendor call.
