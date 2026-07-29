# Sector Leaders Card - Design Spec v1

> ## CHANGE LOG — implementation corrections
>
> This doc is the approved design. Where the build diverges, the divergence is recorded here so the
> artifact never silently disagrees with the running system. All three below are **operator
> decisions taken during implementation**, not unilateral changes.
>
> ### 2026-07-29 · endpoint namespace (SL-S1)
> `GET /api/v3/defense/sector-leaders` → **`GET /api/v2/defense/sector-leaders`**.
> The `v3` in the original spec matched the *frontend* route `/v3/defense`, but the API and the
> page version independently — a page redesign is not an API contract change. Every existing
> defense route is under `/api/v2/defense/`; one v3 defense route would split the namespace and the
> asymmetry would never be cleaned up. If defense migrates, it migrates as a cohort.
> §4 below is updated in place.
>
> ### 2026-07-29 · dispersion measured at the wrong level (SL-S2) — supersedes §3.3
> As specified, dispersion pooled every confirming industry in a sector: 30–245 names across up to
> 20 industries. That measures **inter-industry separation**, not intra-group dispersion — the
> p90–p10 spread is dominated by how far Oil & Gas Integrated sits from Thermal Coal, not by how far
> XOM sits from OXY. Measured live, **10 of 11 sectors returned "buy names"** and the verdict
> carried no information.
>
> Corrected to a hybrid:
> - **spread** measured **within one industry** — the pool selection actually happens from
> - **excess** measured against the **sector ETF** — the instrument otherwise bought; there is
>   usually no tradeable industry ETF, so XLE stays the benchmark for every Energy industry
>
> Excess is deliberately *not* measured against the industry's own composite: the top quartile
> always beats its own mean, so that would be near-tautological.
>
> Per-industry dispersion is now **the verdict**. Sector-level is retained as a logged diagnostic,
> present in the payload, never rendered as a verdict. The `>= 8 priced names` floor applies **per
> industry**; below it the verdict is omitted, never pooled upward to rescue it.
> **Thresholds are unchanged at 12 / 4 / 6** — changing the level and the cut points together would
> leave neither testable against outcome data.
>
> Live result after the correction: **26 buy names / 14 mixed / 2 buy the ETF** across 42 decided
> industries, 69 omitted as too thin.
>
> ### 2026-07-29 · exposure gap ships without the signed figure (SL-S1) — qualifies §3.1
> Recon established that **no rank-implied sizing band exists anywhere in the tree** (see
> `docs/_findings/sector_leaders_recon_2026-07-29.md` §3). `rank_implied_weight_pct` returns `None`
> as the design instructs. Rather than render the whole strip as "unknown", the card shows **rank
> and weight adjacently** and lets the juxtaposition carry it — rank 1 at 3.9% against rank 11 at
> 7.4% is legible with no policy. The third cell reads "unknown — no sizing policy configured" and
> turns into the signed `pp` figure by itself when a policy lands.


Trade AI v12 · Defense Desk (`/v3/defense`) · approved design, 2026-07-29
Bundle: `SectorLeadersCard.jsx`, `sector_leaders_service.py`,
`test_sector_leaders_service.py`, this README.

**Status: approved design, reference implementation. Not drop-in code.**

---

## 1. The problem this solves

The Defense Desk currently tells the operator which sectors, sub-sectors, and
industries are leading and lagging. It does not tell him where to act.

Concretely, from the live page on 2026-07-29:

```
Energy · XLE · RESEARCH WATCH
Why: LEADING vs SPY with RS20 +10.5% and slope +4.4%
confirming industries: Oil & Gas Integrated, Thermal Coal, Oil & Gas Equipment
promote only when: A complete governed recommendation card must appear.
```

The chain terminates at the ETF. To act, the operator has to leave the app and
find constituent names elsewhere.

**The system already knows how to do this - on one side only.** The Short-Side
panel descends lagging industry to named constituent with entry, stop, size cap,
and account restriction:

- `SHORT ADVISORY · XPEV` - Auto Manufacturers LAGGING
- `SHORT ADVISORY · ACM` - Engineering & Construction LAGGING
- `SHORT ADVISORY · PLAB` - Semiconductor Equipment & Materials LAGGING

The industry-to-constituent join exists and runs. It is wired to one direction.
This card is the missing symmetric half.

## 2. Four defects in the current tile

1. **Chain terminates one level too high.** Sector to industry to nothing.
2. **Every card returns the same verdict.** Six of eight read `RESEARCH WATCH`
   with the identical string *"promote only when: A complete governed
   recommendation card must appear."* The board header reads `eligible 0`.
3. **"Why" restates the quadrant.** *"LEADING vs SPY with RS20 +10.5%"* is the
   axis values already plotted. It reads as justification, carries no new
   information.
4. **A null renders as punctuation.** `breadth 55% (56/-- covered)` appears on
   every sector card. A missing denominator is displayed as an em-dash inside a
   confident sentence.

## 3. What the card adds

### 3.1 Exposure gap

The one genuinely actionable number, currently uncomputed. Live examples:

| Sector | Rank | Book weight | Gap |
|---|---|---|---|
| Energy | 1 of 11 | 3.9% | underweight |
| Financials | 2 of 11 | 25.2% | likely overweight |
| Technology | 11 of 11 | 7.4% | overweight the worst sector |

Today the operator derives this by holding eleven ranks and eleven weights in
his head. The card computes it.

**The rank-implied weight band is operator policy, not a constant.** It must be
sourced from wherever the rotation sizing rules already live, and it must
respect the defensive-lean directive and the core registry. If no policy source
exists, return `None` and render "unknown". Do not ship a stub band.

### 3.2 RS versus own industry - the load-bearing metric

Inside a leading sector, every constituent shows positive RS against SPY. That
is sector beta arriving, not name selection. The card ranks on relative strength
against the name's **own industry composite**, which is what separates leaders
inside a leading group from passengers.

In the sample payload, OXY renders dimmed at -2.4 despite Energy ranking #1: a
laggard wearing a leader's sector. The current page cannot express this.

### 3.3 Dispersion - the ETF-versus-names decision

Whether to buy names at all is conditional, and the card decides it rather than
assuming:

- spread >= 12pp AND top-quartile excess >= 4pp -> **buy names**, the ETF dilutes
- spread <= 6pp -> **buy the ETF**, the group moves together, single-name risk unpaid
- between -> mixed, stated as mixed

Requires >= 8 priced constituents. Below that, both fields return `None` and the
verdict is omitted rather than guessed.

### 3.4 The null contract

`<Val>` on the frontend and `Optional[float]` plus `data_gaps` on the backend.
Every numeric render passes through `<Val>`; a null becomes italic "unknown"
with a hover reason. This is a structural fix - after adaptation it must be
impossible for a null to render as punctuation again.

## 4. API contract

```
GET /api/v2/defense/sector-leaders?sector={key}&horizon={W|M|Q}
```

Read-only. No POST/PUT/PATCH/DELETE in this feature.

> **Namespace corrected 2026-07-29 (operator decision, supersedes the original
> `/api/v3/` in this doc).** The `v3` here matched the *frontend* route
> `/v3/defense`, but the API and the page version independently — a page redesign
> is not an API contract change. Every existing defense route is under
> `/api/v2/defense/`; one lonely v3 defense route would split the namespace and
> the asymmetry would never get cleaned up. If defense migrates to v3 later, it
> migrates as a cohort.

```json
{
  "key": "energy",
  "name": "Energy",
  "etf": "XLE",
  "state": "LEADING",
  "rank": 1,
  "rank_total": 11,
  "rank_change": 6,
  "rs20": 10.5,
  "book_weight_pct": 3.9,
  "rank_implied_weight_pct": [9, 12],
  "data_age_hours": 17,
  "refresh_interval_hours": 24,
  "dispersion": { "spread_pp": 18.4, "top_quartile_excess_pp": 8.1, "n": 21 },
  "industries": [
    {
      "key": "oil_gas_integrated",
      "name": "Oil & Gas Integrated",
      "rank": 8,
      "rank_change": 2,
      "constituent_count": 24,
      "passing_count": 9,
      "filter_summary": "price >= $5, ADV20 >= $2M, mcap >= $300M",
      "source_note": "Finviz Elite f=ind_oilgasintegrated - fetched 2026-07-29 09:40 ET",
      "constituents": [
        {
          "symbol": "XOM", "price": 118.40,
          "rs_vs_industry": 6.2, "rs_vs_spy": 12.4,
          "pct_from_52w_high": -2.1, "adv_20d": 14000000,
          "days_to_earnings": 8, "held": null, "is_core": false,
          "blocked_accounts": [], "blocked_reason": null
        }
      ]
    }
  ],
  "data_gaps": []
}
```

Every numeric field is nullable. `data_gaps` carries a human-readable reason for
each null so the UI can explain itself.

## 5. Hard constraints

1. Renders and returns nothing that places, stages, or approves an order.
2. No writes. No `paper_trade_proposals`. No broker adapter import.
3. Taxable may short. Rollover IRA and Roth IRA may not - inverse ETF and
   covered calls only. Alpaca live accounts are read-only and never routable.
4. Core registry positions are trim-ladder-only, never full-exit. The card
   badges them; it must never imply a full exit.
5. No fabricated values. `None` plus a `data_gaps` entry, always.
6. Live schema is authoritative. Documentation in this project is known stale -
   the Drive doc sync has been dead since roughly 2026-07-19.

## 6. Highest-risk unknown

**Does a per-constituent return column exist over the same window used for the
industry composite?**

`rs_vs_industry` is the metric the entire card ranks on. If that data is not
available, the card cannot be built as designed. The honest fallback is to use
`rs_vs_spy` and **rename the column in the UI** so it does not claim a precision
it lacks - not to silently substitute one for the other.

This is flag-back #1. Resolve it in recon, before any component code.

## 7. Second unknown

The short-side industry-to-constituent join exists. Does it cover all 144 Finviz
industries, or only the lagging pool used by the short advisories? If the
latter, extending it to the leading pool is the actual work of this stage, and
scope should be re-estimated accordingly.
