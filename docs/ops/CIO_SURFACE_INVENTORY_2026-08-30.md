# CIO Surface Inventory — every number, its producer, and where two surfaces disagree

Date: 2026-08-30
Agent: Wave A / A4
Authority: READ_ONLY_ADVISORY · MBI=0 · inventory only — no surface, renderer or scope label changed
Proof under test: **M4** — *"Every number on an operator surface traces to one regenerable
producer, and no two surfaces state the same quantity differently without a labeled scope."*

**Verdict: M4 is FALSE, but not for the reasons the wave brief assumed.** Three of the four
divergences named in the brief do not hold as stated; four divergences the brief did not name
do. The single largest gap is not a mislabeled number — it is that the payload publishes
447 distinct numeric fields and 19 of its 31 top-level blocks carry no as-of of their own.

## Tags

`[VERIFIED]` = a command was run and its output is quoted · `[CODE]` = source read · `[DOC-CLAIM]` = a document asserts it

## Verification environment

Served release under test: `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`
→ `66f97259-main-exact-phase2-20260830-112142` (`current_pin` on the payload agrees). `[VERIFIED]`

```
$ curl -s -o cio_home.json -w "HTTP %{http_code} bytes=%{size_download}\n" \
    http://127.0.0.1:7777/api/v3/cio/home
HTTP 200 bytes=219797
```

### Correction to standing guidance: `TRADEAI_ROOT` breaks the lineage collector

Existing operator memory says CIO dry runs need `TRADEAI_ROOT`. **For the lineage collector the
opposite is true** — setting it silently produces a zero book, which is exactly the failure mode
that guidance exists to prevent. `[VERIFIED]`

```
$ TRADEAI_ROOT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild \
    python scripts/cio_lineage_completion_report.py
workflows                0
complete_to_checkpoint   0
EXIT=0

$ python scripts/cio_lineage_completion_report.py      # default resolution
workflows                803
complete_to_checkpoint   448  (55.8%)
EXIT=0
```

Cause `[CODE]`: `canonical_store_registry.production_state_root()` (`:490`) reads `TRADEAI_ROOT`
**before** it checks for the `PERSISTENT_STATE_ROOT.json` marker (`:497`). The real store is
`/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_workflow_lineage.jsonl`
(6,157,862 bytes, 9,054 lines); the rebuild tree has no such file at all. `[VERIFIED]`
Note the exit code is **0 in both cases** — a wrong root is not an error here, it is a silent zero.

## Scale of the surface

`[VERIFIED]` `/api/v3/cio/home`: **447 distinct numeric field paths, 727 numeric leaf values**,
across 31 top-level blocks. This document does not table all 447 individually; it tables the
blocks, and then every number that is stated more than once.

## Part 1 — Block inventory

`regen` = can a reader reproduce it today from a documented command.

| Block | Numbers | Producing function | Regen | As-of | Scope stated |
|---|---|---|---|---|---|
| `cio_now` | decision/action/plan counts, per-decision value+weight | `cio_command_center.build_office_home` | yes | **none of its own** | partial |
| `capital_plan` | 30 cash/deploy figures | `cio_capital_plan.build_capital_plan` | yes | **none of its own** | yes — `help` tooltips in CC |
| `posture` | concentration, risk heat, CAGR, income | `cio_command_center` ← report_v2 | yes | **none of its own** | no |
| `opportunities` | 6 re-entry counts + watch counts | `build_opportunities` + `overlay_surface_a_reentry_on_opportunities` | yes | **none of its own** | **no — see D1** |
| `report` | traceability, field counts | `cio_report_v2.build_coverage_matrix` | yes | 16:11:19 | **denominator dropped — see D6** |
| `evidence`/`consistency` | validator states, parity | `cio_decision_parity` | yes | 16:11:19 | yes |
| `strategy_context`, `research_context`, `seasonality` | ~180 almanac stats | `cio_seasonality_engine` / `cio_research_*` | yes | per-slice | yes (in_sample/oos layered) |
| `operator_trust` | `holdings.total` | `_trust_holdings` → `holdings_sanity.declared_total` | yes | **none of its own** | no |
| `cash` | `cash_usd`, `cash_n` | `cio_operator_product._holdings_sections:137` | yes | **none of its own** | **no — see D2** |
| `temperament` | `cash`, `cash_pct`, `cash_band` | `cio_investment_product.extract_cash_metrics:690` | yes | **`regime_as_of` = 2026-08-28** | **no — see D2, D3** |
| `holdings_thesis_coverage` | held/dust/instrument-id counts | `cio_held_thesis_coverage` | yes | **none of its own** | yes — dust policy stated |
| `coverage` | 12 counts incl. `reentry_near` | `build_office_coverage:985` | yes | **none of its own** | prose note only |
| `graph_impact` | neighbour counts, shared value | `cio_graph_impact` | yes | **none of its own** | yes — hop/cap stated |
| `notifications` | considered 444, suppressed 439 | `cio_notification_policy` | yes | **none of its own** | yes — by_reason breakdown |
| `cash_letter` | `cash_usd`, `cash_investable_usd` | `cio_record_narrative.build_cash_letter:99` | yes | 16:11:19 | **mixed vintage — see D4** |
| `record_narrative_coverage` | rows 26 / from_record 10 | `attach_record_narratives:1385` | yes | **none of its own** | yes — explicit note |
| `reentry_books` | (labels only, no numbers) | `cio_reentry_surface_labels` | n/a | n/a | **yes — fully labeled** |

