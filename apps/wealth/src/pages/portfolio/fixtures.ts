// Synthetic fixtures for the Holdings tab. EVERY value here is invented.
//
// Why fixtures: portfolio-holdings@2 is PROPOSED, not APPROVED_FOR_WIRING (runbook step 5), so no page may bind
// a live reader yet. The repo is public, so the fixture carries no household data at all — not even a real
// symbol. Symbols are prefixed `QZ` and accounts `SYN_` so a screenshot can never be mistaken for the book.
//
// The fixture is authored to the contract, not the other way round: every displayed value is a stored field,
// exactly as the wire will serve it. The page computes nothing from these numbers — and it never sums rows:
// the per-account totals below come from `accounts[]`, the way the producer publishes them.
//
// Four books, because four cases must render honestly:
//   FIXTURE_BOOK                 populated — one worthless delisted zero row, one unpriced row, one dead
//                                CUSIP omitted by the read filter
//   FIXTURE_BOOK_EMPTY           no rows — a sentence, never a table of zeros
//   FIXTURE_BOOK_STALE           same rows, stale clock — last known good with its age
//   FIXTURE_BOOK_LAST_KNOWN_GOOD an UNASSESSED P/E that still carries its value (review F1/F9)

import { VALUATION_CONTRACT_VERSION } from '../../contracts/valuation'
import { unassessed, type ValuationAssessment } from '../../contracts/valuation'
import type {
  AccountTotal,
  BookMeasure,
  ClockProvenance,
  DeclaredClock,
  FibLadder,
  HoldingsBook,
  HoldingsRow,
  Protection,
  ServedFreshness,
} from './contract'
import { PORTFOLIO_HOLDINGS_CONTRACT_VERSION } from './contract'

const SYNTHETIC_REASON = 'synthetic fixture: no approved valuation methodology wired'

function equityValuation(key: string): ValuationAssessment {
  return unassessed(key, 'EQUITY', SYNTHETIC_REASON)
}

const fundValuation: ValuationAssessment = {
  contract: VALUATION_CONTRACT_VERSION,
  methodology_id: 'fixture:fund-metric@1',
  account_security_key: 'SYN_ROLL:QZFD',
  instrument_type: 'FUND',
  status: 'FUND_METRIC',
  trailing: null,
  forward: null,
  fund_metric: {
    name: 'weighted holdings P/E (provider-defined)',
    definition: 'Provider aggregate over disclosed holdings; not a company earnings multiple.',
    value: 17.4,
    source: 'fixture',
    as_of: '2026-11-14T14:00:00Z',
  },
  as_of: '2026-11-14T14:00:00Z',
  reason: 'fund: a company P/E does not apply; carrying the provider fund metric instead',
}

const cashValuation = (key: string): ValuationAssessment => unassessed(key, 'CASH', 'cash has no earnings multiple')

/**
 * An UNASSESSED trailing P/E that KEEPS its last known value — the case review F1 is about. The status stays
 * UNASSESSED (the evidence is stale) and the value stays 18.75; the renderer must show both, or downstream a
 * last-known-good multiple becomes a bare word and a stale number becomes a fresh one.
 */
export function staleTrailingPe(key: string): ValuationAssessment {
  return {
    contract: VALUATION_CONTRACT_VERSION,
    // Renamed from 'fixture:last-known-good@1' (review R2, page-wide): this id can render in the evidence
    // table, and §K reserves "last-good" for a validated receipt. A synthetic id is not one.
    methodology_id: 'fixture:stale-clock@1',
    account_security_key: key,
    instrument_type: 'EQUITY',
    status: 'UNASSESSED',
    trailing: {
      measure: 'PE_TRAILING',
      status: 'UNASSESSED',
      value: 18.75,
      earnings: {
        period: 'TTM to 2026-09-30',
        basis: 'GAAP diluted',
        source: 'fixture',
        as_of: '2026-11-06T00:00:00Z',
      },
      benchmarks: [],
      relative: null,
      reason: '8 days old, past the 7-day stale window; last known value kept',
      evidence_ids: [],
    },
    forward: null,
    fund_metric: null,
    as_of: '2026-11-06T00:00:00Z',
    reason: 'trailing P/E is stale; last known value kept',
  }
}

const ONCE_READ = '2026-11-14T02:00:00Z'

