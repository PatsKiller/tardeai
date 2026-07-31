// Pure-logic tests for reentryDecisionScorecard.ts. Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/reentryDecisionScorecard.test.ts
import {
  buildReEntryScorecard,
  checkPlanIntegrity,
  composeDecisionNarrative,
  computeRiskReward,
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
    avgExit: 120,
    exitDate: '2026-02-01',
    classified: 'CLASSIFIED',
    mandate: 'core',
    flags: ['growth'],
    eventGaps: 0,
    ...overrides,
  }
}

console.log('reentryDecisionScorecard v1.5')

// READY: in zone, hard gates green, RSI <= 50
{
  const r = buildReEntryScorecard(base({ price: 100, rsi: 42 }))
  check('READY lane NOW', r.lane === 'NOW')
  check('READY state', r.state === 'READY TO REVIEW')
  check('READY has hard passes', r.hardPass === r.hardTotal)
  check('READY action', r.action.includes('Review'))
  check('READY reason has price', r.reason.includes('100') || r.reason.includes('$100'))
  check('READY reason has RSI', r.reason.includes('42') || r.reason.includes('RSI'))
  check('READY reason not generic-only', !/^Price is inside the entry zone and/.test(r.reason))
  check('READY has highlights', r.highlights.length >= 1)
  check('READY R:R present', r.riskReward !== null && r.riskReward > 0)
}

// Symbol-specific: TSLA-like vs JEPQ-like reasons differ
{
  const tsla = buildReEntryScorecard(base({
    price: 307.58, rsi: 26.1, entryLow: 300.69, entryHigh: 313.50, stop: 295, target: 320,
    resistance: 406.51, resistanceDistancePct: -25.1, resistanceSide: 'BELOW',
    avgExit: 395.54, exitDate: '2026-02-05', classified: 'AUTO-TAGGED', mandate: 'unclassified',
    analystRec: 'BUY', analystCount: 40, eventGaps: 2, pe: null, forwardPe: null, ma50: null, ma200: null, macdHistogram: null,
  }))
  const jepq = buildReEntryScorecard(base({
    price: 57.99, rsi: 32.1, entryLow: 57.20, entryHigh: 58.50, stop: 56.50, target: 62,
    resistance: 60.51, resistanceDistancePct: -4.3, resistanceSide: 'BELOW',
    avgExit: 58.35, exitDate: '2025-12-01', classified: 'CLASSIFIED', mandate: 'core',
    flags: ['growth', 'dividend'], pe: null, forwardPe: null,
  }))
  check('TSLA READY', tsla.state === 'READY TO REVIEW')
  check('JEPQ READY', jepq.state === 'READY TO REVIEW')
  check('narratives differ', tsla.reason !== jepq.reason)
  check('TSLA mentions 307 or zone', /307|300\.69|313/.test(tsla.reason))
  check('JEPQ mentions 57 or zone', /57\.|58\./.test(jepq.reason))
  check('TSLA unclassified note', /unclassif/i.test(tsla.reason))
  check('TSLA vs exit', tsla.vsExitPct !== null && tsla.vsExitPct < 0)
}

// NEAR: just above zone
{
  const r = buildReEntryScorecard(base({ price: 104, rsi: 48 }))
  check('NEAR lane', r.lane === 'NEAR')
  check('NEAR state', r.state === 'NEAR ENTRY')
  check('NEAR reason has pct', r.reason.includes('%') || r.reason.includes('above'))
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

// Plan integrity: VIVS-class inverted stop/target cannot READY
{
  const r = buildReEntryScorecard(base({
    price: 0.33, rsi: 17.1, entryLow: 0.33, entryHigh: 0.40, stop: 0.35, target: 0.30,
  }))
  check('inverted plan not READY', r.state !== 'READY TO REVIEW')
  check('plan integrity gate WAIT', r.gates.find(g => g.id === 'plan_integrity')?.state === 'WAIT')
  check('planIntegrityOk false', r.planIntegrityOk === false)
  check('narrative mentions plan', /plan|stop|target/i.test(r.reason))
}

// Resistance sanity: AMD-class price far above resistance level
{
  const r = buildReEntryScorecard(base({
    price: 487.90, rsi: 35.4, entryLow: 475, entryHigh: 505, stop: 452, target: 555,
    resistance: 220.27, resistanceDistancePct: 120.2, resistanceSide: 'ABOVE',
    avgExit: 161.34,
  }))
  check('AMD still can READY (zone+RSI hard)', r.state === 'READY TO REVIEW' || r.lane === 'NEAR')
  const res = r.gates.find(g => g.id === 'resistance')
  check('resistance soft WAIT when suspect', res?.state === 'WAIT')
  check('reason mentions suspect or res', /suspect|res|220|resistance/i.test(r.reason))
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

// helpers
{
  check('integrity ok', checkPlanIntegrity(98, 102, 95, 110).ok === true)
  check('integrity fail stop>=target', checkPlanIntegrity(0.33, 0.4, 0.35, 0.3).ok === false)
  check('R:R ~2', Math.abs((computeRiskReward(100, 95, 110) ?? 0) - 2) < 0.01)
  const n = composeDecisionNarrative(base({ price: 100, rsi: 40 }), {
    state: 'READY TO REVIEW', distancePct: 0, riskReward: 2, rsiBand: 'pullback',
    vsExitPct: -16.7, planIntegrityOk: true, planIntegrityWhy: 'ok', resistanceSuspect: false,
  })
  check('compose has zone', /98|102|100/.test(n.reason))
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
