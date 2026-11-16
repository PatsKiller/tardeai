'use strict'
// Production-SHAPED synthetic fixtures for the seven Portfolio routes. Shapes were derived by reading
// src/api/readers.ts, the page adapters (adapter.ts, performanceAdapter.ts, incomeAdapter.ts, homeAdapter.ts)
// and the backend producers. Every value is invented: QZ* tickers, SYN_* account keys, made-up amounts.
// Timestamps are computed from `now` at serve time so freshness rules see current clocks.

const iso = ms => new Date(ms).toISOString()

// Account keys are what the wire carries; labels are what a person may read. SYN_* must never be visible.
const ACCOUNTS = {
  taxable: { key: 'SYN_taxable', label: 'Synthetic Taxable' },
  roth: { key: 'SYN_roth', label: 'Synthetic Roth' },          // rows say SYN_roth ...
  rothAlias: { key: 'SYN_roth_ira' },                           // ... scope list / reconciliation say SYN_roth_ira (alias)
  idle: { key: 'SYN_idle', label: 'Synthetic Idle' },           // in scope list, no rows
  missing: { key: 'SYN_nodata', label: 'Synthetic NoPerf' },    // holds positions, no performance result
}
const SMALL = Array.from({ length: 12 }, (_, i) => 'QZS' + String.fromCharCode(65 + i))
// Raw keys the visible text must never contain (case-insensitive).
const RAW_KEY_RE = /\bsyn_[a-z0-9_]+/i

const HOLDINGS_COLUMNS = ['Security', 'Account', 'Shares (served)', 'Price (served)', 'Average cost (adapted)', 'Value (served)']