**19 of 31 top-level blocks carry no as-of of their own** `[VERIFIED]`: `cio_now`, `capital_plan`,
`posture`, `opportunities`, `consistency`, `operator_trust`, `new_position_if`,
`holdings_thesis_coverage`, `surface_a_status`, `watch_block_summary`, `cash`, `case_summaries`,
`reentry_books`, `coverage`, `graph_impact`, `notifications`, `instrument_narratives`,
`record_narrative_coverage`, `_serving`.

They inherit the envelope `as_of` = `2026-08-30T16:11:19`, which is **composition time, not
measurement time**. That this matters is proved on the payload itself: `temperament.regime_as_of`
= `2026-08-28 16:05:01-04:00`, two days older than the envelope that carries it. `[VERIFIED]`
Every cash number and every re-entry count is in this group. **The as-of column of M4 is
unanswerable for the majority of the surface.**

## Part 2 — The divergence register

Each is classified. The distinction is load-bearing: *different quantities needing labels* is a
documentation fix; *same quantity computed twice* is a bug.

### D1 — `reentry_total` is a Book A number sitting in a Book B field position — **BUG**

`[VERIFIED]` Seven re-entry numbers, all reproduced bit-for-bit against the live store:

| Field | Value | Book | Population |
|---|---|---|---|
| `opportunities.reentry` (list) | 6 rows | **queue (third source)** | desk suggestions, truncated `[:6]` |
| `opportunities.queue_reentry_total` | 43 | **queue (third source)** | staged desk directive hits |
| `opportunities.reentry_total` | **25** | **Book A** | NEAR + REENTER |
| `opportunities.surface_a_reentry_count` | 70 | Book A | whole book |
| `opportunities.surface_a_reentry_near` | **25** | Book A | NEAR only |
| `opportunities.surface_a_reentry_reenter` | 0 | Book A | REENTER only |
| `coverage.reentry_near` | **25** | Book A | NEAR only |

`[CODE]` `cio_command_center.py:1211-1212` computes `overlay = sa_near + sa_reenter` (25 + 0) and
assigns it to `reentry_total`, **overwriting** the queue value written at `:790`. So the field
named as the total of the 6-row list above it belongs to a different book, a different
population, and a different question. The list's true population is 43.

Three publications of one value: `reentry_total`, `surface_a_reentry_near` and
`coverage.reentry_near` are all the same 25 by construction, not coincidence. And the identity is
fragile — the assignment is a **three-way branch** `[CODE]` (`:1211-1215`):

```python
if sa_count > 0:
    overlay = sa_near + sa_reenter
    opp["reentry_total"] = overlay if overlay > 0 else sa_count
else:
    opp["reentry_total"] = queue_total
```

So `reentry_total` can be **25** (Book A NEAR+REENTER), **70** (Book A whole, on a WAIT/AVOID-only
day), or **43** (the queue) — **three different books under one field name, selected silently by
the day's data.** Nothing on the payload tells the reader which branch fired.

Aggravating, and worth Wave E's attention: `reentry_pipes` (`:1201-1206`) exists precisely to map
fields to pipes, and it names `"queue": "opportunities.reentry / queue_reentry_total"` — the one
field that changed books, `reentry_total`, is **the one field the pipe map omits.**

