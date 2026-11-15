# Portfolio › Holdings (fixture slice + served adapter)

**Status: the contract is PROPOSED.** `portfolio-holdings@2` is PROPOSED by cc-deepseek-6 and **not
APPROVED_FOR_WIRING** (runbook step 5). The page's DEFAULT path is still the synthetic fixture and says so in a
banner. A **served adapter** (`adapter.ts` → `liveProps.ts` → `HoldingsLive.tsx`) now exists for review: it issues
one read-only GET of `/api/v2/portfolio/holdings` through the shell's client, on the route `/wealth/portfolio/holdings`.
Nothing here holds a token, sends a write, or fetches any other reader. No render code changed to accept served data —
that is the adapter's job, and it is the only thing it does.

`@2`, not `@1`: review r2 (`REVIEW-PORTFOLIO-HOLDINGS-r2-cc-deepseek-8-20261115T0031Z`) required a rename
(`rowsRead` → `priceableRows`) and a new required field (`BookMeasure.verified`). A changed shape under an
unchanged version number is the drift the suffix exists to stop.

Fixture slice: branch `wt/wealth-portfolio-holdings-20261114`, base `44d36686a`. Adapter: branch
`wt/wealth-adapter-20261115`, base `wt/wealth-shell-20261114` head, because `apps/wealth/src/pages/portfolio/`
does not exist there (the r3 patch creates it).

## Files

| file | what it is |
|---|---|
| `contract.ts` | `portfolio-holdings@2` types — proposed r3. Units, clocks, population, per-account totals, the four book measures and their provenance are part of the type comments. |
| `fixtures.ts` | four synthetic books: populated, empty, stale, and last-known-good (an UNASSESSED P/E that keeps its value). Every value is invented. |
| `fixtureInvariants.ts` | no React, no DOM: checks the fixture against what the wire would guarantee, including the population arithmetic and the last-known-good cell. |
| `cells.ts` | pure text for the valuation cells (`peCellText`, `assessmentSummary`) — no React, so the invariants can pin the rendering. |
| `format.ts` | formatters only. Pins the two unit traps: `portfolioPct` is already a percent; `marketCapB` is in millions. `multiple()` rounds for display only. |
| `presets.ts` | the four presets (Holdings, Fundamentals, Protection, Levels) — column names, method note, stated limits. |
| `HoldingsTable.tsx` | one cell renderer per column key; the identity cell opens the row drawer when a page passes `onRowOpen`. |
| `HoldingsPage.tsx` | the page: fixture banner, read-status notice, counts with their scope, population, declared clocks, book measures, per-account totals, session, freshness, search, presets, three states, row drawer. |
| `detail.ts` | pure: the drawer's fields for ONE row — the same row identity, no join, no recomputation. |
| `adapter.ts` | pure: the served response body → `HoldingsBook`. Never throws; refuses with a reason. |
| `liveProps.ts` | pure: `Envelope` → page props, including the last-known-good / not-current / health-unproven notices. |
| `HoldingsLive.tsx` | the route: one `getJson` read → `holdingsProps` → `HoldingsPage`. |
| `adapterTests.ts` | plain node harness: synthetic fixtures plus a planted payload per C-rule, and the live-wiring verdicts. |

## Truthfulness rules the page enforces

- **Fixture data says so** above the table, in the page itself, not only in this file.
- **A count names its scope**: "non-cash over the notional floor" is separate from all rows / securities / cash /
  under the floor, and the population block states the priceable population (`priceableRows`, the wire's
  `scope_coverage.priceable.row_count` — deliberately *not* its `rows_read`, which is the post-filter 30), rows in
  the book, what the read removed, and the floor it was measured against. **Two populations, never merged:**
  `excluded` is rows removed before the counters (an omission), `listedNotCounted` is rows that are IN the table and
  outside the counted scope — the wire's `scope_coverage.excluded`, which means the opposite of an omission.
  Rendering them together would print "omitted: 14" about 14 visible rows.
- **The floor mark is adapter-derived.** The wire marks no row; it serves `min_position_usd`, each row's
  `market_value`, and two counts (`non_cash_over_100`, `held_under_100`). `belowFloor` is that comparison, made
  once in the adapter; the invariant in `fixtureInvariants.ts` is its definition, and it never fires on an unpriced
  row — unknown is not "below".
- **Every clock is shown with its role.** The document build clock is called out because on the live wire it is a
  day older than the positions clock; the page ages the book from `asOfClock`, never from the build clock.
- **An unpriced row is not a zero row** (`marketValue: null` ⇒ "N/A — unpriced"); a worthless row is a served zero
  and renders "$0.00 · worthless".
- **An UNASSESSED P/E that carries a value keeps the value**, marked "last known" — dropping it would turn
  last-known-good into last-known-word.
