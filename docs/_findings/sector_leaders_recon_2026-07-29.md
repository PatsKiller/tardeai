# Sector Leaders Card — Stage SL-S0 Recon

**Date:** 2026-07-29
**Target:** `/v3/defense` (Defense Desk, Command Center v3)
**Design bundle:** `docs/_design/sector_leaders_v1/` (pulled from Drive, see §0)
**Status:** recon complete — **stopped for sign-off**, no feature code written.

---

## HEADLINE ANSWERS

| Question | Answer |
|---|---|
| **S0.1** — per-constituent RS vs own industry | **`INDUSTRY_RS_AVAILABLE`** |
| **S0.2** — industry→constituent join coverage | **`FULL_COVERAGE`** (with a stated caveat on membership provenance) |
| **S0.3** — rank-implied sizing policy | **`NO_POLICY_SOURCE`** |

Scope recommendation: **proceed, with one scope change and one blocking operator decision.** See §7.

---

## 0. IRON RULE + BUNDLE VERIFICATION

### State check (run before anything else)

```
$ python3 -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'],len(d.get('holdings',[])))"
1257805.65 34
```

Non-zero on both. Proceeded.

### Drive bundle

Downloaded via the `sync-docs-to-drive.sh` auth pattern (`gog drive download`, account
`john@jwwhiting.com`, keyring password read from `~/.openclaw/credentials/gog_keyring_password`
and never echoed).

```
$ ls -la docs/_design/sector_leaders_v1/
-rw------- 1 johnclaw johnclaw  6898 Jul 29 11:12 README_SECTOR_LEADERS_v1.md
-rw------- 1 johnclaw johnclaw 14870 Jul 29 11:12 SectorLeadersCard.jsx
-rw------- 1 johnclaw johnclaw 13302 Jul 29 11:12 sector_leaders_service.py
-rw------- 1 johnclaw johnclaw  4580 Jul 29 11:12 test_sector_leaders_service.py

$ md5sum docs/_design/sector_leaders_v1/*
2994644589470e0ac95f3a910e6efeb5  README_SECTOR_LEADERS_v1.md
a6b88459fb8c83bb063863c6bc2f6b5c  SectorLeadersCard.jsx
0a6075a1eb9d8fbc051003c3c19ef888  sector_leaders_service.py
06b0dc6cf86584c83d23727f2519453d  test_sector_leaders_service.py

$ file docs/_design/sector_leaders_v1/*
README_SECTOR_LEADERS_v1.md:    Unicode text, UTF-8 text
SectorLeadersCard.jsx:          JavaScript source, Unicode text, UTF-8 text
sector_leaders_service.py:      Python script, ASCII text executable
test_sector_leaders_service.py: Python script, ASCII text executable
```

Drive metadata reported all four as `mimeType: text/plain` with byte sizes matching the
downloaded files exactly. **No Google Docs export path was involved.** Files are plain text as
required.

---

## 1. S0.1 — THE LOAD-BEARING QUESTION `[FLAG-BACK #1]`

**Answer: `INDUSTRY_RS_AVAILABLE`.** The windows match by construction, because both sides are
Finviz-sourced over Finviz's own window definitions.

### Which table holds per-symbol returns, over which windows

The obvious candidate is **not** the answer. `symbol_profiles` has `perf_week_pct` and
`perf_month_pct` columns, but they are **effectively unpopulated**:

```
$ SELECT count(*) AS rows_total,
         count(*) FILTER (WHERE perf_week_pct  IS NOT NULL) AS has_perf_week,
         count(*) FILTER (WHERE perf_month_pct IS NOT NULL) AS has_perf_month,
         max(perf_updated_at) AS perf_freshest
    FROM symbol_profiles;

rows_total | has_perf_week | has_perf_month | perf_freshest
      2196 |             2 |              2 | 2026-07-25 07:15:01-04
```

**2 rows out of 2,196.** `symbol_profiles` is not a viable return source.

The real source is the **file-backed Finviz enrichment cache**,
`data/state/ticker_enrichment_cache.json` — 4,013 symbols, already the source
`defense_recommendations.py` uses via `_enrich()` (`scripts/defense_recommendations.py:75-77`):

| Field | Populated | Window |
|---|---|---|
| `perf_week_pct` | 3,799 / 4,013 | Finviz Perf Week |
| `perf_month_pct` | 3,733 / 4,013 | Finviz Perf Month |
| `perf_quarter_pct` | 3,612 / 4,013 | Finviz Perf Quarter |
| `week52_high_pct` | 3,805 / 4,013 | — (feeds `pct_from_52w_high`) |
| `avg_vol_m` | 3,767 / 4,013 | 20d avg volume (feeds `adv_20d`) |
| `market_cap_b` | — | market cap |
| `short_float_pct`, `sma20/50/200_pct`, `rsi`, `atr`, `beta` | — | — |