function holdingsBody(now) {
  const at = ms => iso(now - ms)
  const active = { state: 'PROTECTED', stop: 90, source: 'synthetic stop read', as_of: at(600e3), reason: 'Resting stop recorded and confirmed' }
  const pending = { state: 'PROTECTED', stop: null, source: 'synthetic stop read', as_of: at(600e3), reason: 'Recorded · pending activation' }
  const stale = { state: 'PROTECTED', stop: 88, source: 'synthetic stop read', as_of: at(9 * 86400e3), reason: 'Resting stop recorded' }
  const gap = { state: 'GAP', cause: 'Not Protected', reason: 'No stop reported' }
  const rows = []
  const add = (symbol, acct, label, o) => rows.push({
    symbol, name: 'Synthetic ' + symbol, account_key: acct, account_label: label, shares: 10, price: 100,
    market_value: 1000, cost_basis_total: 800, avg_cost: 80, cost_basis_source: 'synthetic lots', gain_loss: 200,
    gain_loss_pct: 25, portfolio_pct: 1, day_change: 5, day_change_pct: 0.5, asset_type: 'EQUITY', sector: 'Technology',
    industry: 'Software', pe: 22, forward_pe: 19, eps_ttm: 4.5, eps_next_y: 5.1, peg: 1.4, beta: 1.1, rsi: 55,
    yield_pct: 0.6, market_cap_b: 120, market_session: 'regular', price_as_of: at(60e3),
    protection_state: o.protection ? o.protection.state : null, protection_stale: o.protection_stale,
    ...o,
  })
  const T = ACCOUNTS.taxable, R = ACCOUNTS.roth
  add('QZBIG', T.key, T.label, { market_value: 5000, shares: 50, cost_basis_total: 4000, avg_cost: 80, gain_loss: 1000, protection: active, protection_stale: false, portfolio_pct: 20 })
  add('QZBIG', R.key, R.label, { market_value: 3000, shares: 30, cost_basis_total: 2400, avg_cost: 80, gain_loss: 600, protection: pending, protection_stale: false, portfolio_pct: 12 })
  add('QZDUP', T.key, T.label, { market_value: 2000, shares: 20, sector: 'Healthcare', industry: 'Biotech', protection: stale, protection_stale: true, portfolio_pct: 8 })
  add('QZDUP', R.key, R.label, { market_value: 1500, shares: 15, sector: 'Healthcare', industry: 'Biotech', protection: gap, portfolio_pct: 6 })
  add('QZGAP', T.key, T.label, { market_value: 1200, sector: 'Energy', industry: 'Pipelines', protection: gap, portfolio_pct: 5 })
  add('QZUNK', R.key, R.label, { market_value: 900, sector: 'Financials', industry: 'Banks', protection: { state: 'UNKNOWN', cause: 'No Stop Read' }, portfolio_pct: 3.5 })
  // >100% ownership row: institutional ownership above 100% is a real provider artefact, shown, never clamped.
  add('QZOWN', T.key, T.label, { market_value: 1100, sector: 'Industrials', industry: 'Machinery', inst_own_pct: 112.4, insider_own_pct: 3.2, protection: active, protection_stale: false, portfolio_pct: 4.4 })
  // Fund with no company P/E.
  add('QZFND', R.key, R.label, { market_value: 2500, asset_type: 'ETF', sector: null, industry: null, pe: null, forward_pe: null, eps_ttm: null, eps_next_y: null, peg: null, protection: active, protection_stale: false, portfolio_pct: 10 })
  // Collapsed small rows (< $100 floor, no material loss).
  SMALL.forEach((s, i) => add(s, i % 2 ? R.key : T.key, i % 2 ? R.label : T.label, { market_value: 10 + i, shares: 1, price: 10 + i, cost_basis_total: 9 + i, avg_cost: 9 + i, gain_loss: 1, gain_loss_pct: 5, portfolio_pct: 0.04, sector: i % 3 ? 'Technology' : 'Materials', protection: i % 4 ? gap : stale, protection_stale: i % 4 ? undefined : true }))
  // Small row with a material loss stays above the fold.
  add('QZPIN', T.key, T.label, { market_value: 40, shares: 4, price: 10, cost_basis_total: 190, avg_cost: 47.5, gain_loss: -150, gain_loss_pct: -78.9, portfolio_pct: 0.1, protection: gap })
  // Unpriced row: unknown, never zero.
  add('QZNOPX', R.key, R.label, { market_value: null, price: null, gain_loss: null, gain_loss_pct: null, day_change: null, day_change_pct: null, portfolio_pct: null, protection: { state: 'UNKNOWN', cause: 'No Stop Read' } })
  // Cash sweep.
  add('QZCASH', T.key, T.label, { name: 'Synthetic sweep', is_cash: true, asset_type: 'CASH', market_value: 700, price: 1, shares: 700, cost_basis_total: 700, avg_cost: 1, gain_loss: 0, gain_loss_pct: 0, day_change: 0, day_change_pct: 0, portfolio_pct: 2.8, sector: null, industry: null, pe: null, forward_pe: null, eps_ttm: null, eps_next_y: null, peg: null, beta: null, rsi: null, yield_pct: null, market_cap_b: null, protection: null, protection_state: null })

  const nonCash = rows.filter(r => !r.is_cash)
  const under = nonCash.filter(r => r.market_value !== null && r.market_value < 100).length
  return {
    ok: true,
    data: {
      holdings: rows,
      truth: { as_of: at(60e3), stale: false, gap: null },
      freshness: { status: 'FRESH', clock: 'quote', clock_label: 'QUOTE', as_of: at(60e3), age_s: 60, limit_s: 1800, limit_source: 'synthetic registry', window: 'open', rule: 'synthetic' },
      clock_provenance: {
        positions: { as_of: at(120e3), source_field: 'positions_as_of' },
        position_list: { as_of: at(90e3), source_field: 'built_at' },
        quote: { as_of: at(60e3), source_field: 'last_repriced' },
        valuation: { as_of: at(100e3), source_field: 'valuation_as_of' },
        stops: { as_of: at(600e3), source_field: 'stops_read_at' },
        rendered_at: { as_of: at(1e3), source_field: 'rendered_at' },
        day_pnl: { status: 'KNOWN', as_of: at(60e3) },
      },
      scope_coverage: {
        min_position_usd: 100,
        rows_read: rows.length,
        scopes: { 'holdings.all_rows': rows.length, 'holdings.non_cash': nonCash.length, 'holdings.cash': 1, 'holdings.non_cash_over_100': nonCash.length - under, 'holdings.held_under_100': under },
        excluded: [{ reason: 'under notional floor', count: under, scope: 'holdings.non_cash' }],
        priceable: { row_count: nonCash.length + 2, measured_rows: nonCash.length - 1 },
        scope: { accounts: [ACCOUNTS.taxable.key, ACCOUNTS.rothAlias.key, ACCOUNTS.idle.key] },
      },
      reconciliation: { accounts: [
        { account: ACCOUNTS.taxable.key, end_equity: { value_usd: 11000, as_of: at(120e3), source: 'synthetic' } },
        { account: ACCOUNTS.roth.key, end_equity: { value_usd: 8000, as_of: at(120e3), source: 'synthetic' } },
      ] },
      measures: { as_of: at(120e3), measures: {
        account_value: { label: 'Account value', status: 'MEASURED', value: 19000, basis: 'synthetic stored account totals', as_of: at(120e3) },
        price_move_estimate: { status: 'UNKNOWN', gap: { reason: 'synthetic: not measured' } },
      } },
      metrics: [],
      evidence: { portfolio: { clocks: { stale_after_hours: 0.5 } } },
    },
    _swr: { age_s: 30, stale: false },
  }
}

