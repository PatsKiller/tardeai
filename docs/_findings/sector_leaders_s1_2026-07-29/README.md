# Sector Leaders Card — SL-S1 verification evidence

**Date:** 2026-07-29 · **Stage:** SL-S1 implementation
**Recon:** `docs/_findings/sector_leaders_recon_2026-07-29.md`
**Design bundle:** `docs/_design/sector_leaders_v1/`

---

## How these were captured

The live dashboard on :7777 is **SHA-pinned** by a systemd drop-in
(`~/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf`) to
`/home/johnclaw/trade-ai-releases/portfolio-server/306f8179…/`, and that release directory
contains **both** the backend and the built frontend `dist`. Neither the new endpoint nor the new
card can appear on :7777 without cutting a new release and restarting the service.

Rather than redeploy a live trading dashboard unasked, these screenshots were taken against a
**scratch instance on 127.0.0.1:7899** serving the working tree. No source edits were needed —
`PORT` is a module global read at bind time, so a wrapper overrides it. The scratch instance was
stopped after capture. Production on :7777 was never touched, and was confirmed still serving
normally throughout (`/api/v2/defense/posture` → HTTP 200, `/sector-leaders` → 404 as expected,
since it is not deployed).

**This is genuine browser verification of the real built bundle — not a mock — but it is not yet
verification on the deployed production instance.** See "Deploy" below.

---

## The shots

| File | Shows |
|---|---|
| `01_flag_off.png` | Flag OFF (default). Sector Leaders absent; all eight `RESEARCH WATCH` tiles render unchanged. The `breadth 55% (56/— covered)` defect is visible on every tile — untouched, as instructed. |
| `02_card_energy.png` | Energy, rank 1. Rank/weight/exposure-gap strip; laggards dimmed with `LAGS ITS OWN GROUP`; SHEL's three nulls as italic `unknown`; earnings chips; data-gaps fold; routing footer. |
| `03_constituents_lagging.png` | Constituent table expanded — the dimming and lagging chips at full width. |
| `04_technology_rank9.png` | Technology at the bottom of the board against Energy at the top — the rank/weight inversion, no sizing policy required. *(Captured before the 9→11 sector fix; `06`/`07` supersede.)* |
| `05_full_page.png` | Whole `/v3/defense` page with the flag on — new card sitting below the untouched RESEARCH WATCH board. |
| `06_energy_11of11.png` | Energy after the sector-count fix: `rank 1 of 11`, matching the rest of the desk. |
| `07_realestate_stale.png` | Real Estate: `RANK 10 OF 11`, amber `STALE · AS OF 2026-07-13` chip, carry-forward explained in data gaps. *(Sector-level dispersion, superseded by SL-S2.)* |
| `08_energy_perindustry_verdicts.png` | **SL-S2.** Energy with per-industry verdicts: Oil & Gas Integrated `BUY NAMES`, Oil & Gas Equipment `MIXED`, Thermal Coal *no verdict* (3 names < 8). Three verdicts inside one sector where pooling gave one. |
| `09_staples_buytheetf.png` | **SL-S2.** Consumer Staples: Packaged Foods `BUY NAMES`, Household & Personal Products `BUY THE ETF`, ten industries omitted each with its exact name count in data gaps. |
| `10_realestate_mixed.png` | **SL-S2.** Real Estate per-industry verdicts alongside the staleness badge. |

---

## Verified in these captures

- **Flag default OFF** — 0 Sector Leaders headings with no localStorage key; 1 when set to `on`.
- **Existing tile untouched** — `RESEARCH WATCH` count is 7 in both states;
  `git status` shows `ActionableSectorDecisionBoard.tsx` unmodified.
- **`<Val>` null contract holds** — every null renders as italic `unknown` with a hover reason.
  The six em-dashes inside the card were checked individually and are all **prose inside
  sentences** ("Dispersion 49.9pp — top names are beating XLE by 8.6pp"), never a null render.
- **`rs_vs_industry` is the ranking key and the displayed column**, sorted descending, nulls last.
- **Names lagging their own group are dimmed and chipped** — IMO, PBR, EC, NFG, DEC, TGS inside
  a LEADING industry.
- **Account eligibility enforced, not annotated** — footer reads
  `shorting allowed in: Schwab Taxable, Alpaca Paper`; both IRAs are routable long but excluded
  from shorting; five read-only accounts blocked outright.
