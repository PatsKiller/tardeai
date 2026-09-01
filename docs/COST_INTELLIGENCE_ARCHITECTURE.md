# Investment Cost Intelligence — Architecture (v1.2, 2026-07-19)

Status:      ACTIVE
as_of:       2026-07-19T12:50:59-04:00
Measured at: efcc51365 / not measured

**Canonical ledger:** `investment_cost_events` (dedupe_key UNIQUE — every charge
counted exactly once, DB-enforced) + `fund_expense_rate_history` (dated OER
rates; missing rate = visible gap, zero accrual, never a guess).

**Three classes, never silently merged** (every row labeled actual/estimated ×
cash/embedded):
1. **ACTUAL_CASH** — broker-posted charges, normalized from `trade_transactions`
   (identity rides the ledger dedupe_key) and `options_fill_evidence`
   commissions/fees. Actual charges supersede estimates (superseded flag kept
   for audit).
2. **EMBEDDED_FUND_COST_ESTIMATE** — daily accrual `market value × net OER ÷ 365`.
   Fund NAV performance is already net of operating expenses: the accrual is
   explanatory and is NEVER subtracted from NAV-based P&L a second time.
3. **EXECUTION_FRICTION_ESTIMATE** — spread/slippage estimates, labeled, separate.

**Ingestion:** `investment_costs.py` — `ingest_actual_fees()` +
`accrue_fund_expenses()`; cron daily 17:05 weekdays. Current real coverage:
$47.92 of sell-side regulatory fees (150 events) reconciled 1:1 against the raw
ledger; option fees flow automatically from fill evidence; OER accruals start
when the operator fills `fund_expense_rate_history` (unmatched panel lists the
missing symbols).

**Independent reconciliation** (`costs_reconciliation`, P14 — not tautological):
ledger-fee totals vs normalized events · fill fees vs outcome fees · journal
P&L vs lifecycle outcomes · charge-counted-once (event vs distinct keys) ·
embedded-never-cash guard. Surfaced on the Costs tab (ALL CHECKS PASS / DRIFT).

**API:** GET `/api/v2/journal/costs/{summary,timeseries,by-security,unmatched,
reconciliation}` (from/to/grain/symbol/account filters; payloads carry labels).

**UI:** TradeInView (JournalHub) top-level **Costs** tab — KPI strip per class +
reconciliation card, time chart (week/month/quarter/year), by-security table,
unmatched & unresolved queue, NAV-double-count reminder line.

**Known limits (honest):** execution-friction estimation not yet populated
(class exists, no writer until lifecycle tickets record mid-vs-fill on real
positions); statement-level reconciliation awaits statement ingestion; OER
table starts empty by design.