/**
 * The row-level classification provenance the wire serves (contract r6 §5). The fixture's source says
 * `fixture`: it is synthetic, and a screenshot must never read it as a provider's classification clock.
 */
function profiled(assetType: string, source = 'fixture'): Pick<HoldingsRow, 'assetType' | 'profileSource' | 'profileUpdatedAt'> {
  return { assetType, profileSource: source, profileUpdatedAt: '2026-11-14T13:00:00Z' }
}

function protection(over: Partial<Protection> & Pick<Protection, 'state' | 'reason'>): Protection {
  return { stop: null, basis: null, asOf: ONCE_READ, stale: false, nextStep: 'Review this row before acting.', ...over }
}

const LADDER_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]

function ladder(high: number, low: number, prices: number[], nearest: number, fromHigh: number): FibLadder {
  return {
    method: 'FIB_52W_RANGE',
    levels: LADDER_RATIOS.map((ratio, i) => ({ ratio, price: prices[i] })),
    nearestLevel: nearest,
    retracementFromHighPct: fromHigh,
    window: { high, low, asOf: '2026-11-14T01:00:00Z' },
  }
}

const ROWS: HoldingsRow[] = [
  {
    accountKey: 'SYN_TAX', accountLabel: 'Synthetic taxable', symbol: 'QZTA', name: 'Qzeta Alpha Corp',
    kind: 'SECURITY', shares: 200, price: 75.0, priceAsOf: '2026-11-14T21:00:00Z', avgCost: 60.0,
    marketValue: 15000.0, gainLoss: 3000.0, gainLossPct: 25.0, portfolioPct: 15.0,
    dayChange: 240.58, dayChangePct: 1.63, marketCapB: 41200.0, yieldPct: 1.8,
    belowFloor: false, worthless: false,
    fundamentals: { sector: 'Information technology', industry: 'Systems software', peTrailing: 21.4, peForward: 18.9, epsTtm: 3.5, epsNextY: 3.97, peg: 1.62, beta: 1.1, perfYtdPct: 18.2, rsi: 61.3, sma20Pct: 2.4, sma50Pct: 5.1, sma200Pct: 12.7, week52HighPct: 6.8, shortFloatPct: 1.9, insiderOwnPct: 0.6, instOwnPct: 84.2, analystRating: 'buy' },
    protection: protection({ state: 'PROTECTED', stop: 68.0, basis: 'resting broker stop (GTC)',
      reason: 'a resting stop is recorded for this position', nextStep: 'None — protection is in place.' }),
    fib: ladder(82.5, 58.0, [82.5, 76.72, 73.14, 70.25, 67.36, 63.24, 58.0], 76.72, 30.61),
    valuation: equityValuation('SYN_TAX:QZTA'),
    ...profiled('EQUITY'),
  },
  {
    accountKey: 'SYN_TAX', accountLabel: 'Synthetic taxable', symbol: 'QZBR', name: 'Qzeta Beta Holdings',
    kind: 'SECURITY', shares: 150, price: 40.0, priceAsOf: '2026-11-14T21:00:00Z', avgCost: 44.0,
    marketValue: 6000.0, gainLoss: -600.0, gainLossPct: -9.09, portfolioPct: 6.0,
    dayChange: -60.0, dayChangePct: -0.99, marketCapB: 1850.0, yieldPct: null,
    belowFloor: false, worthless: false,
    fundamentals: { sector: 'Industrials', industry: 'Diversified holdings', peTrailing: 12.8, peForward: 13.4, epsTtm: 3.13, epsNextY: 2.99, peg: 2.1, beta: 0.9, perfYtdPct: -8.4, rsi: 42.1, sma20Pct: -3.2, sma50Pct: -5.6, sma200Pct: -1.1, week52HighPct: 24.6, shortFloatPct: 4.4, insiderOwnPct: 2.1, instOwnPct: 71.5, analystRating: 'hold' },
    protection: protection({ state: 'GAP', reason: 'no resting stop and no recorded decision to hold unprotected',
      nextStep: 'Set a protective stop or record the decision to hold unprotected.' }),
    fib: null,
    valuation: equityValuation('SYN_TAX:QZBR'),
    ...profiled('EQUITY'),
  },
  {
    accountKey: 'SYN_ROTH', accountLabel: 'Synthetic retirement', symbol: 'QZGA', name: 'Qzeta Gamma Industries',
    kind: 'SECURITY', shares: 80, price: 120.0, priceAsOf: '2026-11-14T21:00:00Z', avgCost: 100.0,
    marketValue: 9600.0, gainLoss: 1600.0, gainLossPct: 20.0, portfolioPct: 9.6,
    dayChange: 63.9, dayChangePct: 0.67, marketCapB: 96400.0, yieldPct: 2.4,
    belowFloor: false, worthless: false,
    fundamentals: { sector: 'Health care', industry: 'Medical devices', peTrailing: 27.6, peForward: 23.1, epsTtm: 4.35, epsNextY: 5.19, peg: 1.9, beta: 0.78, perfYtdPct: 9.6, rsi: 55.8, sma20Pct: 1.2, sma50Pct: 3.9, sma200Pct: 8.4, week52HighPct: 11.2, shortFloatPct: 2.3, insiderOwnPct: 1.4, instOwnPct: 88.9, analystRating: 'buy' },
    protection: protection({ state: 'PROTECTED', stop: 108.0, basis: 'resting broker stop (GTC)',
      reason: 'a resting stop is recorded for this position', nextStep: 'None — protection is in place.' }),
    fib: ladder(132.0, 96.0, [132.0, 123.5, 118.25, 114.0, 109.75, 103.7, 96.0], 118.25, 33.33),
    valuation: equityValuation('SYN_ROTH:QZGA'),
    ...profiled('EQUITY'),
  },
  {
    accountKey: 'SYN_ROTH', accountLabel: 'Synthetic retirement', symbol: 'QZDL', name: 'Qzeta Delta Systems',
    kind: 'SECURITY', shares: 300, price: 12.5, priceAsOf: '2026-11-14T21:00:00Z', avgCost: 15.0,
    marketValue: 3750.0, gainLoss: -750.0, gainLossPct: -16.67, portfolioPct: 3.75,
    dayChange: 0.0, dayChangePct: 0.0, marketCapB: 640.0, yieldPct: null,
    belowFloor: false, worthless: false,
    fundamentals: { sector: 'Communication services', industry: 'Interactive media', peTrailing: 34.2, peForward: 28.7, epsTtm: 0.37, epsNextY: 0.44, peg: 2.6, beta: 1.42, perfYtdPct: -21.3, rsi: 31.7, sma20Pct: -6.1, sma50Pct: -11.4, sma200Pct: -19.8, week52HighPct: 42.1, shortFloatPct: 7.8, insiderOwnPct: 0.3, instOwnPct: 62.4, analystRating: 'hold' },
    protection: protection({ state: 'UNKNOWN', asOf: null,
      reason: 'the broker stop read did not cover this account',
      nextStep: 'Re-read the protection state for this account.' }),
    fib: ladder(18.4, 9.6, [18.4, 16.32, 15.04, 14.0, 12.96, 11.48, 9.6], 12.96, 67.05),
    valuation: equityValuation('SYN_ROTH:QZDL'),
    ...profiled('EQUITY'),
  },
  {
    accountKey: 'SYN_ROLL', accountLabel: 'Synthetic rollover', symbol: 'QZEP', name: 'Qzeta Epsilon Group',
    kind: 'SECURITY', shares: 60, price: 210.0, priceAsOf: '2026-11-14T21:00:00Z', avgCost: 195.0,
    marketValue: 12600.0, gainLoss: 900.0, gainLossPct: 7.69, portfolioPct: 12.6,
    dayChange: 126.0, dayChangePct: 1.01, marketCapB: 230500.0, yieldPct: 0.9,
    belowFloor: false, worthless: false,
    fundamentals: { sector: 'Energy', industry: 'Integrated oil & gas', peTrailing: 10.4, peForward: 11.2, epsTtm: 20.19, epsNextY: 18.75, peg: 1.3, beta: 0.95, perfYtdPct: 4.7, rsi: 48.9, sma20Pct: 0.6, sma50Pct: -1.8, sma200Pct: 2.9, week52HighPct: 9.1, shortFloatPct: 1.2, insiderOwnPct: 4.8, instOwnPct: 66.1, analystRating: 'buy' },
    protection: protection({ state: 'PROTECTED', stop: 190.0, basis: 'resting broker stop (GTC)',
      reason: 'a resting stop is recorded for this position', nextStep: 'None — protection is in place.' }),
    fib: null,
    valuation: equityValuation('SYN_ROLL:QZEP'),
    ...profiled('EQUITY'),
  },
  {
    accountKey: 'SYN_ROLL', accountLabel: 'Synthetic rollover', symbol: 'QZFD', name: 'Qzeta Income Fund',
    kind: 'SECURITY', shares: 400, price: 25.0, priceAsOf: '2026-11-14T21:00:00Z', avgCost: 24.5,
    marketValue: 10000.0, gainLoss: 200.0, gainLossPct: 2.04, portfolioPct: 10.0,
    dayChange: -20.04, dayChangePct: -0.2, marketCapB: null, yieldPct: 5.6,
    belowFloor: false, worthless: false,
    fundamentals: { sector: null, industry: null, peTrailing: null, peForward: null, epsTtm: null, epsNextY: null, peg: null, beta: 0.64, perfYtdPct: 3.1, rsi: null, sma20Pct: 0.4, sma50Pct: 1.1, sma200Pct: null, week52HighPct: 4.2, shortFloatPct: null, insiderOwnPct: null, instOwnPct: null, analystRating: null },
    protection: protection({ state: 'PROTECTED', stop: 23.5, basis: 'resting broker stop (GTC)',
      reason: 'a resting stop is recorded for this position', nextStep: 'None — protection is in place.' }),
    // A fund's ladder carries the nearest level and the retracement only — the wire's `fib` shape for funds.
    fib: {
      method: 'FIB_52W_RANGE', levels: [], nearestLevel: 25.1, retracementFromHighPct: 51.85,
      window: { high: 27.8, low: 22.4, asOf: '2026-11-14T01:00:00Z' },
    },
    valuation: fundValuation,
    // A fund: its classification is the fund itself, never invented look-through (r6 §5 / INTEGRATION).
    ...profiled('MUTUAL_FUND'),
  },
  {
    // A worthless, delisted identifier the producer keeps at zero: a FACT, not a missing value. It renders
    // "$0.00 · worthless" — never as an unpriced row, and never silently dropped from a count that includes it.
    accountKey: 'SYN_TAX', accountLabel: 'Synthetic taxable', symbol: 'QZDX', name: 'Qzeta Delta Delisted',
    kind: 'SECURITY', shares: 40, price: null, priceAsOf: null, avgCost: 12.5,
    marketValue: 0.0, gainLoss: null, gainLossPct: null, portfolioPct: 0,
    dayChange: null, dayChangePct: null, marketCapB: null, yieldPct: null,
    belowFloor: true, worthless: true,
    fundamentals: null,
    protection: protection({ state: 'UNKNOWN', asOf: null,
      reason: 'no broker stop read for a delisted zero-value identifier',
      nextStep: 'Record the write-off decision; there is nothing left to protect.' }),
    fib: null,
    valuation: equityValuation('SYN_TAX:QZDX'),
    ...profiled('EQUITY'),
  },
  {
    // An unpriced holding: no price served, so the value is UNKNOWN — never $0.00, and never under the floor:
    // the mark is derived only from a served value, so an unknown value cannot be "below".
    accountKey: 'SYN_ROLL', accountLabel: 'Synthetic rollover', symbol: 'QZNV', name: 'Qzeta Nova Materials',
    kind: 'SECURITY', shares: 25, price: null, priceAsOf: null, avgCost: 88.0,
    marketValue: null, gainLoss: null, gainLossPct: null, portfolioPct: 0,
    dayChange: null, dayChangePct: null, marketCapB: null, yieldPct: null,
    belowFloor: false, worthless: false,
    fundamentals: null,
    protection: protection({ state: 'GAP', reason: 'no resting stop and no recorded decision to hold unprotected',
      nextStep: 'Set a protective stop once a price is served, or record the decision.' }),
    fib: null,
    valuation: equityValuation('SYN_ROLL:QZNV'),
    ...profiled('EQUITY'),
  },
  {
    accountKey: 'SYN_TAX', accountLabel: 'Synthetic taxable', symbol: 'CASH', name: 'Cash',
    kind: 'CASH', shares: 43050.0, price: 1.0, priceAsOf: null, avgCost: null,
    marketValue: 43050.0, gainLoss: null, gainLossPct: null, portfolioPct: 43.05,
    dayChange: 0.0, dayChangePct: 0.0, marketCapB: null, yieldPct: null,
    belowFloor: false, worthless: false,
    fundamentals: null,
    protection: null,
    fib: null,
    valuation: cashValuation('SYN_TAX:CASH'),
    ...profiled('CASH'),
  },
]

