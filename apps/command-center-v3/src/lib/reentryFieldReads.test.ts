// Pure-logic tests for reentryFieldReads.ts and the MACD half of reentryDecisionScorecard.ts.
// Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/reentryFieldReads.test.ts
//
// LQ-20261107-235: the re-entry page printed "MACD UNAVAILABLE" on every row even though the
// system holds the histogram's DIRECTION for most symbols, and printed "Catalyst: unavailable"
// for three different situations. These tests pin the replacement: a direction is reported as a
// direction and never dressed up as a magnitude, and the catalyst line distinguishes the cases.
import {
  buildReEntryScorecard,
  type ScorecardInput,
} from './reentryDecisionScorecard.ts'
import {
  catalystLabel,
  macdLabel,
  macdReadFromDeskRow,
} from './reentryFieldReads.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

function base(overrides: Partial<ScorecardInput> = {}): ScorecardInput {
  return {
    price: 100, asOf: new Date().toISOString(), rsi: 40, trend: 'IMPROVING',
    entryLow: 98, entryHigh: 102, stop: 95, target: 110, support: 97, resistance: 105,
    resistanceDistancePct: -4.8, resistanceSide: 'BELOW', ma20: 99, ma50: 98, ma200: 90,
    macdHistogram: 0.1, macdSlope: 0.02, relativeStrength: 1.2, pe: 22, forwardPe: 18,
    held: false, regimeLabel: 'RISK_ON', maxAgeHours: 96, avgExit: 120, exitDate: '2026-02-01',
    classified: 'CLASSIFIED', mandate: 'core', flags: ['growth'], eventGaps: 0,
    ...overrides,
  }
}

function macdGate(r: ReturnType<typeof buildReEntryScorecard>) {
  return r.gates.find(g => g.id === 'macd')
}

console.log('reentryFieldReads — LQ-20261107-235')

// --- macdReadFromDeskRow: the desk row's own vocabulary, nothing invented -------------------
{
  const read = macdReadFromDeskRow({ macd_histogram_direction: 'down', macd_signal: 'NEUTRAL' })
  check('desk row: direction down', read.direction === 'down')
  check('desk row: signal kept as stored', read.signal === 'NEUTRAL')
}
{
  const read = macdReadFromDeskRow({ macd_histogram_direction: 'UP', macd_signal: '' })
  check('desk row: direction normalised to lowercase', read.direction === 'up')
  check('desk row: empty signal becomes null', read.signal === null)
}
{
  const read = macdReadFromDeskRow({ macd_histogram_direction: 'sideways', macd_signal: 'BULLISH' })
  check('desk row: unknown direction refused', read.direction === null)
  check('desk row: signal still readable', read.signal === 'BULLISH')
}
{
  const read = macdReadFromDeskRow(null)
  check('no desk row: no direction', read.direction === null)
  check('no desk row: no signal', read.signal === null)
}

// --- macdLabel: a magnitude wins, a direction is labelled as one, absence says why ---------
{
  const l = macdLabel({
    histogram: 0.12, slope: 0.03,
    read: { direction: 'up', signal: 'BULLISH' }, onDesk: true,
  })
  check('magnitude: positive sign', l.label === 'pos↑')
  check('magnitude: no apology needed', l.why === null)
}
{
  const l = macdLabel({ histogram: -0.4, slope: null, read: { direction: null, signal: null }, onDesk: true })
  check('magnitude: negative sign, no arrow without a slope', l.label === 'neg')
  check('magnitude: no apology needed', l.why === null)
}
{
  const l = macdLabel({
    histogram: null, slope: null,
    read: { direction: 'down', signal: 'NEUTRAL' }, onDesk: true,
  })
  check('direction only: printed as a direction', l.label === 'down · neutral')
  check('direction only: nothing to explain', l.why === null)
  check('direction only: never claims a sign', !l.label.includes('pos') && !l.label.includes('neg'))
}
{
  const l = macdLabel({
    histogram: null, slope: null,
    read: { direction: 'up', signal: null }, onDesk: true,
  })
  check('direction only without a signal', l.label === 'up')
}
{
  const l = macdLabel({ histogram: null, slope: null, read: { direction: null, signal: null }, onDesk: true })
  check('on the desk, no MACD: n/a', l.label === 'n/a')
  check('on the desk, no MACD: says the snapshot is the gap', l.why === 'the indicator snapshot has no MACD for this symbol')
}
{
  const l = macdLabel({ histogram: null, slope: null, read: { direction: null, signal: null }, onDesk: false })
  check('not on the desk: n/a', l.label === 'n/a')
  check('not on the desk: says the symbol was never on it', l.why === 'this symbol is not on the re-entry decision desk')
}
{
  const l = macdLabel({ histogram: 0, slope: 0, read: { direction: 'down', signal: 'NEUTRAL' }, onDesk: true })
  check('zero histogram is a magnitude, not an absence', l.label === 'pos')
}

// --- catalystLabel: three cases that used to read as one word ------------------------------
{
  check('catalyst: the headline is shown as-is', catalystLabel({ catalyst_headline: 'Wins a supply contract' }) === 'Wins a supply contract')
  check('catalyst: blank headline is not evidence', catalystLabel({ catalyst_headline: '   ' }) === 'no catalyst headline on this symbol\'s watchlist row')
  check('catalyst: watch row without a headline', catalystLabel({ symbol: 'AAA' }) === 'no catalyst headline on this symbol\'s watchlist row')
  check('catalyst: no watch row at all', catalystLabel(null) === 'no watchlist row for this symbol')
}

// --- the scorecard's MACD gate decides from a direction where that is honest ---------------
{
  const g = macdGate(buildReEntryScorecard(base({ macdHistogram: null, macdSlope: null, macdDirection: 'up' })))
  check('gate: rising direction PASSes the improving clause', g?.state === 'PASS')
  check('gate: says it is direction only', Boolean(g?.current.includes('direction only')))
  check('gate: never claims a sign', !/hist 0\./.test(g?.current ?? ''))
}
{
  const g = macdGate(buildReEntryScorecard(base({ macdHistogram: null, macdSlope: null, macdDirection: 'down' })))
  check('gate: falling direction WAITs', g?.state === 'WAIT')
  check('gate: says falling', Boolean(g?.current.includes('falling')))
  check('gate: reason is not "negative" (sign unknown)', !(g?.why ?? '').toLowerCase().includes('negative'))
}
{
  const g = macdGate(buildReEntryScorecard(base({ macdHistogram: null, macdSlope: null })))
  check('gate: no magnitude and no direction stays UNAVAILABLE', g?.state === 'UNAVAILABLE')
}
{
  const g = macdGate(buildReEntryScorecard(base({ macdHistogram: 0.1, macdSlope: 0.02, macdDirection: 'down' })))
  check('gate: a magnitude outranks the direction', g?.state === 'PASS')
  check('gate: a magnitude is printed as one', Boolean(g?.current.startsWith('hist 0.100')))
}
{
  const r = buildReEntryScorecard(base({ macdHistogram: null, macdSlope: null, macdDirection: 'up' }))
  check('narrative: direction-only MACD is in the soft bits', r.reason.includes('MACD↑') || JSON.stringify(r).includes('MACD↑'))
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
