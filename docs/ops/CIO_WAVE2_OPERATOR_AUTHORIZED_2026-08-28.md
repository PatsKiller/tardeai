# CIO Wave 2 — operator-authorised applies + slice 12a live-activation fix

Authority: **READ_ONLY_ADVISORY** · MBI **0** · INTERDICT **0** (left as found)
CURRENT pin: `5f215504` (#621, promoted 2026-08-29T02:39:18Z) · health/cio/home 200
No cap raised · no `--backend live` · no notify · no Telegram · **no history deleted**

Three operator decisions executed, plus one defect found by verifying the promote.

---

## Defect found by verifying the promote — slice 12a was not live

`#621` promoted cleanly and `/v3/cio/home` still reported:

```
coverage.held_n        19      (should be 15)
coverage.with_plan     14      including JEPI, LDOS, SRNE — all dust
holdings_thesis_coverage.dust_tickers   None
```

**Cause.** `cio_operator_product` prefers the persisted brief's
`holdings_thesis_coverage` and only recomputed it when `held_n` was missing —
a condition a *pre-12a* block satisfies. So the stale block kept being served
until the next brief persist happened to rewrite it. The slice was correct;
whether the operator saw it was a matter of timing.

**Fix.** The freshness check now also treats a block missing the 12a keys
(`dust_tickers`, `held_n_including_dust`) as stale and recomputes. The fail-soft
zero block gained the same keys so it cannot itself look pre-12a.

This is why an exact-main promote is verified against the live payload and not
against the merge commit. A green CI and a clean promote both held while the
surface was still wrong.

---

## Decision 2 — attach the two earned research joins (AUTHORIZED)

Dried both first; both `critique: VALID` and attachable.

| plan_id | research_id | hermes_result_id | symbol | critique |
|---|---|---|---|---|
| `plan_5463afc7bc04` | `res_700c97861291` | `rr_9281c7e7988a` | BJDX | VALID |
| `plan_9f4df5b991f3` | `res_57ab7a7067d8` | `rr_a1c0d31c6448` | RGNT | VALID |

```
before: plans_missing_result_id 254 · would_attach 2
after : plans_missing_result_id 252 · would_attach 0 · attached 2
```

`would_attach` was exactly 2, so `--apply` wrote exactly those two — the 474
were never touched, as instructed.

**CASE_SUMMARY was not double-minted.** Both plans already carried one from the
forward path at completion time; the total stayed **328**. That is slice 23's
`(symbol, plan_id, result_id)` dedup doing its job, not a missed mint.

## Decision 4 — cancel orphan S6 (AUTHORIZED)

An `S6_CONCENTRATION_OR_DISPOSITION` plan asks a question that presupposes a
position. Implemented as a rule derived from holdings rather than a hardcoded
symbol list, so it stays correct as the book changes.

```
would_cancel 20
  cash_sleeve     1   CASH
  not_held        1   QCOM
  dust_residual  18   SRNE      (same dust rule as SCHG)
cancelled 20 · notify false · deletes_history false
```

Eighteen SRNE plans, not one — the detector had been re-firing on a $0.90
residual. A plan naming *any* held non-dust symbol is kept, so a multi-symbol
plan is never orphaned by one bad leg. S1 plans on dust are out of scope; slice
12c already keeps S1 off dust and double-governing would hide which rule acted.

**Cancelled, never deleted.** `cio_plans.jsonl` grew 4,958 → 4,998 lines
(append-only `PLAN_UPDATED` events). Every plan stays readable.

### Live effect

| surface | before | after |
|---|---|---|
| `coverage.held_n` | 19 | **15** |
| `coverage.with_plan` | 14 (incl. JEPI/LDOS/SRNE) | **11** |
| `graph_impact.s6_symbols` | 8 (incl. CASH/QCOM/SRNE) | **5** — AMANX BND DIV SCHD SPCX |
| `graph_impact.skipped` | CASH, QCOM, SRNE | **[]** |
| `telegram_sent` | false | false |

**Standing risk, not fixed here:** nothing stops the S6 detector re-creating
these. The 18 SRNE plans are evidence it already does. Cancelling is the
authorised action; teaching the detector the dust rule is a separate change and
is *not* made tonight.

## Decision 3 — cost_cap classification (AUTHORIZED)

Already implemented in slices 19–21 on this branch: `COST_CAP_EXCEEDED`,
`daily request cap` and `RESERVATION_FAILED` carrying that message all classify
as `cost_cap` with `is_worker_bug: false`, never `provider_error`. No cap raised,
no `--backend live`.

## Decision 5 — slice 13 stays a measurement

No identity minted. The re-entry and watch surfaces still resolve 100% and stamp
0%; nothing was stamped tonight.

---

## Rails

| Rail | State |
|---|---|
| Writes performed | 2 research attaches + 20 S6 cancels — **both explicitly authorised** |
| History deleted | **none** — append-only, 4,958 → 4,998 lines |
| Blanket backfill on the 474 | **not run** |
| Identity minted | 0 |
| Caps raised | none |
| `--backend live` | not run |
| notify / Telegram | off; `telegram_sent` false |
| MBI / INTERDICT | 0 / 0 |
| Backups | `cio_plans.jsonl` copied to the session scratchpad before each apply |

## Tests

`tests/test_cio_wave2_orphan_s6_hygiene.py` — 9 assertions: a held subject is
never orphaned, the three reasons classified distinctly, one bad leg not
orphaning a multi-symbol plan, S1 left alone, dry writing nothing, apply
cancelling with the reason carried into `status_reason`, and `deletes_history`
false.

`tests/test_cio_wave2_slice12a_live_activation.py` — 7 assertions covering the
pre-12a block, two half-migrated shapes, empty and absent, plus guards that the
staleness check and the fail-soft block both carry the 12a keys.