- **Staleness badged per source** against that sector's own `as_of`.
- **No console errors.**

---

## Deploy — NOT DONE, needs an operator decision

To put this on :7777 requires: commit → new release checkout at the new SHA → edit the systemd
drop-in → `systemctl --user restart portfolio-server`.

Two reasons that was not done unilaterally:

1. It restarts a live trading dashboard.
2. `scripts/api_v2.py` currently carries ~57 lines of **uncommitted work from the in-flight
   alert-notification workstream**, and 18 other files are modified. Committing to cut a release
   would sweep that up. My own additions to that file are 38 lines, purely additive.

---

## Test evidence

**Reference tests — pass unchanged.** `tests/test_sector_leaders_service.py` is a byte-identical
copy of the Drive artifact (`md5 06b0dc6cf86584c83d23727f2519453d`, verified against
`docs/_design/sector_leaders_v1/` after every service edit). `tests/conftest.py` already puts
`scripts/` on `sys.path`, so it drops in with no import shim.

```
$ .venv/bin/python -m pytest tests/test_sector_leaders_service.py -q
..................                                                       [100%]
18 passed in 0.07s
```

**Full suite — NOT green, but not made worse.** The suite has a 116-failure standing baseline.
To prove none of it is mine, it was run twice: once as built, once with
`scripts/sector_leaders_service.py` and the test file moved aside and the 38-line handler +
route line stripped from `api_v2.py`.

```
BASELINE (my changes removed):  116 failed, 4658 passed, 23 skipped  in 392.03s
WITH MY CHANGES:                116 failed, 4676 passed, 23 skipped  in 472.64s

failures only with my changes (regressions):  0
failures only in baseline (fixed/flaky):      0
```

The two failure sets are **identical, node-id for node-id**. The 18-test delta in `passed` is
exactly this stage's new tests. The 116 span 57 unrelated files (`test_strat_arch1_due_diligence`,
`test_reentry_*`, `test_screener_*`, …) and none mentions `sector_leaders`.

`scripts/api_v2.py` was restored from a byte-verified copy (`cmp` identical).

**Safety proofs.** Every SQL statement in the service was checked by AST walk, not grep:

```
8 execute() calls total — all 8 parse to SELECT
  line 341 SELECT  broker_accounts …        line 478 SELECT  trade_ai_scans …
  line 370 SELECT  sector_momentum_state …  line 499 SELECT  ticker_prices …
  line 390 SELECT  sector_momentum_state …  line 530 SELECT  operator_core_registry
  line 448 SELECT  industry_momentum_state… line 537 SELECT  symbol_profiles …
```

`paper_trade_proposals`: 0 occurrences in any new module. No broker adapter import. One `fetch()`
in the UI, no `method` option (GET). No POST/PUT/PATCH/DELETE branch references the route.

**Build.** `npm run build` green — `[design-guard] pass (275 files checked against baseline)`,
chip-scope tests pass, `tsc` clean. Zero raw hexes added; defense stays at its 0-violation baseline.

---

## SL-S2 additions (2026-07-29, same day)

### Dispersion correction — level, not thresholds

Operator-authorized, supersedes README §3.3. Spread now measured **within one industry**; excess
still measured against the **sector ETF**. Per-industry is the verdict; sector-level is retained as
a logged diagnostic (`dispersion_scope` marks it `DIAGNOSTIC ONLY`) and never rendered as a verdict.
Thresholds unchanged at 12 / 4 / 6.

The pure function `compute_dispersion()` was **already correct** — it always measured spread within
whatever pool it was given, against whatever ETF return it was passed. The defect was purely the
call site passing a sector-wide pool. So the four original dispersion tests still hold and were
deliberately **not** rewritten; eight new tests were added for the level contract instead.

Before → after, per-industry verdict distribution across 42 decided industries:

```
sector-level (old):  10 of 11 sectors -> "buy names"      (no information)
per-industry (new):  26 buy names / 14 mixed / 2 buy the ETF, 69 omitted as thin
```

The case that proves the hybrid was the right shape: **Other Industrial Metals & Mining**, spread
**47.6pp** but top quartile **−5.35pp vs XLB** → `mixed`. Wide spread, but the leaders still trail
the ETF you would otherwise buy. Pooled, this was swept into "buy names".