const DAY_PNL: DeclaredClock = {
  status: 'UNKNOWN',
  at: null,
  reason: 'stored day change has no declared per-row observation clock',
}

const SESSION: HoldingsBook['session'] = {
  status: 'KNOWN',
  phase: 'weekend',
  latestOpenSession: '2026-11-13',
  asOf: '2026-11-14T21:00:00Z',
  source: 'performance reader (market_session)',
  reason: 'the session label is served by the performance reader, not by the rows',
}

const CLOCKS: ClockProvenance[] = [
  { role: 'POSITIONS', at: '2026-11-14T21:00:00Z', source: 'broker position clock', isBuildClock: false, mixed: true, unknownRows: 0 },
  { role: 'QUOTE', at: '2026-11-14T21:00:00Z', source: 'last repriced quote', isBuildClock: false },
  // The trap this contract exists to surface: the document build clock is a day older than the positions clock.
  { role: 'BUILD', at: '2026-11-13T21:00:00Z', source: 'position list document build', isBuildClock: true },
]

// Per-account totals exactly as the producer publishes them. They are NEVER derived here, and the page never
// sums rows to reach them: SYN_TAX carries the worthless zero row and the cash row, SYN_ROLL the unpriced one.
const ACCOUNTS: AccountTotal[] = [
  { accountKey: 'SYN_TAX', accountLabel: 'Synthetic taxable', totalUsd: 64050.0, cashUsd: 43050.0,
    asOf: '2026-11-14T21:00:00Z', source: 'producer document build (per-account total_usd / cash_usd)' },
  { accountKey: 'SYN_ROTH', accountLabel: 'Synthetic retirement', totalUsd: 13350.0, cashUsd: 0.0,
    asOf: '2026-11-14T21:00:00Z', source: 'producer document build (per-account total_usd / cash_usd)' },
  { accountKey: 'SYN_ROLL', accountLabel: 'Synthetic rollover', totalUsd: 22600.0, cashUsd: 0.0,
    asOf: '2026-11-14T21:00:00Z', source: 'producer document build (per-account total_usd / cash_usd)' },
]

