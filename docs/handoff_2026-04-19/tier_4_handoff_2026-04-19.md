# Trade AI v12 — Tier 4 Handoff: Historical Portfolio Reconstruction

**Version:** 1.0  
**As-of:** 2026-04-19  
**Tier:** 4 — Future multi-day project (~13-19 hours)  
**Audience:** Developer + Architect (after readiness criteria met)  
**Status:** NOT YET READY TO EXECUTE — see readiness checklist

---

## Why Tier 4 is different

Tier 1, 2, 3 tasks can be executed today with current data. **Tier 4 (Phase 11) cannot.** It requires data that doesn't exist yet:

1. **30-60 days of daily portfolio snapshots** — accumulating starting when P2-1 ships. Until then, can't test reconstruction queries against meaningful data.

2. **Historical broker transaction data** — needs to be exported from Schwab and Fidelity by John, processed, and imported. Schwab provides 24 months of transaction history via export; older data may need manual reconstruction or just be permanently lost.

3. **Architectural decisions** that are easier with real data in hand than designed in a vacuum.

Writing detailed execution prompts now would produce code that can't be tested for 1-2 months. By then, the system will have evolved and prompts will be stale.

This document instead provides:
- **Readiness checklist** — what must be true before starting
- **Strategic outline** — what Phase 11 entails at a high level
- **Sub-phase summaries** — work breakdown when ready
- **Open questions** — decisions to make when we get there

---

## Readiness checklist

Before starting Phase 11, ALL of these must be true:

### Data accumulation

- [ ] **Phase P2-1 has been live for 30+ days** — daily portfolio_snapshots writing reliably
- [ ] **Phase P2-2 has been live for 30+ days** — price_cache populated and current
- [ ] Postgres `portfolio_snapshots` table has at least 30 rows
- [ ] Postgres `holdings` table has at least 30 rows (one per day)
- [ ] No gaps longer than 5 days in snapshot dates (indicates pipeline reliability)

### Transaction data

- [ ] John has exported Schwab transaction history CSVs (Schwab → Accounts → History → Export)
- [ ] John has exported Fidelity 401k transaction history CSVs (Fidelity → History → Export)
- [ ] CSVs cover at least 12 months of historical activity
- [ ] CSVs include: date, account, action (buy/sell/dividend/split), ticker, shares, price, fees

### Foundation work

- [ ] Tier 1 complete (especially P2-1, P2-2, Phase 0)
- [ ] Tier 2 complete (especially P3-1 performance_history)
- [ ] All current tests passing
- [ ] No dual-write failures in past week

### Storage capacity

- [ ] At least 5GB free disk space (transaction history + reconstruction tables can be large)
- [ ] Postgres backup verified working (P5-1 ran for 30+ days)

If ANY checkbox is unchecked, Phase 11 should NOT start. Address blockers first.

---

## Phase 11 strategic outline

**End goal:** Time-travel slider in UI shows portfolio state on any past date, including:
- Total value across all accounts
- Per-position holdings (what tickers, share counts)
- Per-position values priced at historical close
- Sector breakdown
- Gain/loss vs cost basis at that date

### Why this is multi-day work

Three independent components, each non-trivial:

1. **Data ingestion** — broker CSV parsing for two different formats (Schwab vs Fidelity), normalization, deduplication
2. **Reconstruction logic** — replay transactions backward from current holdings to derive historical position composition
3. **UI integration** — extend existing time-travel UI (built in Phase 8D-3b) to also reconstruct portfolio state

Each takes 4-7 hours including testing. Plus design decisions between sub-phases.

---

## Sub-phase breakdown

### 11A — Snapshot accumulation (~0 hrs new work)

**What:** Phase P2-1 (Tier 1) already does this. As days pass, `portfolio_snapshots` and `holdings` tables fill up automatically.

**No code:** Just wait.

**Deliverable:** 30+ days of accumulated snapshots before 11B can start.

---

### 11B — `/api/portfolio/as_of/<date>` reconstruction endpoint (~3-4 hrs)

