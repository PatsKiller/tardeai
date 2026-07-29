# Sector momentum engine — two sectors running on stale relative strength

**Filed:** 2026-07-29 · **Found during:** SL-S1 (Sector Leaders card) · **Status:** DIAGNOSED, NOT FIXED
**Classification:** **decision-quality defect** — not a rendering bug

The operator has been reading Real Estate and Communications positioning off relative strength up
to **16 days old**, and nothing on the Defense Desk indicates it. The existing `RESEARCH WATCH`
board renders both as current.

This was found while building an unrelated card. It is filed with the diagnosis complete and
deliberately not fixed — a UI stage is the wrong place to change a nightly engine.

---

## 1. Observed

`sector_momentum_state`, non-STYLE rows, by `as_of`:

```
2026-07-28 |  9 | XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
2026-07-27 |  9 | XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
2026-07-24 |  9 | XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
2026-07-23 | 10 | XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
2026-07-22 |  8 | XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLY
2026-07-21 |  9 | XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
```

Eleven sectors are configured in `config/sector_momentum.json`. The engine writes **9 of 11** on a
normal close. The two missing are **XLRE (Real Estate)** and **XLC (Communications)**.

Their last written rows, from the desk snapshot `data/runtime/sector_momentum_latest.json`:

| ETF | Sector | Last `as_of` | Age at filing | State it is still asserting | Effective book weight |
|---|---|---|---|---|---|
| `XLRE` | Real Estate | **2026-07-13** | **16 days** | LAGGING, RS20 −4.43 | 0.6% ($4,211) |
| `XLC` | Communications | **2026-07-23** | **6 days** | LAGGING, RS20 −3.09 | 3.0% ($20,057) |

Both carry real exposure. Neither is a phantom row.

---

## 2. Why — root cause, traced

### It is NOT the engine's "warming up" guard

`sector_momentum_engine.compute_states()` skips a sector when it has fewer than
`need = rs_windows.long (60) + slope_lookback_days (5) + 1 = 66` closes date-aligned with SPY.
That was the obvious hypothesis and it is **wrong**:

```
sym   own_closes_130d  aligned_with_spy  verdict                       newest
XLRE               77                77  OK (>= need 66)               2026-07-13
XLC                79                79  OK (>= need 66)               2026-07-23
XLY/XLF/XLP/…      90                90  OK                            2026-07-29
```

Both clear the gate comfortably. The engine is not skipping them.

### It IS upstream: their price feed stopped

The engine dates each row from that ETF's **own last available close** (`s[i]` where
`i = len(s)-1`). If prices stop arriving, the engine keeps writing a row — dated to the last close
it can see. So the row is not missing; it is **frozen and correctly dated**, and then falls out of
any `max(as_of)` query.

`ticker_prices` by source shows the handover that broke them:

```
symbol source          rows  first        last
XLC    yfinance          73  2026-03-23   2026-07-13
XLC    market_quotes      6  2026-05-20   2026-07-23
XLRE   yfinance          77  2026-03-23   2026-07-13
XLRE   market_quotes    (none)
XLE    market_quotes     56  2026-05-04   2026-07-29
XLU    market_quotes     28  2026-06-22   2026-07-29
```

`yfinance` stopped supplying sector ETFs around **2026-07-13**. A `market_quotes` path took over
and covers the other nine. **XLRE has zero `market_quotes` rows. XLC has six.**

### Why those two and not the others

`price_db_sync.py` documents its universe:

```
1. finviz_quote_cache.json (Schwab tickers)
2. holdings.json (Fidelity current prices)
3. market_quotes (watchlist + proposal symbols — via ensure_price_history)
4. yfinance gap-fill for symbols still short on close history
```

Sector ETFs are in that universe **only incidentally** — because they happen to be held or
watchlisted. Checking:

```
holdings:  XLI HELD · XLB HELD · XLE, XLK, XLU, XLC, XLRE not held

watchlist_items:
  XLRE | removed    | 2026-05-31     <-- only row
  XLC  | removed    | 2026-05-31
  XLC  | researched | 2026-07-23     <-- matches its last price date exactly
  XLE  | researched | 2026-07-29
  XLK  | researched | 2026-07-29
  XLU  | active     | 2026-07-29
```

**XLRE's only watchlist row was removed on 2026-05-31.** It is not held and not watchlisted, so
nothing fetches it. XLC's `researched` row was last touched 2026-07-23 — precisely its last price
date, which is why it has six sporadic quotes rather than none.

**Root cause in one line:** the sector momentum engine depends on daily closes for 11 specific
ETFs, but nothing guarantees those 11 are in the price-fetch universe. Coverage is a side effect of
holdings and watchlist membership. Removing XLRE and XLC from the watchlist on 2026-05-31 silently
removed them from the price feed; `yfinance` masked it until ~2026-07-13.

---

## 3. Why this is a decision-quality defect

1. The engine **fails silently**. A frozen row is indistinguishable from a fresh one at the
   consumer, because `as_of` is correct — it just is not today.
2. `/api/v2/defense/posture` serves the snapshot, which **carries the last known row forward** for
   all 11. That is the right call for continuity and the wrong call without a staleness signal.
3. The `RESEARCH WATCH` board renders `as of 2026-07-28` from the board-level generation time, so
   XLRE reads as current when its underlying RS is from 07-13.
4. Consequence: **Real Estate has been asserting LAGGING / RS20 −4.43 for 16 days on 16-day-old
   prices.** If that sector has since turned, the desk has not noticed and would not.

---

## 4. Recommended fix — not implemented

**Primary — guarantee the engine's own inputs.** The 11 sector ETFs plus `SPY` and `QQQ` are
*engine infrastructure*, not user watchlist entries. They should be fetched unconditionally,
independent of holdings or watchlist state. Add them as a pinned universe in whatever feeds
`ticker_prices` (`price_db_sync.py` / `external_market_data_ingest.py`), sourced from
`config/sector_momentum.json` so the list cannot drift from what the engine reads.

**Secondary — make the engine fail loudly.** When a sector's newest aligned close is older than
N sessions, it should emit a staleness marker rather than a normal-looking row. Today the only
signal is a date the consumer must think to compare.

**Tertiary — surface it on the existing board.** The `RESEARCH WATCH` tile shows a single
board-level `as of`. It should show each sector's own `as_of` and badge the stale ones. (The
Sector Leaders card already does this — `RANK 10 OF 11 · STALE · AS OF 2026-07-13` — which is how
this was found.)

**Verification after any fix:** all 11 ETFs present in `ticker_prices` for the latest session, and
`sector_momentum_state` writing 11 of 11 rows on the next close.

---

## 5. Scope note

Not fixed here deliberately. Touching a nightly engine that writes the table the whole Defense Desk
reads is not a change to make inside a UI stage, and the fix belongs with whoever owns the price
pipeline. The Sector Leaders card mitigates the *symptom* by badging per-sector staleness and
listing it in `data_gaps`; the underlying data remains stale until this is addressed.