Book B (`cio_desk_depth.build_reentry_book`) contributes **nothing** to the payload — its only
caller is `cio_desk_synthesis.py:510`, which never enters `build_office_home`. `[CODE]`
The `reentry_books.b` block advertises a producer whose output is not present.

### D2 — the cash total is computed four times under two different rules — **BUG**

`630784.82` is not passed down from one place. `[CODE]`

1. `cio_operator_product.py:137` — `sum(market_value for h in cash_rows)` → `cash.cash_usd`
2. `cio_capital_plan.py:1303` — `sum(_fnum(h["market_value"]) for h if h["is_cash"])` → `capital_plan.cash_total_usd`
3. `cio_investment_product.py:640` — `totals.get("total_cash")` (trusts the written total) → `temperament.cash`
4. `SLEEVE:CASH` InstrumentRecord, rule 3 frozen at `2026-08-29T23:28` → `cash_letter.cash_usd`

(1) and (2) are the **identical computation duplicated**. (3) is a **different rule**. The
codebase already knows they diverge — `cio_operator_renderers.py:24-30` `[CODE]`:

```
# Two writers publish a cash total and they disagree on CURRENT by ~$52.7k:
#   product.cash.cash_usd   = sum of the is_cash position rows
#   temperament.cash        = portfolio_totals.total_cash
# Slice 36 says the evening line is the live temperament number. Slice 40 says
# detect, never merge. So the brief prints temperament.cash AND says the sources
# disagree — it never averages them and never silently picks the larger one.
```

The `cash_lines()` detect-never-merge guard protects **the operator brief text only**.
`/v3/cio/home` publishes `cash.cash_usd` and `temperament.cash` as bare independent numbers with
no reconciliation. They agree today only because the *writer* was changed
(`portfolio_repricer.py:622` now stamps `total_cash_source: "position_rows"`), making rule 3 equal
rule 1. **Nothing structural enforces it.**

### D3 — two `cash_band` objects, same name, opposite semantics — **NEEDS LABEL**

`[VERIFIED]` on one payload:

```
capital_plan.cash_band  = {"min_pct": 20.0, "max_pct": 25.0}
temperament.cash_band   = {"lo": null, "hi": 20.0, "source": "attention_threshold_pct"}
```

`[CODE]` `temperament`'s `hi` is `CASH_ATTENTION_BAND_PCT = 20.0`, hardcoded at
`cio_investment_product.py:73` — an **upper attention threshold** (cash above 20% is notable).
`capital_plan`'s `min_pct` is the desk thesis `cash_band_min_pct` — a **lower reserve floor**.

The same literal `20.0` is a ceiling in one block and a floor in the other, from independent
sources, under the same field name. At 49.03% cash both read "outside the band", so the
contradiction is currently invisible — but the two blocks disagree about where the ceiling is
(20% vs 25%). Genuinely different quantities; they need labels, not a merge.

### D4 — `cash_letter` mixes vintages inside one object — **NEEDS LABEL**

`[CODE]` `cash_usd` (`cio_record_narrative.py:99`) is read from the frozen `SLEEVE:CASH` record
(`cash_written_at: 2026-08-29T23:28:23`); `cash_investable_usd` (`:123`) is **live** capital-plan
output. If holdings reprice and the record is not re-minted, the letter states a stale cash figure
beside a fresh investable figure with no marker distinguishing them.

### D5 — `complete_to_checkpoint` published vs regenerated — **STALE, NOT WRONG**

| Source | workflows | complete | pct |
|---|---|---|---|
| `CIO_DILIGENCE_SCOREBOARD.json` `.now.lineage` `[DOC-CLAIM]` | 752 | 406 | 54.0 |
| `CIO_DILIGENCE_SCOREBOARD.md` NOW block `[DOC-CLAIM]` | 752 | 406 | 54.0 |
| `P1_WS2_EVENT_LIFECYCLE_BASELINE` `[DOC-CLAIM]` | 752 | 406 | **53.99** |
| Regenerated today `[VERIFIED]` | **803** | **448** | **55.79** |

