Status:      ACTIVE
as_of:       2026-09-01T14:20:54-04:00
Measured at: origin/main 8898c7fbb · CURRENT 0a591048b (BUILD_SHA, by file content)
Canonical repo path: docs/ops/CIO_DATA_ASOF_GAPS_2026-09-01.md
Authority:   record for the #825 follow-up; not a behaviour spec
See also:    docs/ops/CIO_BANNER_DATA_ASOF_2026-09-01.md (#825)
             docs/ops/CIO_BANNER_WAKE_CLOSEOUT_2026-09-01.md

# Three gaps #825 left, closed

#825 rebound the PORTFOLIO chip from the loader clock to `data_as_of` and is correct. Three
things it did not cover were reported at the time and are fixed here. **None was a live
behaviour bug** — the age and the STALE verdict were already right. Two were honesty defects
in what the surface *says*, and one was a missing gate.

## Gap 1 — the API emission was pinned by nothing

`compute_data_as_of` had been correct and tested throughout the period the banner was wrong,
because `/api/v2/overview` never emitted the field. #825 added the emission and validated it
with `tsc` and a TypeScript unit test — **neither of which can see a Python payload.**
Deleting the two lines from `overview()` turned nothing red.

Now pinned in `tests/test_holdings_data_clock.py`, beside the writer tests that were already
there. Asserted over the **AST**, not by grepping the source: a grep cannot tell code from a
comment quoting it, and the emission carries a comment naming both fields.

Three assertions, because presence is not correctness:

- the payload emits `data_as_of` and `data_as_of_account`
- each is read as `h.get("<field>")` from the holdings document — not recomputed, not
  defaulted, and **not borrowed from another clock**
- `as_of` remains published as loader provenance and is not sourced from the data clock, so
  the demotion cannot be made cosmetic

## Gap 2 — the tile named the one field it is not reporting

`MetricStrip.tsx` rendered a hardcoded `as_of {value}` while the value it prints for
PORTFOLIO and TODAY is now the **data** clock. The number was right and the label was wrong.

The label is now per-tile (`asOfLabel`), defaulting to `as_of` — which stays correct for
SETUPS, whose `asOf` really is a cache timestamp — and set to `data_as_of` for PORTFOLIO and
TODAY, with the responsible account named beside it.

## Gap 3 — UNDATED rendered the loader's date

The UNDATED branch set `asOf: overview.as_of`. So a block labelled `STALE · data UNDATED`
still printed a date in the slot a reader now believes is the money's clock — **the original
defect wearing an honest label.** #825's tests pinned `dataAsOf === null` on that branch but
never `asOf`, so nothing could see it.

`asOf` is now `null` when the money has no date. The loader stamp remains on the payload for
any consumer that wants it.

### Gaps 2 and 3 had to land together

Fixing gap 3 alone would have made the UNDATED tile render **nothing at all** — the row is
guarded by `{asOf && …}`. Silence must never be indistinguishable from a healthy block
(AGENTS.md §9.1), so the renderer now emits an explicit `data_as_of UNDATED` line.

## Proof the gates fire

Nine mutations, each reverted and the source verified byte-identical.

| # | mutation | result |
|---|---|---|
| 1 | UNDATED falls back to the loader date (pre-fix shape) | **3 red** |
| 2 | blank `asOf` everywhere — a lazy "fix" that breaks the dated case | **2 red** |
| 3 | renderer hardcodes the `as_of` label again | **red** |
| 4 | the tile label survives only as a **comment** | **red** |
| 5 | UNDATED tile renders nothing again | **red** |
| 6 | drop `data_as_of` from the payload | **4 red** |
| 7 | `data_as_of` reads `h.get("as_of")` — the loader clock | **red** |
| 8 | the emission survives only as a **comment** | **4 red** |
| 9 | `as_of` sourced from the data clock — demotion made cosmetic | **red** |

Mutation 2 exists because the obvious way to satisfy mutation 1's assertion is to blank
`asOf` unconditionally, which would silently remove the data clock from the dated case too.

## A limitation, stated rather than glossed

The gap-2 check is a **source-shape assertion, not a render test.** This app has no
jsdom/render harness, so nothing here proves what a browser paints; it proves the component
no longer contains the defective shape. It lives in `scripts/test_metric_strip_labels.mjs`,
following the existing `scripts/test_chip_scope.mjs` precedent, and is wired into
`npm run build` beside it. Comments are stripped before matching, so a comment quoting the
old shape cannot satisfy or break it.

It went into an `.mjs` rather than the TypeScript test because `tsc` has no `@types/node` in
this app — the existing test file already shims `process` for the same reason, and adding the
dependency for one check would be a heavier change than the check.

## Live expectation

No dollar amount changes and no clock is refreshed. The chip already read ~29.5d; it now also
**labels** that number `data_as_of` and names `moomoo_taxable_live`. A block with no data
clock, which does not occur on the live payload today, would read `data_as_of UNDATED`
instead of silently printing the loader's date.

**A promote is required for the surface half**: `apps/command-center-v3/dist/` is untracked
and built at promote time, and the API runs from `CURRENT`.
