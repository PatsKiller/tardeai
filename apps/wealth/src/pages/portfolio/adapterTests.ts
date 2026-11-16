// Adapter tests — plain node, no framework, no jsdom (adapter.ts has no React).
//
//   tsc --module commonjs adapterTests.ts && node adapterTests.js
//
// Every payload here is SYNTHETIC (acct_a/acct_b, SYNX/EXMP, round numbers). The planted payloads are the point:
// each C-rule is asserted against a payload that would fool the naive mapping, so a regression shows up as a
// named failure rather than as a plausible-looking book. `run()` exits non-zero on the first failure count.

import { createClient } from '../../api/client'
import type { Envelope } from '../../api/client'
import { READERS, specFor } from '../../api/readers'
import { adaptHoldings } from './adapter'
import type { HoldingsBook } from './contract'
import { detailFields, detailHeading, detailSections } from './detail'
import { lastKnownSentence, notCurrent } from './format'
import { HOLDINGS_PATH, holdingsProps } from './liveProps'

const NOW = Date.parse('2026-11-15T00:30:00Z')
let failures = 0
const fails: string[] = []

function check(name: string, cond: boolean, detail = ''): void {
  if (!cond) {
    failures += 1
    fails.push(`${name}${detail ? ` — ${detail}` : ''}`)
  }
}

function eq<T>(name: string, got: T, want: T): void {
  check(name, Object.is(got, want), `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`)
}

/** The `data` block of a synthetic wire, shaped like the served payload (field names only; values invented). */
function wireData(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    count: 5,
    holdings: [row({ symbol: 'SYNX' }), row({ symbol: 'EXMP2', market_value: 25.0 }), row({ symbol: 'ZERO', market_value: 0 }), row({ symbol: 'UNPRICED', market_value: null, price: null }), row({ symbol: 'CASH', is_cash: true, asset_type: 'CASH', protection_state: 'EXEMPT', market_value: 900.0, price: 1.0 })],
    as_of: '2026-11-14T19:45:01-05:00',
    truth: { source: 'synthetic', as_of: '2026-11-14T19:45:01-05:00', stale: false, gap: null },
    clock_provenance: {
      positions: { source_field: 'holdings[].position_clock', as_of: '2026-11-15T00:30:04.728689Z', status: 'KNOWN', mixed: true, unknown_rows: 0 },
      position_list: { source_field: 'positions_built_at', as_of: '2026-11-13T15:24:05.766599+00:00', gap: null },
      valuation: { source_field: 'generated_at', as_of: '2026-11-15T00:29:07.779965+00:00', gap: null },
      quote: { source_field: 'last_repriced', as_of: '2026-11-14T19:45:01-05:00', gap: null },
      day_pnl: { source_field: 'holdings[].day_change', as_of: null, status: 'UNKNOWN', gap: { reason: 'stored day_change has no declared per-row observation clock' } },
    },
    scope_coverage: {
      min_position_usd: 100.0,
      scopes: {
        'holdings.all_rows': 5, 'holdings.non_cash': 4, 'holdings.cash': 1,
        'holdings.non_cash_over_100': 2, 'holdings.held_under_100': 2, 'holdings.unpriced': 1,
      },
      rows_read: 3,
      rendered_rows: 5,
      excluded: [{ reason: 'priced under $100: listed, not counted', count: 2, scope: 'holdings.held_under_100' }],
      priceable: { row_count: 6, measured_rows: 3, unknown_rows: 1, unknown: [] },
      filtered_rows: null,
      findings: [],
    },
    measures: {
      as_of: '2026-11-15T00:30:07.484281Z',
      measures: {
        account_value: { label: 'Account value', basis: 'broker_positions_store', value: 1_000_000.0, status: 'MEASURED', as_of: '2026-11-15T00:30:07.484281Z', gap: null },
        price_move_estimate: { label: 'Estimated price movement', definition: 'sum of per-position moves', basis: 'broker_positions_store', value: -1_000.0, status: 'MEASURED', as_of: '2026-11-15T00:30:07.484281Z', gap: null },
        account_value_change_1d: { label: 'Change since prior close', definition: 'ending − starting', basis: 'broker_positions_store', value: -1_000.0, status: 'MEASURED', start: { equity_usd: 1_001_000.0, as_of: '2026-11-13T23:30:05Z' }, end: { equity_usd: 1_000_000.0, as_of: '2026-11-15T00:30:07.484281Z' }, gap: null },
        verified_daily_pnl: { label: 'Verified daily P&L', definition: 'matched snapshots', value: null, status: 'UNKNOWN', as_of: null, gap: { reason: 'no stored signed reconciliation: the verified label stays UNKNOWN' } },
      },
    },
    metrics: [
      { metric_id: 'portfolio.account_value', verified: false, receipt: null },
      { metric_id: 'portfolio.price_move_estimate', verified: false, receipt: null },
      { metric_id: 'portfolio.account_value_change_1d', verified: false, receipt: null },
      { metric_id: 'portfolio.verified_daily_pnl', verified: false, receipt: null },
    ],
    reconciliation: {
      accounts: [
        { account: 'acct_a', end_equity: { value_usd: 600_000.0, source: 'the positions store’s broker marks' } },
        { account: 'acct_b', end_equity: { value_usd: 400_000.0, source: 'the positions store’s broker marks' } },
      ],
    },
    evidence: { portfolio: { clocks: { stale_after_hours: 0.5 } } },
    stops_read: { stale: false, status: 'READ' },
    ...over,
  }
}

/** The full response body: `data` is the book, `_swr` sits BESIDE it (the shape the route serves). */
function wire(dataOver: Record<string, unknown> = {}, rootOver: Record<string, unknown> = {}): Record<string, unknown> {
  return { ok: true, data: wireData(dataOver), _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 12, stale: false }, ...rootOver }
}