The wave brief predicted 447 / 55.87%. It regenerates as **448 / 803 (55.79%)** — the brief's
figure was itself already stale, because the lineage store is append-only and still growing
(mtime 12:06 during this session). **This quantity is regenerable but not reproducible to a fixed
value**; any document quoting it without a timestamp is wrong within hours. Note also 54.0 vs
53.99 for the identical measurement — two roundings of one number in two documents.

### D6 — `source_traceability_pct: 100.0` publishes an aggregate that discards its denominator — **BUG**

`[VERIFIED]` payload: `source_traceability_pct: 100.0`, `field_count: 65`, `fields_present: 32`,
`fields_unavailable: [4 names]`. 29 fields are neither present nor named unavailable.

The producer is honest `[CODE]` — `cio_report_v2.build_coverage_matrix:331`:

> `source_traceability_pct` = reported numerical fields that carry a source, as a percentage of
> reported numerical fields (unavailable fields are not reported, so they do not dilute traceability).

and it returns `numeric_reported_count` — **the actual denominator**. The projection drops it.
`[CODE]` `api_v2.py:27869-27878`:

```python
"field_count": (full.get("coverage") or {}).get("field_count"),
"source_traceability_pct": cp.get("source_traceability_pct"),
"fields_present": len(cp.get("fields_present") or []),
"quality_flag_count": len(cp.get("quality_flags") or []),
```

`numeric_reported_count` is never projected; `fields_present` and `quality_flags` are collapsed
from member lists to bare counts. **On the surface, "100%" has no visible denominator and is
unfalsifiable.** The `except` branch (`:27881`) returns `field_count: 0` on any failure, which
renders as a real zero rather than an error.

### D7 — "identity resolvable" names two populations three orders of magnitude apart — **NEEDS LABEL**

This is the brief's strongest claim and it **holds**, with numbers.

`[VERIFIED]` regenerating the P2-WS4 census today:

```
production_records  n=91  resolvable_n=90  resolvable_pct=98.9  stamped_pct=90.1
  by_identity_status: CONFIRMED 89 / UNRESOLVED_WITH_REASON 1 / MISSING 1
  unresolved_symbols: ["HEALTH"]
```

The published 98.9% was **88/89** `[DOC-CLAIM]`; it regenerates as **90/91**. The percentage is
unchanged while the population grew by two — the figure looks stable precisely because its
members were discarded.

Meanwhile, on the catalyst population `[VERIFIED]` (census re-run today, reproduces exactly):

```
catalyst_earnings: accepted 39478 · normalized 585 · recoverable 588 · full_lifecycle 1.49%
drop_reasons:
  catalyst_graph_skip:symbol_not_registered  = 35928
  catalyst_graph_skip:entity_has_no_issuer   =  2962
```

**38,890 identity-resolution failures**, none of which appear in the 98.9%. The scoreboard states
`identity production resolvable 98.9%` with no population qualifier. The same census output also
publishes `slice13_compat.total_resolvable_pct = 100.0` over 111 rows — **a third "resolvable"
percentage in the same object.** Three numbers, one word, no labels.

Genuinely different quantities. The fix is a scope label on each, not a merged number.

### D8 — the event lifecycle numbers were not regenerable from the served release — **BUG (fixed on main, not deployed)**

`[VERIFIED]` The instrument that produces the scoreboard's lifecycle figures does not compile in
`CURRENT`:

```
$ python -m py_compile scripts/cio_event_lifecycle_census.py     # in CURRENT
  File "scripts/cio_event_lifecycle_census.py", line 26
    from __future__ import annotations
SyntaxError: from __future__ imports must occur at the beginning of the file
CURRENT_COMPILE_EXIT=1
```

