# Defense/Sectors Data Quality — Five-Session Shadow Comparison

**Generated:** 2026-07-24
**Branch:** `agent/defense-data-quality-v1` (PR #168, draft)
**Producer:** `scripts/defense_shadow_replay.py`
**Machine-readable report:** `/tmp/defense_shadow_5session.json` (not committed — see *Sanitisation*)
**Calculation version:** `defense-quality-v1`

> **This is a historical shadow replay, not a live walk-forward claim.**
> Nothing in this document activates a methodology, changes a live recommendation, or
> authorises an order. Legacy output remains authoritative.

---

## Sessions replayed

`2026-07-17`, `2026-07-20`, `2026-07-21`, `2026-07-22`, `2026-07-23`

These are the five most recent sessions for which `sector_momentum_state` holds a
**complete** board (≥8 rows). Partial days were excluded deliberately: `2026-07-18`
(3 rows), `2026-07-14` and `2026-07-13` (1 row each) are interrupted engine runs, and
replaying them would surface a missing run as if it were a methodology delta.

---

## Headline result

| Bucket | Count | Meaning |
|---|---:|---|
| `unchanged` | **18** | Legacy and contract agree exactly |
| `changed_correctly` | **27** | Both arms produce a value; they differ by the known methodology change |
| `not_applicable_style_pair` | **15** | IWM−SPY, RSP−SPY, VUG−VTV — index spreads with no constituents; neither arm ever produced breadth |
| `potential_false_exclusion` | **0** | — |
| `legacy_false_exclusion` | **0** | — |
| `insufficient_evidence` | **0** | — |

**60 comparisons total; 45 are real sector comparisons.**

### The safety question

**No false exclusions were found, in either direction.**

- There is **no** case where legacy published a breadth number and the contract withholds
  one. The tightened calculation does not blind any sector that previously reported.
- There is **no** case where legacy withheld and the contract newly publishes. The change
  does not widen eligibility either.

Every one of the 45 sector comparisons resolved in **both** arms. The disagreement is
purely in the value, never in whether a value exists.

### Delta distribution (45 comparisons)

| Statistic | Value |
|---|---|
| Minimum | **−5 pts** |
| Maximum | **+4 pts** |
| Mean | **−0.73 pts** |
| Median | **0 pts** |
| \|delta\| > 5 pts | **0** |
| \|delta\| > 10 pts | **0** |

Largest observed differences:

| Session | Sector | Legacy | Exact | Delta |
|---|---|---:|---:|---:|
| 2026-07-23 | Communications | 38% | 33% | **−5** |
| 2026-07-21 | Consumer Staples | 59% | 55% | −4 |
| 2026-07-22 | Financials | 59% | 55% | −4 |
| 2026-07-22 | Utilities | 45% | 49% | +4 |
| 2026-07-17 | Healthcare | 63% | 60% | −3 |
| 2026-07-20 | Financials | 60% | 57% | −3 |

The mean is slightly negative, meaning the exact 20-session window reports marginally
**lower** breadth than the 30-calendar-day average did. That direction is consistent with
the window being genuinely shorter and more recent — but a 45-observation sample across
five sessions in one market regime is **not** sufficient to call that a durable bias, and
this report does not claim one.

**No delta is labelled "better".** The exact calculation is preferred because it is
*reproducible* — a fixed count of distinct trading dates with deterministic duplicate
handling — not because its numbers are nearer some external truth. No external breadth
reference was available to adjudicate against.

---

## Per-comparison fields

Each row in the JSON report carries:

`session`, `sector`, `etf`, `state_published`, `breadth_published`,
`breadth_legacy_replay`, `breadth_exact`, `delta_pts`, `coverage_n_legacy`,
`coverage_n_exact`, `membership_n`, `duplicate_dates_removed`, `exact_quality`,
`stale`, `recommendation_eligible`, `bucket`, `reason`, `payload_hash`.

`payload_hash` is a canonical SHA-256 over `(sector, session, breadth_exact,
exact_quality, recommendation_eligible)`, so any later re-run that changes an outcome
changes the hash.

---

## Duplicate-date removal

**0 duplicate same-day observations were found across all five sessions.**

The last-observation-wins dedup path is therefore **defensive, not currently corrective**.
It is stated plainly here because reporting the field without this note would imply the
change is fixing an active problem in the present data. It is not — it removes a class of
failure (same-day repricer double-writes) that the current window does not exhibit.

---

## Stale quarantine

| Fact | Value |
|---|---|
| SLA | 4 days |
| Sectors flagged stale | **9** |
| Sectors marked `recommendation_eligible = false` | **9** |

All nine are the `2026-07-17` board, which is 7 days old relative to the 2026-07-24
evaluation date. Sessions `07-20` through `07-23` are inside SLA and remain eligible.

No row was deleted. Stale rows keep their published values and their state; they lose only
the ability to originate a **new** add recommendation.

---

## Market-state wording (NH/NL)

The `market_movers` capture was measured at **exactly 15 rows per signal** across all nine
signals in the current capture — the source is capped.

| Before | After |
|---|---|
| `new_high` / `new_low` presented without scope | `source_scope = top_movers_sample` |
| — | `sample_cap_per_signal = 15` (measured from the capture, not hardcoded) |
| — | `source_as_of` = capture timestamp |
| — | `quality.state = sample_only`, reason `not comprehensive breadth` |

The wording change is a **scope correction, not a data change**: the same 15 rows are
returned, but they may no longer be read as exchange-wide market breadth. The cap is
derived from the capture itself so that if Finviz changes the export size, the claim
narrows or widens with the evidence instead of silently drifting.

---

## Recommendation inclusion / exclusion

| Metric | Legacy | Shadow |
|---|---:|---:|
| Sector comparisons producing a breadth value | 45 | 45 |
| Additions (shadow publishes, legacy withheld) | — | **0** |
| Removals (legacy published, shadow withholds) | — | **0** |
| Rows made recommendation-ineligible by the stale SLA | 0 | **9** |
| Sector states changed by this tranche | — | **0** |

The nine stale-ineligible rows are the **only** eligibility movement in the entire replay,
and they are a function of the age SLA, not of the breadth calculation.

**Sector and account concentration effects: none observed.** No sector changed state and no
recommendation was added or removed, so no concentration shift can be attributed to this
tranche.

---

## Honest limits

These are properties of the replay method and must not be dropped when quoting the result.

1. **Membership is resolved as of today.** `screener_symbol_membership` and
   `trade_ai_scans` carry no effective-dated history, so a symbol that joined a sector
   after a replayed session is treated as a member of it on that session. Prices are
   correctly as-of each session; membership is not. Both arms are affected identically,
   so the *comparison* stays fair, but neither arm's absolute value is a faithful
   reconstruction of what would have printed that day.
2. **The legacy arm is a reimplementation, not an archive.** It reproduces the
   `CURRENT_DATE - 30` calendar average and the `count(*) >= 15` gate exactly, evaluated
   as of each past session — but it is recomputed now, not read from what the process
   emitted that day. `breadth_published` (the value actually stored in
   `sector_momentum_state`) is carried in the JSON alongside it for cross-checking.
3. **One regime, five sessions, 45 observations.** Too small to characterise behaviour
   across volatility regimes, sector rotations or holiday-shortened weeks.
4. **`ticker_prices` quality was not audited here.** A separate finding on this host
   (corrupt bars, e.g. sub-dollar closes for a mega-cap between ~$200 sessions) affects
   any close-derived measure. This replay inherits whatever is in the table.

---

## Sanitisation

The machine-readable report is written to `/tmp/defense_shadow_5session.json` and is
**deliberately not committed**. It contains per-symbol sector membership derived from the
scan tables. This markdown carries only aggregate statistics, sector-level values and
bucket counts — no symbol lists, no positions, no dollar amounts, no account identifiers.

---

## Status

**NOT ACTIVATED.** The exact-breadth calculation is wired into the producer, but the
recommendation path is unchanged and legacy output remains authoritative. Operator
approval is required before any of this becomes decision-bearing.