**Caveat carried forward:** the only sector that produced a differentiated verdict under the OLD
sector-level computation was Real Estate, and XLRE last refreshed 2026-07-13. That reading rested
on 16-day-old data and is not evidence about either threshold set.

### Guard 1 — confidently empty

`empty_reason` is now set whenever a card has no industries, and it distinguishes the two cases
that look identical on screen:

- **join failure** — no industry rows under *any* alias of the sector name
- **absence of candidates** — rows exist but none is LEADING/IMPROVING

An empty list is a well-formed answer, so `<Val>` cannot catch it — `<Val>` catches a null number,
not a null result set.

### Guard 2 — join contract test

`tests/test_sector_leaders_join_contract.py` — parameterized across **all 11** configured sectors,
asserting each resolves against the sector vocabulary `industry_momentum_state` actually uses. It is
a schema contract, not a data assertion: it skips (not fails) when the industry table is empty, so
an engine outage is not misattributed to a join defect.

Proven to fail on the real regression by removing the `Financials` alias:

```
AssertionError: sector 'Financials' resolves to none of the sector values present in
industry_momentum_state.
    tried aliases : ['Financials']
    table has     : ['Basic Materials', 'Communication Services', 'Consumer Cyclical', …,
                     'Financial Services', …]
1 failed, 11 passed
```

Config restored immediately; `git status` clean.

### `moomoo_taxable_live` capabilities entry

Added, additive only — `git diff` shows **8 insertions, 0 deletions**, no existing value touched.

Agreement verified against `broker_accounts` for all 9 accounts. Note the check must test the right
invariant: `account_capabilities.json` has **no routability field**, so it cannot contradict
`broker_accounts` about routing. `alpaca_taxable_live` carrying `can_short_stock: true` while being
non-routable is not a conflict — those are orthogonal facts (margin permission vs API wiring). The
invariant that matters is that routability derives from `broker_accounts` alone and capabilities can
never widen it:

```
9/9 accounts: service read_only == NOT broker_accounts routable
long  permitted: Schwab Rollover IRA, Schwab Roth IRA, Schwab Taxable, Alpaca Paper
short permitted: Schwab Taxable, Alpaca Paper
non-routable leaked into permitted: NONE
violations: 0
```

### Drive artifacts reconciled

`README_SECTOR_LEADERS_v1.md` gained a CHANGE LOG recording all three implementation corrections
(endpoint namespace, dispersion level, exposure-gap juxtaposition). Both files re-uploaded in place
to the same file IDs, byte-exact, still `text/markdown` / `text/plain` — no Docs conversion.

```
test_sector_leaders_service.py
  md5 06b0dc6cf86584c83d23727f2519453d   SUPERSEDED
  md5 dcc5ae67e84731a5bcf8e7ab31a2c95f   CURRENT
```

Note for the Drive-sync ticket: `resolve_folder()` still takes `matches[0]` on an ambiguous folder
name. It resolved correctly here by ordering luck; Drive does not guarantee that ordering is stable.

---

## Incidental observations (logged, not fixed)

1. **`tests/test_llm_content_quality.py` does not parse** — `SyntaxError: unterminated string
   literal` at line 33 (implicit string concatenation across lines outside brackets). Committed
   broken on 2026-07-26 in `8d5e5736`; it aborts collection for the whole suite. Excluded from the
   runs below via `--ignore`.
2. **Sector-level dispersion is near-degenerate.** With the design's 12pp/6pp thresholds, 10 of 11
   sectors return "buy names"; only Real Estate returns "mixed". Pooling 30–245 names across up to
   20 industries guarantees a wide p10–p90 spread at a 1-month horizon. Measured per-industry the
   same thresholds give 23 "buy names" / 12 "mixed" / 1 "buy the ETF" across 36 industries. Shipped
   as designed (sector-level, per README §3.3) with per-industry dispersion added as additive data
   and a `dispersion_scope` label stating what was pooled. **Threshold calibration is a design
   decision and is left to the operator.**
3. **`XLC` and `XLRE` have not refreshed since 2026-07-23 and 2026-07-13.** The sector engine
   writes 9 of 11 rows on a normal close; the desk snapshot carries the other two forward. Worth a
   look at `sector_momentum_engine.py` — two sectors carrying real book exposure have been running
   on stale RS for up to 16 days, and nothing on the existing board says so.