function row(over: Record<string, unknown>): Record<string, unknown> {
  return {
    symbol: 'SYNX', name: 'Synth Corp', account: 'acct_a', account_key: 'acct_a', account_label: 'Acct A',
    is_cash: false, asset_type: 'EQUITY', shares: 100, price: 150.0, price_as_of: '2026-11-14T19:45:01-05:00',
    market_value: 15_000.0, portfolio_pct: 1.5, avg_cost: 120.0, cost_basis_source: 'broker_avg_price',
    cost_basis_total: 12_000.0, gain_loss: 3_000.0, gain_loss_pct: 25.0, day_change: 12.0, day_change_pct: 0.08,
    market_cap_b: 2_500.0, yield_pct: null, market_session: null, protection_state: 'GAP', protection: { state: 'GAP', source: 'stops', as_of: '2026-11-14T01:55:11Z', cause: 'Not Protected', reason: 'no resting stop', counted: false },
    pe: 18.5, forward_pe: 16.2, eps_ttm: 8.1, eps_next_y: 9.3, peg: 1.4, beta: 1.15,
    sector: 'Synthetic tech', industry: 'Synthetic widgets', perf_ytd_pct: 12.3, rsi: 58.4,
    sma20_pct: 1.7, sma50_pct: 3.1, sma200_pct: 9.9, week52_high_pct: 4.4,
    short_float_pct: 2.2, insider_own_pct: 1.1, inst_own_pct: 77.7, analyst_rating: 'buy',
    ...over,
  }
}

function book(dataOver: Record<string, unknown> = {}, rootOver: Record<string, unknown> = {}): HoldingsBook {
  const r = adaptHoldings(wire(dataOver, rootOver))
  if (r.book === null) throw new Error(`adapter refused a payload the test expected to read: ${r.error}`)
  return r.book
}

// ---- C3: the population's two numbers, and the population the wire calls "excluded" -------------------------
{
  const b = book()
  // Audit 2026-11-16 (A): the read is rows_read; priceable.row_count is the account-value measure's own
  // population and is never subtracted from the read.
  eq('A readRows comes from rows_read', b.population.readRows, 3)
  eq('C3 renderedRows is the rows actually rendered', b.population.renderedRows, 5)
  eq('A measure population keeps its own count', b.population.measurePopulation?.rowCount, 6)
  eq('A measure difference is cross-population', b.population.measurePopulation?.differenceFromRead, 3)
  eq('A completeness is unverified until a producer receipt', b.population.completeness, 'BROKER_COMPLETENESS_UNVERIFIED')
  // The wire's scope_coverage.excluded is the under-floor population — listed, not omitted.
  eq('C3 listed-not-counted keeps its count', b.population.listedNotCounted[0]?.count, 2)
  eq('C3 listed-not-counted keeps its scope', b.population.listedNotCounted[0]?.scope, 'holdings.held_under_100')
  // rows_read 3 < rendered 5: no omission can exist; the mismatch is reported as coverage, never as "omitted".
  eq('A no omission when read <= rendered', b.population.excluded.length, 0)
}
{
  // Same-population gap: rows_read 7 and 5 rendered → 2 omitted, rule stated as unknown.
  const sc = wireData().scope_coverage as Record<string, unknown>
  const g = book({ scope_coverage: { ...sc, rows_read: 7, priceable: { row_count: 40, measured_rows: 30 } } })
  eq('A omission = rows_read − rendered', g.population.excluded[0]?.count, 2)
  check('A omission rule says the producer does not state it', /no rule/i.test(g.population.excluded[0]?.rule ?? ''))
  // The measure population (40) never inflates the omission.
  eq('A measure count does not become an omission', g.population.excluded.reduce((t, e) => t + e.count, 0), 2)
  // Alias normalization: a scope key that extends a row key resolves to it; an unmatched key is reported.
  const aliased = book({ scope_coverage: { ...sc, scope: { accounts: ['acct_a_ira', 'acct_zz'] } } })
  eq('A alias scope key resolves to the row key', aliased.population.aliasedAccounts[0]?.rowKey, 'acct_a')
  eq('A unmatched scope account is reported', aliased.population.scopeAccountsWithoutRows.join(','), 'acct_zz')
}
{
  const b = book()
  // C4: the counts add up against the rows the adapter emitted.
  eq('C4 allRows matches the listed rows', b.counts.allRows, 5)
  eq('C4 cash count', b.counts.cash, 1)
  eq('C4 non-cash count', b.counts.nonCash, 4)
  eq('C2 under-floor count is the producer’s', b.counts.heldUnderFloor, 2)
  eq('C2 over-floor count is the producer’s', b.counts.nonCashOverFloor, 2)
  eq('floor is the producer’s', b.population.floorUsd, 100)
}

// ---- C2: the floor flag is derived once, and unknown is not under --------------------------------------------
{
  const b = book()
  const synx = b.rows.find(r => r.symbol === 'SYNX')!
  const cheap = b.rows.find(r => r.symbol === 'EXMP2')!
  const unpriced = b.rows.find(r => r.symbol === 'UNPRICED')!
  const zero = b.rows.find(r => r.symbol === 'ZERO')!
  eq('C2 above the floor is not below it', synx.belowFloor, false)
  eq('C2 below the floor is flagged', cheap.belowFloor, true)
  eq('C2 an unpriced row is never below the floor', unpriced.belowFloor, false)
  eq('C2 an unpriced row keeps a null value, not $0.00', unpriced.marketValue, null)
  eq('C2 a zero-value security is worthless', zero.worthless, true)
  eq('C2 a zero-value security is a fact, not an absence', zero.marketValue, 0)
  // No floor served → nothing can be below it, and the adapter must not invent 0 or 100.
  const noFloor = book({ scope_coverage: { ...(wireData().scope_coverage as Record<string, unknown>), min_position_usd: null } })
  eq('C2 no floor served → no row is below it', noFloor.rows.some(r => r.belowFloor), false)
  eq('C2 no floor served → floorUsd is null', noFloor.population.floorUsd, null)
}

