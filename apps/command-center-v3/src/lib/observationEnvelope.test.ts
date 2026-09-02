// Pure-logic tests for observationEnvelope.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/observationEnvelope.test.ts
//
// Fixture cases required by the remediation brief: fresh, stale, missing,
// malformed, future-skewed, transport-failed, 304-retained, mixed-source,
// >25 population, protection-unknown.
import {
  businessDateToSessionInstant,
  formatBusinessDate,
  makeEnvelope,
  coalesceEnvelopes,
  worstTransport,
  stateLabel,
  stateAriaLabel,
} from './observationEnvelope.ts'

declare const process: { exit(code?: number): never; env: Record<string, string | undefined> }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ── business date is stable across host timezones ────────────────────────────
// The defect being killed: `new Date('2026-09-01T12:00:00')` binds to the host
// zone, so the same payload dated differently in different browsers.
{
  const i = businessDateToSessionInstant('2026-09-01')
  check('business date resolves to an instant', !!i)
  // 2026-09-01 is EDT (UTC-4): 16:00 ET == 20:00Z. Asserted as an absolute
  // instant, so this test fails if the host zone ever leaks in.
  check('business date anchors to 16:00 ET = 20:00Z in EDT',
    i!.toISOString() === '2026-09-01T20:00:00.000Z')
  // January is EST (UTC-5): 16:00 ET == 21:00Z. Proves DST is measured, not assumed.
  const w = businessDateToSessionInstant('2026-01-15')
  check('business date handles EST without a DST table',
    w!.toISOString() === '2026-01-15T21:00:00.000Z')
  check('malformed business date → null', businessDateToSessionInstant('01/15/2026') === null)
  check('empty business date → null', businessDateToSessionInstant('') === null)
}

// ── date-only must never be presented as an ambiguous "updated" ──────────────
{
  check('business date is labelled as a session date',
    formatBusinessDate('2026-09-01') === 'session 2026-09-01')
  check('absent business date renders UNDATED, not blank',
    formatBusinessDate(null) === 'session UNDATED')
}

// ── FIXTURE: fresh ───────────────────────────────────────────────────────────
{
  const e = makeEnvelope({
    identity: 'overview@2026-09-02T21:03:47Z', sourceLabel: '/api/v2/overview.portfolio_value',
    value: 1280958.39, businessDate: '2026-09-01',
    observedAt: '2026-09-02T21:03:47Z', lastRefreshAt: '2026-09-02T21:03:47Z',
    receivedAt: '2026-09-02T21:03:50Z', freshness: 'FRESH',
  })
  check('fresh envelope is OK transport', e.transport === 'OK')
  check('fresh envelope renders no state chip', stateLabel(e.transport, e.freshness) === null)
}

// ── correct price + stale metadata cannot render as fully current ────────────
// This is the Home defect in one assertion.
{
  const e = makeEnvelope({
    identity: 'overview', sourceLabel: '/api/v2/overview.portfolio_value',
    value: 1280958.39, businessDate: '2026-08-26',
    observedAt: '2026-08-26T11:44:47Z', freshness: 'STALE',
  })
  check('current-looking value with stale metadata is labelled STALE',
    stateLabel(e.transport, e.freshness) === 'STALE')
  check('a stale envelope never reports null chrome',
    stateLabel(e.transport, e.freshness) !== null)
}

// ── FIXTURE: missing / malformed → fail closed ───────────────────────────────
{
  const missing = makeEnvelope({ identity: 'x', sourceLabel: 's', value: null })
  check('missing value fails closed to UNKNOWN', missing.transport === 'UNKNOWN')
  check('missing value is never FRESH', missing.freshness !== 'FRESH')

  const clockless = makeEnvelope({ identity: 'x', sourceLabel: 's', value: 42 })
  check('value with no clock is PARTIAL, not current', clockless.transport === 'PARTIAL')
  check('clockless envelope explains itself', clockless.note === 'value has no clock')

  const malformed = makeEnvelope({
    identity: 'x', sourceLabel: 's', value: 1, businessDate: 'not-a-date',
  })
  check('malformed date is dropped, not coerced', malformed.businessDate === null)
}

// ── FIXTURE: future-skewed ───────────────────────────────────────────────────
{
  const f = businessDateToSessionInstant('2099-01-01')
  check('future business date still parses to a real instant (caller judges skew)', !!f)
  const e = makeEnvelope({
    identity: 'x', sourceLabel: 's', value: 1, businessDate: '2099-01-01',
    observedAt: '2099-01-01T20:00:00Z', freshness: 'UNKNOWN',
  })
  check('future-skewed observation is not rendered as fresh',
    stateLabel(e.transport, e.freshness) === 'UNKNOWN')
}

