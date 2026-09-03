// Pure-logic tests for retained-observation aging across 304 responses.
// Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/retainedObservation.test.ts
//
// Proves the transport liveness / data freshness separation: a 304 (or a
// failed refetch) retains the COMPLETE canonical observation envelope and only
// advances `receivedAt`. The data clock does not move, so the observation keeps
// aging toward stale even while the server keeps answering 304.
import {
  makeEnvelope,
  retainObservation,
  observationAgeHours,
  isObservationStale,
  stateLabel,
  type ObservationEnvelope,
} from './observationEnvelope.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// Observation seen at 2026-09-03T12:00:00Z, received by the browser 3s later.
const OBSERVED = '2026-09-03T12:00:00Z'
const RECEIVED0 = '2026-09-03T12:00:03Z'

function base(): ObservationEnvelope<number> {
  return makeEnvelope({
    identity: 'overview.portfolio_value',
    sourceLabel: '/api/v2/overview.portfolio_value',
    value: 1280958.39,
    businessDate: '2026-09-02',
    observedAt: OBSERVED,
    lastRefreshAt: OBSERVED,
    receivedAt: RECEIVED0,
    freshness: 'FRESH',
  })
}

// ── retention preserves the whole envelope, not just the value ───────────────
{
  const env = base()
  const r = retainObservation(env, '2026-09-03T12:05:00Z')

  check('retained value is unchanged', r.value === 1280958.39)
  check('retained identity is unchanged', r.identity === 'overview.portfolio_value')
  check('retained sourceLabel is unchanged', r.sourceLabel === '/api/v2/overview.portfolio_value')
  check('retained businessDate is unchanged', r.businessDate === '2026-09-02')
  check('retained observedAt is unchanged', r.observedAt === OBSERVED)
  check('retained lastRefreshAt is unchanged', r.lastRefreshAt === OBSERVED)
  check('retained freshness is unchanged', r.freshness === 'FRESH')
  check('retained transport is RETAINED', r.transport === 'RETAINED')
  check('retained receivedAt advances', r.receivedAt === '2026-09-03T12:05:00Z')
  check('retained envelope explains itself', !!r.note)
}

// ── the data clock, not the receipt clock, drives age ────────────────────────
{
  const now = Date.parse('2026-09-03T18:00:00Z')  // 6h after observation
  const env = base()
  const age = observationAgeHours(env, now)
  check('age is measured from observedAt', age != null && Math.abs(age - 6) < 0.001)

  // A retained observation at the same instant must report the same age: the
  // 304 receipt does not reset it.
  const r = retainObservation(env, '2026-09-03T17:59:59Z')
  const rage = observationAgeHours(r, now)
  check('retained observation ages identically', rage === age)
}

// ── repeated 304: age grows across each response, never resets ───────────────
{
  const observed = Date.parse(OBSERVED)
  const env = base()

  const t2 = observed + 2 * 3_600_000   // +2h
  const t4 = observed + 4 * 3_600_000   // +4h
  const t6 = observed + 6 * 3_600_000   // +6h

  const r2 = retainObservation(env, new Date(t2).toISOString())
  const r4 = retainObservation(r2, new Date(t4).toISOString())
  const r6 = retainObservation(r4, new Date(t6).toISOString())

  const a2 = observationAgeHours(r2, t2)
  const a4 = observationAgeHours(r4, t4)
  const a6 = observationAgeHours(r6, t6)

  check('age grows across repeated 304s', a2 === 2 && a4 === 4 && a6 === 6)
  check('data clock never moved', r6.observedAt === OBSERVED && r6.lastRefreshAt === OBSERVED)
  check('receipt clock tracked each 304', r6.receivedAt === new Date(t6).toISOString())
}

// ── staleness threshold: the retained observation crosses it on time ─────────
{
  const observed = Date.parse(OBSERVED)
  const env = base()
  const THRESHOLD = 4  // hours

  // At +2h it is not stale; at +4h (== threshold) it is; at +6h it remains stale.
  const r2 = retainObservation(env, new Date(observed + 2 * 3_600_000).toISOString())
  const r4 = retainObservation(env, new Date(observed + 4 * 3_600_000).toISOString())
  const r6 = retainObservation(env, new Date(observed + 6 * 3_600_000).toISOString())

  check('not stale below threshold',
    isObservationStale(r2, observed + 2 * 3_600_000, THRESHOLD) === false)
  check('stale AT the threshold',
    isObservationStale(r4, observed + 4 * 3_600_000, THRESHOLD) === true)
  check('stale past the threshold',
    isObservationStale(r6, observed + 6 * 3_600_000, THRESHOLD) === true)
}

// ── stale + retained renders both facts; a 304 never looks fresh ─────────────
{
  const observed = Date.parse(OBSERVED)
  const env = base()
  const late = retainObservation(env, new Date(observed + 6 * 3_600_000).toISOString())
  // The server verdict on the envelope is still FRESH, but the retained
  // transport state must still be visible — transport liveness is not data
  // freshness, and the retention itself is surfaced.
  check('retained observation surfaces the retention',
    stateLabel(late.transport, late.freshness) === 'RETAINED')

  // If the underlying data was already STALE, retention must say BOTH.
  const staleEnv = makeEnvelope({
    identity: 'x', sourceLabel: 's', value: 1, businessDate: '2026-08-26',
    observedAt: '2026-08-26T11:44:47Z', freshness: 'STALE',
  })
  const staleRetained = retainObservation(staleEnv, '2026-09-03T12:00:00Z')
  check('stale + retained renders both facts',
    stateLabel(staleRetained.transport, staleRetained.freshness) === 'STALE · RETAINED')
}

// ── undatable observation: no data clock → no age, but never a false stale ──
{
  const undatable = makeEnvelope({
    identity: 'x', sourceLabel: 's', value: null, transport: 'ERROR', freshness: 'UNKNOWN',
  })
  check('undatable observation has no age', observationAgeHours(undatable, Date.now()) === null)
  check('undatable observation is never stale', isObservationStale(undatable, Date.now(), 1) === false)
}

console.log(`\nretainedObservation: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