// ---- C1: the measures are a JOIN, and MEASURED is not VERIFIED ----------------------------------------------
{
  const b = book()
  const av = b.measures.find(m => m.id === 'account_value')!
  eq('C1 four measures', b.measures.length, 4)
  eq('C1 measured-carried value', av.valueUsd, 1_000_000)
  eq('C1 verified comes from metrics[]', av.verified, false)
  eq('C1 no receipt invented', av.receiptId, null)
  check('C1 the reason says measured-not-verified', /not verified/i.test(av.reason))
  // C1.2: account_value publishes no definition — the basis is quoted instead.
  eq('C1.2 definition falls back to basis', av.definition, 'broker_positions_store')
  // C1.2: change_1d's clock is end.as_of, not the block's as_of.
  const ch = b.measures.find(m => m.id === 'account_value_change_1d')!
  eq('C1.2 change_1d clock is end.as_of', ch.asOf, '2026-11-15T00:30:07.484281Z')
  // C1.2: verified_daily_pnl's reason comes from gap.reason and its status stays UNKNOWN.
  const pnl = b.measures.find(m => m.id === 'verified_daily_pnl')!
  eq('C1.1 verified_daily_pnl stays UNKNOWN', pnl.status, 'UNKNOWN')
  eq('C1.1 UNKNOWN has no value', pnl.valueUsd, null)
  eq('C1.1 UNKNOWN has no clock', pnl.asOf, null)
  check('C1.2 UNKNOWN reason comes from gap.reason', /UNKNOWN/.test(pnl.reason))
  // The contract's rule, applied to the adapter's own output: verified ⇒ receipt; receipt ⇒ verified.
  for (const m of b.measures) {
    check(`C1 integrity: ${m.id} verified without receipt`, !(m.verified && m.receiptId === null))
    check(`C1 integrity: ${m.id} receipt without verified`, !(!m.verified && m.receiptId !== null))
  }
}

// ---- C1 planted: a verified measure with no receipt must not be silently "measured, not verified" -----------
{
  const planted = wire({ metrics: [{ metric_id: 'portfolio.account_value', verified: true, receipt: null }] })
  const b = adaptHoldings(planted).book!
  const av = b.measures.find(m => m.id === 'account_value')!
  eq('C1 planted verified carries through', av.verified, true)
  eq('C1 planted missing receipt stays null', av.receiptId, null)
  // The adapter must NOT repair the contradiction; the invariant is what rejects it.
  check('C1 planted contradiction is visible (verified && no receipt)', av.verified && av.receiptId === null)
  const withReceipt = adaptHoldings(wire({ metrics: [{ metric_id: 'portfolio.account_value', verified: true, receipt: 'rcpt-a' }] })).book!
  const av2 = withReceipt.measures.find(m => m.id === 'account_value')!
  eq('C1 a served receipt is carried', av2.receiptId, 'rcpt-a')
  eq('C1 a served receipt implies verified', av2.verified, true)
  // A missing metrics[] block is not "verified false with a reason": it is no evidence at all, and still false.
  const noMetrics = adaptHoldings(wire({ metrics: [] })).book!
  eq('C1 no metrics block → verified false', noMetrics.measures.every(m => m.verified === false), true)
  eq('C1 no metrics block → no receipts', noMetrics.measures.every(m => m.receiptId === null), true)
}

// ---- A2: the clocks, including the build clock that must stay identified -------------------------------------
{
  const b = book()
  const roles = b.clocks.map(c => c.role)
  eq('A2 five declared clocks', roles.join(','), 'POSITIONS,BUILD,QUOTE,VALUATION,STOPS')
  const build = b.clocks.find(c => c.role === 'BUILD')!
  eq('A2 the build clock is the position_list clock', build.at, '2026-11-13T15:24:05.766599+00:00')
  eq('A2 the build clock is flagged', build.isBuildClock, true)
  eq('A2 only the build clock is build', b.clocks.filter(c => c.isBuildClock).length, 1)
  const pos = b.clocks.find(c => c.role === 'POSITIONS')!
  eq('A2 the positions clock carries mixed', pos.mixed, true)
  eq('A2 the positions clock carries unknown rows', pos.unknownRows, 0)
  // The book's as-of is `truth.as_of`, and on this wire that instant is the QUOTE clock (F-1/R2): the label follows
  // the VALUE — the declared clock whose instant equals it — never a literal role printed over whichever field
  // happened to be readable, and never the verdict's governing clock.
  eq('A2 book asOf is truth.as_of', b.asOf, '2026-11-14T19:45:01-05:00')
  eq('A2 book asOfClock follows the value (QUOTE, not a POSITIONS literal)', b.asOfClock, 'QUOTE')
  // Day change is a declared UNKNOWN clock whose reason is the producer's.
  eq('A2 day-change clock stays UNKNOWN', b.dayPnl.status, 'UNKNOWN')
  eq('A2 day-change clock has no invented instant', b.dayPnl.at, null)
  check('A2 day-change reason is the producer’s', /day_change/.test(b.dayPnl.reason))
}

