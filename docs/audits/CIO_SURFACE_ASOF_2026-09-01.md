Status:      ACTIVE
as_of:       2026-08-31T23:24:33-04:00
Measured at: d276657b721011ae126d234b6300c9225d651a3e (served release
             /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546)
Canonical repo path: docs/audits/CIO_SURFACE_ASOF_2026-09-01.md
Authority:   dated field-level census of operator surfaces; not a behaviour spec
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md, AGENTS.md §9.5 §13.4 §15

---

# CIO operator surfaces — field-level `as_of` and provenance census

Worker D, federated overnight wave 2026-09-01. Docs only. No code was edited, no
commit made, no store written. Every fix in §7 is a proposal.

## 0 · Headline

Six findings, in descending order of how much they should change someone's day.

1. **Three different values for "total cash" are live right now, and all three are
   in a single response body from a single endpoint.** `/api/v3/cio/home` states
   total cash **14 times across 3 distinct values**: `$630,791.10` (×2),
   `$630,790.42` (×5), `$630,784.82` (×7, including the operator sentence "Cash
   sleeve 630784.82."). A reader finds the contradiction without ever leaving one
   page. `/api/v2/overview` independently agrees with the *first* of the three,
   so the cross-surface gap is real but is the smaller half of the finding. §6.
   [VERIFIED]
2. **Class-A (agent-originated) fields on an operator surface: 22 instances, not
   zero.** This contradicts `CIO_ASIS_VS_SPEC_2026-08-30.md`. The label is also
   *wrong* — the producer is a deterministic f-string. Both halves are defects.
   §4. [VERIFIED] + [CODE]
3. **The three-way-branch field is `capital_plan.cash_earmarked_redeploy_usd` /
   `capital_plan.sources[key=earmarked_redeploy_usd].usd` = `$630,790.42`.** It
   reads as a total of earmarked redeploy dollars. It is a *ceiling*. Raw earmark
   is `$1,026,129.22`; it was clamped to cash on hand. The flag that says so
   (`maturities_capped_to_cash`) is computed and then dropped before serving. §5.
   [VERIFIED]
4. **The AS-IS doc's cash claim is now half wrong, and the half that is right is
   the more used surface.** `/api/v3/cio/home` gives cash a correct
   oldest-contributing-balance `as_of` (`2026-08-03`, `mixed_ages: true`,
   `distinct_stamps: 3`). `/api/v2/overview` does not: `data.total_cash` inherits
   `data.as_of = 2026-08-29`, which is **26 days too fresh**. §3. [VERIFIED]
5. **On `/api/v3/cio/home`, 1,140 of 2,098 value-bearing fields (54.3%) have no
   evidence clock** — 589 carry only the root envelope clock, 543 sit under a
   block whose `as_of` is composition time stamped within 0.6 s of the envelope,
   8 hang directly off the root. §3. [VERIFIED]
6. **The surface ships its own self-declared failure and nobody is stopped by
   it**: `consistency.decision_field_parity.ok = false`, with three actionable
   decisions listed under `missing_sizing_on_actionable`. §6. [VERIFIED]

### Corrections to the brief, up front

The brief is wrong in three places. Per AGENTS.md §11, the finding wins.

- **`/v3/cio` is not a JSON surface.** It is a static SPA route serving
  `apps/command-center-v3/dist/index.html`
  (`scripts/portfolio_server.py:1915-1958`). The JSON the operator actually reads
  comes from `/api/v3/cio/*`. I censused `/api/v3/cio/home`. §1.
- ~~**Provenance classes are AGENTS.md §13.5, not §13.4.**~~ **WITHDRAWN — I was
  wrong and the brief was right.** The D/T/M/A/S block is at `AGENTS.md:785-793`,
  which is a `###` subsection *of* `## 13.4`. See correction 8 in §8 for the round
  trip. The `as_of` rule the brief leans on is §9.1 (`AGENTS.md:461-463`),
  reinforced by §9.5 (`AGENTS.md:563-570`).
- **"Expect 0" for class A was the wrong prior.** It is 22. §4.

---

## 1 · The two surfaces, precisely

### How I established the served release actually serves them

```
$ readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
/home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546

$ cat .../GIT_SHA
d276657b721011ae126d234b6300c9225d651a3e

$ cat .../BUILD_STAMP.json
{ "build_sha": "d276657b7...", "source_sha": "d276657b7...", "git_sha": "d276657b7...",
  "branch": "main", "label": "main-exact-phase2", "stamped_at": "2026-09-01T02:56:30Z" }
```
[VERIFIED]

The process, its port, and its root:

```
$ ps -eo pid,ppid,etime,cmd | grep -Ei 'uvicorn|gunicorn|python.*api_v|flask|portfolio'
2076495  7039  16:52  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546/scripts/portfolio_server.py

$ ss -lntp | grep 2076495
LISTEN 0 128  0.0.0.0:7777  0.0.0.0:*  users:(("python",pid=2076495,fd=3))

$ ls -l /proc/2076495/cwd
/proc/2076495/cwd -> /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546
```
[VERIFIED]

The running process's cwd and argv are the concrete release directory, not the
`CURRENT` symlink — so a rotation mid-audit would not silently re-point my
measurements. I re-checked `CURRENT` at the end of the audit (23:24:33 ET) and it
still resolved to the same directory. No rotation occurred during this census.
[VERIFIED]

The live payload agrees, and self-reports pin match:

```
"_serving": { "schema": "ServingFreshness@v1",
  "process_started_at": "2026-08-31T22:56:47-04:00",
  "source_pin":   "d276657b721011ae126d234b6300c9225d651a3e",
  "loaded_pin":   "d276657b721011ae126d234b6300c9225d651a3e",
  "current_pin_sha": "d276657b721011ae126d234b6300c9225d651a3e",
  "pin_match": true }
```
[VERIFIED]

### Both surfaces are genuinely operator-reachable

The shipped SPA bundle fetches both:

```
$ grep -rho "api/v3/cio/[a-z-]*" .../apps/command-center-v3/dist/assets | sort -u
api/v3/cio/agent-research-ops   api/v3/cio/brain      api/v3/cio/decision
api/v3/cio/dispositions         api/v3/cio/home       api/v3/cio/intelligence
api/v3/cio/investment-product   api/v3/cio/plans      api/v3/cio/symbol-thesis
api/v3/cio/universe-theses
$ grep -rho "api/v2/overview" .../apps/command-center-v3/dist/assets | sort -u
api/v2/overview
```
[VERIFIED]

### Surface A — `/api/v3/cio/home`

| | |
|---|---|
| Route dispatch | `scripts/api_v2.py:40597` — `if base_path.startswith("/api/v3/cio")` |
| Handler | `scripts/api_v2.py:40607` → `_cio.get_cio_home()` |
| Producer | `scripts/api_v3_cio.py:1094` `def get_cio_home()` |
| Composers | `scripts/lib/cio_command_center.py`, `cio_investment_product.py`, `cio_operator_product.py`, `cio_capital_plan.py`, `cio_record_narrative.py`, `cio_operator_renderers.py` |
| SPA shell | `scripts/portfolio_server.py:1915` (static `/v3/...` → `dist/index.html`) |
| Envelope | `version: office_home_1.3.0`, `authority: READ_ONLY_ADVISORY` |

[CODE], route line numbers re-read from the served release before citing.

Full GET sub-route set under `/api/v3/cio` (`api_v2.py:40601-40716`), 40 GET
paths including aliases:

```
(empty) | dashboard | home | brain | brain/maturity-contract | brain/policy
brain/policy-provenance | brain/portfolio-state | brain/market-context
brain/seasonality | brain/portfolio-thesis | brain/capital-plan
brain/methodology | brain/learning-review | brain/intelligence-lifecycle
brain/model-performance | brain/learning-cockpit | brain/data-health
investment-product | investment-books | books | dispositions | decision/<key>
snapshot | actions | delegation | thesis | universe-theses | agent-research-ops
thesis-research-proposal | thesis-ri-pipeline/<sym> | thesis-research-context/<sym>
r71-fabric-map | symbol-thesis/<sym> | intelligence/<sym> | ask-thesis/<sym>
desk-note | plans | plans/<plan_id>
```
[CODE]

POST sub-routes exist under the same prefix (`api_v2.py:40717+`). **Not touched
— HARD PIN.** No POST was issued at any point in this audit.

Live read:

```
$ curl -s -X GET http://127.0.0.1:7777/api/v3/cio/home
HTTP 200 bytes=237920
{"version": "office_home_1.3.0", "authority": "READ_ONLY_ADVISORY",
 "as_of": "2026-09-01T03:14:43.983358+00:00", "cio_now": {...
```
[VERIFIED]

### Surface B — `/api/v2/overview`

| | |
|---|---|
| Route table | `scripts/api_v2.py:35921` — `"/api/v2/overview": overview` |
| Handler | `scripts/api_v2.py:2419` `def overview()` |
| Cash read site | `scripts/api_v2.py:2606-2610` |
| Concurrency | semaphore-exempt, `scripts/portfolio_server.py:2721` |

[CODE]

`/api/v2/overview` has no sub-routes; it is a single flat endpoint. The related
`/api/v2/trade-ai*`, `/api/v2/risk-regime/latest` etc. listed beside it at
`portfolio_server.py:2715-2727` are siblings in the exemption list, not children.

Live read:

```
$ curl -s -X GET http://127.0.0.1:7777/api/v2/overview
HTTP 200 bytes=15253 t=0.080204s
{"ok": true, "data": {"portfolio_value": 1282976.11, "derived_total_value": 1282976.11,
 "total_value_drift": 0, "total_cash": 630791.1, "today_change": -1569.77, ...
```
[VERIFIED]

All measurements below are from these two GET responses, captured 2026-09-01
03:14:43 UTC / 03:18:36 UTC at pin `d276657b7`. Only GETs were issued: the two
above, plus `/api/v3/cio/brain/capital-plan` and
`/api/v2/redeploy/opportunity-set`. Two files were read from disk read-only
(`holdings.json`, `cio_instrument_records.jsonl`).

---

## 2 · Field-level census

The full leaf enumeration is 2,254 rows for Surface A and 188 for Surface B —
too large to transcribe honestly here, and a transcribed table would be a
number quoted rather than regenerated. Instead this section gives the
**regeneration method**, the **aggregate counts**, and the **complete row list
for every block where the answer is anything other than a clean pass**. Anyone
can rebuild the full table from the method in one command.

### Method

Array elements are collapsed to `[*]`, so a "field" is a distinct dotted schema
path, not an occurrence. A field is scored:

| verdict | meaning |
|---|---|
| `OWN-EVIDENCE` | its immediate parent object carries an `as_of` that is a data clock |
| `OWN-COMPOSITION` | parent carries an `as_of`, but it is within 5 s of the envelope clock — a **false pass** |
| `INHERITED-<kind>` | nearest ancestor with an `as_of`, and which kind that clock is |
| `TIMESTAMP-FIELD` | the field is itself a stamp |

The composition/evidence split is the load-bearing one, and it is the brief's
point: a block-level timestamp covering a field computed at a different moment
is a defect, not a pass. A block that stamps itself `as_of = now` has not given
its fields an `as_of`; it has given them a receipt for the render.

### Surface A — `/api/v3/cio/home`

```
total distinct leaf paths        2254
  INHERITED-COMPOSITION          1090
  OWN-EVIDENCE                    660
  INHERITED-EVIDENCE              298
  TIMESTAMP-FIELD                 156
  OWN-COMPOSITION                  50

value-bearing (non-timestamp)    2098
  backed by an EVIDENCE clock     958   (45.7%)
  backed by composition/nothing  1140   (54.3%)
```
[VERIFIED]

### Surface B — `/api/v2/overview`

```
total distinct leaf paths         188
  INHERITED (from data)           161
  OWN (data / data.pricing)        21
  TIMESTAMP-FIELD                   5
  NONE                              1   (ok)
```
[VERIFIED]

Surface B has exactly **two** clocks for 183 value-bearing fields:
`data.as_of = "2026-08-29"` and `data.pricing.last_repriced = "2026-08-31
16:45:02 ET"`. Nothing below `data` carries a stamp of its own. Every field
scored `OWN` is a direct child of `data` or `data.pricing` and is therefore
`INHERITED` in substance — the parent's clock is not that field's clock. Counted
honestly, **182 of 183 value-bearing fields on `/api/v2/overview` carry no
`as_of` of their own, and the 183rd (`ok`) carries none at all.** [VERIFIED]

### Blocks that get it right (Surface A)

These carry a real evidence clock and say what it means. They are the model the
rest of the surface should be held to.

| block | `as_of` | why it is right |
|---|---|---|
| `cash` | `2026-08-03` | oldest contributing balance; `mixed_ages: true`, `distinct_stamps: 3`, per-account spread published |
| `capital_plan.cash_as_of` | `2026-08-03` | same, plus `document_as_of: 2026-08-29` kept separate |
| `operator_product.cash` | `2026-08-03` | same |
| `temperament` | `2026-08-03` | inherits the cash clock, correctly — it is a cash-derived block |
| `holdings_thesis_coverage` / `coverage` | three clocks | `cost_basis_as_of 2026-08-14T21:25:43Z`, `positions_as_of 2026-08-29`, `priced_as_of 2026-08-31 16:45:02 ET` — refuses to collapse three ages into one |
| `operator_product` | `2026-09-01T03:13:05Z` | product composition time, and `block_as_of.note` says so explicitly |
| `cio_now.decisions[*].cc_narrative` | `2026-08-30T02:34:32Z` | record write time, genuinely the narrative's age |
| `instrument_narratives.*` (37) | `2026-08-30T02:34:32Z` | same |

[VERIFIED]

`block_as_of` deserves quoting in full, because it is the best thing on either
surface:

```json
"block_as_of": {
  "cash": "2026-08-03",
  "portfolio": "2026-08-29",
  "product_composition": "2026-09-01T03:13:05+00:00",
  "note": "Block age is the oldest contributing evidence for that block.
           product_composition is when the brief/product was composed —
           never read it as cash age."
}
```
[VERIFIED]

### Blocks whose `as_of` is a composition clock — the false passes

543 fields sit under a block that *has* an `as_of` which is not a data clock.
Every one of these blocks would pass a naive "does it have an as_of" check.

| block | stamped `as_of` | Δ vs envelope | fields covered |
|---|---|---|---|
| `research_context` | `2026-09-01T03:14:43.345125Z` | 0.6 s | 215 |
| `strategy_context.research_context` | `2026-09-01T03:14:43.345125Z` | 0.6 s | 215 |
| `strategy_context` | `2026-09-01T03:14:43.365089Z` | 0.6 s | 50 |
| `evidence` | `2026-09-01T03:14:43.808956Z` | 0.2 s | 19 |
| `seasonality` | `2026-09-01T03:14:43.341809Z` | 0.6 s | 17 |
| `strategy_context.seasonality` | `2026-09-01T03:14:43.341809Z` | 0.6 s | 17 |
| `report` | `2026-09-01T03:14:43.808956Z` | 0.2 s | 10 |
| **total** | | | **543** |

[VERIFIED]

`seasonality` is the clearest case. Its content includes
`research_context.governed_almanac.slices.*.layers.current_application.as_of_year`
— an almanac keyed to a *year*. Stamping that block `2026-09-01T03:14:43.341809Z`
tells the operator the seasonality read is 0.6 seconds old. It is a year-scale
artifact. The envelope clock is not merely uninformative here; it is misleading
in the direction of freshness, which is the only direction that matters.

### Blocks with no `as_of` at all — inheriting only the root envelope

589 fields inherit `as_of = "2026-09-01T03:14:43.983358+00:00"`, which is
composition time.

| top-level block | fields |
|---|---|
| `graph_impact` | 140 |
| `cio_now` | 89 |
| `holdings_thesis_coverage` | 49 |
| `posture` | 36 |
| `capital_plan` (non-cash fields) | 34 |
| `notifications` | 33 |
| `opportunities` | 27 |
| `reentry_books` | 24 |
| `new_position_if` | 20 |
| `watch_block_summary` | 20 |
| `coverage` | 20 |
| `record_narrative_coverage` | 20 |
| `operator_trust` | 16 |
| `surface_a_status` | 16 |
| `case_summaries` | 15 |
| `consistency` | 14 |
| `_serving` | 8 |
| `block_as_of` | 4 |
| `provenance_footer` | 4 |
| root scalars (`version`, `authority`, `earmark_narrative`, `canonical_cio_source`, `model_produced`, `telegram_sent`, `delivery`, `ok`) | 8 |
| **total** | **597** (589 inherited + 8 direct) |

[VERIFIED]

`posture` (36 fields — concentration, risk_heat, sector_tilts, performance,
income, tax_issues) is the largest un-stamped block of genuinely dated
judgment-adjacent content. `graph_impact` (140) is 1-hop neighbour analysis over
holdings whose own price age is `2026-08-31 16:45:02 ET` and whose position age
is `2026-08-29`; neither reaches the block.

### Fields that inherit an `as_of` that is not theirs

These are the ones the brief asks to be named specifically — the block clock is
real, but it is the wrong clock for these fields.

| field | inherits | its real age | why the inherited clock is wrong |
|---|---|---|---|
| `cash_letter.cash_usd` | `cash_letter.as_of = 2026-08-03` | `2026-08-30T02:34:32Z` | value is read from the stored `SLEEVE:CASH` record, not from the cash rows the `2026-08-03` clock describes. §6. |
| `cash_letter.what` | same | same | renders that stored value as prose: "Cash sleeve 630784.82." |
| `cash_letter.cash_investable_usd` | same | live (`03:14:43`) | comes from the *live* capital plan, so this block mixes two ages under one stamp |
| `capital_plan.recommended_deploy_usd` | `capital_plan.cash_as_of = 2026-08-03` | opportunity-queue age (unstated) | a deploy recommendation is not as-of the cash's oldest balance |
| `capital_plan.recommended_raise_usd` | same | opportunity-queue age | same |
| `capital_plan.deployable_usd` | same | mixed | cash clock + queue clock |
| `capital_plan.post_plan_cash_usd` / `_pct` | same | mixed | projection over both |
| `capital_plan.sources[*].usd` where `key=trims_usd` (`$166,926.15`) | same | queue age | prospective trims are not cash-dated |
| `capital_plan.uses[*].usd` (all) | same | queue + sector age | none of these are cash-dated |
| `capital_plan.plan_digest` / `plan_version` | same | composition | a digest has no data age |
| `temperament.cash` / `operator_product.temperament.cash` | `temperament.as_of = 2026-08-03` | stored-field write time (unstated) | value is the **stored** `portfolio_totals.total_cash` (`630791.10`), not the row sum the `2026-08-03` clock describes. §6. |
| `temperament.narrative_voice.*` | `temperament.as_of = 2026-08-03` | composition | template metadata, not cash-dated |

[VERIFIED] for the values and the inheritance; [CODE] for the "real age"
attribution, traced to the producers cited in §5 and §6.

`capital_plan` is the instructive case. It carries `cash_as_of` and **no plain
`as_of`**, so every non-cash field in the block falls through to the cash clock.
The block did the hard part — it computed a real evidence clock for cash — and
then let 34 unrelated fields borrow it.

---

## 3 · The headline: fields missing their own `as_of`

**Surface A — `/api/v3/cio/home`.** 2,254 distinct leaf paths; 156 are themselves
timestamps; **2,098 value-bearing**. Of those:

- **958 (45.7%)** are backed by a real evidence clock.
- **1,140 (54.3%)** are not: 589 inherit only the root envelope clock, 543 sit
  under a block whose `as_of` is composition time, 8 hang directly off the root.

**Surface B — `/api/v2/overview`.** 188 distinct leaf paths; 5 timestamps; **183
value-bearing**. **182 carry no `as_of` of their own** (they inherit
`data.as_of` or `data.pricing.last_repriced`); **1 (`ok`) carries none at all**.
Counted as the brief asks — INHERITED is not YES — Surface B's compliance rate
is **0 of 183**.

The block-by-block breakout is the two tables in §2.

### The cash claim, confirmed and refuted

The AS-IS doc asserts "most payload blocks — including every cash number — carry
no `as_of` of their own". Regenerated, the claim splits.

**Every cash-related field, both surfaces:**

| # | field | surface | class | own `as_of`? | value | note |
|---|---|---|---|---|---|---|
| 1 | `data.total_cash` | B | D (undeclared) | **INHERITED-FROM-`data`** (`2026-08-29`) | `630791.10` | **26 days too fresh.** Real oldest balance is `2026-08-03`. |
| 2 | `data.today_by_account.moomoo_taxable_live.value` | B | D (undeclared) | INHERITED-FROM-`data` | `500.00` | this is the `2026-08-03` cash row itself, presented as of `2026-08-29` |
| 3 | `data.today_by_account.alpaca_taxable_live.value` | B | D (undeclared) | INHERITED-FROM-`data` | `5000.00` | `2026-08-04` balance, same |
| 4 | `cash.cash_usd` | A | **D (declared)** | **YES** — `2026-08-03` | `630790.42` | correct: oldest contributing balance |
| 5 | `cash.cash_n` | A | D | YES — `2026-08-03` | `5` | |
| 6 | `cash.status` | A | D | YES — `2026-08-03` | `PRESENT` | |
| 7 | `cash.cash_as_of.{as_of, oldest_row_as_of, newest_row_as_of, mixed_ages, distinct_stamps, unstamped, unstamped_accounts, by_account[*], document_as_of, source, note}` | A | D | YES (self) | — | 11 fields; the compliant implementation |
| 8 | `capital_plan.cash_total_usd` | A | D (undeclared) | YES — `2026-08-03` | `630790.42` | |
| 9 | `capital_plan.cash_reserved_usd` | A | D (undeclared) | YES — `2026-08-03` | `256595.22` | |
| 10 | `capital_plan.cash_investable_usd` | A | D (undeclared) | YES — `2026-08-03` | `374195.20` | |
| 11 | `capital_plan.cash_earmarked_redeploy_usd` | A | D (undeclared) | YES — `2026-08-03` | `630790.42` | **the three-way-branch field. §5** |
| 12 | `capital_plan.cash_free_unearmarked_usd` | A | D (undeclared) | YES — `2026-08-03` | `0.00` | an artifact of the clamp in #11, not a measurement |
| 13 | `capital_plan.cash_band.{min_pct,max_pct}` | A | D (undeclared) | INHERITED-FROM-`capital_plan` | `20.0 / 25.0` | policy constants; no data age. Harmless but mis-stamped. |
| 14 | `capital_plan.cash_posture` | A | D (undeclared) | YES — `2026-08-03` | `above policy band` | three-way branch output (`cio_capital_plan.py:162-169`), rendered as prose |
| 15 | `capital_plan.account_cash[*].{account, settled_cash_usd, as_of}` | A | D | **YES** (per-row) | — | correct: per-account stamps |
| 16 | `capital_plan.post_plan_cash_usd` / `_pct` | A | D (undeclared) | INHERITED-not-theirs | `321793.24 / 25.08` | projection over cash + queue |
| 17 | `operator_product.cash.*` | A | **D (declared)** | YES — `2026-08-03` | mirrors #4-7 | |
| 18 | `operator_product.block_as_of.cash` | A | D | YES (self) | `2026-08-03` | |
| 19 | `temperament.cash_as_of.*` / `operator_product.temperament.cash_as_of.*` | A | D | YES — `2026-08-03` | — | |
| 20 | **`cash_letter.cash_usd`** | A | **S (undeclared)** | **INHERITED-not-theirs** (`2026-08-03`) | **`630784.82`** | **stale stored value. §6** |
| 21 | **`cash_letter.what`** | A | T over S | INHERITED-not-theirs | `"Cash sleeve 630784.82."` | the operator sentence carries the stale number |
| 22 | `cash_letter.cash_source` | A | S | INHERITED | `position_rows` | claims the row-sum producer; the value is not the current row sum |
| 23 | `cash_letter.cash_investable_usd` | A | D | INHERITED-not-theirs | `374195.20` | live value beside a stale one, one stamp over both |
| 24 | `block_as_of.cash` | A | D | YES (self) | `2026-08-03` | |

**Verdict on the AS-IS cash claim:**

- **REFUTED for `/api/v3/cio/home`.** The cash block carries a correct, well-documented
  `as_of` of its own. `cash_evidence_as_of()` at
  `scripts/lib/cio_capital_plan.py:841-890` is a faithful implementation of
  AGENTS.md §9.1 — it takes the oldest stamp, publishes the spread, and refuses
  to fall back to `now`. Its docstring records the 2026-08-30 measurement that
  motivated it. Whether the AS-IS doc was wrong on 2026-08-30 or the fix landed
  after it, the claim does not hold at pin `d276657b7`. [VERIFIED] + [CODE]
- **CONFIRMED for `/api/v2/overview`.** `data.total_cash` has no clock of its own
  and borrows one that is 26 days too fresh. [VERIFIED]
- **NEWLY BROKEN in a way the AS-IS doc does not describe:** `cash_letter.cash_usd`
  has an `as_of` that is present, plausible, and belongs to a different number.
  That is worse than a missing stamp, because it survives inspection. §6.

### Why `2026-08-29` is the wrong clock for cash, concretely

```
$ python3 -c "... holdings.json is_cash rows ..."
moomoo_taxable_live | as_of= 2026-08-03 | broker_position_as_of= 2026-08-03 | mv= 500.0
alpaca_taxable_live | as_of= 2026-08-04 | broker_position_as_of= 2026-08-04 | mv= 5000.0
schwab_taxable      | as_of= 2026-08-31 | broker_position_as_of= 2026-08-14 | mv= 37899.91
schwab_roth         | as_of= 2026-08-31 | broker_position_as_of= 2026-08-14 | mv= 1472.71
schwab_rollover_ira | as_of= 2026-08-31 | broker_position_as_of= 2026-08-14 | mv= 585917.8
```
[VERIFIED] — read from
`/home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state/holdings.json`

A cash row carries two conflicting dates. `as_of` on the three Schwab rows says
`2026-08-31`; `broker_position_as_of` says `2026-08-14`. The first is a refresh
stamp, the second is when the broker last confirmed the balance.
`_CASH_STAMP_KEYS` at `cio_capital_plan.py:828-830` prefers
`canonical_mark_as_of` → `broker_position_as_of` → `as_of` → `updated_at`, with a
comment stating exactly why `updated_at` is last. The CIO surface therefore
reads the evidence clock. `/api/v2/overview` reads none of them — it takes
`portfolio_totals.as_of = 2026-08-29`, a document-level stamp.

AGENTS.md §9.1 (`AGENTS.md:461-463`) is unusually specific here:

> A cash block's age is the **oldest contributing balance**, not a composition
> timestamp and not the freshest component. A 27-day-old $500 makes the block 27
> days old.

That $500 is `moomoo_taxable_live`, stamped `2026-08-03`. Measured
2026-08-31, it is **28 days old**. The rule appears to have been written about
this exact row, and `/api/v2/overview` still presents it as 2 days old.

---

## 4 · Agent-originated count — it is 22, not 0

### Declared provenance classes, both surfaces

```
== /api/v3/cio/home
  declared-class field INSTANCES: {'D': 106, 'T': 4, 'A': 22}
  A distinct paths: ['case_summaries.class',
                     'case_summaries.items[*].class',
                     'operator_product.case_summaries.class',
                     'operator_product.case_summaries.items[*].class']
  T distinct paths: ['temperament.narrative_voice.class',
                     'operator_product.temperament.narrative_voice.class',
                     'reentry_books.a.class', 'reentry_books.b.class']
== /api/v2/overview
  declared-class field INSTANCES: {}
    NONE - no field on this surface declares a provenance class
```
[VERIFIED]

**Class-A count: Surface A = 22 instances across 4 distinct paths. Surface B = 0
(because Surface B declares nothing at all).**

### This contradicts the AS-IS doc — loudly

`CIO_ASIS_VS_SPEC_2026-08-30.md` states: *"Agent-originated fields reaching any
operator surface: zero."* At pin `d276657b7`, **22 field instances on
`/api/v3/cio/home` are stamped `"class": "A"` and are served to the operator.**
The block also self-describes in prose the operator can read:

```json
"case_summaries": {
  "banner": "A-context · NON_AUTHORITATIVE · does not change action",
  "authority_class": "NON_AUTHORITATIVE_CONTEXT",
  "class": "A",
  "source": "durable CASE_SUMMARY ACTIVE",
  "count": 10, "financial_action": false, "changes_action": false }

"provenance_footer": {
  "model_produced": false,
  "classes": "D counts/sums · T templates · A case-summary context", ... }
```
[VERIFIED]

Per AGENTS.md §11 and CLAUDE.md rule 10, the finding wins. The AS-IS doc's
sentence is false as measured at the point of display.

### But the label is also wrong, which is the more serious defect

Producer chain, read at the served release:

- `class: "A"` is a **hardcoded string literal**, twice:
  `scripts/lib/cio_investment_product.py:917` (block) and `:963` (per item).
  Nothing computes it.
- `items[*].content` is `rec.get("content")` — copied verbatim from a stored
  `CASE_SUMMARY` durable-memory record (`cio_investment_product.py:960`). By the
  §13.4 definitions that is **S**, snapshot-derived.
- That stored content was itself produced by `safe_case_content()` at
  `scripts/lib/hermes_case_summary.py:68-98`, which is a **pure f-string** over
  deterministic inputs — `critique.verdict`, `result_id`, an answered/total count
  from `_answered_count()`, and `plan.situation_type`:

```python
body = (
    f"Hermes research {verdict} for this case. Result {rid} closed the research gap"
    f"{sit_bit}{qbit} Thesis tension remains advisory-only; no order or stop implied."
)
```
  That is **T**, template.
- Subject selection is not agent judgment either: `collect_case_summaries()`
  takes *every* `CASE_SUMMARY` memory with status `ACTIVE`/`ADMITTED`, sorts by
  `created_at` descending, and truncates at `CASE_SUMMARY_CAP`
  (`cio_investment_product.py:934-945`). Recency and a cap, not a chosen subject.
- The payload states `model_produced: false` at both the root and in
  `provenance_footer`. [VERIFIED]

Against the §13.4 definition — *"A: the agent chose the subject, sought
evidence, formed a view"* — **none of the three conditions is met.** No agent
chose the subject, sought evidence, or formed a view.

So both readings of "how many class-A fields reach an operator surface" are
defects, and they point in opposite directions:

| reading | count | defect |
|---|---|---|
| **as displayed** (§9.5: "provenance class at the point of display") | **22** | contradicts the AS-IS doc's "zero" |
| **as produced** (§13.4 definition) | **0** | 22 fields are **mislabelled A** when they are T-over-S |

A field mislabelled `A` is worse than an unlabelled one. `A` is the class
reserved for judgment, and AGENTS.md §13.4 reserves `AgentView@v1` — the only
class-A artifact type — for a claim with reasoning, confidence and a falsifier,
"marked as opinion everywhere it is displayed". `case_summaries` carries a
banner saying `NON_AUTHORITATIVE_CONTEXT` and `changes_action: false`, so the
mislabel does not currently mislead toward action. It does corrupt the census:
any future check asking "has an agent-originated field reached the operator yet"
will answer yes, and be wrong. It also burns the signal that is supposed to fire
when `AgentView@v1` finally gets a producer.

### What the true zero means

Counted by producer rather than by label, **class-A count on both surfaces is
zero**, and the AS-IS doc's companion sentence — *"Every sentence the operator
reads is a rule, a threshold, a template, or a constant"* — is **substantively
correct**, verified against producers rather than labels. Every string I traced
resolved to an f-string over counts, a filter over a book, a stored constant, or
a value copied from a record. `model_produced: false` holds. Nothing on either
surface was written by a model or reasoned to by an agent.

### The closest near-miss

**`operator_product.executive_summary`** — and within it, the clause **`[D]
Nothing requires action today.`**

```
[T] RISK OFF — SELECTIVE RISK. [D] Nothing requires action today.
[D] Closest re-entries: ATAI +2.9% vs exit, BOXL -3.0% vs exit, TDG -11.0% vs exit.
Tracking 70 former names (26 near, 30 waiting, 14 avoid); 26 on close watch.
Advisory only — no orders placed.
```
[VERIFIED]

This reads as a Chief Investment Officer's morning verdict: a risk posture, an
all-clear, a shortlist, a coverage claim. It is none of those. The codebase has
already diagnosed it, in `scripts/lib/cio_p90_voice.py:24-35`:

```python
EXEC_SUMMARY_NOTE = (
    "the field name asserts synthesis; the value is an f-string over counts "
    "and filters (P9.0 #3)")
NOTHING_NOTE = (
    "emitted when action_book.DO_NOW is empty; derived, not a considered "
    "all-clear judgment (P9.0 #2)")
```
[CODE]

`"Nothing requires action today."` is a module-level constant at
`cio_p90_voice.py:21`, emitted on `len(action_book.DO_NOW) == 0`. AGENTS.md §9.1
names this exact string as a standing trap: *"Never render a template or a
constant in a register that implies judgment. 'Nothing requires action today'
reads as a verdict and is `do_n == 0`."*

The mitigation in place is the `[D]` / `[T]` inline stamp, which is real and
better than nothing. It is also the weakest possible form of the fix: it relies
on the operator knowing what `[D]` means and reading it every time, on a sentence
engineered to be read quickly. The field name still asserts synthesis. Runner-up
near-misses: `capital_plan.cash_posture` = `"above policy band"` (a three-way
branch rendered as a judgment), and `temperament.narrative_voice`, which is
labelled `T` with an admirably blunt note: *"f-string over regime label, as-of,
FS receipt count and ratified lesson count; not a written view"*.

### Class coverage is the unstated problem

§9.5 requires a provenance class **on every field**. Measured:

| surface | fields declaring a class | value-bearing fields | coverage |
|---|---|---|---|
| `/api/v3/cio/home` | 132 | 2,098 | **6.3%** |
| `/api/v2/overview` | 0 | 183 | **0%** |

[VERIFIED]

`/api/v2/overview` — the surface that carries the portfolio value, the cash
total, the day change and the account breakdown — declares no provenance class on
any field.

---

## 5 · The three-way-branch field

**Found.** `capital_plan.cash_earmarked_redeploy_usd`, surfaced to the operator as
`capital_plan.sources[key="earmarked_redeploy_usd"]`:

```json
{ "label": "Earmarked redeploy (already in cash)",
  "usd": 630790.42,
  "key": "earmarked_redeploy_usd" }
```
[VERIFIED]

### The branch

`scripts/lib/cio_capital_plan.py:388-396`:

```python
maturities_raw = round(sum(m["amount_usd"] for m in maturities), 2)
# Cap earmark at cash on hand (cannot label more redeploy $ than exists as cash)
cash = _fnum(cash_total) if cash_total is not None else None
if cash is not None and maturities_raw > cash + 0.01:
    maturities_usd = round(cash, 2)
    capped = True
else:
    maturities_usd = maturities_raw
    capped = False
```

Three paths: `cash is None` → uncapped; `raw > cash` → **clamped to cash**;
otherwise → raw. Returned at `:411` as `"earmarked_redeploy_usd": maturities_usd`.
[CODE]

### Which path fired — measured, not assumed

```
$ curl -s -X GET http://127.0.0.1:7777/api/v2/redeploy/opportunity-set
HTTP 200 bytes=4924
open_events n= 38
sum remaining_usd = 1026129.22
cash_total        = 630790.42
raw > cash ?      True
  DXCM 20380.04 | BND 27198.12 | SCHD 215911.75 | QCOM 8818.51 | DIVI 44678.88 | JEPI 86132.9 | ...
```
[VERIFIED]

`$1,026,129.22 > $630,790.42 + 0.01` → the **clamped** branch fired.

### What the operator would reasonably believe, versus what it is

| | |
|---|---|
| **Reads as** | "Of my cash, $630,790.42 is already earmarked for redeploy." A total. A sum of open redeploy commitments that happens to equal all my cash. |
| **Actually is** | A **ceiling**. Open redeploy commitments total **$1,026,129.22**. The figure shown is `min(raw, cash)` — the arithmetic bound on how much redeploy money can be sitting in cash, not how much is committed. |
| **Hidden** | **$395,338.80** of earmark — 38.5% of the real figure — is invisible on the surface. |
| **Knock-on** | `capital_plan.cash_free_unearmarked_usd = 0.00` is not a measurement that free cash is zero. It is `max(0, cash − earmark)` where earmark was clamped *to* cash, so it is arithmetically forced to `0.00` for any raw earmark ≥ cash. It reads as "you have no uncommitted cash". What it means is "the clamp fired". |
| **Fingerprint** | `cash_earmarked_redeploy_usd == cash_total_usd == 630790.42` **exactly**. That equality is the visible signature of the clamp: `min(raw, cash)` returns `cash` whenever `raw > cash`, so an earmark that equals the cash total to the cent is the payload telling you the branch fired — detectable from the response alone, without reading `cio_capital_plan.py`. An earmark that genuinely happened to equal cash to the cent would be a coincidence of 1-in-millions; the equality should be read as a clamp until proven otherwise. |
| **Direction** | The clamp *understates* commitment. An operator reading "$630,790 earmarked, $0 free" already sees a fully-committed sleeve, so the error does not invite over-deployment here. But `cash_free_unearmarked_usd` is pinned at `0.00` across the whole region `raw ≥ cash`, so it cannot move to signal a change. It is a constant wearing a measurement's name — AGENTS.md §9.5's own test: *"A field whose value never moves regardless of input is a constant, not a judgment."* |

### The disclosure exists and is dropped before serving

The producer computes the flag. It never reaches the operator:

```
maturities_capped_to_cash   in /api/v3/cio/home payload:  False
maturities_raw_usd          in /api/v3/cio/home payload:  False
maturities_capped_to_cash   in /api/v3/cio/brain/capital-plan payload:  False
```
[VERIFIED] — `in` here is substring presence over the full serialized payload;
both keys are absent entirely.

`build_capital_sources()` returns both `"maturities_raw_usd": maturities_raw` and
`"maturities_capped_to_cash": capped` (`cio_capital_plan.py:409-410`), and the
full plan carries `maturities_capped_to_cash` through to
`capital_sources` (`:751`). The `/api/v3/cio/home` projection selects
`capital_plan.sources` down to `{label, usd, key}` triples and drops both. The
single field that would tell the operator this number is a bound rather than a
sum is computed, carried most of the way, and then discarded at the last step.

This is a precise instance of AGENTS.md §9.5's *"a field whose value depends on a
three-way branch reads as a total"* — regenerated, with the branch quoted, the
inputs measured, and the fired path identified.

### Two other three-way branches worth naming

- `cash_posture()` at `cio_capital_plan.py:162-169` — four paths
  (`NO_PORTFOLIO` / `ABOVE_BAND` / `IN_BAND` / `BELOW_BAND`), surfaced as
  `capital_plan.cash_posture = "above policy band"`. Only `ABOVE_BAND` was
  reachable in the live state. It reads as a judgment; it is `cash_pct >=
  band.min_pct`.
- `deployable_usd = posture["investable_usd"] + prospective_raise`
  (`cio_capital_plan.py:635-637`) = `$541,121.35`. Reads as available cash. It is
  investable cash (`$374,195.20`) **plus prospective trims/exits that have not
  happened** (`$166,926.15`). `deploy_funding.note` does disclose this in prose;
  the top-level `capital_plan.deployable_usd` does not.

---

## 6 · Consistency check (M4 territory)

### Quantities appearing on both surfaces

| quantity | `/api/v2/overview` | `/api/v3/cio/home` | agree? |
|---|---|---|---|
| **total cash** | `data.total_cash` = **630791.10** | `cash.cash_usd` = **630790.42**; `capital_plan.cash_total_usd` = **630790.42**; `operator_product.cash.cash_usd` = **630790.42**; `cash_letter.cash_usd` = **630784.82** | **NO — three distinct values** |
| portfolio value | `data.portfolio_value` = 1282976.11 | not exposed at top level on this surface | n/a |
| position count | `data.position_count` = **15** | `holdings_thesis_coverage.held_n` = **15** | values agree; **scopes do not** |

[VERIFIED]

### M4 failure 1 — total cash, three producers, all three in one response body

This is the finding to lead with, and it is **not** primarily a cross-surface
disagreement. **`/api/v3/cio/home` alone states total cash 14 times across three
distinct values.** Every occurrence, from the single 237,920-byte response
captured at 03:14:43 UTC:

```
=== 630791.10  (2 occurrences) ===
    temperament.cash
    operator_product.temperament.cash
=== 630790.42  (5 occurrences) ===
    capital_plan.cash_total_usd
    capital_plan.cash_earmarked_redeploy_usd
    capital_plan.sources[2].usd
    cash.cash_usd
    operator_product.cash.cash_usd
=== 630784.82  (7 occurrences) ===
    cash_letter.cash_usd
    cio_now.decisions[2].cc_narrative.evidence_refs[3].total_cash
    cio_now.decisions[3].cc_narrative.evidence_refs[1].total_cash
    opportunities.watch[1].cc_narrative.evidence_refs[1].total_cash
    opportunities.reentry[0].cc_narrative.evidence_refs[2].total_cash
    opportunities.reentry[3].cc_narrative.evidence_refs[2].total_cash
    opportunities.reentry[4].cc_narrative.evidence_refs[2].total_cash
```
[VERIFIED]

An operator does not need two tabs to find this. One page contradicts itself
three ways, and the stalest of the three (`630784.82`) is the one rendered as
prose and the one cited **six times as evidence** underneath individual
decisions and re-entry candidates — `cc_narrative.evidence_refs[*].total_cash`
is the number a decision points at to justify itself.

The three underlying producers:

```
holdings.json portfolio_totals.total_cash  = 630791.10   (stored field)
sum of the 5 is_cash rows in the same file = 630790.42
gap                                        = 0.68
SLEEVE:CASH record cash_usd                = 630784.82   (stored, written 2026-08-30T02:34:32Z)
```
[VERIFIED] — read from
`/home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state/holdings.json`
and `.../data/cio/cio_instrument_records.jsonl`

1. The **stored** `portfolio_totals.total_cash` → `630791.10`. Read by
   `/api/v2/overview` (`api_v2.py:2606-2610`) **and by `temperament` on
   `/api/v3/cio/home`**.
2. The **`is_cash` row sum** → `630790.42`. Used by `cash` and `capital_plan` on
   `/api/v3/cio/home`. Confirmed independently by
   `/api/v3/cio/brain/capital-plan` `observed_cash_usd` = `630790.42`.
3. The **stored `SLEEVE:CASH` record** → `630784.82`. Used by `cash_letter` and by
   every `cc_narrative.evidence_refs[*].total_cash`.

`temperament` is the one I missed on the first pass and it is the sharpest of the
three, because it breaks the tidy story that "the CIO surface uses the row sum
and overview uses the stored field". It does not: **`/api/v3/cio/home` carries
all three producers at once.** `temperament` is also stamped
`as_of: "2026-08-03"` — the cash-*evidence* clock — while carrying the
stored-field value, so it is a further instance of the inherited-not-theirs class
in §2, and it belongs in that table.

The code at `api_v2.py:2593-2601` documents an invariant that has since broken:

```python
# ... #635 made portfolio_repricer._recalc_totals write total_cash from
# the is_cash position rows on every pass, and the 2026-08-29 Saturday proof
# showed the stored field agreeing with the row sum to the cent
# (630,784.82, source=position_rows, gap 0.00) across holdings.json,
# /v2/overview and /v3/cio.
#
# Read the stored field. Two places deriving the same number is how the
# original drift went unnoticed for three months: the read site quietly
# papered over a writer that had stopped writing.
```

The comment's reasoning is sound and its conclusion is now false. Measured
2026-08-31, the gap is **$0.68, not $0.00**. And `630,784.82` — the exact value
the comment cites as the agreed figure — is what the `SLEEVE:CASH` record still
holds and what `cash_letter` still renders. The comment is a fossil of the moment
all three agreed. The deliberate choice to read the stored field rather than
recompute is the right call *if* the writer is verified to still be writing; the
$0.68 gap is evidence that it is not, and the read site no longer papers over it —
it now disagrees with the other surface instead.

### M4 failure 2 — `cash_letter` disagrees with the block beside it

The sharpest instance, because it is **intra-surface** — one payload, two cash
totals, one stamp.

`scripts/lib/cio_record_narrative.py:103-105`:

```python
cash_usd = rec.get("cash_usd")
if cash_usd is None:
    cash_usd = cp.get("cash_total_usd")
```

The stored record wins whenever it has a value. It does:

```
$ python3 ... cio_instrument_records.jsonl, subject_key == SLEEVE:CASH
cash_usd          = 630784.82
cash_source       = position_rows
cc_narrative.what = Cash sleeve 630784.82.
cc_narrative.as_of= 2026-08-30T02:34:32.327723+00:00
```
[VERIFIED]

Meanwhile `cash_investable_usd` on the same block comes from the **live** plan
(`cio_record_narrative.py:131`, `cp.get("cash_investable_usd")`). The served
block:

```json
"cash_letter": {
  "schema": "CashSleeveLetter@v1",
  "cash_usd": 630784.82,            // stale, from the record
  "cash_source": "position_rows",   // names the live producer; not the live value
  "cash_investable_usd": 374195.2,  // live, from the capital plan
  "what": "Cash sleeve 630784.82.",
  "as_of": "2026-08-03",            // the cash-evidence clock — belongs to neither number
  "as_of_source": "cash_evidence_oldest_balance",
  "composition_as_of": "2026-09-01T03:14:43.983358+00:00",
  "from_record": true, "copy_step": "migration", "writer": "deterministic" }
```
[VERIFIED]

Three defects stacked in one block:

1. **It does not reconcile with itself.** `630784.82 − 256595.22 = 374,189.60`,
   but the block shows `374,195.20`. The two numbers cannot both be true of the
   same book at the same moment.
2. **`cash_source: "position_rows"` is false of the value shown.** It names the
   live row-sum producer; the value came from a stored record.
3. **`as_of: 2026-08-03` belongs to neither number.** It is the cash-evidence
   clock (correct for `cash.cash_usd`, inherited here). The real age of
   `cash_letter.cash_usd` is `2026-08-30T02:34:32Z`. The stamp is present,
   plausible, and wrong — the failure mode that survives inspection.

The block's own prose reaches the operator: **"Cash sleeve 630784.82."** That is
the sentence a reader takes away, and it is $5.60 stale and $6.28 away from what
`/api/v2/overview` says.

`_stamp_cash_letter_provenance` (`cio_command_center.py:1526-1533`) exists
specifically to fix an earlier version of this — its docstring says
*"`build_cash_letter` historically stamped `as_of=now` (composition)."* The fix
replaced a composition clock with the cash-evidence clock. It corrected the
stamp without noticing that the *value* it stamps no longer comes from the cash
rows.

### Latent M4 — `position_count` agrees today by luck

| | |
|---|---|
| `/api/v2/overview` `data.position_count` | `15`, no scope label |
| `/api/v3/cio/home` `holdings_thesis_coverage` | `held_n: 15`, `held_n_including_dust: 19`, `dust_n: 4`, plus a full `dust_policy` object (`dust_residual@v1`, threshold `$50.00`, per-ticker across accounts, `rejected_alternative`, `deletes_lots: false`) |

[VERIFIED]

The values agree. The **scopes** are labelled on one side only. The operator
reading `position_count: 15` cannot tell whether dust is in or out; the honest
answer is that there are 19 positions and 4 are dust. The moment the dust
threshold, the book, or the policy changes, these two fields diverge with no
labelled scope to explain why — and the divergence will look like a bug in one of
them rather than a difference in question. §9.5: *"No two surfaces may state the
same quantity differently without a labeled scope saying which question each
answers."* Today they state it identically without a labelled scope, which
satisfies the letter and not the purpose.

### The surface ships a self-declared parity failure

```json
"consistency": {
  "capital_plan_digest": "b4447d901b4adeb5...",
  "plan_version": "capital_plan_1.3.0",
  "office_home_version": "office_home_1.3.0",
  "decision_field_parity": {
    "version": "decision_field_parity_1.0.0",
    "ok": false,
    "decision_count": 19,
    "surfaces_checked": 2,
    "missing_required": [ {"decision_id": "dec_443cc15b67e6bd40", "surface": 1,
                           "missing": ["recommended_delta_usd"]}, ... ×4 ],
    "field_mismatches": [],
    "missing_sizing_on_actionable": ["dec_443cc15b67e6bd40",
                                     "dec_b219249e141ee327",
                                     "dec_f66c157dd02fc150"] } }
```
[VERIFIED]

The surface runs its own two-surface parity check, **fails it**, and serves the
failure inline. `ok: false` with three actionable decisions missing
`recommended_delta_usd`. This is genuinely good practice — §9.5 asks for exactly
this, and a failure that reaches a surface rather than a log line is what
AGENTS.md §9.1 demands. It also means the M4 gap is **already measured by the
system and already visible**, and the surface renders normally around it. The
`consistency` block itself has no `as_of` of its own (14 fields inheriting the
root envelope), so an operator cannot tell whether `ok: false` is from this
render or a stale carry.

### What would remain to be shown for M4

**I am not declaring M4 observed, and nothing here should be read as observing
it.** M4 requires one regenerable producer per number. What this census shows is
the opposite for the single most important number on either surface. To close it,
someone would still have to show, at a named pin:

1. `/api/v2/overview` `data.total_cash`, `/api/v3/cio/home` `cash.cash_usd`, and
   `cash_letter.cash_usd` all resolving to the same producer, agreeing to the
   cent, and each carrying that producer's evidence clock.
2. `portfolio_repricer._recalc_totals` demonstrably writing on every pass — the
   $0.68 gap is the evidence it currently is not, and a run that closes the gap
   once is not evidence the writer is live.
3. `position_count` carrying a scope label naming which question it answers.
4. `consistency.decision_field_parity.ok` reading `true`, with its own `as_of`.
5. A re-run at a later pin showing all four still hold — one agreeing snapshot is
   what the 2026-08-29 proof was, and it did not survive three days.

---

## 7 · Proposed morning diffs

**Proposals only. Nothing in this section was applied. No file outside this
document was modified, and no commit was made.** All line numbers are from the
served release at pin `d276657b7`; re-read before editing, as the working tree
may differ.

Ordered by ratio of operator harm removed to blast radius.

### P1 — `cash_letter` must not render a stale stored cash total
**Producer change.** `scripts/lib/cio_record_narrative.py:103-105`.

Invert the precedence so the live plan wins and the record is the fallback, and
surface the disagreement rather than hiding it:

```python
cash_usd = cp.get("cash_total_usd")
if cash_usd is None:
    cash_usd = rec.get("cash_usd")
```

Plus a `cash_usd_source` field (`"live_plan"` / `"record_fallback"`) and, when
both exist and differ by more than a cent, a `cash_record_drift_usd` field so the
gap reaches the surface instead of being silently resolved. `what` regenerates
from the corrected value automatically (`:112-114`).

- **Fixes:** the `630784.82` on the operator's page; the internal
  non-reconciliation with `cash_investable_usd`; the false
  `cash_source: "position_rows"`.
- **Does not touch:** any store. The record is read, never written.
- **Risk:** low. Single read-site precedence flip in one block.
- **Flag:** none. Not operator-ranked, no schema change, no store write.

### P2 — disclose the earmark clamp
**Renderer change.** The `/api/v3/cio/home` `capital_plan.sources` projection.

The producer already computes both fields (`cio_capital_plan.py:409-410`) and
carries them into `capital_sources` (`:751`). The home projection narrows
`sources` to `{label, usd, key}` and drops them. Widen that projection to carry
`maturities_capped_to_cash` and `maturities_raw_usd` through, and make the label
conditional:

```
"Earmarked redeploy (capped at cash on hand — $1,026,129 committed)"
```
when `maturities_capped_to_cash` is true.

- **Fixes:** §5 in full. The operator learns the number is a bound, and learns
  the $395,338.80 that is currently invisible.
- **Producer:** unchanged — both values already exist.
- **Risk:** low. Additive fields plus a conditional label string.
- **Flag:** **changes what an operator reads on a ranked surface.** The label is
  part of the capital-plan presentation. Under AGENTS.md §17 this is
  **OPERATOR-ONLY — propose and stop.** Recommended, not to be applied by an
  agent.

### P3 — give `/api/v2/overview` a cash block with its own `as_of`
**Producer change.** `scripts/api_v2.py:2606-2610` and the return dict at `:2611+`.

`cash_evidence_as_of()` (`cio_capital_plan.py:841-890`) already does exactly this
job correctly for the CIO surface and takes plain holdings rows. Call it here and
add a sibling block:

```python
"cash_as_of": cash_evidence_as_of(holdings, doc=h),
```

leaving `data.total_cash` where it is. `data.as_of` stays the positions clock; the
cash's own clock arrives beside it.

- **Fixes:** the 26-day understatement — the single largest freshness error found.
- **Reuses:** the compliant implementation. No new logic, no new type.
- **Risk:** low-moderate. Additive field on a high-traffic, semaphore-exempt
  endpoint; `cash_evidence_as_of` is pure and I/O-free, but the endpoint is
  latency-sensitive (measured 80 ms).
- **Flag:** additive to an operator-ranked surface's payload. It does not change
  ranking or any existing value. Worth an operator's nod; not in the §17 list.

### P4 — one producer for total cash
**Producer change, and the only one here that is really a decision.**

Three call sites read three sources (§6). Converging them requires choosing which
is canonical. The `api_v2.py:2593-2601` comment argues, correctly, that two read
sites deriving the same number is how the original three-month drift hid — so the
answer is not "make `/api/v2/overview` recompute too". The answer is one producer
both surfaces call.

Minimum honest step, and the only part I would propose an agent do: add a
**parity assertion** that surfaces the gap rather than resolving it, in the shape
`consistency.decision_field_parity` already uses:

```json
"cash_parity": { "ok": false, "stored_usd": 630791.10, "row_sum_usd": 630790.42,
                 "record_usd": 630784.82, "gap_usd": 0.68,
                 "as_of": "<evidence clock>" }
```

- **Flag:** choosing the canonical producer is a **schema and store question**
  (which of `portfolio_totals.total_cash`, the row sum, or the `SLEEVE:CASH`
  record is authoritative) and it determines what an operator reads on a ranked
  surface. **OPERATOR-ONLY per §17 — propose and stop.** The parity assertion is
  additive and safe; the convergence is not an agent's call.
- **Do not** "fix" the $0.68 by writing to `holdings.json`. That is an
  authoritative store, and §9 / rule 5 apply.

### P5 — stop stamping composition clocks as `as_of`
**Producer change**, seven blocks, 543 fields.
`report`, `evidence`, `strategy_context`, `strategy_context.research_context`,
`strategy_context.seasonality`, `seasonality`, `research_context`.

Rename the field in each from `as_of` to `composition_as_of`, and add a real
`as_of` where an evidence clock exists (`seasonality` has an almanac year;
`research_context` has per-slice application years). Where none exists, emit
`"as_of": null, "unstamped": true` — the pattern `cash_evidence_as_of` already
uses (`cio_capital_plan.py:877-882`), and the docstring's reasoning applies
verbatim: *"a visible absence rather than a false freshness."*

`cash_letter` already models the correct shape — `as_of` + `composition_as_of` +
`as_of_source` side by side. Copy it.

- **Risk:** moderate. Renaming a served field can break SPA consumers. Ship
  `composition_as_of` additively first, migrate readers, then change `as_of`.
- **Flag:** schema change on an operator-ranked surface. Sequenced migration,
  operator-visible. Propose and stop on the `as_of` rename; the additive
  `composition_as_of` half is safe.

### P6 — `block_as_of` should cover every block
**Renderer change.** `block_as_of` currently names three blocks (`cash`,
`portfolio`, `product_composition`) and its `note` is the clearest provenance
writing on the surface. Extend it to one entry per top-level block, with `null`
where unknown. That converts 597 silent root-inheritors into an explicit,
auditable table without touching any producer.

- **Risk:** low. Additive.
- **Flag:** additive to an operator-ranked surface.

### P7 — reclassify `case_summaries` from `A` to `T`
**Producer change.** `scripts/lib/cio_investment_product.py:917` and `:963` —
two hardcoded string literals.

Per §4, the content is an f-string (`hermes_case_summary.py:68-98`) reproduced
from a stored record. The honest classes are `T` for the generated prose and `S`
for the reproduction. Update `provenance_footer.classes` at
`cio_operator_product.py` accordingly (currently `"D counts/sums · T templates ·
A case-summary context"`).

- **Fixes:** the mislabel; restores `A` as a meaningful signal for when
  `AgentView@v1` gets a producer.
- **Flag:** **do not apply without the architect.** If `A` was deliberately
  chosen to reserve the slot for the future `AgentView@v1` producer, this diff
  erases an intentional marker. The AS-IS doc's "zero class-A" claim suggests it
  was *not* deliberate — but that is inference, not evidence, and §13.4 names
  `AgentView@v1` as specified-with-no-producer, which is consistent with either
  reading. **Propose and stop; ask.**

### P8 — provenance class coverage
**Producer change**, both surfaces. §9.5 requires a class on every field; measured
coverage is 6.3% and 0%. Full per-field classes are a large change; the tractable
first step is a **block-level `class`** on every top-level block (most are
uniformly `D`), which raises coverage to near-total for a small diff.
`/api/v2/overview` needs this most and currently has nothing.

- **Flag:** additive; schema change on operator-ranked surfaces. Sequence after
  P5/P6.

### Explicitly not proposed

- Nothing that writes to `holdings.json`, `cio_instrument_records.jsonl`, or any
  store. The $0.68 and the $5.60 are **evidence**, not bugs to be normalized away,
  and normalizing them destroys the evidence that a writer stopped writing.
- Nothing touching `place_order`, broker paths, 2FA, order routes, or
  `BehaviorWriteRefused`. **HARD PIN.**
- No change to notification delivery, dedupe, or any scheduled job.
- No new `@v1` type. Every proposal reuses an existing field, type, or shape.

---

## 8 · Corrections

Kept in the document per the evidence standard.

1. **`/v3/cio` is a static SPA route, not a JSON API.** My first search for route
   handlers assumed the brief's framing. `portfolio_server.py:1915` serves
   `apps/command-center-v3/dist/index.html` for `/v3/*`. The JSON surface is
   `/api/v3/cio/*`, dispatched at `api_v2.py:40597`. Corrected before any
   measurement was taken.
2. ~~**Provenance classes are §13.5, not §13.4.**~~ **WITHDRAWN.** See correction
   8 below — this "correction" was itself wrong, and the brief's original §13.4
   citation was correct.
3. **`api_v3_cio.py` defines no routes.** It is a module of handler functions;
   routing lives in `api_v2.py`. My initial `grep` for `@app.route` returned
   nothing and I briefly mis-read that as the file being unrouted.
4. **My first `as_of` classifier scored 885 fields "YES" on Surface A.** That was
   wrong — it counted any ancestor `as_of` as a pass, including composition
   clocks. Rewritten to separate evidence clocks from composition clocks, which
   moved 543 fields from pass to fail. The 45.7% / 54.3% split in §3 is from the
   corrected pass. The first number should not be cited.
5. **I initially read `capital_plan` as having no block clock.** It has
   `cash_as_of` and no plain `as_of`, so its non-cash fields fall through to the
   root envelope. Both statements needed to be made separately; §2 does so.
6. **I first attributed the Schwab cash rows the date `2026-08-31`**, from a
   `p.get('as_of') or p.get('price_as_of') or p.get('updated_at')` fallback in my
   own probe. The rows carry *two* dates and `broker_position_as_of` (`2026-08-14`)
   is the evidence clock. My probe replicated in miniature the exact defect this
   audit is about. Corrected in §3.
7. **The brief's "expect 0" for class A was a premise, not a measurement.** It is
   22 as displayed, 0 as produced. §4 gives both and does not privilege the
   brief's prior.
8. **I corrected the brief on the provenance-class citation, the coordinator
   re-measured, and the brief was right.** Recorded in full because the round
   trip is the useful part.
   - I claimed provenance classes live in §13.5, not §13.4. My line numbers
     (`AGENTS.md:785-793`) were correct; my section attribution was not.
   - The coordinator re-measured:
     ```
     $ grep -n "^## 13\.\|^### Provenance" AGENTS.md
     689:## 13.4 · The type vocabulary — what already exists
     785:### Provenance classes — every operator-facing field carries one
     834:## 13.5 · Pre-build check
     847:## 13.6 · Operator surface data producers
     ```
     I reproduced this independently. Line 785 falls between 689 and 834, so
     `### Provenance classes` is a **subsection of `## 13.4`**. §13.5 is
     "Pre-build check" and contains no provenance classes at all. **The brief's
     original §13.4 citation was correct.** Reverted at lines 546, 566, 576, 579
     and 1096; the two "correction" entries are struck through rather than
     deleted.
   - **The near-miss, named explicitly:** I resolved the citation by finding the
     nearest **`###`** heading above line 785 and treating it as a peer of the
     `##` sections, instead of resolving the nearest enclosing **`##`** heading.
     A `###` under a `##` is a subsection, not a sibling. **The fix is to resolve
     the nearest enclosing `##`, never the nearest `###`.** A line range alone
     cannot distinguish the two, and I cited from the line range.
   - Why this one matters more than the others here: a bad citation in a
     delivered audit is the §4 defect the standard exists to prevent, and this
     one appeared in a section whose entire purpose was correcting someone else.
     A confident correction is exactly the claim that gets re-used without
     re-checking. AGENTS.md §11's "when a finding contradicts the brief, the
     finding wins" is not a licence to skip verifying the finding first — and I
     did not verify this one before writing it down.
9. **I understated the cash contradiction as cross-surface when it is
   single-body.** My first draft of §0 and §6 framed `$630,791.10` as a
   `/api/v2/overview` value contrasted against the CIO surface. The coordinator
   re-measured and found all three values inside a single `/api/v3/cio/home`
   response. I reproduced it (§6). A reader never has to leave one page to find
   the contradiction. §0 finding 1 and §6 were rewritten; the cross-surface gap
   is real but is the smaller half of the finding.

---

## 9 · What this census structurally cannot see

### States I could not produce

The live book sat in one state. Every branch not taken hides fields.

| unreachable state | branch site | what is hidden |
|---|---|---|
| `cash_as_of.unstamped = true` | `cio_capital_plan.py:877-882` | populated `unstamped_accounts`; measured `unstamped: false`, `unstamped_accounts: []` |
| `cash_posture` ∈ {`IN_BAND`, `BELOW_BAND`, `NO_PORTFOLIO`} | `cio_capital_plan.py:162-169` | 3 of 4 paths unobserved; only `ABOVE_BAND` seen. A `BELOW_BAND` book may render different capital-plan fields entirely. |
| `maturities_capped_to_cash = false` | `cio_capital_plan.py:390-396` | the uncapped path; I only observed the clamp firing. The `cash is None` path is also unobserved. |
| `operator_product.status != "AVAILABLE"` | `cio_operator_product.py:103-131` | the default/degraded product shape — a different field set. Measured `AVAILABLE`. |
| `collect_case_summaries` provider failure | `cio_investment_product.py:927-930` | `quality: "DATA_UNAVAILABLE"` + `reason` — 2 fields never seen |
| `build_cash_letter_section` failure paths | `cio_command_center.py:1493-1522` | `available: false` + `reason`, and `record_refused` — 3 fields never seen |
| notification `IMMEDIATE` / `DIGEST` / `SUPPRESSED` | notification policy | measured `delivery: "dashboard"`, `telegram_sent: false` only. The `notifications` block (33 fields, no `as_of`) may carry more under a firing state. |
| `deploy_exceeds_investable_cash = false` | `cio_capital_plan.py:653` | measured `true`; the non-gap prose in `deploy_funding.note` unobserved |
| empty books | throughout | `earnings` (10), `new_position_if` (5), `case_summaries` (10), `reentry_books`, `watch_block_summary` all non-empty. Empty-state renderings unobserved. |

**Rough scale of what this hides:** the branches above are ~9 unreached states.
Where I could count the alternate shape from source it is 2-5 fields each; where
I could not (`operator_product` degraded, `BELOW_BAND` capital plan, a firing
notification) it could be dozens. **A defensible estimate is 30-80 fields not
enumerated here, and I cannot narrow it without producing those states.** I did
not attempt to, because producing them means writing state — out of scope, and
several would require touching stores or the notification path.

### Sub-routes not censused

I censused `/api/v3/cio/home` and `/api/v2/overview`. **38 other GET sub-routes**
under `/api/v3/cio` were enumerated (§1) but not walked. Several are certainly
operator-facing — the SPA bundle fetches `brain`, `plans`, `dispositions`,
`intelligence`, `symbol-thesis`, `universe-theses`, `investment-product`,
`agent-research-ops`, `decision`. `/api/v3/cio/brain/capital-plan` alone returns a
different schema (`CashDeploymentSituation@v1`) with a **fourth** presentation of
cash — `observed_cash_usd: 630790.42` alongside `verified_cash_usd: null`,
`investable_cash_usd: null`, and `reserved_cash_usd: null`, where
`/api/v3/cio/home` states `cash_investable_usd: 374195.20` and
`cash_reserved_usd: 256595.22` as known. **The same two quantities are `null` on
one surface and populated on another.** I did not pursue it. It is very likely a
further M4 instance and it is the first thing I would look at next.

Symbol-scoped routes (`intelligence/<sym>`, `symbol-thesis/<sym>`,
`thesis-ri-pipeline/<sym>`, `ask-thesis/<sym>`, `plans/<plan_id>`) multiply per
subject; their field counts are unbounded by this census.

### Structural blind spots

- **A census reads the payload, not the pixels.** A field present in JSON may
  never render, and a rendered string may be assembled client-side from several
  fields — in which case *its* provenance and `as_of` exist nowhere in this
  document. The SPA bundle is minified; I confirmed which endpoints it fetches,
  not which fields it shows or how it composes them. **Every count here is an
  upper bound on what the operator sees and a lower bound on what they might be
  shown.**
- **Provenance class was read where declared and traced to a producer where I
  followed the chain.** I traced `case_summaries`, `cash`, `cash_letter`,
  `executive_summary`, `narrative_voice`, and the capital-plan fields. The
  remaining ~106 `D` declarations I did **not** independently verify against
  their producers. Given that the one class I did audit end-to-end turned out to
  be mislabelled, **the `D` declarations should be treated as unverified.**
- **§9.5's constancy test was not run.** *"Test by feeding the producer
  materially different situations and finding which rendered fields are
  byte-identical across all of them."* That requires executing producers against
  varied inputs. I observed one situation. `cash_free_unearmarked_usd = 0.00` is
  a constant-in-disguise I could identify **by reading the branch** (§5), not by
  testing — and that is the only one this method could catch. **There are almost
  certainly others, and this census is structurally blind to them.**
- **One moment in time.** Everything is pin `d276657b7`, 2026-09-01
  03:14-03:18 UTC. The `$0.68` gap and the fired clamp are true of that moment.
  AGENTS.md §11 warns that six promotes in an hour have been seen from a peer
  session; I re-checked `CURRENT` at the end and it had not rotated, but a
  re-measurement at any later pin may differ and **should regenerate rather than
  quote these numbers**.

### UNKNOWN count

Fields I enumerated but could not confidently assign a provenance class from
declaration or a traced producer: **1,966 of 2,098** on `/api/v3/cio/home` (132
declared, of which ~26 traced to producers), and **183 of 183** on
`/api/v2/overview`. Per the evidence standard, that count is itself the
measurement: **the great majority of what the operator reads on these two
surfaces has no stated provenance, and cannot be given one without walking each
producer.**
