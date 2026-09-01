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

No dollar amount changes and no clock is refreshed **by this change**. A block with no data
clock would read `data_as_of UNDATED` instead of silently printing the loader's date.

> **Superseded within two minutes of the promote — see the addendum below.** The value the
> chip renders changed for an unrelated upstream reason, and the sentence that used to sit
> here ("the chip already read ~29.5d ... and names `moomoo_taxable_live`") became false.
> Recording that rather than quietly editing it, because *why* it became false is the finding.

**A promote is required for the surface half**: `apps/command-center-v3/dist/` is untracked
and built at promote time, and the API runs from `CURRENT`.


---

# Addendum — the chip got "fresher" by losing an account

**Not caused by this change.** Measured after the promote, and recorded because the surface
now looks reassuring for a reason nobody chose.

## What moved

| | 13:00 | 14:30 |
|---|---|---|
| `data_as_of` | `2026-08-03` | `2026-09-01` |
| `data_as_of_account` | `moomoo_taxable_live` | `alpaca_taxable_live` |
| chip age | **29.5d, STALE** | **0.6d, not stale** |
| `total_cash` | 631,013.62 | 630,513.62 |
| `portfolio_value` | 1,278,305.39 | 1,278,568.26 |

`holdings.json` was rewritten at **14:30:32** (`positions_built_at 13:30:02`,
`last_repriced 14:30:02`) — **two minutes before this promote**, and by the repricer, not by
anything here. This change touches a label, an `asOf` value on one branch, and tests.

## The finding

**`moomoo_taxable_live` now has zero holdings rows.** It is still declared in
`account_summaries`, with `total_value: 0`. So is `fidelity_rollover_ira`.

At 13:00 the moomoo rows carried `2026-08-03` and were the reason the book read 29 days old.
They are gone, so the oldest surviving row is today's, and the banner improved from **29.5d
to 0.6d without a single stale figure being refreshed.**

**The staleness was not fixed. The stale rows left.**

## What cannot be concluded

Two possibilities produce this identical signature, and they have opposite implications:

1. the account was legitimately emptied or closed, and zero is the truth; or
2. a collector returned nothing and the writer persisted the empty result — the fail-open
   shape AGENTS.md §7 describes, where "the file keeps its normal name, shape, size class and
   a *fresh* mtime, so every staleness check reads it as current."

**Establish which before reasoning from it** (§7, the `attempts_24h` rule). Nothing here does,
and nothing was changed to find out: holdings state is operator-only under §17.

## The surface that did NOT follow, and why that matters

The CIO cash path did **not** jump to fresh:

```
capital_plan.cash_as_of  as_of 2026-08-14 · oldest_row 2026-08-14
                         newest_row 2026-09-01 · mixed_ages true
```

That is PP3 (#822) working as designed: it dates the **cash rows**, not the whole book, so a
surviving 08-14 cash row keeps the cash surface honest at 18 days while the portfolio banner
reads 0.6d. The two numbers disagree because they measure different things, and both are
correct for what they measure.

**Detector shape, stated plainly:** `compute_data_as_of` is the oldest row across the entire
book. It is the right definition for "how old is this book", and it structurally cannot
distinguish *a stale row that got refreshed* from *a stale row that disappeared*. A freshness
metric that improves when data is removed will read as good news on the day it should read as
an alarm. The chip is not wrong; it is answering a narrower question than a reader will
assume when the number drops by 29 days overnight.

## Proposed, not done

- Establish which of the two possibilities produced the empty moomoo book. Operator-only.
- Consider surfacing an account that transitions to zero rows while remaining declared — a
  drop-out is invisible in every number on the banner today.