// The four book-level governed measures the wire publishes. C1: none is verified today — `data.metrics[]`
// reports `verified: false, receipt: null` for all four — so the fixture carries no invented receipt. One is
// UNKNOWN and stays UNKNOWN: the book's verified daily P&L is not served.
const MEASURES: BookMeasure[] = [
  { id: 'account_value', label: 'Account value', status: 'MEASURED', valueUsd: 100000.0,
    // The wire publishes `basis` and no `definition` for this measure (C1.2).
    definition: 'sum of served market values including cash, measured on the positions clock',
    verified: false, receiptId: null, asOf: '2026-11-14T21:00:00Z', reason: 'measured' },
  { id: 'price_move_estimate', label: 'Price-move estimate', status: 'MEASURED', valueUsd: 350.44,
    definition: 'sum of stored per-position day change; an estimate, not a reconciled P&L',
    verified: false, receiptId: null, asOf: '2026-11-14T21:00:00Z', reason: 'measured' },
  { id: 'account_value_change_1d', label: 'Account value change, 1 day', status: 'MEASURED', valueUsd: 349.6,
    definition: 'day-over-day change in account value under the producer methodology',
    // This measure has no `as_of` of its own; the clock below is the wire's `end.as_of` (C1.2).
    verified: false, receiptId: null, asOf: '2026-11-14T21:00:00Z', reason: 'measured' },
  { id: 'verified_daily_pnl', label: 'Verified daily P&L', status: 'UNKNOWN', valueUsd: null,
    definition: 'reconciled session profit; requires a stored reconciliation with allocated components',
    verified: false, receiptId: null, asOf: null,
    // The wire states this one in `gap.reason` (C1.2).
    reason: 'no stored reconciliation; the current read reports PARTIAL and leaves a residual unallocated' },
]