// ---- F-1: the clock label follows the field, and the served fundamentals are carried -------------------------
{
  // Without truth.as_of the positions aggregate is named as such — the fallback is labelled, never silent.
  const noTruth = book({ truth: { source: 'synthetic', stale: false, gap: null } })
  eq('F-1 no truth.as_of → POSITIONS', noTruth.asOfClock, 'POSITIONS')
  eq('F-1 positions as_of is the declared aggregate', noTruth.asOf, '2026-11-15T00:30:04.728689Z')
  // With no clock provenance at all the role is UNDECLARED, not a guess.
  const bare = adaptHoldings({ data: { holdings: [row({})], as_of: '2026-11-14T19:45:01-05:00' } })
  eq('F-1 an unlabelled as_of is UNDECLARED', bare.book?.asOfClock, 'UNDECLARED')

  const r = book().rows[0]
  const f = r.fundamentals
  eq('fund trailing P/E is the wire pe', f?.peTrailing, 18.5)
  eq('fund forward P/E is the wire forward_pe', f?.peForward, 16.2)
  eq('fund EPS TTM as served', f?.epsTtm, 8.1)
  eq('fund EPS next year as served', f?.epsNextY, 9.3)
  eq('fund PEG as served', f?.peg, 1.4)
  eq('fund beta as served', f?.beta, 1.15)
  eq('fund sector as served', f?.sector, 'Synthetic tech')
  eq('fund industry as served', f?.industry, 'Synthetic widgets')
  eq('fund YTD as served', f?.perfYtdPct, 12.3)
  eq('fund RSI as served', f?.rsi, 58.4)
  eq('fund SMA20 as served', f?.sma20Pct, 1.7)
  eq('fund SMA50 as served', f?.sma50Pct, 3.1)
  eq('fund SMA200 as served', f?.sma200Pct, 9.9)
  eq('fund 52-week high distance as served', f?.week52HighPct, 4.4)
  eq('fund short float as served', f?.shortFloatPct, 2.2)
  eq('fund insider ownership as served', f?.insiderOwnPct, 1.1)
  eq('fund institutional ownership as served', f?.instOwnPct, 77.7)
  eq('fund analyst rating as served', f?.analystRating, 'buy')
  // A block the enrichment never reached is null, not a row of zeroes the page would have to disbelieve.
  const nulls = {
    pe: null, forward_pe: null, eps_ttm: null, eps_next_y: null, peg: null, beta: null, sector: null, industry: null,
    perf_ytd_pct: null, rsi: null, sma20_pct: null, sma50_pct: null, sma200_pct: null, week52_high_pct: null,
    short_float_pct: null, insider_own_pct: null, inst_own_pct: null, analyst_rating: null,
  }
  eq('fund an all-null block is null', book({ holdings: [row({ symbol: 'BARE', ...nulls })] }).rows[0]?.fundamentals, null)
  // A served zero stays a served zero: it is a value, not an absence.
  eq('fund a served 0 PEG stays 0', book({ holdings: [row({ symbol: 'ZPEG', peg: 0, sector: null, industry: null, pe: null, forward_pe: null, eps_ttm: null, eps_next_y: null, beta: null, perf_ytd_pct: null, rsi: null, sma20_pct: null, sma50_pct: null, sma200_pct: null, week52_high_pct: null, short_float_pct: null, insider_own_pct: null, inst_own_pct: null, analyst_rating: null })] }).rows[0]?.fundamentals?.peg, 0)
}

// ---- Session: one row's label is not the book's session ------------------------------------------------------
{
  const b = book()
  eq('session UNKNOWN when no row labels it', b.session.status, 'UNKNOWN')
  check('session reason counts the rows', /(0 of 5|no row declares a market session \(5 rows\))/.test(b.session.reason), b.session.reason)
  const one = book({ holdings: (wireData().holdings as Record<string, unknown>[]).map((h, i) => (i === 0 ? { ...h, market_session: 'after_hours' } : h)) })
  eq('session UNKNOWN when ONE row labels it', one.session.status, 'UNKNOWN')
  check('session reason says one row is not the book', /1 of 5/.test(one.session.reason), one.session.reason)
  const all = book({ holdings: (wireData().holdings as Record<string, unknown>[]).map(h => ({ ...h, market_session: 'regular' })) })
  eq('session KNOWN only when every row agrees', all.session.status, 'KNOWN')
  eq('session phase is the agreed label', all.session.phase, 'regular')
  eq('session names its source', all.session.source, 'holdings[].market_session')
}

// ---- Rows: identity, units, cash, protection, and the two serveds-is-not-the-same traps ----------------------
{
  const b = book()
  const synx = b.rows.find(r => r.symbol === 'SYNX')!
  eq('row key is account:symbol-shaped', synx.accountKey, 'acct_a')
  eq('portfolioPct is kept as a percent', synx.portfolioPct, 1.5)
  eq('market cap stays in millions', synx.marketCapB, 2_500)
  eq('price clock is the served string, verbatim', synx.priceAsOf, '2026-11-14T19:45:01-05:00')
  eq('protection is mapped from the row', synx.protection?.state, 'GAP')
  eq('protection names its next step', typeof synx.protection?.nextStep, 'string')
  const cash = b.rows.find(r => r.symbol === 'CASH')!
  eq('cash row is CASH', cash.kind, 'CASH')
  eq('cash has no protection claim', cash.protection, null)
  // A 0.0 average cost with no declared basis source is "no basis served", not a $0.00 cost.
  const noBasis = book({ holdings: [{ ...row({ symbol: 'NOBASE' }), avg_cost: 0.0, cost_basis_total: 0.0, cost_basis_source: null }] })
  eq('0.0 with no source is no basis', noBasis.rows[0].avgCost, null)
  // A served total and served shares give the per-share basis the contract defines — not a shares × price guess.
  const fromTotal = book({ holdings: [{ ...row({ symbol: 'FROMTOTAL', shares: 50 }), avg_cost: 0.0, cost_basis_total: 5_000.0, cost_basis_source: null }] })
  eq('basis total / shares is the remaining basis', fromTotal.rows[0].avgCost, 100)
  // The two contract gaps: served but clockless (fib) and served but not an assessment (valuation).
  eq('fib is absent rather than given an undeclared clock', synx.fib, null)
  eq('valuation is absent rather than invented from a bare pe', synx.valuation, null)
}