The fix landed in `#705` (on `origin/main`, this branch's base) but the served release predates it
`[VERIFIED]` — `BRANCH_COMPILE_EXIT=0`. Running the fixed script against `CURRENT`'s data
reproduces the published headline **exactly**: `weighted_full_lifecycle_pct 2.17`,
`mean 67.16`, `min 1.49`, `accepted_total 39752`, `recoverable_total 862`. `[VERIFIED]`

So those numbers are correct and regenerable — but for a period they were being quoted from a
release in which no operator could have regenerated them. The file now carries its own tombstone
`[CODE]`: *"Declared below the `__future__` import on purpose: a module-level assignment ABOVE it
is a SyntaxError, which is exactly how this file spent 10 hours unrunnable while its numbers were
still being quoted."*

### D9 — duplicate publication paths (aliases, not divergences) — **NO ACTION**

`[VERIFIED]` byte-identical at both paths in today's payload:

`research_context` ≡ `strategy_context.research_context` · `seasonality` ≡
`strategy_context.seasonality` · `cash` ≡ `operator_product.cash` · `temperament` ≡
`operator_product.temperament` · `case_summaries` ≡ `operator_product.case_summaries` ·
`earnings` ≡ `operator_product.earnings` · `new_position_if` ≡ `operator_product.new_position_if`

These are aliases of one object, not two computations. Recorded so a future audit does not
re-raise them as divergences. They do, however, double the number of paths at which a consumer
can bind to a quantity.

### D10 — the Telegram renderer restates numbers at a different precision — **COSMETIC**

`[CODE]` `cio_telegram_converse.format_structured_reply._clean` rewrites any float with 3+
decimals to 2dp: `re.sub(r"\b\d+\.\d{3,}\b", _rnd, t)`. The JSON surface applies no such rule
(`weight_pct: 1.7036` ships as-is). The same quantity therefore reads `182.51` on Telegram and
`182.50959999999998` in CC. Presentational, but it is a same-quantity-stated-differently case and
belongs in the register.

### Not a divergence: the two portfolio totals

The brief's framing implied two competing computations. `[VERIFIED]` They are **one quantity at
two vintages**: `1286402.75` is `holdings.json portfolio_totals.total_value` at
`last_pipeline_run 2026-08-29T19:28:19`; `1287999.68` is the same field pre-repricer, preserved in
`data/cio/backups/holdings.json.pre-repricer-20260829T205145Z`. Each `evidence_ref` carries its
own `as_of`, so they *are* labeled — but the CC page renders the refs without surfacing age, so
two totals appear adjacent with no visible reason. **Fix the rendering, not the number.**

Relatedly, and contrary to a natural back-solve: **every percentage on this payload uses the same
denominator.** `49.03` is rounded from `49.0345…`; `630784.82 / 1286402.75 = 49.03%` exactly.
`[VERIFIED]` There is no percentage anywhere on the payload computed against `1287999.68`.

### Not a bug, but under-reported: `cash_free_unearmarked_usd = 0.0`

`[VERIFIED]` 38 open redeploy events sum to **$1,026,129.22**, clamped to cash at
`cio_capital_plan.py:390-393` (`maturities_capped_to_cash: True`). So
`cash_earmarked_redeploy_usd = 630784.82` means *"the earmark saturated 100% of cash"*, and
`cash_free_unearmarked_usd = 0.0` is an artifact of saturation — **not a finding that no cash is
free.** `cio_financial_truth_gate.py:861` already flags this ("earmark may be over-labeled"), but
`capital_sources` copies `maturities_usd` and the `capped` flag and **not** `maturities_raw_usd`,
so the reader cannot see the overshoot magnitude. Another aggregate that discards its members.

The documented layer invariants themselves hold exactly `[VERIFIED]`:
`630784.82 − 257280.55 = 373504.27` ✓ (total − reserve = investable).

## Part 3 — Agent-originated fields reaching an operator surface

**Answer: 25 model-written string instances across 3 field paths. Zero of them carry a truthful
provenance marker. Zero live LLM calls occur in the request path.**

The brief expected a low number and expected several fields marked model-assisted to be
deterministic. Both are true — **and the reverse error is the larger one.**

### A marker census gives the wrong answer

`[VERIFIED]` Every provenance marker on the payload:

```
writer            n=63   {'migration:deterministic': 44, 'deterministic_fallback': 16, 'cognition:defer_honored': 3}
narrative_source  n=50   {'deterministic': 32, 'record': 18}
llm_deferred      n=0    llm_model  n=0
```

Taken at face value this reads **zero agent-originated fields** — no writer names a model. That
conclusion is wrong. The `writer` key describes **the migration step that copied the text, not the
text's author.**

`[VERIFIED]` Three narratives, all stamped `writer: migration:deterministic`:

```
EXIT:ACHV  "Under desk@v5 (defensive_observe): S3_REENTRY_CANDIDATE on ACHV. Fire=reentry_NEAR.
            Synthesize cash_buying_power, catalyst, catalysts, hermes_research, ho…"
EXIT:DFSC  "Under desk@v5 / defensive_observe, DFSC is flagged as a reentry candidate (S3,
            fire=reentry_NEAR). The book is broadly diversified (30 holdings) with a large…"
HELD:XLB   "XLB is trading at 53.22, just below your 53.36 basis, triggering the basis reclaim
            zone. Street mean target is unavailable, so there is no new fundamental anchor…"
```

The first is the f-string form (`cio_plan_enrichment.py:1023`) — note the raw field-name list
bleeding through. The second and third are generated prose. **Same writer label.**

### The 25

Provenance established by matching each frozen record back to the plan that produced it in
`cio_plans_projection.json`, which carries `narrative_source` stamped at
`cio_plan_enrichment.py:1862` — set **only** after a successful bridge call. 8 records match a
plan with `narrative_source="llm"`; 24 match `template`; 4 match `None`; 2 have no match.
Store-wide: 233 `llm` / 725 `template` / 17 `None`.

| Field path | Instances | Subjects |
|---|---|---|
| `instrument_narratives.<key>.what` | 8 | `EXIT:DFSC, FATN, LGPS, RKLB, TDG, TRX, ZSL` + `HELD:XLB` |
| `instrument_narratives.<key>.thesis_fit` | 7 | the seven `EXIT:` keys |
| `instrument_narratives.<key>.risks` | 10 | those 8 + `HELD:BND`, `HELD:SCHD` |

On the decision/opportunity rows, exactly **one** model-written field reaches the surface:
`cio_now.decisions[SCHD].cc_narrative.risks`, republished at
`opportunities.watch[SCHD].cc_narrative.risks`. That row is stamped `narrative_source: "record"`
and `writer: "cognition:defer_honored"` — **both point away from an LLM.**

Structural cause `[CODE]`: `cio_instrument_record.cc_narrative()` (`:146-163`) takes **one**
`writer` for a blob whose `what`, `thesis_fit` and `risks` can each have a different author. The
defer path rewrites `what` while preserving `old["risks"]` verbatim, so a model-written `risks`
inherits a hand-written `what`'s label.

### Marked as model-assisted, in fact deterministic

- `writer: "cognition:defer_honored"` — reads as agent cognition; `[CODE]`
  `cio_rehydrate.py:191` is `f"Operator deferred: {note}."` where `note` is **operator** text.
- `writer: "cognition:residual_web"` — `[CODE]` `cio_residual_web.py:549` is an f-string counting
  refs. No live record carries it, but it is a mislabel waiting to ship.
- `case_summaries.class = "A"` (= "judgment", the payload's only A-classed field) — `[CODE]`
  `hermes_case_summary.py:82` is an f-string. The clearest class mislabel on the surface.
- `/v3/cio` publishes `"model_provider": "deepseek-v4-pro"` — `[CODE]` `api_v3_cio.py:2360`, a
  hardcoded literal in a payload that makes no model call.
- `temperament.narrative` / `narrative_class: "T"` — correctly classed. `[CODE]`
  `cio_investment_product.py:1313` is an f-string, as the brief suspected. Also deterministic
  despite narrative-sounding names: `earmark_narrative`, `operator_product.executive_summary`,
  `temperament.portfolio_implication` (a constant), `decisions[].what_changes_call`.

### `record_narrative_coverage` does not measure authorship

`[VERIFIED]` `rows: 26, from_record: 10, from_deterministic_fallback: 16`. `[CODE]`
`from_record` (`cio_command_center.py:1313`) increments when a **store row existed** for that
subject — it says nothing about who wrote the prose. Empirically it means the opposite here:
**all 10 `from_record` `what` values are deterministic templates.** The block's own note is
accurate — *"The composer renders prose; it never calls a model"* — and correctly describes the
request path. It is the `writer` labels on the replayed text, not the composer, that mislead.

The class taxonomy `[CODE]` (`cio_p90_voice.py:3`) is `T` = template, `D` = derived count,
`A` = judgment. It is a **voice** taxonomy, not an authorship one — **no letter means
"written by a model."** There is currently no field on any operator surface that truthfully
marks model-authored text.

## Part 4 — Findings that contradict the wave brief

The brief said to treat its examples as claims to verify. Four did not survive.

1. **"Two re-entry books exist and neither states its scope."** `[VERIFIED]` False as stated —
   `reentry_books` publishes `scope`, `question`, `precedence`, `not_this_book` and a named
   producer for **both** books, plus *"Never combined."* `cio_reentry_surface_labels.py` exists
   for exactly this. The real finding (D1) is narrower and worse: the labels stop at the **book
   object**, and every scalar is extracted after the stamp is left behind, so no *number* carries
   a scope — and `reentry_total` has silently changed books.
2. **"The Command Center does not label the re-entry surface."** `[VERIFIED]` False —
   `CioHub.tsx:1385` renders *"Surface A · former holdings vs exit trigger (not candidates vs
   cash-stage R:R under desk thesis)."* The real defect is that the **queue** chips (6 of 43,
   Book-agnostic) are rendered **inside** that Surface A card, gated on a Book A number.
