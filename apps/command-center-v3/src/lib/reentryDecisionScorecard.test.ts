// Pure-logic tests for reentryDecisionScorecard.ts. Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/reentryDecisionScorecard.test.ts
import {
  buildReEntryScorecard,
  extractLevelsFromContext,
  filterByLane,
  type ScorecardInput,
} from './reentryDecisionScorecard.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

function base(overrides: Partial<ScorecardInput> = {}): ScorecardInput {
  const asOf = new Date().toISOString()
  return {
    price: 100,
    asOf,
    rsi: 40,
    trend: 'IMPROVING',
    entryLow: 98,
    entryHigh: 102,
    stop: 95,
    target: 110,
    support: 97,
    resistance: 105,
    resistanceDistancePct: -4.8,
    resistanceSide: 'BELOW',
    ma20: 99,
    ma50: 98,
    ma200: 90,
    macdHistogram: 0.1,
    macdSlope: 0.02,
    relativeStrength: 1.2,
    pe: 22,
    forwardPe: 18,
    held: false,
    regimeLabel: 'RISK_ON',
    maxAgeHours: 96,
    ...overrides,
  }
}

console.log('reentryDecisionScorecard')

// READY: in zone, hard gates green, RSI <= 50
{
  const r = buildReEntryScorecard(base({ price: 100, rsi: 42 }))
  check('READY lane NOW', r.lane === 'NOW')
  check('READY state', r.state === 'READY TO REVIEW')
  check('READY has hard passes', r.hardPass === r.hardTotal)
  check('READY action', r.action.includes('Review'))
}

// NEAR: just above zone
{
  const r = buildReEntryScorecard(base({ price: 104, rsi: 48 })) // ~2% above high 102
  check('NEAR lane', r.lane === 'NEAR')
  check('NEAR state', r.state === 'NEAR ENTRY')
}

// WAIT: far above zone
{
  const r = buildReEntryScorecard(base({ price: 130, rsi: 55 }))
  check('WAIT far above', r.lane === 'WATCH' && r.state === 'WAIT')
}

// HELD override
{
  const r = buildReEntryScorecard(base({ held: true, price: 100, rsi: 40 }))
  check('HELD lane WATCH', r.lane === 'WATCH')
  check('HELD state', r.state === 'CURRENTLY HELD')
}

// MISSING MARKET
{
  const r = buildReEntryScorecard(base({ price: null, rsi: null }))
  check('MISSING MARKET', r.state === 'MISSING MARKET' && r.lane === 'WATCH')
}

// MISSING PLAN
{
  const r = buildReEntryScorecard(base({ entryLow: null, entryHigh: null }))
  check('MISSING PLAN', r.state === 'MISSING PLAN')
}

// STALE
{
  const old = new Date(Date.now() - 200 * 36e5).toISOString()
  const r = buildReEntryScorecard(base({ asOf: old }))
  check('STALE when asOf old', r.state === 'STALE')
}

// Soft valuation extreme does not block READY if hard green
{
  const r = buildReEntryScorecard(base({ pe: 100, forwardPe: 90, price: 100, rsi: 40 }))
  check('extreme PE still READY if hard pass', r.lane === 'NOW' && r.state === 'READY TO REVIEW')
  const val = r.gates.find(g => g.id === 'valuation')
  check('valuation soft WAIT when extreme', val?.state === 'WAIT')
}

// extractLevelsFromContext
{
  const levels = extractLevelsFromContext(
    {
      price: 50,
      rsi_14: 33,
      last_enriched_at: new Date().toISOString(),
      decision_packet: {
        selected_family: { mechanics: { entry_low: 48, entry_high: 52, stop: 45, target: 60 } },
      },
      fundamentals: { pe: 15, forward_pe: 12 },
    },
    {},
  )
  check('extract price', levels.price === 50)
  check('extract rsi', levels.rsi === 33)
  check('extract entry', levels.entryLow === 48 && levels.entryHigh === 52)
  check('extract pe', levels.pe === 15 && levels.forwardPe === 12)
}

// filterByLane
{
  const rows = [
    { score: { lane: 'NOW' as const } },
    { score: { lane: 'NEAR' as const } },
    { score: { lane: 'WATCH' as const } },
  ]
  check('filter NOW', filterByLane(rows, 'NOW').length === 1)
  check('filter NEAR', filterByLane(rows, 'NEAR').length === 1)
  check('filter WATCH', filterByLane(rows, 'WATCH').length === 1)
  check('filter ALL', filterByLane(rows, 'ALL').length === 3)
}

// Fail-closed: location UNAVAILABLE without zone
{
  const r = buildReEntryScorecard(base({ entryLow: null, entryHigh: null, price: 100, rsi: 40 }))
  const loc = r.gates.find(g => g.id === 'location')
  check('location UNAVAILABLE without plan', loc?.state === 'UNAVAILABLE')
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