- **Book measures are the producer's, and a receipt is never invented.** The rule the ledger holds is
  **MEASURED ⇒ value + clock; VERIFIED ⇒ receipt**. The receipt lives in a *separate* wire block
  (`data.metrics[]`, keyed `portfolio.<id>`), so the adapter must JOIN two blocks — `measures.measures{}` for the
  value and clock, `data.metrics[]` for `verified` and `receipt`. Today all four are `verified: false, receipt:
  null`; the fixture carries no `fixture:rcpt-*` string, and the invariant rejects one. A MEASURED measure with
  `verified: false` is the normal case and renders "measured, not verified". `verified_daily_pnl` is UNKNOWN and
  renders UNKNOWN; it is never shown as a zero or replaced by the price-move estimate.
- **Per-account totals are the producer's.** When `accounts` is null the block is absent; the page never sums rows.
- **The session label is not invented.** The rows carry none (`market_session` is null on 29 of the 30 served rows on
  the captured live body — the cash row is the one that labels `after_hours`), so the label is the session field,
  with its source, and `UNKNOWN` renders as `UNKNOWN`.
- **The day column is labelled "no declared clock"** because the wire declares `day_pnl` UNKNOWN.
- **A stale book is "last known good" with its age**, never silently current.
- **Missing is not zero**: `null` renders `N/A — <reason>`; empty is a sentence, not a table of zeros.
- **Colour is never the only carrier**: the protection cell is label + icon glyph + tooltip (`Cue` contract).
- **The client computes nothing**: no shares×price, no P/L arithmetic, no row sums, no score, no P/E threshold.
- **No support/resistance claim**: the ladder is labelled Fibonacci retracement of the 52-week range; the reference's
  Support / Resistance / Timeframe / Next review columns have no reader and are not renamed into one.

## Wiring (done here; two hunks are shell-owned and need the shell owner's word)

```tsx
// App.tsx — one explicit route, ahead of the FAMILIES map (React Router ranks by specificity)
<Route path="portfolio/holdings" element={<HoldingsLive />} />
// api/readers.ts — one row (the file's own header: "Page owners may add rows")
{ path: '/api/v2/portfolio/holdings', heavy: true, clock: 'producer', asOfAt: 'data.truth.as_of', … }
```

**Shell owner (cc-opus-3) to confirm:** the inline `<button>` in the identity cell and the drawer's `<dl>` need the
shell's existing tokens/classes to render as intended — no new colour, no new size, no new class name was added.
The reader row is the registry's first `portfolio` row; its note carries the measurements (271,806 B; 6–79 ms).

**The registry rule that shaped the row:** `shell-logic.test.mjs` requires every declared `unavailableWhen` path to
sit under `data.`. This route's freshness annotation (`_swr`) sits BESIDE `data`, so its `stale` verdict cannot be a
registry rule; `liveProps.ts` reads it from the adapted book instead and withdraws the claim of current. If the shell
wants root paths in the registry, that is a shell change, not a page one.

Two notes carried from review:

1. **F10 — the default prop must become `null` at APPROVED_FOR_WIRING.** Today `book` defaults to `FIXTURE_BOOK`
   and the in-page banner says so. `HoldingsLive` always passes `book` explicitly, so the live route cannot fall
   through to the fixture; the default stays only for the fixture/invariant path until approval.
2. **A GET is read-only with respect to the book, not to the disk.** `/api/v2/portfolio/holdings` is a read-only
   handler chain, but a GET through the SWR layer writes its own cache file. "Non-mutating" means no order, no
   flag, no credential — not no disk write.

## Adapter: what the served wire does and does not carry

Measured on the served route (R13 `3ac0b4058`), one read, 271,806 B, 6–79 ms. The adapter's job is a rename plus a
label plus an honest `null`; it computes exactly ONE field (`belowFloor`, C2) and nothing else.

