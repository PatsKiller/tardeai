// Pure-logic tests for portfolioDayFigure.ts — synthetic fixtures only.
// No HTTP (never 127.0.0.1:7777), no broker, no real P&L, money, holdings or account data.
//   node --experimental-strip-types src/lib/portfolioDayFigure.test.ts
//
// Data-truth audit 2026-11-07, defect 6: the portfolio page showed a day figure it computed from the
// rows it held (+$5,592) beside the header's +$5,576 (the backend's today_move) and a stored
// portfolio_totals.day_change of $10,409, while /api/v2/overview reported today_change null because
// economic day P&L is unproven (OI-044). The page's figure must come from the backend, and when the
// backend says unproven the page must say so instead of inventing a number.
import { portfolioDayFigure } from './portfolioDayFigure.ts'

declare const process: { exit(code?: number): void }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// The live shape, 2026-11-06 evening, with synthetic account names and placeholder amounts.
const UNPROVEN = 'Economic account-day P&L is unproven: stored day_change mixes prior-mark deltas and fill-aware session P&L'
const overview = {
  today_change: null,
  today_pct: null,
  today_pnl: {
    status: 'UNKNOWN', complete: false, scope: 'ALL_ACCOUNTS_ECONOMIC_DAY',
    coverage_reason: UNPROVEN, gap: { reason: UNPROVEN, ticket: 'OI-044' },
    market_session: { status: 'KNOWN', latest_open_session: '2026-11-06' },
  },
  today_move: {
    status: 'REPORTED', change: 4321.5, change_pct: 0.4504, session_date: '2026-11-06',
    session_source: 'holdings.last_repriced', complete: true, missing_accounts: [], partial_accounts: [],
    economic_status: 'UNKNOWN',
    by_account: {
      synthetic_alpha: { change: 2100.25, change_pct: 0.3683 },
      synthetic_beta: { change: 0.67, change_pct: 0.1272 },
    },
  },
}

{
  // The defect: a page-side sum of the rows on screen. The figure is the backend's, not a sum.
  const fig = portfolioDayFigure(overview)
  check('the whole-book figure is the backend today_move, not a row sum', fig.change === 4321.5)
  check('and its percentage is the backend percentage, rounded for display', fig.pct === 0.45)
  check('and it carries the economic caveat beside it', (fig.note ?? '').includes('economic P&L unproven'))
  check('a shown figure carries no "why not" reason', fig.reason === null)
}

{
  // An account chip narrows to the attribution the backend itself makes.
  const fig = portfolioDayFigure(overview, { account: 'synthetic_alpha' })
  check('an account filter reads today_move.by_account', fig.change === 2100.25 && fig.pct === 0.37)
  check('an account figure keeps the economic caveat', (fig.note ?? '').includes('economic P&L unproven'))
  const empty = portfolioDayFigure(overview, { account: 'synthetic_gamma' })
  check('an account the backend does not attribute gets NO figure', empty.change === null && empty.pct === null)
  check('and says so in words', (empty.reason ?? '').includes('synthetic gamma'))
}

{
  // A signal sub-tab has no backend attribution at all: showing a sum of some rows would invent one.
  const fig = portfolioDayFigure(overview, { account: 'synthetic_alpha', signalFiltered: true })
  check('a signal filter shows no figure', fig.change === null && fig.note === null)
  check('and says the backend attributes day P&L per account', (fig.reason ?? '').includes('per account'))
}

{
  // The backend says unproven and reports no move: the page shows no number and the backend's reason.
  const noMove = { ...overview, today_move: { status: 'UNKNOWN', change: null } }
  const fig = portfolioDayFigure(noMove)
  check('no proven figure and no move -> no number', fig.change === null)
  check("the reason is the backend's own coverage reason", fig.reason === UNPROVEN)
  check('the reason names the word the audit asked for', (fig.reason ?? '').includes('unproven'))
}

{
  // Not loaded is not unproven: a tab that does not fetch the overview shows no figure and no verdict.
  const fig = portfolioDayFigure(null)
  check('no overview -> no figure', fig.change === null && fig.note === null)
  check('and the reason is "not loaded", not "unproven"', fig.reason === 'day P&L is not loaded on this view')
}

{
  // When the backend DOES prove the economic total, it wins and there is no caveat.
  const proven = {
    today_change: 987.65, today_pct: 0.81,
    today_pnl: { status: 'KNOWN', complete: true, market_session: { status: 'KNOWN', latest_open_session: '2026-11-06' } },
    today_move: { status: 'REPORTED', change: 4321.5, change_pct: 0.4504 },
  }
  const fig = portfolioDayFigure(proven)
  check('a proven economic total is shown as-is', fig.change === 987.65 && fig.pct === 0.81)
  check('with no unproven caveat', fig.note === null && fig.reason === null)
}

{
  // A non-finite number is never a figure.
  const junk = { ...overview, today_move: { ...overview.today_move, change: Number.NaN } }
  const fig = portfolioDayFigure(junk)
  check('a non-finite move is not shown', fig.change === null)
}

console.log(`\nportfolioDayFigure: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