// ---- Accounts: the producer's own per-account equity; never a sum of rows -----------------------------------
{
  const b = book()
  eq('accounts are served', b.accounts?.length, 2)
  eq('account total is the served equity', b.accounts?.[0].totalUsd, 600_000)
  eq('account cash is null, not 0', b.accounts?.[0].cashUsd, null)
  const none = book({ reconciliation: {} })
  eq('no totals block → accounts is null, not []', none.accounts, null)
}

// ---- Malformed payloads: refuse, never throw ----------------------------------------------------------------
{
  for (const bad of [null, undefined, 'x', 42, [], {}, { ok: false }]) {
    const r = adaptHoldings(bad)
    check(`malformed payload refuses without throwing: ${JSON.stringify(bad)}`, r.book === null && r.error !== null)
  }
  // A row without a symbol is not rendered, and the note says so.
  const b = book({ holdings: [...(wireData().holdings as Record<string, unknown>[]), { market_value: 5 }] })
  check('a symbol-less row is not rendered', b.rows.length === 5)
  check('a symbol-less row is reported in the note', /1 listed row\(s\) carried no symbol/.test(b.coverageNote), b.coverageNote)
  // No readable as_of anywhere → refuse; a book with no clock is the one thing the page must not draw.
  const noClock = adaptHoldings({ ok: true, data: { holdings: [], scope_coverage: {} } })
  check('no as_of → refuse', noClock.book === null && noClock.error !== null)
  // No _swr: freshness cannot be proven, so it is not claimed.
  const noSwr = book({}, { _swr: undefined })
  eq('no _swr → stale', noSwr.freshness.stale, true)
  check('no _swr → noted', /no _swr/.test(noSwr.coverageNote))
}

// ---- Coverage note: the numbers in it are the served numbers ------------------------------------------------
{
  const b = book()
  check('note states rows, cash and non-cash', /5 rows as served: 1 cash and 4 non-cash/.test(b.coverageNote), b.coverageNote)
  check('note states the floor population split', /2 non-cash rows at or above the 100 floor and 2 below/.test(b.coverageNote), b.coverageNote)
}

