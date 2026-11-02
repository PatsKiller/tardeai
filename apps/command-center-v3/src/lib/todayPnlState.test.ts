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
  status: 'KNOWN',
  market_session: { status: 'KNOWN', latest_open_session: '2026-11-04' },
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
  check('(a) incomplete census is named INCOMPLETE COVERAGE', s.label?.includes('INCOMPLETE COVERAGE') === true)
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
  check('(a) missing funded account is warn', s.tone === 'warn' && s.label?.includes('INCOMPLETE COVERAGE') === true)
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
  check('(c) an aged reason names the P&L clock', /P&L session .* predates latest opened session/.test(aged.reason ?? ''))

  check('(c) the two conditions do not share a label', aged.label !== incomplete.label)
  check('(c) the two conditions do not share a reason', aged.reason !== incomplete.reason)
  check('(c) neither label is a bare STALE', aged.label !== 'STALE' && incomplete.label !== 'STALE')

  // Both at once: both are stated, neither is folded away.
  const both = deriveTodayPnlState(overview({
    ...incompletePnl,
    calculated_at: agedPnl.calculated_at,
    session_date: agedPnl.session_date,
  }), NOW)
  check('(c) both conditions says both', both.label?.includes('INCOMPLETE COVERAGE') === true && both.label.includes('AGED SOURCE') && both.economicUnknown)
  check('(c) both reasons are carried', /partial: 1 row/.test(both.reason ?? '') && /predates latest opened session/.test(both.reason ?? ''))
}

// ---- session semantics: a Friday P&L is not aged over a weekend / pre-open ----
{
  const mondayPreOpen = new Date('2026-11-02T09:00:00-05:00') // Monday, before 09:30 ET
  const mondayOpen = new Date('2026-11-02T09:31:00-05:00')    // Monday, after the open
  const fridayPnl = { ...currentPnl, calculated_at: '2026-10-30T15:57:07-04:00', session_date: '2026-10-30' }
  check('(c) Friday P&L is current on Monday pre-open', deriveTodayPnlState(overview({ ...fridayPnl, market_session: { status: 'KNOWN', latest_open_session: '2026-10-30' } }), mondayPreOpen).agedSource === false)
  check('(c) Friday P&L is aged once Monday has opened', deriveTodayPnlState(overview({ ...fridayPnl, market_session: { status: 'KNOWN', latest_open_session: '2026-11-02' } }), mondayOpen).agedSource === true)
  const saturday = new Date('2026-10-31T12:00:00-04:00') // the day after that Friday
  check('(c) Friday P&L is current on Saturday', deriveTodayPnlState(overview({ ...fridayPnl, market_session: { status: 'KNOWN', latest_open_session: '2026-10-30' } }), saturday).agedSource === false)
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

  // Missing proof remains unknown; neither the face nor metadata can affirm it.
  const empty = deriveTodayPnlState(null, NOW)
  check('(d) a missing overview reports UNKNOWN without claiming an aged source or known census', empty.tone === 'warn' && empty.economicUnknown && empty.sessionUnknown && !empty.agedSource)
}

// Exact backend6b refusal: narrower row completeness and legacy amounts are not economic proof.
const refused = { status: 'UNKNOWN', complete: false, scope: 'ALL_ACCOUNTS_ECONOMIC_DAY',
  gap: { reason: 'Synthetic full-account day unproven', ticket: 'OI-044' }, session_date: null,
  funded_account_count: null, represented_account_count: null, unknown_rows: null,
  missing_accounts: null, partial_accounts: null, stored_row_evidence: { known_sum: 0, row_values_complete: true } }
const refusedInput = { today_pnl: refused, data_as_of: '2026-11-26T20:00:00Z', last_repriced: '2026-11-26T20:00:00Z',
  market_session: { status: 'KNOWN', latest_open_session: '2026-11-25' } }
const refusedBefore = JSON.stringify(refusedInput)
const refusal = deriveTodayPnlState(refusedInput, new Date('2026-11-26T20:00:00Z'))
check('economic UNKNOWN is visible with source gap/OI044', refusal.economicUnknown && refusal.tone === 'warn' && refusal.label?.includes('UNKNOWN') === true && refusal.reason?.includes('OI-044') === true)
check('null session never borrowed from fresh position/quote clocks', refusal.sessionUnknown && !refusal.agedSource)
check('null census and raw row completeness stay unchanged', JSON.stringify(refusedInput) === refusedBefore && refused.funded_account_count === null && refused.unknown_rows === null)
check('complete=true alone never supplies economic proof', deriveTodayPnlState({ today_pnl: { complete: true } }, NOW).economicUnknown)
check('backend unknown calendar never falls back to a client weekday', deriveTodayPnlState(overview({ ...currentPnl, market_session: { status: 'UNKNOWN', latest_open_session: null } }), NOW).sessionUnknown)
check('missing own P&L session never borrows calculation date', deriveTodayPnlState(overview({ ...currentPnl, session_date: null }), NOW).sessionUnknown)
check('invalid declared session is unknown', deriveTodayPnlState(overview({ ...currentPnl, session_date: '2026-02-30' }), NOW).sessionUnknown)
check('future declared session is unknown rather than fresh', deriveTodayPnlState(overview({ ...currentPnl, session_date: '2026-11-05' }), NOW).sessionUnknown)
const holidayPnl = { ...currentPnl, session_date: '2026-11-25', market_session: { status: 'KNOWN', latest_open_session: '2026-11-25' } }
check('Thanksgiving respects backend latest-open Nov25', !deriveTodayPnlState(overview(holidayPnl), new Date('2026-11-26T20:00:00Z')).agedSource)
check('Friday preopen respects same backend Nov25 reference', !deriveTodayPnlState(overview(holidayPnl), new Date('2026-11-27T14:29:59Z')).agedSource)
const fridayOpened = { ...holidayPnl, market_session: { status: 'KNOWN', latest_open_session: '2026-11-27' } }
check('Friday exact open ages Nov25 only when backend reference advances', deriveTodayPnlState(overview(fridayOpened), new Date('2026-11-27T14:30:00Z')).agedSource)
check('early close does not rewind backend session reference', deriveTodayPnlState(overview(fridayOpened), new Date('2026-11-27T20:00:00Z')).agedSource)

// Explicit refusal is different from an absent legacy calendar field.
const nullCalendar = deriveTodayPnlState({ today_pnl: { ...currentPnl, calculated_at: null, market_session: null }, market_session: { status: 'KNOWN', latest_open_session: '2026-11-04' } }, NOW)
check('explicit null calendar is not supplied by a different top snapshot', nullCalendar.sessionUnknown && nullCalendar.tone === 'warn' && !nullCalendar.agedSource)
const staleTopCalendar = deriveTodayPnlState({ today_pnl: { ...currentPnl, market_session: null }, market_session: { status: 'KNOWN', latest_open_session: '2026-11-03' } }, NOW)
check('explicit null calendar does not invent a future-session comparison', staleTopCalendar.sessionUnknown && !staleTopCalendar.reason?.includes('exceeds'))
const legacyPnl: TodayPnlPayload = { ...currentPnl }
delete legacyPnl.market_session
check('absent legacy nested field can use explicitly named top backend reference', !deriveTodayPnlState({ today_pnl: legacyPnl, market_session: { status: 'KNOWN', latest_open_session: '2026-11-04' } }, NOW).sessionUnknown)

console.log(`\ntodayPnlState: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