| contract field | served source | note |
|---|---|---|
| `rows`, `counts` | `data.holdings[]`, `scope_coverage.scopes` | row key = `account_key ?? account_id ?? account` |
| `population.priceableRows` | `scope_coverage.priceable.row_count` (33) | **not** `rows_read` (30) — taking rows_read reports a 0-row gap for a book that read 33 |
| `population.excluded` | `priceable.row_count − rendered_rows` (3) | the producer publishes the gap but **no rule**; `filtered_rows` is null and `findings` is empty, so the rule is stated as unknown |
| `population.listedNotCounted` | `scope_coverage.excluded[]` (14, under the floor) | the wire's word "excluded" means LISTED AND NOT COUNTED — the opposite of an omission. Mapping it into `excluded` would print "omitted: 14" about 14 visible rows |
| `measures` (4) | `measures.measures{}` + `data.metrics[]` | MEASURED ⇒ value + clock, VERIFIED ⇒ receipt; all four are `verified:false, receipt:null`, rendered "measured, not verified". `verified_daily_pnl` is UNKNOWN with `gap.reason` and is never shown as a number |
| `clocks` | `clock_provenance.positions / position_list / quote / valuation` | `position_list` is the DOCUMENT build clock (a day older); the book ages from `truth.as_of`, which is the quote clock |
| `session` | `holdings[].market_session` | null on 29/30 rows; KNOWN only when every row declares the same label, else UNKNOWN with a counted reason |
| `freshness` | root `_swr.age_s / stale`, threshold `evidence.portfolio.clocks.stale_after_hours` | only a served `stale: false` is fresh: no `_swr` **or** no `stale` verdict ⇒ stale, and the three cases (absent block / unaged block / aged stale block) each say which one they are. `age_s` absent ⇒ `ageSeconds: null`, never 0 |
| `accounts[].totalUsd` | `reconciliation.accounts[].end_equity.value_usd` | served, never summed; **`cashUsd` is null** — the route serves per-account equity, not per-account cash |

**Reported absent rather than papered over** (each null has its reason on screen and in the drawer):

- **`fib`** — the route serves a ladder with NO clock for it; `FibLadder.window.asOf` is required, and stamping it
  with the quote clock would label a clock the producer never declared for the ladder.
- **`valuation`** — `valuation-assessment@1` is not wired on this route. A bare `pe`/`forward_pe` number is not an
  assessment; turning one into a status is exactly the claim that contract forbids.
- **`accounts[].cashUsd`** — not served per account.
- **protection stop price** — `stops_read` publishes counts only; the per-row stop renders as "no resting stop" with
  the producer's cause and the read clock.

## Verify

Requires a writable scratch dir and one checkout with an app's `node_modules` installed (TypeScript
5.9.3, `@types/react`, `@types/react-dom`) — this worktree has no `node_modules` of its own. The `paths` map below
borrows those types read-only; nothing is installed and nothing is written into either checkout.

```bash
WT=$(git rev-parse --show-toplevel)                              # this worktree
CC_NM=/path/to/a/checkout/apps/<app>/node_modules                # set this; must contain typescript/@types/react
SB=/tmp/holdings-check                                           # any writable scratch dir
mkdir -p "$SB"

cat > "$SB/tsconfig.check.json" <<JSON
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["node"],
    "typeRoots": ["$CC_NM/@types"],
    "baseUrl": "$WT",
    "paths": {
      "react": ["$CC_NM/@types/react"],
      "react/jsx-runtime": ["$CC_NM/@types/react/jsx-runtime"],
      "react-dom/client": ["$CC_NM/@types/react-dom/client"],
      "react-router-dom": ["$CC_NM/react-router-dom"],
      "vite/client": ["$CC_NM/vite/client"]
    }
  },
  "include": ["$WT/apps/wealth/src/**/*"]
}
JSON

# 1. types — the whole wealth src. Expect rc 0 and no output.
node "$CC_NM/typescript/bin/tsc" -p "$SB/tsconfig.check.json"

# 2. the app's own gates (read-only scripts; they fail the real build too)
node scripts/check-contracts.mjs && node scripts/check-design-fidelity.mjs && node --test scripts/tests/shell-logic.test.mjs

# 3. adapter + live-wiring tests, compiled to CommonJS and run in node. The two extra flags are needed because
#    the shell's own modules import with `.ts` extensions; `--typeRoots` is what makes `process` type-check.
CJS="--target ES2020 --module commonjs --moduleResolution node --strict --skipLibCheck --allowImportingTsExtensions --rewriteRelativeImportExtensions --typeRoots $CC_NM/@types --types node"
node "$CC_NM/typescript/bin/tsc" $CJS --outDir "$SB/emit2" "$WT/apps/wealth/src/pages/portfolio/adapterTests.ts"
printf '{"type":"commonjs"}' > "$SB/emit2/package.json"
node "$SB/emit2/pages/portfolio/adapterTests.js"        # PASS — adapter assertions green

# 4. fixture invariants — no React, no DOM, no jsdom (fixtureInvariants.ts is pure).
node "$CC_NM/typescript/bin/tsc" $CJS --outDir "$SB/emit" "$WT/apps/wealth/src/pages/portfolio/fixtureInvariants.ts"
printf '{"type":"commonjs"}' > "$SB/emit/package.json"          # the .js files are CJS; no package.json exists to say so
node -e "const {checkAllFixtures}=require('$SB/emit/pages/portfolio/fixtureInvariants.js');const v=checkAllFixtures();if(v.length){console.error(v.join('\n'));process.exit(1)}console.log('PASS — 0 violations')"
```