// ---- The live wiring: envelope → page props, and the reader row that decides what "current" means ------------
{
  // Nothing in this section fetches: `holdingsProps` and `specFor` are pure, and the one client call throws
  // BEFORE any request would leave the process (the heavy-reader guard).
  const spec = specFor(HOLDINGS_PATH)
  eq('reader row: path', spec.path, HOLDINGS_PATH)
  eq('reader row: heavy (its own page only)', spec.heavy, true)
  eq('reader row: producer clock', spec.clock, 'producer')
  eq('reader row: as_of from truth.as_of', spec.asOfAt, 'data.truth.as_of')
  eq('reader row: two unavailability rules', spec.unavailableWhen.length, 2)
  // The shell's registry requires every declared path under `data.`; `_swr` sits beside it, so a root rule here
  // would be rejected by shell-logic.test.mjs — the SWR verdict is read from the book instead.
  check('reader row declares no rule outside data.', spec.unavailableWhen.every(r => r.at.startsWith('data.')))
  check('reader row is in READERS itself', READERS.some(r => r.path === HOLDINGS_PATH))
  let shellRefused = false
  try {
    void createClient().get(HOLDINGS_PATH, { from: 'shell' })
  } catch {
    shellRefused = true
  }
  check('a shell read of the holdings route is refused (heavy)', shellRefused)

  const env = (over: Partial<Envelope<unknown>> = {}): Envelope<unknown> => ({
    ok: true, status: 200, data: wire(), error: null, fetchedAt: '2026-11-15T00:30:01Z',
    lastGood: null, lastGoodAt: null, lastGoodAgeSeconds: null, timedOut: false,
    spec: specFor(HOLDINGS_PATH), ...over,
  })
  const truth = (stale: boolean, gap: unknown): Record<string, unknown> => ({
    source: 'synthetic', as_of: '2026-11-14T19:45:01-05:00', stale, gap,
  })

  const l = holdingsProps(null, NOW)
  eq('no envelope yet → loading', l.loading, true)
  eq('no envelope yet → no book', l.book, null)
  eq('no envelope yet → no error', l.error, null)

  const ok = holdingsProps(env(), NOW)
  check('a current read yields a book', ok.book !== null, String(ok.error))
  eq('a current read is not loading', ok.loading, false)
  eq('a current read has no error', ok.error, null)
  eq('a current read has no notice', ok.notice, null)
  eq('the served book is LIVE', ok.book?.source, 'LIVE')
  eq('a current read keeps the served freshness verdict', ok.book?.freshness.stale, false)

  // The producer says the positions document is stale: the body exists, and it may be shown as last known only.
  const stale = holdingsProps(env({ data: wire({ truth: truth(true, null) }) }), NOW)
  check('producer stale → a book is still shown', stale.book !== null)
  eq('producer stale → the book is marked stale', stale.book?.freshness.stale, true)
  check('producer stale → the notice says not current and names the field', /Not current:.*data\.truth\.stale/.test(stale.notice ?? ''), String(stale.notice))
  check('producer stale → the book note carries the same reason', /Not current:/.test(stale.book?.coverageNote ?? ''))

  // The SWR layer says its cached body is stale. Its flag lives at the root, which a registry rule may not read,
  // so this verdict has to come from the adapted book — and it must still withdraw the claim of being current.
  const swrStale = holdingsProps(env({ data: wire({}, { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 500, stale: true } }) }), NOW)
  eq('swr stale → the book is not current', swrStale.book?.freshness.stale, true)
  // F-2/F-5: with no produced verdict, the only clock is the CACHE's, and the notice says exactly that.
  check('swr stale → the notice says the cache is what is old', /Not current: this response is 500 s old in the cache/.test(swrStale.notice ?? ''), String(swrStale.notice))
  check('swr stale → the notice never reports a producer verdict that was not served', !/freshness block reports/.test(swrStale.notice ?? ''), String(swrStale.notice))
  check('swr stale → the note carries the same reason', /in the cache/.test(swrStale.book?.coverageNote ?? ''))

  // A declared gap in the positions document fires too (null means "no gap published").
  const gap = holdingsProps(env({ data: wire({ truth: truth(false, { reason: 'synthetic gap' }) }) }), NOW)
  check('a declared truth.gap → not current', /data\.truth\.gap/.test(gap.notice ?? ''), String(gap.notice))

  // ---- R1: an absent freshness block is not aged, and is not described as one that reported --------------------
  const noSwrBook = book({}, { _swr: undefined })
  eq('R1 no _swr → ageSeconds is null, never 0', noSwrBook.freshness.ageSeconds, null)
  eq('R1 no _swr → blockPresent false', noSwrBook.freshness.blockPresent, false)
  eq('R1 no _swr → stale', noSwrBook.freshness.stale, true)
  const noticeAbsent = holdingsProps(env({ data: wire({}, { _swr: undefined }) }), NOW)
  check('R1 absent block → the notice names both absences', /carries no cache block and no produced freshness verdict/.test(noticeAbsent.notice ?? ''), String(noticeAbsent.notice))
  check('R1 absent block → the notice does NOT say a block reported staleness', !/reports this body stale/.test(noticeAbsent.notice ?? ''), String(noticeAbsent.notice))
  check('R1 absent block → no invented "age 0 s"', !/\bage 0 s\b/.test(noticeAbsent.notice ?? ''), String(noticeAbsent.notice))

  // ---- R1: a present block that serves no age is stale, and says the age is unserved ---------------------------
  const unaged = book({}, { _swr: { as_of: '2026-11-15T00:29:00Z', stale: true } })
  eq('R1 unaged block → ageSeconds is null', unaged.freshness.ageSeconds, null)
  eq('R1 unaged block → blockPresent true', unaged.freshness.blockPresent, true)
  const noticeUnaged = holdingsProps(env({ data: wire({}, { _swr: { as_of: '2026-11-15T00:29:00Z', stale: true } }) }), NOW)
  check('R1 unaged block → the notice says the age is not served', /age is not served/.test(noticeUnaged.notice ?? ''), String(noticeUnaged.notice))
  check('R1 unaged block → no invented "0 s" age', !/\b0 s\b/.test(noticeUnaged.notice ?? ''), String(noticeUnaged.notice))

  // ---- R2: a present block with NO stale verdict is stale (a missing boolean must never read as fresh) --------
  const unflagged = book({}, { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 41 } })
  eq('R2 _swr without a stale verdict → stale', unflagged.freshness.stale, true)
  eq('R2 _swr without a stale verdict → blockPresent true', unflagged.freshness.blockPresent, true)
  const noticeUnflagged = holdingsProps(env({ data: wire({}, { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 41 } }) }), NOW)
  check('R2 _swr without a stale verdict → a notice is shown', noticeUnflagged.notice !== null, String(noticeUnflagged.notice))
  eq('R2 _swr without a stale verdict → the book is not current', noticeUnflagged.book?.freshness.stale, true)

  // ---- C1 (F-2/F-3/F-5): the producer's verdict over its SOURCE clocks decides, not the cache window ----------
  {
    const verdict = (over: Record<string, unknown>) => ({
      status: 'FRESH', stale: false, clock: 'quote', clock_label: 'QUOTE', as_of: '2026-11-15T00:15:00Z',
      age_s: 900, limit_s: 900, window: 'open',
      limit_source: 'config/data_source_authority.json domains[quote_price].stale_after_hours',
      rule: 'oldest source-observation clock against its registry window', gap: null, ...over,
    })
    const fresh = book({ freshness: verdict({}) })
    eq('C1 a served FRESH verdict is carried', fresh.freshness.served?.status, 'FRESH')
    eq('C1 the served verdict carries its own limit', fresh.freshness.served?.limitSeconds, 900)
    eq('C1 asOfClock comes from the served clock role', fresh.asOfClock, 'QUOTE')
    // R2 (review 2026-11-15T040420Z): the governing clock is the one furthest past its OWN limit — usually stops
    // or positions — while truth.as_of is the QUOTE clock by construction. The label must follow the VALUE.
    const stopsGovern = book({ freshness: verdict({ clock: 'stops', clock_label: 'STOP READ', as_of: '2026-11-15T00:20:00Z' }) })
    eq('C1 R2 asOfClock follows the value it labels, not the verdict clock', stopsGovern.asOfClock, 'QUOTE')
    eq('C1 R2 the governing clock is still named by the verdict', stopsGovern.freshness.served?.clock, 'stops')

    // R5 (review 2026-11-15T040420Z): `clock_provenance.rendered_at` is the response's own render time. When the
    // wire serves it, the ledger declares it under REQUEST; an older body simply has no such clock.
    eq('C1 R5 no render clock when the wire serves none', book().clocks.some(c => c.role === 'REQUEST'), false)
    const rendered = wireData()
    ;(rendered.clock_provenance as Record<string, unknown>).rendered_at =
      { source_field: 'rendered_at', as_of: '2026-11-15T00:31:00Z', gap: null }
    const withRender = adaptHoldings(env({ data: rendered })).book!
    eq('C1 R5 the served render time is declared as REQUEST', withRender.clocks.find(c => c.role === 'REQUEST')?.at, '2026-11-15T00:31:00Z')
    eq('C1 R5 the render clock never ages the book', withRender.asOfClock, 'QUOTE')

    // A cache-stale body whose SOURCE clocks are current is current: the cache age is not the book's age (F-3).
    const cacheOld = holdingsProps(env({ data: wire({ freshness: verdict({}) },
      { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 500, stale: true } }) }), NOW)
    eq('C1 cache stale + verdict FRESH → the PAGE does not withdraw the book', cacheOld.book !== null && notCurrent(cacheOld.book.freshness), false)
    eq('C1 … while the cache fact itself is still served as what it is', cacheOld.book?.freshness.stale, true)
    eq('C1 cache stale + verdict FRESH → no not-current notice', cacheOld.notice, null)

    const staleVerdict = holdingsProps(env({ data: wire({
      freshness: verdict({ status: 'STALE', stale: true, age_s: 3600 }),
    }, { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 12, stale: false } }) }), NOW)
    eq('C1 verdict STALE → the book is not current', staleVerdict.book?.freshness.stale, true)
    check('C1 the notice names the SOURCE clock, its age and the limit applied',
      /Not current: the QUOTE clock is 60 min old, past the limit 900 s/.test(staleVerdict.notice ?? ''), String(staleVerdict.notice))
    check('C1 the notice names where the limit came from', /data_source_authority/.test(staleVerdict.notice ?? ''), String(staleVerdict.notice))
    check('C1 the notice does not blame the cache for a producer verdict', !/in the cache/.test(staleVerdict.notice ?? ''), String(staleVerdict.notice))

    const unknownVerdict = holdingsProps(env({ data: wire({
      freshness: verdict({ status: 'UNKNOWN', stale: null, clock: null, clock_label: null, as_of: null, age_s: null,
        limit_s: null, limit_source: null, gap: { reason: 'no stops observation clock is published' } }),
    }) }), NOW)
    eq('C1 UNKNOWN → the served verdict is neither fresh nor stale', unknownVerdict.book?.freshness.served?.stale, null)
    eq('C1 UNKNOWN → the book is not claimed current', unknownVerdict.book?.freshness.stale, true)
    check('C1 UNKNOWN → the notice says the verdict could not be computed, and why',
      /could not compute a freshness verdict \(no stops observation clock is published\)/.test(unknownVerdict.notice ?? ''),
      String(unknownVerdict.notice))
    // Review 2026-11-15T0509Z §5.2: the ALERT BOX said only "could not compute a verdict" while the strip and the
    // Read status notice printed the producer's reason. One sentence, two audiences — the alert carries it too.
    const alert = lastKnownSentence(unknownVerdict.book!.freshness)
    check('C1 §5.2 the last-known-good alert carries the producer\'s own reason',
      /no stops observation clock is published/.test(alert), alert)

    // Review 2026-11-15T0509Z §5.3: a withheld read stamp is a DATUM, not the book's clock. It must not fill the
    // clock's `at` slot, and it is carried under its own field so the ledger can print what was withheld.
    const cp = (stops: Record<string, unknown>) => ({
      positions: { source_field: 'holdings[].position_clock', as_of: '2026-11-15T00:30:04Z', status: 'KNOWN' },
      position_list: { source_field: 'positions_built_at', as_of: '2026-11-13T15:24:05+00:00' },
      valuation: { source_field: 'generated_at', as_of: '2026-11-15T00:29:07+00:00' },
      quote: { source_field: 'last_repriced', as_of: '2026-11-15T00:30:00Z' },
      stops: { source_field: 'stop_last_known.captured_at', ...stops },
    })
    const withheld = book({ clock_provenance: cp({ status: 'UNKNOWN', as_of: null, last_read_as_of: '2026-11-15T00:29:00Z' }) })
    const withheldStops = withheld.clocks.find(c => c.role === 'STOPS')
    eq('C1 §5.3 the withheld datum never fills the clock', withheldStops?.at, null)
    eq('C1 §5.3 … it is carried under its own field', withheldStops?.withheldAsOf, '2026-11-15T00:29:00Z')
    const standing = book({ clock_provenance: cp({ status: 'KNOWN', as_of: '2026-11-15T00:29:00Z', last_read_as_of: '2026-11-15T00:29:00Z' }) })
    eq('C1 §5.3 when the clock stands, the same datum is not repeated as withheld',
      standing.clocks.find(c => c.role === 'STOPS')?.withheldAsOf, undefined)
  }

  // ---- F-7: per-row staleness is the ROW's own clock, never the book's stop-read flag -------------------------
  {
    const rows = book({
      stops_read: { stale: true, status: 'STALE' },
      holdings: [row({ symbol: 'ROWA', protection_stale: false }), row({ symbol: 'ROWB', protection_stale: true }),
        row({ symbol: 'ROWC' })],
    }).rows
    eq('F-7 a current row is not stale, whatever the book flag says', rows[0].protection?.stale, false)
    eq('F-7 an expired row is stale', rows[1].protection?.stale, true)
    eq('F-7 no served per-row clock → null, never false', rows[2].protection?.stale, null)
  }

  // ---- A3: the freshness numbers are the body's, not constants ------------------------------------------------
  const aged = book({}, { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 41, stale: true } })
  eq('A3 age_s 41 → ageSeconds 41', aged.freshness.ageSeconds, 41)
  eq('A3 stale_after_hours 0.5 → 1800 s', aged.freshness.staleAfterSeconds, 1800)

  // ---- R1b: an ABSENT stale-limit clock is null, never a served 0 s (a 0 s limit is an invented number) -------
  const noLimitSwr = { _swr: { as_of: '2026-11-15T00:29:00Z', age_s: 41, stale: true } }
  const noLimitBook = book({ evidence: {} }, noLimitSwr)
  eq('R1b no stale_after_hours → staleAfterSeconds is null, never 0', noLimitBook.freshness.staleAfterSeconds, null)
  const noLimit = holdingsProps(env({ data: wire({ evidence: {} }, noLimitSwr) }), NOW)
  check('R1b unserved limit → the notice says the limit is not served', /limit not served/.test(noLimit.notice ?? ''), String(noLimit.notice))
  check('R1b unserved limit → no invented "limit 0 s"', !/limit 0 s\b/.test(noLimit.notice ?? ''), String(noLimit.notice))
  // The served clock is unchanged: 0.5 h is still 1800 s, and the notice still names it.
  const servedLimit = holdingsProps(env({ data: wire({}, noLimitSwr) }), NOW)
  eq('R1b served 0.5 h → staleAfterSeconds stays 1800', servedLimit.book?.freshness.staleAfterSeconds, 1800)
  check('R1b served limit → the notice still names the served 1800 s limit', /limit 1800 s/.test(servedLimit.notice ?? ''), String(servedLimit.notice))

  // A failed read with nothing kept: ERROR, never a table of nulls.
  const failed = holdingsProps(env({ ok: false, status: 503, data: null, error: 'HTTP 503' }), NOW)
  eq('a failed read with no last good → error', failed.error, 'HTTP 503')
  eq('a failed read with no last good → no book', failed.book, null)

  // A failed read with a last good body: shown, aged, labelled — and the error is not ALSO raised.
  const held = holdingsProps(env({ ok: false, status: 503, data: null, error: 'HTTP 503', lastGood: wire(), lastGoodAgeSeconds: 120 }), NOW)
  check('a failed read with a last good → the book is shown', held.book !== null)
  eq('… marked stale', held.book?.freshness.stale, true)
  eq('… with the last good age, not the body age', held.book?.freshness.ageSeconds, 120)
  check('… and a notice that says last good with its age', /last good read \(2 min old\)/.test(held.notice ?? ''), String(held.notice))
  eq('… and no error raised alongside it', held.error, null)

  // Empty is a served empty, not a failure and not a stale body.
  const empty = holdingsProps(env({ data: wire({ holdings: [], count: 0 }) }), NOW)
  eq('an empty served book → no error', empty.error, null)
  eq('an empty served book → 0 rows', empty.book?.rows.length, 0)

  // A body the adapter cannot read is an error, never an empty table.
  const junk = holdingsProps(env({ data: { ok: true } }), NOW)
  check('a body with no data block → error and no book', junk.error !== null && junk.book === null)
}