**What:** New endpoint similar to Phase 8D-1 but for portfolio (not personal_situation).

**Design:**

For dates AFTER P2-1 went live:
```sql
-- Find nearest snapshot at-or-before target date
SELECT data FROM holdings 
WHERE as_of <= '2026-05-15' 
ORDER BY as_of DESC 
LIMIT 1;
```

Returns the snapshot, which includes per-position composition. Then for each position:
```sql
-- Get historical close price
SELECT close_price FROM price_cache 
WHERE symbol = 'LMT' AND price_date <= '2026-05-15' 
ORDER BY price_date DESC 
LIMIT 1;
```

Multiply shares × price = position value at that date. Sum = portfolio total.

**For dates BEFORE P2-1 went live:** Return null/error until 11D.

**Response shape:**
```json
{
  "ok": true,
  "as_of": "2026-05-15",
  "source": "snapshot|reconstructed",
  "snapshot_age_days": 0,
  "total_value": 1206068.64,
  "account_summaries": {...},
  "holdings": [
    {"symbol": "LMT", "shares": 100, "price": 488.20, "value": 48820, ...}
  ]
}
```

**When ready:** After 11A (30+ days of data).

---

### 11C — Transaction import from broker CSVs (~5-8 hrs)

**What:** Parse Schwab + Fidelity CSV exports into a normalized `transactions` table.

**New schema:**
```sql
CREATE TABLE transactions (
    id serial PRIMARY KEY,
    transaction_date date NOT NULL,
    account varchar(50) NOT NULL,
    action varchar(20) NOT NULL,          -- 'BUY'|'SELL'|'DIV'|'SPLIT'|'TRANSFER'|'FEE'
    symbol varchar(10),
    shares numeric(15,6),
    price_per_share numeric(12,4),
    total_amount numeric(14,2),
    fees numeric(8,2),
    notes text,
    source_csv text,                       -- which import file this came from
    imported_at timestamptz DEFAULT now(),
    UNIQUE(transaction_date, account, action, symbol, shares, total_amount)
);
CREATE INDEX idx_txn_date ON transactions(transaction_date DESC);
CREATE INDEX idx_txn_symbol ON transactions(symbol);
CREATE INDEX idx_txn_account ON transactions(account);
```

**Implementation:**

- Schwab CSV parser (column mapping unique to Schwab format)
- Fidelity CSV parser (different format, different columns)
- Normalizer that converts both into the unified schema
- Deduplication via UNIQUE constraint
- Validation: total shares match, dates monotonic, etc.
- Import script with progress reporting

**Open questions:**
- How to handle stock splits (need to retroactively adjust shares)
- How to handle dividends (DIV action with no share change)
- How to handle cash transfers between accounts (no symbol)
- How to handle 401k vs taxable accounts (different tax treatment, may need separate logic later)

**When ready:** After John exports CSVs.

---

### 11D — Pre-P0 historical reconstruction (~3-4 hrs)

**What:** For dates before Phase P0 went live (2026-04-19), no holdings snapshots exist. Reconstruct them by replaying transactions backward.

**Algorithm:**

```
Start with: today's holdings
For each historical date (going backward):
    For each transaction on that date:
        REVERSE the transaction:
        - BUY → subtract shares
        - SELL → add back shares  
        - DIV → no share change (was income)
        - SPLIT → reverse the split ratio
    Save the resulting holdings as a synthetic snapshot for that date
    
End at: earliest transaction date
```

**Implementation:**
- Reconstruction script `linux_port_v2/linux/reconstruct_historical_holdings.py`
- Walks transactions newest-first
- Inserts into `holdings` table with `source='reconstructed'` flag
- Idempotent (UNIQUE on as_of)

**Verification:**
- Manual spot-check: pick a date with known portfolio value, run reconstruction, compare
- Reconciliation: latest reconstructed snapshot should match earliest live snapshot

**When ready:** After 11C (transactions imported).

---

### 11E — Time-travel UI integration (~2-3 hrs)