Freshness: `cached_at` spans `2026-07-17T14:32` → `2026-07-29T11:19`; **3,394 / 4,013 refreshed
within the last 7 days.**

### Which table holds industry composite returns, over which windows

`industry_momentum_state` — written by `scripts/finviz_industry_groups.py` from the Finviz Elite
group export (`grp_export.ashx v=141`).

```
$ SELECT max(as_of), count(*), count(DISTINCT industry), count(DISTINCT sector)
    FROM industry_momentum_state WHERE as_of = (SELECT max(as_of) FROM industry_momentum_state);

latest     | rows | industries | sectors
2026-07-28 |  144 |        144 |      11
```

Columns: `perf_week`, `perf_month`, `perf_quarter`, `perf_ytd`, `change_1d`, `rel1w`, `rel1m`,
`state`, `stocks`.

### Do the windows match?

**Yes — and this is the crux.** `ticker_enrichment_cache.perf_month_pct` and
`industry_momentum_state.perf_month` are *the same vendor's Perf Month over the same definition*,
one at ticker granularity and one at group granularity. No window reconciliation is required;
`rs_vs_industry = name.perf_month_pct − industry.perf_month` is apples-to-apples.

Live proof, computed against the 2026-07-28 industry state:

```
== Oil & Gas Integrated [LEADING]  finviz perf_month = 11.78
   priced members with perf_month_pct: 17/19
     EQNR   rs_vs_ind  +16.25   perf_1m  +28.03   52wH% -8.14
     XOM    rs_vs_ind   +4.83   perf_1m  +16.61   52wH% -10.06
     BP     rs_vs_ind   +3.48   perf_1m  +15.26   52wH% -10.81
     CVX    rs_vs_ind   +2.18   perf_1m  +13.96   52wH% -10.62
     YPF    rs_vs_ind   +0.87   perf_1m  +12.65   52wH% -10.61

== Semiconductors [LAGGING]  finviz perf_month = -9.00
   priced members with perf_month_pct: 49/64
     AVGO   rs_vs_ind  +13.35   perf_1m   +4.35
     NVDA   rs_vs_ind  +11.33   perf_1m   +2.33
     TXN    rs_vs_ind   +6.63   perf_1m   -2.37
     ADI    rs_vs_ind   +3.19   perf_1m   -5.81
```

Both cases behave as the design predicts: a leading group where individual names spread from
+16.25 to below zero, and a lagging group where AVGO/NVDA are strongly positive *relative to their
own industry* while still negative in absolute terms. The metric separates name selection from
group beta, exactly as §3.2 of the README requires.

### The path NOT taken, and why it matters

I also tested computing the composite ourselves from `ticker_prices` (1.08M rows, 5,717 symbols,
2021-07-27 → 2026-07-29, ~4,400 symbols priced per session). Equal-weighted member returns diverge
sharply from the Finviz composite:

| Industry | our equal-wt 1m (price ≥ $5) | Finviz `perf_month` |
|---|---|---|
| Oil & Gas Integrated | 9.63 | 11.78 |
| Oil & Gas E&P | 2.45 | 5.56 |
| Semiconductors | **−18.93** | **−9.00** |

The Semiconductors gap is cap-weighting: Finviz's group composite is cap-weighted, our equal-weight
mean is dragged by small-caps. **Mixing the two sources would produce a garbage `rs_vs_industry`**
(e.g. NVDA would read ~+21 instead of +11.33). The implementation must take *both* sides from
Finviz. `ticker_prices` should be used only where Finviz has no equivalent — and for this card,
it has one everywhere.

**Recommendation:** implement `rs_vs_industry` from the enrichment cache + `industry_momentum_state`
only. No column rename is needed; the metric is honest as specified. Do **not** fall back to
`rs_vs_spy`.

---

## 2. S0.2 — THE INDUSTRY→CONSTITUENT JOIN `[FLAG-BACK #2]`

**Answer: `FULL_COVERAGE`** — the join is not restricted to the lagging pool. But the membership
source is a screener-derived pool, not an official constituent list, and that must be labelled.

### Which module and function performs the join

`scripts/defense_recommendations.py` → `taxable_short()`, lines 620-630:

```python
def taxable_short(industries, cur, enrich, as_of, held_symbols=frozenset(), equities=None) -> list:
    c = CFG["taxable_short"]
    if not CAPS.get("schwab_taxable", {}).get("can_short_stock"):
        return []
    pool = (industries.get("candidates") or {}).get("defensive_short_pool") or []
    pool_names = [p["industry"] for p in pool]
    if not pool_names:
        return []
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, industry FROM trade_ai_scans
                   WHERE industry = ANY(%s) ORDER BY symbol, scanned_at DESC""", (pool_names,))
    members = cur.fetchall()
```

That four-line query **is** the join. It is not industry-state-aware — the restriction to lagging
industries comes entirely from `pool_names`, which `finviz_industry_groups.py:259` populates as
`defensive_short_pool` (confirmed LAGGING only). Point the same query at leading industries and it
works unchanged.

### Which table holds industry membership — full DDL

`trade_ai_scans` (69 columns; the relevant subset):

```
id                bigint          symbol            text
run_id            text            sector            text
run_date          date            industry          text
run_type          text            country           text
scanned_at        timestamptz     sector_etf        text
price             real            ticker_perf_1m    real
score             integer         sector_perf_1m    real
grade             text            vs_sector_pct     real
```

```
$ SELECT count(*), count(DISTINCT symbol), count(DISTINCT industry),
         min(scanned_at), max(scanned_at) FROM trade_ai_scans;

rows_total | symbols | industries | oldest              | newest
     55359 |    3828 |        156 | 2026-05-04 09:28-04 | 2026-07-29 10:01-04
```

Note `trade_ai_scans` carries `ticker_perf_1m` / `sector_perf_1m` / `vs_sector_pct`. These are
**vs SECTOR, not vs industry** — there is no industry-relative column here. They are not a
substitute for S0.1's metric.

### Does it cover all 144 Finviz industries, or only the lagging pool?

All of them, and the leading pool is as well covered as the lagging pool:

```
$ -- members per industry from trade_ai_scans, grouped by the industry's momentum state
state      | industries | with >=8 members @ px>=$5 | zero members | avg members @ px>=$5
IMPROVING  |         48 |                        27 |            0 |                 16.7
LAGGING    |         24 |                        20 |            0 |                 16.7
LEADING    |         64 |                        41 |            1 |                 15.0
WEAKENING  |          8 |                         6 |            0 |                 31.1
```

**64 LEADING industries, 41 of them clear the ≥8-priced-constituent dispersion floor, only 1 has
no members at all.** Extending the join to the leading pool is a `WHERE` clause, not a stage.
The scope re-estimate the prompt hedged against is **not** required.

