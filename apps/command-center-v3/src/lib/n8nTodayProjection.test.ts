const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
  ok(value: unknown) { if (!value) throw new Error('expected truthy value') },
  match(value: string, pattern: RegExp) { if (!pattern.test(value)) throw new Error(`expected ${value} to match ${pattern}`) },
}
import { projectN8nToday, displayCount, type N8nTodayPayload } from './n8nTodayProjection.ts'
const NOW = Date.parse('2026-10-18T16:00:00Z')
const complete: N8nTodayPayload = { schema: 'N8nToday@v2', status: 'OK', as_of: '2026-10-18T16:00:00Z',
  runs: { totals: { live: 0, dry_run: 4 } }, failures_total: 0, lock_skips: [], heals_total: 2, diagnoses: { total: 3 }, cutovers_total: 0,
  coverage: { sources: { runs: { complete: true }, relay: { complete: true }, diagnoses: { complete: true }, cutovers: { complete: true } },
    window: { since: '2026-10-18T04:00:00Z', through: '2026-10-18T16:00:00Z', timezone: 'America/New_York' }, run_namespaces: { included: ['d', 'e', 'g', 'p'], excluded: 'undated keys excluded' } } }
const unavailable = projectN8nToday(null, { error: true, nowMs: NOW })
assert.equal(unavailable.status, 'UNAVAILABLE'); assert.equal(unavailable.counts.live, null)
assert.equal(displayCount(unavailable.counts.failures), 'UNAVAILABLE'); assert.ok(!unavailable.empty('runs').includes('No matching'))
const success = projectN8nToday(complete, { nowMs: NOW })
assert.equal(success.counts.live, 0); assert.equal(success.counts.recoveryActions, 2)
assert.match(success.empty('runs'), /observed coverage/); assert.match(success.coverageLabel, /d, e, g, p/)
const retainedError = projectN8nToday(complete, { error: true, nowMs: NOW + 60_000 })
assert.equal(retainedError.status, 'STALE'); assert.equal(retainedError.counts.live, null); assert.equal(retainedError.lastGoodAgeSeconds, 60)
const stale = projectN8nToday(complete, { nowMs: NOW + 4 * 60_000 })
assert.equal(stale.status, 'STALE'); assert.equal(stale.counts.live, null)
const partial = projectN8nToday({ ...complete, status: 'PARTIAL', coverage: { ...complete.coverage, sources: { runs: { complete: false }, diagnoses: { complete: true } } } }, { nowMs: NOW })
assert.equal(partial.counts.live, null); assert.equal(partial.counts.diagnoses, 3)
assert.match(partial.empty('runs'), /UNAVAILABLE/)
const legacy = projectN8nToday({ schema: 'N8nToday@v1', status: 'OK', as_of: complete.as_of, runs: { totals: { live: 5 } } }, { nowMs: NOW })
assert.equal(legacy.status, 'PARTIAL'); assert.equal(legacy.counts.live, null); assert.match(legacy.coverageLabel, /Legacy/)
const future = projectN8nToday({ ...complete, schema: 'N8nToday@v99' }, { nowMs: NOW })
assert.equal(future.status, 'UNAVAILABLE'); assert.equal(future.data, null)
assert.equal(projectN8nToday({ ...complete, as_of: '2099-01-01T00:00:00Z' }, { nowMs: NOW }).counts.live, null)
console.log('n8nTodayProjection: unavailable/stale/partial, exact source coverage, v1/v2 and unknown-version cases passed')

// A capture timestamp cannot establish prior successful source observation.
for (const status of ['UNAVAILABLE', 'STALE', 'OK']) {
  const payload = { schema: 'N8nToday@v2', status, as_of: '2026-10-18T16:00:00Z', last_good_at: null }
  assert.equal(projectN8nToday(payload, { nowMs: NOW }).lastGoodAgeSeconds, null, `${status} explicit null is never a last-good capture`)
  assert.equal(projectN8nToday(payload, { nowMs: NOW, error: true }).lastGoodAgeSeconds, null, `${status} explicit null is never retained last-good on API error`)
}