3. **"`complete_to_checkpoint` regenerates today as 447 / 55.87%."** `[VERIFIED]` It regenerates
   as **448 / 803 (55.79%)**. The brief's own figure was stale on arrival; the store grows
   continuously.
4. **"Cash appears as four competing figures."** Partly. The four *names* exist, but three are one
   number by alias (D9) and the genuine defect is different and worse: four **computations** under
   two **rules** (D2), currently agreeing only because a writer was patched upstream.

Additionally, the brief implied `cash_letter` carries a `class` key — `[VERIFIED]` it does not;
it carries `writer` and `from_record`.

## Part 5 — Handoff to Wave E

Ranked by what an operator could act on wrongly today.

| # | Finding | Class | Suggested fix |
|---|---|---|---|
| D1 | `reentry_total` publishes Book A's NEAR count in the queue's total position, and switches books on a fallback | **bug** | Rename to `surface_a_reentry_actionable`; make `opportunities.reentry_total` = 43 or delete it; add `reentry_total` to `reentry_pipes` |
| D2 | Cash total computed 4× under 2 rules; agreement is incidental | **bug** | Extend the `cash_lines()` detect-never-merge guard to the JSON surface, or collapse (1) and (2) to one call |
| D6 | `source_traceability_pct: 100.0` ships without its denominator | **bug** | Project `numeric_reported_count` alongside it |
| D8 | Lifecycle census unrunnable in the served release | **bug (fixed on main)** | Deploy `#705`; add a compile check to the release gate |
| — | 19 blocks with no as-of | **bug** | Stamp per-block measurement time; the envelope as-of is composition time |
| D7 | "identity resolvable" = 98.9% (n=91), 100% (n=111), and ~1.5% (n=39,478) | **needs label** | Qualify every published identity percentage with its population |
| D3 | Two `cash_band` objects, floor vs ceiling, same name | **needs label** | Rename `temperament.cash_band` → `cash_attention_threshold` |
| D4 | `cash_letter` mixes frozen and live vintages | **needs label** | Stamp `cash_written_at` on the letter |
| — | 25 model-written strings under deterministic `writer` labels | **needs label** | Per-field authorship on `cc_narrative`, not one blob-level `writer` |
| — | `cash_free_unearmarked_usd = 0.0` is a saturation artifact | **needs label** | Publish `maturities_raw_usd` ($1,026,129.22) beside the capped value |
| D5 | Lineage % quoted without timestamps; 54.0 vs 53.99 for one number | **stale** | Require an as-of beside every quoted lineage figure |
| D9 | 7 alias paths | none | Record only |
| D10 | Telegram rounds to 2dp, JSON does not | cosmetic | Record only |

### Aggregates that discard their members — flagged as hypotheses, per standing instruction

`source_traceability_pct` (denominator dropped) · `identity_production_resolvable_pct` (88/89 →
90/91 invisible) · `fields_present` and `quality_flag_count` (`len()` of a dropped list) ·
`cash_earmarked_redeploy_usd` (raw $1.03M dropped) · `record_narrative_coverage.from_record`
(counts rows, reads as authorship) · `catalyst_graph_skipped_aggregate=38890` (the census note
concedes it is "counted in stages via aggregate, not per-row materialization").

None of these should be quoted as a measured fact without first restoring its members.

## Reproduction

```bash
curl -s http://127.0.0.1:7777/api/v3/cio/home                          # 447 numeric paths
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
python scripts/cio_lineage_completion_report.py                        # do NOT set TRADEAI_ROOT
python scripts/cio_identity_confidence_census.py --json --identity-only
python scripts/cio_event_lifecycle_census.py --json --root $PWD        # needs #705 to compile
```