Membership quality spot-check (Oil & Gas Integrated, the README's worked example):

```
BP CVE CVX DEC E EC EQNR IMO NFG PBR PBR-A SHEL SKYQ SU TGS TTE VIVK XOM YPF   (19)
```

The majors are all present. Two sub-$5 names (SKYQ $4.16, VIVK $2.58) are present and are removed
by the design's own `MIN_PRICE` filter. For comparison, `symbol_profiles.industry` holds only 12
names for the same industry — `trade_ai_scans` is the better source, confirming the existing
code's choice.

### Refresh cadence and last success

| Source | Job | Cadence | Last success |
|---|---|---|---|
| `trade_ai_scans` | discovery scan pipeline | continuous, RTH | 2026-07-29 10:01 ET |
| `industry_momentum_state` | `finviz_industry_groups.py` | 12:30 (display) + 16:18 `--close` (states) weekdays | 2026-07-28 16:18 ET |
| `sector_momentum_state` | `sector_momentum_engine.py` | 17:25 weekdays | 2026-07-28 17:25 ET |
| `ticker_enrichment_cache.json` | Finviz enrichment | rolling | 2026-07-29 11:19 |

All three cron lines carry the required `cd $PROJ &&` prefix — verified in `crontab -l`.

### The caveat that must be rendered, not hidden

`trade_ai_scans` is a **discovery-scan accumulation**, not an official ETF/index constituent list.
A name appears because a scan surfaced it, so membership is complete for liquid names and thin in
the tail. The codebase already has honest language for exactly this, in
`config/defense_breadth_policy.json`:

```json
"membership_scope": "covered_screener_membership_not_official_etf_constituents"
```

The card's `source_note` and `filter_summary` fields must carry the same disclosure. The design's
`constituent_count` field should be the **covered** count; Finviz's true universe count is
**not available** — `industry_momentum_state.stocks` is `NULL` for every row I sampled (see §5).

---

## 3. S0.3 — SIZING POLICY `[OPERATOR POLICY — do not invent]`

**Answer: `NO_POLICY_SOURCE`.** `rank_implied_weight_pct` must return `None`, and the exposure gap
must render "unknown".

### Where rotation sizing rules live today

Three separate places, **none of which is rank-keyed**:

**1. `config/rotation_sector_targets.json`** — theme comfort lines, not sectors:

```json
"default_comfort_pct": 18,
"themes": {
  "Magnificent 7": {"target": 15, "floor": 0},
  "Energy":        {"target": 5,  "floor": 2},
  "Defense / Aerospace": {"target": 6, "floor": 3},
  ...
}
```

Its own `_comment` states: *"Targets are operator comfort lines, NOT a model output."* Themes
(`Magnificent 7`, `AI datacenter & power`) are a different object from the 11 GICS sectors, and
the values are look-through *theme* percentages. Not usable as a sector band.

**2. `config/defense_recommendations.json`** — three flat scalars:

```
neutral_sector_weight_pct = 9.1
underweight_floor_pct     = 4.0
overweight_alert_pct      = 10.0
```

These are the closest thing to a band that exists. They are **rank-independent** — Energy at rank
1 and Technology at rank 11 get the identical 4.0–10.0 window.

**3. `scripts/defense_data_quality.py:294 allocation_decision()`** — the richest machinery
(benchmarks, account mandates, sector tilts, vol/correlation scalars, `max_active_tilt_pct`). It
reads `cfg["allocation_policy"]`, and:

```
$ python3 -c "import json; print(json.load(open('config/defense_recommendations.json')).get('allocation_policy'))"
None
```

**The key does not exist.** Every lookup falls to its default, so `base_target` resolves to
`neutral_sector_weight_pct` = 9.1 for all 11 sectors, `benchmark = {}`, `mandate = {}`,
`tilt = 0.0`. The function is live but is currently expressing a flat equal-weight prior with no
per-sector or per-rank content.

**Conclusion: no rank → target-weight band exists anywhere in the tree.** Building one is operator
policy. Per the prompt and README §3.1, I did not invent one.

### How the defensive-lean directive modifies it

`config/defense_recommendations.json → rotation_pairs.defensive_lean`:

```json
{
  "enabled": true,
  "set_by": "operator, per the 5-seat oversight panel 2026-07-18 (opus/gpt-5.4: 'defensive
             rotation, not risk-on broadening — equal>cap may be a distribution tell')",
  "defensive_sectors": ["Utilities", "Consumer Staples", "Healthcare"],
  "allow_income_destination": true,
  "cash_remainder": true,
  "_revoke": "set enabled=false when the tape confirms risk-on broadening (breadth + small caps + NH/NL)",
  "max_single_destination_pct": 50
}
```

It is a **destination filter on rotation pairs**, not a weight modifier. It constrains *where* trim
proceeds may go; it says nothing about what weight a rank-1 sector should carry. It cannot be
composed into a band that does not exist.

Note the live tension this creates for the card: **Energy is rank 1 and is not a defensive sector.**
A card that renders "Energy underweight, add" would be pointing away from the standing directive.
The card must surface the directive alongside any exposure verdict.

### How the core registry constrains it

`operator_core_registry` — 12 symbols, all operator-confirmed 2026-07-18:

```
ANET ARKX BND DIVI JEPI JEPQ SCHD SCHG V XAR XLB XLI
```

`account` is `NULL` on all 12 rows — the registry is symbol-scoped, not account-scoped. Per the
hard constraints these are trim-ladder-only and must be badged, never implied as full-exit
candidates. Because the big funds (SCHD, SCHG, JEPI, JEPQ) are core and they are what
*generate* most look-through sector weight, a large share of every sector's effective exposure is
structurally un-exitable. Any exposure gap that ignores this overstates what the operator can act on.

---

## 4. S0.4 — REUSE SURFACE

### Effective sector exposure — the module to reuse

`scripts/fund_lookthrough.py:38 effective_sector_exposure(rows)`. It is already the shared
implementation — `sector_momentum_engine.py:268-270` calls it and persists the result:

```python
from fund_lookthrough import effective_sector_exposure
...
eff = effective_sector_exposure(bm.get("rows", []))
```

**Therefore `sector_momentum_state.book_pct` is already the effective (look-through) weight.**
The card does not need to call the module at all — reading `book_pct` off the sector row *is* the
reuse. `canon_sector()` in the same module handles the Finviz→canonical name mapping.

Live, reproduced end to end:

```
book-map rows: 29    sum value: 676,750
_total: 676,750      _not_decomposed: 88,389

  Financials              $174,331   25.8%   direct 18.2%
  Industrials             $114,480   16.9%   direct  0.1%
  Healthcare              $ 63,735    9.4%   direct  2.5%
  Technology              $ 49,696    7.3%   direct  1.3%
  Consumer Staples        $ 39,693    5.9%   direct  0.0%
  Materials               $ 39,113    5.8%   direct  0.0%
  Energy                  $ 26,547    3.9%   direct  0.0%
  Consumer Discretionary  $ 25,450    3.8%   direct  0.0%
  Communications          $ 20,057    3.0%   direct  0.0%
  Utilities               $ 11,204    1.7%   direct  0.0%
  Dividend Equity         $  8,253    1.2%   direct  1.2%
  Other                   $  6,612    1.0%   direct  0.0%
  Equity Income Fund      $  4,979    0.7%   direct  0.7%
  Real Estate             $  4,211    0.6%   direct  0.0%
```

**⚠ Denominator finding — this materially affects the exposure gap.** The `pct` values are
percentages of **$676,750**, the book-map row total, while `holdings.json.total_value` is
**$1,258,436**. The book map covers 29 of 34 holdings; ~$581,686 (cash / MM / sleeves outside the
map) is excluded from the denominator.

So "Energy 3.9%" means *3.9% of the $677K mapped equity sleeve* = **2.1% of the total portfolio**.
If an operator sizing band is ever written as "% of book" meaning total portfolio, comparing it
against `book_pct` is a ~1.9× category error. The card must state which denominator it is using.
This reinforces the `NO_POLICY_SOURCE` answer: the band cannot be specified until the denominator
is specified.

### Existing API route conventions

Defense routes are **all `/api/v2/defense/*`**, registered in the `ROUTES` dict in
`scripts/api_v2.py` (~line 33630):

```
/api/v2/defense/posture            /api/v2/defense/core
/api/v2/defense/industries         /api/v2/defense/review
/api/v2/defense/recommendations    /api/v2/defense/inverse-stoplights
```

An `/api/v3/*` namespace exists but currently holds only three alerts routes
(`/api/v3/alerts/active`, `/api/v3/alerts/settings`, `/api/v3/alerts/settings/preview`) added by
the in-flight notification work. **The design doc specifies `GET /api/v3/defense/sector-leaders`,
which would be the first `/api/v3` defense route.** This is a convention decision for the
operator — see §7.

House gotchas that apply (from the RI desk skill, all still true in this tree):
- Paths in the GET route map swallow POSTs to the same path — irrelevant here (GET only), but the
  route must be registered GET-only.
- `api_v2.py` hot-reloads; imported modules do **not**. A new `sector_leaders_service` module needs
  a full server restart or an explicit `importlib.reload`.
- The dispatcher wraps payloads under `data` — confirmed live: `/api/v2/defense/posture` returns
  `{"ok": true, "data": {...}}`.

### How `/v3/defense` renders sector tiles

```
App.tsx:165        <Route path="defense" element={<DefenseHub />} />
DefenseHub.tsx:15  import InstitutionalRotationBrief from '../components/rotation/InstitutionalRotationBrief'
InstitutionalRotationBrief.tsx:1   export { default } from './ActionableSectorDecisionBoard'
```

The `RESEARCH WATCH` tile is `components/rotation/ActionableSectorDecisionBoard.tsx` — the status
enum is at line 16, the assignment at 104-115, the tile body at ~404. `InstitutionalRotationBrief`
is a one-line re-export shim.

Design system: `lib/watchTokens.ts` (`BB`, `DASH`, `numStyle`, `heatRamp`) and
`components/TerminalChip.tsx`. Zero raw hex is enforced by `check_design_tokens.sh` inside
`npm run build`, with defense at a 0-violation baseline. **The new card must use tokens only.**

### Position / account tables

`accounts` (5 rows) — `account_label, broker, mode, auto_execution_capable, routing_adapter, enabled`:

```
fidelity_401k        fidelity  live   False  NULL                          False
schwab_rollover_ira  schwab    live   False  NULL                          False
schwab_roth_ira      schwab    live   False  NULL                          False
schwab_taxable       schwab    live   False  NULL                          False
tradeai_automated    alpaca    paper  True   scripts.alpaca_paper_adapter  True
```

`config/account_capabilities.json` is the enforcement matrix and is what `account_eligibility()`
must be adapted to:

| Account | `can_short_stock` | `options_level` | `inverse_etf_ok` | `covered_calls_ok` |
|---|---|---|---|---|
| `schwab_taxable` | **true** (verified 2026-07-17, type=MARGIN) | none | true | false |
| `schwab_rollover_ira` | false | covered | true | true |
| `schwab_roth_ira` | false | none | true | false |
| `tradeai_automated` | true (paper) | — | true | false |
| `alpaca_taxable_live` | true | null | true | false — `verified: false`, *"not active"* |
| `alpaca_ira_live` | false | null | true | false — `verified: false` |

**Adaptation notes for `account_eligibility()`:**
- The config key is `can_short_stock`; the reference function expects `can_short`. Map it.
- **There is no `read_only` flag anywhere in the config.** The operator rule "Alpaca live is
  read-only and never routable" is *not encoded*. It must be derived (`broker == 'alpaca' and
  mode == 'live'`) or added to the config. Deriving it silently would repeat the class of bug this
  codebase keeps hitting — I recommend adding an explicit `read_only: true` to the two
  `alpaca_*_live` entries as part of S1, which is a config edit, not a policy invention.
- The pure function's signature and semantics stay as written; only the adapter that builds the
  `accounts` list changes. `test_sector_leaders_service.py` passes unchanged.

Positions come from `data/portfolios/state/holdings.json` (there is **no** `holdings` table in
Postgres). Account labels there:

```
schwab_rollover_ira 17 · schwab_taxable 12 · schwab_roth 3 · alpaca_taxable_live 1 · moomoo_taxable_live 1
```

Two label defects, both real (see §6): `schwab_roth` ≠ `schwab_roth_ira`, and
`moomoo_taxable_live` has **no** capability record at all.

Core registry: `operator_core_registry (id, symbol, account, designated_at, note)`, 12 rows, §3.

### Price history table and windows

`ticker_prices (id, symbol, price_date, close_price, source, created_at)` — 1,084,093 rows, 5,717
symbols, **2021-07-27 → 2026-07-29**. ~4,400–4,560 symbols per RTH session; 4,430 symbols have
≥25 sessions since 2026-06-01. Any window is computable.

Weekend/holiday rows drop to ~29-60 symbols (held names only) — **date-intersection is mandatory
in any RS math**, the gotcha `sector_momentum_engine` already handles. For this card,
`ticker_prices` is needed only for `_etf_return` and current `price`; the return metrics come
from Finviz per §1.

---

## 5. S0.5 — THE NULL DEFECT

### Where the null denominator originates

`apps/command-center-v3/src/components/rotation/ActionableSectorDecisionBoard.tsx:404`:

```tsx
breadth {sector.breadth_pct == null ? '—' : `${sector.breadth_pct}%`}
({sector.breadth_coverage_n ?? sector.breadth_n ?? '—'}/{sector.breadth_membership_n ?? '—'} covered)
```

```
$ grep -rn "breadth_membership_n\|breadth_coverage_n" scripts/ apps/command-center-v3/src/
apps/command-center-v3/src/components/rotation/ActionableSectorDecisionBoard.tsx:404: ...
```

**One hit. The render site is the only place either identifier exists in the entire tree.** Neither
`breadth_coverage_n` nor `breadth_membership_n` is ever produced by any server module. Confirmed
against the live endpoint — `/api/v2/defense/posture` rows carry `breadth_pct` and `breadth_n` and
nothing else:

```json
{"etf": "XLE", "sector": "Energy", "state": "LEADING", "rs20": 10.51, "slope": 4.38,
 "breadth_pct": 55, "breadth_n": 56, "book_pct": 3.9, "book_dollars": 26482, ...}
```

So the numerator falls through `breadth_coverage_n` → `breadth_n` = 56, and the denominator has no
fallback at all → `—`. That is the exact live string: **`breadth 55% (56/— covered)`**.

The denominator is not merely unwired — the value **does not exist**.
`config/defense_breadth_policy.json` declares `membership_scope:
"covered_screener_membership_not_official_etf_constituents"`, i.e. there is no official membership
count to divide by. `industry_momentum_state.stocks` is `NULL` on every Energy row sampled, so
Finviz's own universe count is not being captured either. The honest fix is to drop the
denominator and render `breadth 55% (56 covered members)` — not to source a number that was never
collected.

### How many other render sites share the pattern

`?? '—'` appears **379 times** across `apps/command-center-v3/src/**/*.tsx`. Most are single-value
renders where an em-dash is defensible. The specific *"null as a denominator inside a confident
sentence"* pattern (`?? '—'}/`) appears **7 times**:

| File:line | Field |
|---|---|
| `components/rotation/ActionableSectorDecisionBoard.tsx:404` | `breadth_membership_n` — **the reported defect** |
| `components/PipelineControlTower.tsx:32` | `closed_trades.have` / `.need` |
| `components/StopManagement.tsx:363` | `stop_qty` / `qty` |
| `components/OptionProposalCardV4.tsx:729` | `prime_score` /100 |
| `pages/HealthHub.tsx:407` | `available_count` / `backends.length` |
| `pages/ActiveTraderConfigTab.tsx:151` | `closed_paper_trades` / `min_closed_validation_trades` |
| `pages/ActiveTraderConfigTab.tsx:153` | `profit_factor` / `min_profit_factor` |

Per the prompt's "do not fix unrelated bugs", I changed none of these. The `<Val>` contract in S1
prevents the class **inside the new card only**; the other 6 sites remain.

---

## 6. INCIDENTAL OBSERVATIONS

Logged, not fixed.

1. **Two of eleven sectors are missing from the live board.** `sector_momentum_state` for
   2026-07-28 has only **9** sector rows — `XLC` (Communications) and `XLRE` (Real Estate) are
   absent, though both are configured in `config/sector_momentum.json` and both carry real book
   exposure (Communications 3.0% / $20,057; Real Estate 0.6% / $4,211). It is not a one-day blip:
   07-28 → 9, 07-27 → 9, 07-24 → 9, 07-23 → 10, 07-22 → **8**, 07-21 → 9. The card's `rank_total`
   would honestly be 9, not the 11 in the design doc, and two sectors would be unreachable.

2. **Effective-exposure denominator is the mapped sleeve, not the portfolio.** $676,750 vs
   $1,258,436 — see §4. Every `book_pct` on the Defense Desk today is ~1.9× larger than the
   same holding's share of total portfolio value. Nothing labels which denominator is in use.

3. **Non-sector labels leaking through `canon_sector()`.** `Dividend Equity` ($8,253),
   `Equity Income Fund` ($4,979) and `Other` ($6,612) — $19,844, 2.9% of the mapped book — are
   bucketed as if they were sectors. They are fund *categories* with no alias entry.

4. **Effective Technology weight has moved a long way.** Defense v4 recorded "tech 24.1% effective
   (5.1% direct)" and WS-E recorded 23.8%; today it is **7.3% effective / 1.3% direct**. Either
   the book changed substantially or a look-through weight regressed. Worth a check before any
   exposure verdict is trusted — this is the number the card would render.

5. **Two enrichment-cache field names lie about their units.** `market_cap_b` is in **millions**
   (XOM = 657,641.8 → $657.6B) and `avg_vol_m` is in **thousands** of shares (XOM = 16,861.44).
   `defense_recommendations.py:637` already compensates
   (`avg_vol_m * 1000 * price / 1e6`); reuse that formula rather than the field name.

6. **Account label drift.** `holdings.json` uses `schwab_roth`; `accounts` and
   `account_capabilities.json` use `schwab_roth_ira`. And `moomoo_taxable_live` (1 position)
   appears in `holdings.json` but exists in neither the `accounts` table nor
   `account_capabilities.json` — an account with **no capability record**, which an eligibility
   check would have to fail closed on.

7. **`allocation_decision()` is running on an absent config.** `allocation_policy` is `None` in
   `config/defense_recommendations.json`, so the function's benchmark/mandate/tilt machinery
   silently degrades to a flat 9.1% for every sector. It is not wrong, but it is not doing what it
   looks like it is doing.

8. **`symbol_profiles` performance columns are dead.** 2/2,196 populated on `perf_week_pct` and
   `perf_month_pct`, last written 2026-07-25. Whatever writes them has effectively stopped. Any
   code reading them is reading nulls.

9. **Earnings coverage is partial.** `symbol_profiles.next_earnings_date` is populated for
   787/2,196 symbols (745 in the future), refreshed 2026-07-29 06:35. `days_to_earnings` will be
   `None` for most constituents and needs a `data_gaps` entry rather than an omission.

---

## 7. OPERATOR NOTE — THE DRIVE FOLDERS AND THE "DEAD" DOC SYNC

Both facts in the prompt are confirmed, and together they explain the P1 symptom — **but the
conclusion is different from the one in the project notes.**

**Confirmed — the recorded folder ID is gone:**

```
$ gog drive get 1oL_OxjCF-q1pq9c-8GCa8YS3TFeQOv41
Google API error (404 notFound): File not found: 1oL_OxjCF-q1pq9c-8GCa8YS3TFeQOv41.
```

**Confirmed — there are two `docs` folders under `Trade_AI_Docs_v2`** (`1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`, 56 children):

| Folder ID | Children | Newest child | Holds `sector_leaders_v1`? |
|---|---|---|---|
| `1BMxbxU9c9rF3NBvXVQtVEewdvkifVkwP` | 110 | **2026-07-21 17:32** | No |
| `1Rb6qcu_D45ehZ0EKwEqwbzkEg9zKlBcA` | 300 | **2026-07-29 15:03** | **Yes** |

**The doc sync is not dead.** It is running hourly and succeeding:

```
[2026-07-29 14:05:23 UTC] sync done: 3 uploaded, 3239 unchanged, 3242 total candidates
[2026-07-29 15:05:01 UTC] === sync start ===
[2026-07-29 15:05:15 UTC] sync done: 0 uploaded, 3242 unchanged, 3242 total candidates
```

2,215 `sync start` entries in the log; the most recent three are 13:05, 14:05, 15:05 UTC today.

**The actual defect is a folder fork.** `scripts/sync-docs-to-drive.sh → resolve_folder()` searches
Drive by name and takes `matches[0]`:

```python
matches=[f['id'] for f in files if f.get('name')=='$part' and 'folder' in f.get('mimeType','')]
print(matches[0] if matches else '')
```

With two folders named `docs`, "first match" is whatever order the Drive API returns. Whichever it
picked got written into `/home/johnclaw/.local/state/drive-folder-cache.txt` and pinned forever:

```
$ head -1 /home/johnclaw/.local/state/drive-folder-cache.txt
docs|1Rb6qcu_D45ehZ0EKwEqwbzkEg9zKlBcA
```

So the sync moved to `1Rb6qcu…` and **`1BMxbxU…` froze on 2026-07-21 17:32** — within days of the
"dead since roughly 2026-07-19" report. Anyone with a bookmark, link, or note pointing at
`1BMxbxU…` has been looking at a tree that stopped updating on 07-21 while the sync ran normally
into the other one.

**Recommended P1 follow-up (not done here — out of scope for this stage):** decide which `docs`
folder is canonical, merge/trash the other, and make `resolve_folder()` fail loudly on an ambiguous
name match instead of silently taking `matches[0]`.

---

## 8. SCOPE RECOMMENDATION

**Proceed to SL-S1**, with the following changes to the plan as written.

### What got easier

- **S0.2 is not the risk it was scoped as.** The join covers the leading pool as well as the
  lagging one. No extra stage, no re-estimate. `3–4 h` for the DB layer stands, likely at the
  lower end.
- **S0.1 resolves cleanly to `INDUSTRY_RS_AVAILABLE`.** No column rename, no `rs_vs_spy`
  substitution, no operator decision needed. The card's ranking key is sound.
- **Effective exposure needs no work** — `sector_momentum_state.book_pct` already *is* the
  look-through weight. Read it; don't call the module.

### What must change in the design

1. **`rank_implied_weight_pct` returns `None` in S1.** No rank-keyed band exists (§3). The
   exposure gap renders "unknown" with a `data_gaps` reason. This is the design's own instruction
   and I am following it — but it means the card ships without §3.1, *the number the README calls
   "the one genuinely actionable number."* The operator should know that going in.
2. **`rank_total` will be 9, not 11** — Communications and Real Estate have no sector row (§6.1).
   Either accept 9, or fix the sector engine first as a prerequisite.
3. **`constituent_count` cannot be the true universe count.** `industry_momentum_state.stocks` is
   NULL. Report covered members only, labelled as such, and put the absence in `data_gaps`.
4. **Add `read_only: true` to the two `alpaca_*_live` entries** in `config/account_capabilities.json`
   so the standing rule is enforced from config rather than derived in code (§4). Small config
   edit; I did not make it without sign-off.
5. **Declare the denominator** on any weight the card renders (§4, §6.2).

### The one blocking decision I need

**Route namespace.** The design specifies `GET /api/v3/defense/sector-leaders`. Every existing
defense route is `/api/v2/defense/*`; `/api/v3/*` currently holds only three alerts routes. I will
follow the design doc and use `/api/v3/defense/sector-leaders` **unless told otherwise** — but if
the intent is that this card should sit with its siblings, say so now, because moving a route after
the component is wired is avoidable churn.

### Revised estimate

| Phase | Original | Revised |
|---|---|---|
| S1 pure functions + tests | 1 h | 1 h — unchanged, tests should pass as written |
| S1 DB layer + endpoint | 3–4 h | **2.5–3 h** — join is a `WHERE` clause, exposure is a column read |
| S1 component + wiring | 2–3 h | 2–3 h — unchanged |

---

## COMMANDS RUN

All queries were read-only, executed through a `SELECT`/`WITH`/`EXPLAIN`-only guard wrapper over
`db_adapter._get_conn()` (shell `psql` peer auth fails for `trade_ai`; the adapter is the
known-good path). No writes, no DDL, no order-path or proposal-table access at any point.
No feature code was written. `git status` is unchanged apart from the two additive paths below.

**Files added by this stage:**
- `docs/_design/sector_leaders_v1/` — the four Drive artifacts, unmodified
- `docs/_findings/sector_leaders_recon_2026-07-29.md` — this document

---

**STOPPED FOR SIGN-OFF. S1 not begun.**