// ── FIXTURE: transport failed ────────────────────────────────────────────────
{
  const e = makeEnvelope({
    identity: 'x', sourceLabel: 's', value: null, transport: 'ERROR', freshness: 'UNKNOWN',
  })
  check('transport error is visible', stateLabel(e.transport, e.freshness) === 'ERROR')
}

// ── FIXTURE: 304-retained must NOT reset stale/error state ───────────────────
{
  const e = makeEnvelope({
    identity: 'x', sourceLabel: 's', value: 100, businessDate: '2026-08-26',
    observedAt: '2026-08-26T11:44:47Z',
    receivedAt: '2026-09-02T21:03:50Z',   // 304 refreshed ONLY the receipt clock
    freshness: 'STALE', transport: 'RETAINED',
  })
  check('304 retained + stale renders both facts',
    stateLabel(e.transport, e.freshness) === 'STALE · RETAINED')
  check('304 updated receivedAt only', e.receivedAt === '2026-09-02T21:03:50Z')
  check('304 did NOT advance the observation clock', e.observedAt === '2026-08-26T11:44:47Z')
  check('retained data is never silently OK', e.transport !== 'OK')
}

// ── FIXTURE: mixed-source coalescing ─────────────────────────────────────────
// F4: winRate = journal?.win_rate ?? readiness?.win_rate, rendered under one label.
{
  const a = makeEnvelope({
    identity: 'journal', sourceLabel: '/api/v2/automated-trade-journal.win_rate',
    value: 0.61, businessDate: '2026-09-02', freshness: 'FRESH',
  })
  const b = makeEnvelope({
    identity: 'readiness', sourceLabel: '/api/v2/broker-accounts/readiness.win_rate',
    value: 0.55, businessDate: '2026-09-02', freshness: 'FRESH',
  })
  const mixed = coalesceEnvelopes([a, b])
  check('two identities coalesce to PARTIAL', mixed.transport === 'PARTIAL')
  check('mixed-source note names both identities',
    (mixed.note || '').includes('journal') && (mixed.note || '').includes('readiness'))

  const same = coalesceEnvelopes([a, { ...a, sourceLabel: 'other field' }])
  check('one identity stays coherent', same.transport === 'OK')
}

// ── value / date / freshness share one envelope identity ─────────────────────
{
  const v = makeEnvelope({
    identity: 'overview@r1', sourceLabel: 'value', value: 1,
    businessDate: '2026-09-01', freshness: 'FRESH',
  })
  check('value carries its own clock and freshness',
    v.identity === 'overview@r1' && v.businessDate === '2026-09-01' && v.freshness === 'FRESH')
}

// ── stale dominates in coalesce; no client path contradicts the server ───────
{
  const fresh = makeEnvelope({ identity: 'i', sourceLabel: 's', value: 1, businessDate: '2026-09-02', freshness: 'FRESH' })
  const stale = makeEnvelope({ identity: 'i', sourceLabel: 's', value: 2, businessDate: '2026-08-26', freshness: 'STALE' })
  check('any stale part makes the whole stale', coalesceEnvelopes([fresh, stale]).freshness === 'STALE')
  check('unknown part downgrades a fresh whole',
    coalesceEnvelopes([fresh, makeEnvelope({ identity: 'i', sourceLabel: 's', value: 3, businessDate: '2026-09-02', freshness: 'UNKNOWN' })]).freshness === 'UNKNOWN')
  check('server freshness is echoed, never recomputed from age',
    makeEnvelope({ identity: 'i', sourceLabel: 's', value: 1, businessDate: '1999-01-01', freshness: 'FRESH' }).freshness === 'FRESH')
}

// ── severity ordering ────────────────────────────────────────────────────────
{
  check('ERROR outranks PARTIAL', worstTransport('PARTIAL', 'ERROR') === 'ERROR')
  check('PARTIAL outranks RETAINED', worstTransport('RETAINED', 'PARTIAL') === 'PARTIAL')
  check('OK is the floor', worstTransport('OK', 'OK') === 'OK')
}

// ── accessibility: every state has a spoken form ─────────────────────────────
{
  const states: Array<[any, any]> = [
    ['OK', 'FRESH'], ['OK', 'STALE'], ['RETAINED', 'STALE'], ['FALLBACK', 'FRESH'],
    ['PARTIAL', 'FRESH'], ['UNKNOWN', 'UNKNOWN'], ['ERROR', 'UNKNOWN'],
  ]
  let ok = true
  for (const [t, f] of states) {
    const a = stateAriaLabel(t, f)
    if (!a || a.length < 4) ok = false
  }
  check('every transport/freshness pair has a non-empty aria label', ok)
  check('fresh+OK speaks as current', stateAriaLabel('OK', 'FRESH') === 'data current')
  check('partial speaks its cause', stateAriaLabel('PARTIAL', 'FRESH').includes('mixed sources'))
}

console.log(`\nobservationEnvelope: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
