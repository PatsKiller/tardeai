// Pure-logic tests for todayPnlState.ts — synthetic fixtures only.
// No HTTP (never 127.0.0.1:7777), no broker, no real P&L, money, holdings or
// account data.
//   node --experimental-strip-types src/lib/todayPnlState.test.ts
import { deriveTodayPnlState } from './todayPnlState.ts'
import type { TodayPnlPayload } from './todayPnlState.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// Wednesday 2026-11-04, 14:00 ET. The latest OPENED session is 2026-11-04.
const NOW = new Date('2026-11-04T14:00:00-05:00')

// Synthetic census. No account identifiers are real; the numbers are placeholders.
const currentPnl = {
  calculated_at: '2026-11-04T14:15:02-05:00',
  session_date: '2026-11-04',
  complete: true,
  funded_account_count: 5,
  represented_account_count: 5,
  missing_accounts: [] as string[],
  partial_accounts: [] as string[],
  unknown_rows: 0,
}

const incompletePnl = {
  ...currentPnl,
  complete: false,
  represented_account_count: 4,
  partial_accounts: ['synthetic_partial_account'],
  unknown_rows: 1,
}

// Friday's P&L, read on Wednesday: the P&L clock predates the latest opened session.
const agedPnl = {
  ...currentPnl,
  calculated_at: '2026-10-30T15:57:07-04:00',
  session_date: '2026-10-30',
}

// A STALE POSITION SURFACE. This is the clock the TODAY tile used to borrow.
const stalePositions = {
  data_as_of: '2026-10-20',
  data_as_of_account: 'synthetic_position_account',
  portfolio_aggregate: {
    portfolio_scope: 'ALL_ACCOUNTS',
    position_observation_stale: true,
    coverage: { stale_after_hours: 48 },
  },
}

const overview = (today_pnl: TodayPnlPayload, withStalePositions = true): Record<string, any> => ({
  today_change: 1234.56,
  today_pct: 2.5,
  portfolio_value: 987654.32,
  today_by_account: { synthetic_account: { change: 1234.56, pct: 2.5, value: 987654.32 } },
  ...(withStalePositions ? stalePositions : {}),
  today_pnl,
})

// ---- (a) incomplete census warns even while the position clock is old ---------
{
  const s = deriveTodayPnlState(overview(incompletePnl), NOW)
  check('(a) incomplete census is warn', s.tone === 'warn')
  check('(a) incomplete census is named INCOMPLETE COVERAGE', s.label === 'INCOMPLETE COVERAGE')
  check('(a) incomplete coverage flag is set', s.incompleteCoverage === true)
  check('(a) an old position clock adds no aged-source condition', s.agedSource === false)
  check('(a) reason states the partial rows, not the position clock', /partial: 1 row\(s\) without a day change/.test(s.reason ?? ''))
  // The same census with the old position surface removed must decide identically:
  // TODAY does not read it in either direction.
  const withoutPositions = deriveTodayPnlState(overview(incompletePnl, false), NOW)
  check('(a) dropping the position clock changes nothing', JSON.stringify(s) === JSON.stringify(withoutPositions))
}

// A missing funded account is the other coverage source and keeps its wording.
{
  const s = deriveTodayPnlState(overview({ ...currentPnl, complete: false, missing_accounts: ['synthetic_missing_account'] }), NOW)
  check('(a) missing funded account is warn', s.tone === 'warn' && s.label === 'INCOMPLETE COVERAGE')
  check('(a) missing reason keeps the funded-account wording', /1 funded acct\(s\) did not report/.test(s.reason ?? ''))
}