// ---- Drawer: the same row identity, and no other row --------------------------------------------------------
{
  const b = book()
  const r = b.rows[0]
  // r2 shape: detailSections returns the tabs plus the panes it cannot fill; the flat list is `fields`.
  const sections = detailSections(r).sections
  const fields = sections.flatMap(s => s.fields)
  const text = fields.map(f => `${f.label} ${f.value} ${f.source}`).join(' | ')
  const head = detailHeading(r)
  check('the drawer leads with the row its own identity', head.title === r.symbol && head.eyebrow.includes(r.accountKey), `${head.title} / ${head.eyebrow}`)
  check('the drawer names the floor flag as adapter-derived', fields.some(f => f.label.startsWith('Below the notional floor') && /ADAPTER-DERIVED/.test(f.source)))
  check('the drawer reports the ladder absent rather than clocking it', /no clock/.test(text), text)
  check('the drawer reports valuation unassessed', /UNASSESSED/.test(text), text)
  // Every served fundamental reaches the drawer, and a bare multiple is named as one rather than as an assessment.
  for (const label of ['Trailing P/E', 'Forward P/E', 'EPS (TTM)', 'EPS, next year (estimate)', 'PEG', 'Beta', 'Sector', 'Industry', 'Performance, year to date', 'Short interest (float)', 'Insider ownership', 'Institutional ownership', 'Analyst rating'])
    check(`the drawer shows ${label}`, fields.some(f => f.label === label), label)
  check('a served P/E is labelled a provider multiple, not an assessment', fields.some(f => f.label === 'Trailing P/E' && /not a valuation assessment/.test(f.source)))
  check('the P/E cell carries the served multiple', fields.some(f => f.label === 'Trailing P/E' && /18\.5x/.test(f.value)), text)
  check('the drawer keeps the served technicals', ['RSI (14)', 'SMA20', 'SMA50', 'SMA200', 'From the 52-week high'].every(l => fields.some(f => f.label === l)))
  check('the drawer never derives a peer median', fields.some(f => f.label === 'Industry / own-history TTM median' && /never|no reader/.test(f.source + f.value)), text)
  const others = b.rows.slice(1).map(x => x.symbol)
  check('no other row of the book appears in the drawer', others.every(s => !text.includes(s)), others.join(','))

  const cashRow = b.rows.find(x => x.kind === 'CASH')
  const cashProt = cashRow ? detailFields(cashRow).find(f => f.label === 'Protection') : undefined
  check('a cash row says protection does not apply', cashProt !== undefined && /not applicable/.test(cashProt.value), cashProt?.value)
  const cashFund = cashRow ? detailSections(cashRow).sections.find(s => s.title === 'Fundamentals') : undefined
  check('a cash row carries no fundamentals block', cashFund !== undefined && /not applicable/.test(cashFund.fields[0]?.value ?? ''), cashFund?.fields[0]?.value)

  const unp = b.rows.find(x => x.symbol === 'UNPRICED')
  const below = unp ? detailFields(unp).find(f => f.label.startsWith('Below the notional floor')) : undefined
  check('an unpriced row is not below the floor in the drawer', below !== undefined && /unknown is not below/.test(below.value), below?.value)
}

if (failures > 0) {
  console.error(`FAIL — ${failures} assertion(s):`)
  for (const f of fails) console.error(`  ✗ ${f}`)
  process.exit(1)
}
console.log('PASS — adapter assertions green')