/** The producer's served verdicts, as they would arrive on `data.freshness` (synthetic, fixed clocks). */
const SERVED_FRESH: ServedFreshness = {
  status: 'FRESH', stale: false, clock: 'quote', clockLabel: 'QUOTE', asOf: '2026-11-14T20:55:00Z',
  ageSeconds: 300, limitSeconds: 900, limitSource: 'config/data_source_authority.json domains[quote_price].stale_after_hours',
  window: 'open', rule: 'oldest source-observation clock against its registry window; the read clock is not an input',
  gap: null,
}
const SERVED_STALE: ServedFreshness = {
  ...SERVED_FRESH, status: 'STALE', stale: true, clock: 'positions', clockLabel: 'POSITIONS',
  asOf: '2026-11-11T20:55:00Z', ageSeconds: 259500,
}

export const FIXTURE_BOOK: HoldingsBook = {
  contract: PORTFOLIO_HOLDINGS_CONTRACT_VERSION,
  source: 'FIXTURE',
  asOf: '2026-11-14T21:00:00Z',
  // F-1: the book's as-of is the QUOTE instant the producer puts in truth.as_of, so it is labelled QUOTE. POSITIONS
  // is an aggregate across rows (the wire marks it mixed) and is not the clock a marks line is drawn from.
  asOfClock: 'QUOTE',
  clocks: CLOCKS,
  rows: ROWS,
  counts: {
    allRows: 9,
    nonCash: 8,
    cash: 1,
    nonCashOverFloor: 6,
    heldUnderFloor: 1,
    primaryScopeLabel: 'non-cash over the notional floor',
  },
  population: {
    // One dead-CUSIP zero-value holding is dropped by the read-side filter before the counters (the wire's
    // 33 -> 30 gap in miniature): it is not a row, and the omission is stated rather than hidden.
    priceableRows: 10,
    renderedRows: 9,
    excluded: [
      {
        kind: 'DEAD_CUSIP_ZERO_VALUE',
        label: 'dead CUSIP, zero value',
        count: 1,
        rule: 'read-side filter (LQ-20261107-1417): a dead-CUSIP holding with zero value is dropped before the counters',
      },
    ],
    // C3: the wire's `scope_coverage.excluded` population — rows that ARE in the table and are outside the
    // counted scope. It is the same row the `heldUnderFloor` count counts, and it must never read as omitted.
    listedNotCounted: [
      // The wire's literal reason is `priced under $100: listed, not counted`; this fixture's own row is the
      // worthless delisted holding, which has no served price, so its reason is phrased as a market value.
      { reason: 'market value under $100: listed, not counted', count: 1, scope: 'holdings.held_under_100' },
    ],
    floorUsd: 100,
  },
  accounts: ACCOUNTS,
  measures: MEASURES,
  session: SESSION,
  freshness: { served: SERVED_FRESH, ageSeconds: 900, staleAfterSeconds: 259200, stale: false, blockPresent: true, withdrawn: false },
  dayPnl: DAY_PNL,
  coverageNote:
    'Nine synthetic rows: six priced securities, one unpriced security, one worthless delisted zero row and one cash row. One dead-CUSIP zero-value row is omitted by the read-side filter and counted in the population block. Cash is inside the weight denominator.',
}