function overviewBody(now) {
  return { ok: true, data: {
    account_labels: { [ACCOUNTS.taxable.key]: ACCOUNTS.taxable.label, [ACCOUNTS.roth.key]: ACCOUNTS.roth.label, [ACCOUNTS.missing.key]: ACCOUNTS.missing.label },
    portfolio_total: { value: 19000, as_of: iso(now - 120e3) },
    clock_provenance: { quote: { as_of: iso(now - 60e3) } },
    market_session: { latest_open_session: iso(now).slice(0, 10) },
  } }
}

function performanceBody(now) {
  const at = ms => iso(now - ms)
  const cell = (change, pct, o = {}) => ({
    change, change_pct: pct, nav_change: change, nav_change_pct: pct, start_value: 10000, end_value: 10000 + change,
    start_date: '2026-01-02', end_date: iso(now).slice(0, 10), source: 'snapshot_pair', quality: 'ok', flags: [],
    snapshot_replaced: false, coverage: { included: 2, total: 3 }, observation_clock: { as_of: at(3600e3), status: 'KNOWN', freshness: 'fresh' }, ...o,
  })
  const periods = p => ({ '1D': cell(120 * p, 0.6 * p), '1W': cell(300 * p, 1.5 * p), '1M': cell(500 * p, 2.5 * p), '3M': cell(900 * p, 4.4 * p), '6M': cell(1400 * p, 6.9 * p), YTD: cell(2100 * p, 10.1 * p), '1Y': cell(3000 * p, 14.2 * p) })
  const household = periods(1)
  for (const k of Object.keys(household)) Object.assign(household[k], { display_change: household[k].change - 50, display_change_pct: household[k].change_pct - 0.2, display_label: 'Synthetic estimate', nav_is_not_market_only: true })
  return { ok: true, data: {
    status: 'OK',
    accounts: {
      [ACCOUNTS.taxable.key]: { eligibility: { status: 'eligible', source: 'synthetic registry' }, periods: periods(0.6) },
      [ACCOUNTS.roth.key]: { periods: periods(0.4) }, // eligibility not served -> withheld, labelled unknown
    },
    periods: household,
    today_pnl: {
      observation_clock: { as_of: at(3600e3), status: 'KNOWN', freshness: 'fresh' },
      mark_session_date: iso(now).slice(0, 10), mark_batch_at: at(60e3), batch_built_at: at(90e3),
      // Holding accounts: taxable, roth and one with NO performance row.
      stored_row_evidence: { source_values: [{ account_id: ACCOUNTS.taxable.key }, { account_id: ACCOUNTS.roth.key }, { account_id: ACCOUNTS.missing.key }] },
    },
    market_session: { latest_open_session: iso(now).slice(0, 10) },
    clock_provenance: { quote: { as_of: at(60e3), status: 'KNOWN' }, valuation: { as_of: at(90e3), status: 'KNOWN' } },
    ytd_pin: { pin_date: '2026-01-02', end_snapshot: 'synthetic-snap', source: 'synthetic', created_at: at(86400e3) },
  } }
}

