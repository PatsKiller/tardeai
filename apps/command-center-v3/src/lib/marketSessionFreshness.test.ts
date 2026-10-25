// Pinned by the same case table as tests/test_session_freshness_20261025.py, so the Python and
// TypeScript helpers cannot drift. Run: node --experimental-strip-types src/lib/marketSessionFreshness.test.ts
// No node:assert / node:fs: CI's tsc has no @types/node (same local check as designTokens.test.ts).
import { closedPhrase, marketIsOpen, marketViewNote, sessionFreshness, tradingAgeHours } from './marketSessionFreshness.ts'

function fail(msg: string): never { throw new Error(msg) }
const assert = {
  equal: (a: unknown, b: unknown, m = '') => { if (a !== b) fail(`${m}: expected ${String(b)} got ${String(a)}`) },
  ok: (c: unknown, m = 'assertion failed') => { if (!c) fail(m) },
}
const tableUrl = new URL('../../../../tests/fixtures/session_freshness/cases_20261025.json', import.meta.url).href
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const table: any = (await import(tableUrl, { with: { type: 'json' } })).default

for (const c of table.phrases) {
  assert.equal(closedPhrase(new Date(c.now)), c.phrase, c.why)
}
for (const c of table.evaluate) {
  const out = sessionFreshness({ asOf: c.as_of, now: new Date(c.now), maxAgeHours: c.max_age_h, closedMaxAgeHours: c.closed_max_age_h, graceMinutes: c.grace_minutes })
  assert.equal(out.state, c.state, c.why)
  assert.equal(out.stale, c.state === 'stale' || c.state === 'unknown', c.why)
  if (c.state === 'latest_close') assert.ok(out.phrase?.startsWith('Market closed · last close'), c.why)
}
for (const c of table.trading_age) {
  const h = tradingAgeHours(c.as_of, new Date(c.now))
  assert.ok(h !== null && Math.abs(h - c.hours) < 0.01, `${c.why}: ${h}`)
}
// DST edges: the first Monday after the November change still opens at 9:30 ET (14:30Z).
assert.equal(marketIsOpen(new Date('2026-11-02T14:29:00Z')), false)
assert.equal(marketIsOpen(new Date('2026-11-02T14:30:00Z')), true)
assert.equal(marketIsOpen(new Date('2026-03-09T13:30:00Z')), true)   // after the March change: 9:30 EDT
// Early close: day after Thanksgiving closes 1:00 PM ET.
assert.equal(marketIsOpen(new Date('2026-11-27T18:01:00Z')), false)
// CIO market view: Friday's close on Sunday is not overdue; on Monday during regular hours it is.
assert.equal(marketViewNote('2026-10-23T20:05:00+00:00', true, new Date('2026-10-25T20:00:00Z')), ' · Market closed · last close Fri 4:00 PM ET · next update Mon')
assert.equal(marketViewNote('2026-10-23T20:05:00+00:00', true, new Date('2026-10-26T15:00:00Z')), ' · Last published view; refresh overdue')
assert.equal(marketViewNote('2026-10-22T20:05:00+00:00', false, new Date('2026-10-25T20:00:00Z')), ' · Last published view; refresh overdue')
assert.equal(marketViewNote(null, true, new Date('2026-10-25T20:00:00Z')), ' · Last published view; refresh overdue')
assert.equal(marketViewNote('2026-10-26T14:00:00+00:00', false, new Date('2026-10-26T15:00:00Z')), '')
console.log('marketSessionFreshness: ok')