/** Same shape, no rows — the empty state, never a table of zeros. */
export const FIXTURE_BOOK_EMPTY: HoldingsBook = {
  ...FIXTURE_BOOK,
  rows: [],
  counts: {
    allRows: 0, nonCash: 0, cash: 0, nonCashOverFloor: 0, heldUnderFloor: 0,
    primaryScopeLabel: 'non-cash over the notional floor',
  },
  population: {
    priceableRows: 0, renderedRows: 0, excluded: [], listedNotCounted: [], floorUsd: 100,
  },
  accounts: null,
  coverageNote: 'No positions are present in this fixture.',
}

/** Same rows, a stale clock — last-known-good must say how old it is. */
export const FIXTURE_BOOK_STALE: HoldingsBook = {
  ...FIXTURE_BOOK,
  freshness: { served: SERVED_STALE, ageSeconds: 314400, staleAfterSeconds: 259200, stale: true, blockPresent: true, withdrawn: false },
}

/** One row's trailing P/E is UNASSESSED but still carries its value: the stale-clock case (F1). */
export const FIXTURE_BOOK_LAST_KNOWN_GOOD: HoldingsBook = {
  ...FIXTURE_BOOK,
  rows: FIXTURE_BOOK.rows.map(r =>
    r.symbol === 'QZTA' ? { ...r, valuation: staleTrailingPe(`${r.accountKey}:${r.symbol}`) } : r,
  ),
  coverageNote:
    'Nine synthetic rows, of which one carries a stale trailing P/E that keeps its last known value. One dead-CUSIP zero-value row is omitted by the read-side filter.',
}