// ---- (b) an old position clock alone is NOT a TODAY fault ---------------------
{
  const s = deriveTodayPnlState(overview(currentPnl), NOW)
  check('(b) old positions + current complete P&L is ok', s.tone === 'ok')
  check('(b) ok has no condition label', s.label === null)
  check('(b) ok has no reason', s.reason === null)
  check('(b) ok sets neither condition', s.incompleteCoverage === false && s.agedSource === false)
  // Proof that the input really did carry the old position clock.
  const src = overview(currentPnl)
  check('(b) fixture position clock is old', src.data_as_of === '2026-10-20')
  check('(b) fixture position surface is stale', src.portfolio_aggregate.position_observation_stale === true)
}

// ---- (c) aged source and incomplete census are DIFFERENT conditions ----------
{
  const aged = deriveTodayPnlState(overview(agedPnl), NOW)
  const incomplete = deriveTodayPnlState(overview(incompletePnl), NOW)

  check('(c) an aged P&L clock alone is warn', aged.tone === 'warn')
  check('(c) an aged P&L clock is named AGED SOURCE', aged.label === 'AGED SOURCE')
  check('(c) an aged P&L clock is not called a coverage fault', aged.incompleteCoverage === false)
  check('(c) an aged reason names the P&L clock', /P&L clock .* predates the latest open session/.test(aged.reason ?? ''))

  check('(c) the two conditions do not share a label', aged.label !== incomplete.label)
  check('(c) the two conditions do not share a reason', aged.reason !== incomplete.reason)
  check('(c) neither label is a bare STALE', aged.label !== 'STALE' && incomplete.label !== 'STALE')

  // Both at once: both are stated, neither is folded away.
  const both = deriveTodayPnlState(overview({
    ...incompletePnl,
    calculated_at: agedPnl.calculated_at,
    session_date: agedPnl.session_date,
  }), NOW)
  check('(c) both conditions says both', both.label === 'INCOMPLETE COVERAGE · AGED SOURCE')
  check('(c) both reasons are carried', /partial: 1 row/.test(both.reason ?? '') && /predates the latest open session/.test(both.reason ?? ''))
}

// ---- session semantics: a Friday P&L is not aged over a weekend / pre-open ----
{
  const mondayPreOpen = new Date('2026-11-02T09:00:00-05:00') // Monday, before 09:30 ET
  const mondayOpen = new Date('2026-11-02T09:31:00-05:00')    // Monday, after the open
  const fridayPnl = { ...currentPnl, calculated_at: '2026-10-30T15:57:07-04:00', session_date: '2026-10-30' }
  check('(c) Friday P&L is current on Monday pre-open', deriveTodayPnlState(overview(fridayPnl), mondayPreOpen).agedSource === false)
  check('(c) Friday P&L is aged once Monday has opened', deriveTodayPnlState(overview(fridayPnl), mondayOpen).agedSource === true)
  const saturday = new Date('2026-10-31T12:00:00-04:00') // the day after that Friday
  check('(c) Friday P&L is current on Saturday', deriveTodayPnlState(overview(fridayPnl), saturday).agedSource === false)
}

// ---- (d) values, counts and the payload are untouched ------------------------
{
  const src = overview(incompletePnl)
  const snapshot = JSON.stringify(src)
  const s = deriveTodayPnlState(src, NOW)
  check('(d) the payload is not mutated', JSON.stringify(src) === snapshot)
  check('(d) the state carries no financial value or count', !('today_change' in s) && !('today_pct' in s) && !('unknown_rows' in s))
  check('(d) the money value is unchanged on the input', src.today_change === 1234.56 && src.today_pct === 2.5)
  check('(d) the census counts are unchanged on the input',
    src.today_pnl.funded_account_count === 5 && src.today_pnl.represented_account_count === 4 && src.today_pnl.unknown_rows === 1)

  // No payload: fail-open here (the tile's own UNDATED meta states the missing
  // session). This helper never invents a coverage or source fault from absence.
  const empty = deriveTodayPnlState(null, NOW)
  check('(d) a missing overview is not a coverage or source fault', empty.tone === 'ok' && empty.label === null)
}

console.log(`\ntodayPnlState: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