**What:** Extend the existing Personal modal time-travel slider (Phase 8D-3b) OR build a new Portfolio time-travel UI.

**Open question:** Single combined slider (one slider controls both Personal and Portfolio reconstruction) or two separate UIs?

**Anticipated UI:**

In the Strategy Center or a new "Time Machine" view:
- Date slider with much wider range (months to years, depending on data)
- Display panel showing:
  - Total portfolio value on that date
  - Top holdings
  - Sector mix
  - Gain/loss vs cost basis
- Side-by-side comparison: today vs that date
- "How did I get from there to here?" summary (transactions in between)

**Implementation:**
- Frontend HTML/JS in command_center.html or new strategy_center.html
- Calls `/api/portfolio/as_of/<date>` (built in 11B)
- Renders charts comparing to today

**When ready:** After 11B and 11D both shipped.

---

## Open architecture questions for Phase 11

These should be discussed before implementation:

### 1. Account-level vs portfolio-level reconstruction

Should we reconstruct per-account or only at portfolio total level?

**Trade-off:**
- Per-account: more useful for tax planning ("what did my Roth IRA look like in 2024?") but more complex
- Portfolio total: simpler, but loses tax-relevant detail

**Recommendation:** Portfolio total in 11B. Per-account in a future enhancement after seeing how the basic version is used.

### 2. Split adjustments

Stock splits create complexity. AAPL had a 4:1 split in 2020. If we have transactions from 2019 with pre-split prices, reconstructing 2018 portfolio needs the unadjusted shares.

**Trade-off:**
- Always use adjusted shares (forward-adjusted, like Yahoo provides) — simpler but loses fidelity
- Track original shares + apply splits in reverse — more accurate but complex

**Recommendation:** Discuss with John before deciding.

### 3. Cost basis reconstruction

Tax lots are complex (FIFO, LIFO, specific identification, wash sales). Do we attempt to reconstruct cost basis per lot, or just track aggregate?

**Trade-off:**
- Per-lot: actual broker behavior, useful for tax reports
- Aggregate: simpler, less accurate for tax purposes

**Recommendation:** Aggregate in initial version. Mark as approximation. Defer per-lot to a future tax-focused phase.

### 4. Missing data handling

What if we have transactions but missing prices for some date+symbol combinations?

**Options:**
- Use most recent available price (forward fill)
- Use linear interpolation
- Mark as "data quality: incomplete" and exclude from totals
- Refuse to reconstruct, show error

**Recommendation:** Forward fill with a "data quality" flag in response. UI can show warning when quality is low.

### 5. Performance

Reconstructing portfolio for 365 dates × 47 holdings × 3 SQL queries each = potentially slow (50K+ queries).

**Mitigations:**
- Cache reconstructed snapshots in `holdings` table once computed
- Materialized views for common date ranges
- Pre-compute commonly-asked dates (year-ends, quarter-ends)

**Recommendation:** Start without optimization, add caching only if performance is a problem.

---

## When to revisit this document

- After Tier 1+2 ship and P2-1 has been running for 30 days → review readiness checklist
- When John exports broker CSVs → review 11C scope
- Before starting any sub-phase → review the relevant section + open questions
- Update this doc if scope changes during implementation

---

## Decisions log (to be filled in)

| Date | Decision | Rationale |
|---|---|---|
| | | |

---

## Acceptance criteria for entire Phase 11 (when complete)

- [ ] Time-travel slider works for any date with available data
- [ ] Total value, per-position values, sector mix all reconstruct correctly
- [ ] Reconstruction performance: < 2 seconds per date
- [ ] Pre-P0 dates work via transaction replay
- [ ] Post-P0 dates work via direct snapshot lookup
- [ ] UI shows data quality indicator when data is incomplete
- [ ] No crashes on dates with missing transaction data
- [ ] Documentation updated in schemas_reference.md

---

*Tier 4 handoff document created 2026-04-19. Update when readiness conditions met. Do NOT execute until checklist clears.*