/**
 * Review R1 fixture: the same book, and this read DOES declare a VALUATION clock (`generated_at`). The basis
 * domain has no clock of its own — basis coverage is per-row — so the page must still render basis UNKNOWN with
 * its own reason. A page that borrows VALUATION here prints a substituted clock under the basis's name.
 */
export const FIXTURE_BOOK_VALUATION_CLOCK: HoldingsBook = {
  ...FIXTURE_BOOK,
  clocks: [
    ...FIXTURE_BOOK.clocks,
    { role: 'VALUATION', at: '2026-11-15T03:30:30.069691+00:00', source: 'generated_at', isBuildClock: false },
  ],
}

/**
 * Review R3(b) fixture: a PUBLISHED row at zero market value. The live book's legacy-classified row is
 * published, so a rule that drops zero-value rows instead of rows with no published gain/loss would silently
 * remove it — and its contribution, so the subtotal moves. The row is synthetic, like every other row here.
 *
 * The contribution has to be non-zero and the market value zero, so it is a WRITTEN-DOWN lot: no served price
 * (delisted), a $500 cost basis and a PUBLISHED loss of −$500 (gainLoss = market value − cost basis), which is
 * what the producer's own field carries. A zero-value row with a zero-gain/loss contribution would make the
 * "it stays in the subtotal" guard vacuous, which is exactly the gap review R3(b) names.
 */
export const FIXTURE_BOOK_LEGACY_PUBLISHED: HoldingsBook = {
  ...FIXTURE_BOOK,
  rows: [
    ...FIXTURE_BOOK.rows,
    {
      ...FIXTURE_BOOK.rows[0],
      accountKey: 'SYN_ROLL', accountLabel: 'Synthetic rollover', symbol: 'QZLGC',
      name: 'Qzeta Legacy Delisted (zero value, published loss)',
      shares: 40, price: null, priceAsOf: null, avgCost: 12.5,
      marketValue: 0.0, gainLoss: -500.0, gainLossPct: -100.0,
      dayChange: null, dayChangePct: null, marketCapB: null, yieldPct: null,
      portfolioPct: 0, belowFloor: true, worthless: true, fundamentals: null, fib: null,
      valuation: equityValuation('SYN_ROLL:QZLGC'),
      protection: protection({ state: 'UNKNOWN', asOf: null,
        reason: 'no broker stop read for a delisted zero-value identifier',
        nextStep: 'Record the write-off decision; there is nothing left to protect.' }),
      ...profiled('EQUITY'),
    },
  ],
  // The extra row is rendered and counted, priced at zero, under the $100 floor and omitted from no population.
  // The two produced counts and the listed-not-counted block move with it; nothing else does (a zero market
  // value changes no account total, no weight and no account-value measure).
  counts: {
    allRows: 10,
    nonCash: 9,
    cash: 1,
    nonCashOverFloor: 6,
    heldUnderFloor: 2,
    primaryScopeLabel: 'non-cash over the notional floor',
  },
  population: {
    priceableRows: 11,
    renderedRows: 10,
    excluded: [
      {
        kind: 'DEAD_CUSIP_ZERO_VALUE',
        label: 'dead CUSIP, zero value',
        count: 1,
        rule: 'read-side filter (LQ-20261107-1417): a dead-CUSIP holding with zero value is dropped before the counters',
      },
    ],
    listedNotCounted: [
      { reason: 'market value under $100: listed, not counted', count: 2, scope: 'holdings.held_under_100' },
    ],
    floorUsd: 100,
  },
  coverageNote:
    'The same nine synthetic rows plus one legacy-classified row at zero market value that IS published (a written-down lot, −$500): it must stay in the subtotal.',
}