// Income: months are placed by observed ex-date months; one payer has none (unplaced) and one has no frequency.
function dividendsBody(now) {
  const T = ACCOUNTS.taxable.key, R = ACCOUNTS.roth.key
  const payers = [
    { account: T, symbol: 'QZDIVQ', yield_pct: 3.1, annual_income: 61.99, monthly_amort: 5.17, frequency: 'Quarterly', months: [1, 4, 7, 10] },
    { account: T, symbol: 'QZDIVM', yield_pct: 5.2, annual_income: 120.0, monthly_amort: 10.0, frequency: 'Monthly', months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] },
    { account: R, symbol: 'QZDIVQ', yield_pct: 3.1, annual_income: 41.0, monthly_amort: 3.42, frequency: 'Quarterly', months: [2, 5, 8, 11] },
    { account: 'SYN_other', symbol: 'QZDIVX', yield_pct: 2.0, annual_income: 33.5, monthly_amort: 2.79, frequency: 'Annual', months: [6] },
    { account: R, symbol: 'QZUNPL', yield_pct: 1.5, annual_income: 24.0, monthly_amort: 2.0, frequency: 'Unknown', months: [] },
    { symbol: 'QZNOACC', yield_pct: 1.0, annual_income: 10.0, monthly_amort: 0.83, frequency: 'Semiannual', months: [3, 9] },
  ]
  const round2 = v => Math.round(v * 100) / 100
  const monthly = Array.from({ length: 12 }, (_, i) => ({ month: i + 1, month_name: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][i], total: 0, symbols: [] }))
  for (const p of payers) for (const m of p.months) { const row = monthly[m - 1]; row.total = round2(row.total + round2(p.annual_income / p.months.length)); if (!row.symbols.includes(p.symbol)) row.symbols.push(p.symbol) }
  const total = round2(payers.reduce((a, p) => a + p.annual_income, 0))
  return { ok: true, data: {
    has_data: true, last_updated: iso(now - 7200e3).slice(0, 19), account_attribution: 'holdings_mv_share',
    total_annual: total, monthly_average: round2(total / 12), payers, monthly_summary: monthly, monthly_summary_basis: 'observed ex-date months',
    ex_div_alerts: [{ symbol: 'QZDIVM', ex_date: '2026-12-10', pay_date: '2026-12-28', amount: 0.83, total_income: 10.0 }],
    unplaced: [{ symbol: 'QZUNPL' }], unplaced_annual: 24.0,
    account_labels: { [T]: ACCOUNTS.taxable.label, [R]: ACCOUNTS.roth.label, SYN_other: 'SYN_OTHER' },
    // registry names are shown; a derived label (the key re-cased) is shown as a stable reference instead.
    account_label_source: { [T]: 'registry', [R]: 'registry', SYN_other: 'derived' },
  } }
}

function headerBody(now, pollAfterS = 60) {
  return { poll_after_s: pollAfterS, as_of: iso(now), session: { key: 'regular' }, cells: {} }
}

// Every endpoint the five live Portfolio routes (and the shell) read. Anything else is reported as unfixtured.
const ENDPOINTS = {
  '/api/v2/wealth/operating-header': headerBody,
  '/api/v2/portfolio/holdings': holdingsBody,
  '/api/v2/portfolio/performance': performanceBody,
  '/api/v2/overview': overviewBody,
  '/api/v2/dividends': dividendsBody,
}

// Counts derived from the fixture (not hard-coded in the cases) so a fixture edit cannot silently desync them.
function expectations(now = Date.now()) {
  const rows = holdingsBody(now).data.holdings
  const cls = r => {
    if (r.is_cash) return 'n/a'
    const p = r.protection
    if (!p) return 'unknown'
    if (p.state === 'GAP') return 'gap'
    if (p.state !== 'PROTECTED') return 'unknown'
    const pend = /pending|activation/i.test((p.reason || ''))
    const dated = p.as_of && Number.isFinite(Date.parse(p.as_of))
    if (r.protection_stale === true || !dated || r.protection_stale !== false) return pend ? 'pending' : 'stale'
    if (pend || !(p.stop > 0)) return 'pending'
    return 'active'
  }
  const by = {}
  for (const r of rows) by[cls(r)] = (by[cls(r)] || 0) + 1
  return { rows: rows.length, byProtection: by, rothRows: rows.filter(r => r.account_key === ACCOUNTS.roth.key).length }
}

module.exports = { ACCOUNTS, SMALL, RAW_KEY_RE, HOLDINGS_COLUMNS, ENDPOINTS, holdingsBody, overviewBody, performanceBody, dividendsBody, headerBody, expectations, iso }