`esModuleInterop` is not needed for this source: it has no default imports, and the CJS step compiles `import type`
away. If you swap the borrow for a `node_modules` link, keep the same `paths` entries.

Mutants run red before the green above (each halted by an invariant, then the file restored and `cmp`-verified
byte-identical): weight 15.0→16.0 (rows no longer sum to 100), one ladder level 76.72→76.90 (off the stated window),
`dayPnl.status` UNKNOWN→KNOWN (hides an undeclared clock), and the F1 revert — `peCellText` returning the bare word
`Unassessed` for an UNASSESSED-with-value assessment (the last-known-good value disappears).

**r3 additions, each killed by a named first line:** `priceableRows` 10→9 (`population gap 0 != excluded 1`); the
listed block's count 1→2 (`listedNotCounted holdings.held_under_100 says 2, the book has 1 rows under floor 100`);
`heldUnderFloor` 1→0 (`heldUnderFloor 0 != 1 rows priced under floor 100`); the r2 invented receipt restored
(`measure account_value carries receipt fixture:rcpt-1 but is not verified`); `verified: true` with no receipt
(`measure account_value is VERIFIED without a receipt`); `asOf: null` on a MEASURED measure (`measure account_value
is MEASURED without a clock`). 6/6 killed, each restored and `cmp`-identical.

**A1 is compile-level, not runtime:** `peCellText` now ends in a `default` with `const _unhandled: never =
pe.status`. Adding a sixth `AssessmentStatus` member (`| 'NEW_STATUS'` in `contracts/valuation.ts`) fails the build
with `cells.ts: error TS2322: Type '"NEW_STATUS"' is not assignable to type 'never'` — a status the renderer does
not know cannot ship as an empty cell.

The page itself was rendered with `react-dom/server` through the real `HoldingsPage` and `HoldingsTable` — no
browser, no served page — in 15 assertions, all passing: the population line (`read 10 · in the book 9 · omitted: 1
dead CUSIP, zero value`), the listed-not-counted line as its own `<dd>` and exactly once, the under-floor count, a
MEASURED measure rendering "measured, not verified — the ledger publishes no receipt", **no `fixture:rcpt` string
anywhere in the markup**, the @2 banner, the corrected nine-row coverage sentence, the F1 cell, and the empty /
no-book states.

**Adapter round — 9 mutants, 9 killed, each by a distinct named assertion** (`rc != 0` plus the assertion's own name
in the output), every file restored by `cp` and `cmp`-identical (never `git checkout` in a scratch tree):

| mutant | killed by |
|---|---|
| population taken from `rows_read` | `C3 priceableRows comes from priceable.row_count — got 3, want 6` |
| removals taken from the wire's `excluded` list | `C3 removal count = priceable − rendered — got 2, want 1` |
| an unpriced row counted as below the floor | `C2 an unpriced row is never below the floor — got true, want false` |
| `verified` inferred from MEASURED (metrics join dropped) | `C1 verified comes from metrics[] — got true, want false` |
| one session label taken as the book session | `session UNKNOWN when ONE row labels it — got "KNOWN", want "UNKNOWN"` |
| a rule-UNKNOWN treated as "no body" | `producer stale → a book is still shown` |
| a stale body still presented as current | `swr stale → the notice says not current — null` |
| drawer drops the unpriced rule | `an unpriced row is not below the floor in the drawer — no` |
| holdings row not marked `heavy` | `reader row: heavy (its own page only) — got false, want true` |

Wiring smoke against the real captured body (one read of R13, not a fixture): `rows 30 · priceable 33 · removals 3 ·
listed-not-counted 14 · asOf 2026-11-14T19:45:01-05:00 · stale false`; with `truth.stale` planted true the notice
reads "Not current: source reports data.truth.stale = true…"; with `_swr.stale` planted true, "Not current: the
freshness block reports this body stale…"; and a 503 with a kept body renders "This is the last good read (42 s old);
the current read failed: HTTP 503." with `freshness.ageSeconds = 42`.

## What is deliberately absent

- No second reader, no write, no token: the live route makes one GET of `/api/v2/portfolio/holdings`. The contract is
  still PROPOSED, which is why the *default* path remains the fixture and the served book is an explicitly wired route.
- No CSS and no colour hex: shared v02 components and tokens are the shell slice's (`cc-opus-3`). **F11:** the
  protection badge emits `cue cue-<level>` (`cue-green` / `cue-amber` / `cue-red` / `cue-neutral`); the shell slice
  must define those four class names or the badge renders unstyled.
- No downside-to-stop, peer TTM median, support/resistance, next-review or timeframe column — none has a served field.
