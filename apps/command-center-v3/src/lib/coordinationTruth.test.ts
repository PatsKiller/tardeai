const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
  ok(value: unknown) { if (!value) throw new Error('expected truthy value') },
  match(value: string, pattern: RegExp) { if (!pattern.test(value)) throw new Error(`expected ${value} to match ${pattern}`) },
}
import { projectCoordination } from './coordinationEvents.ts'
const NOW = Date.parse('2026-10-18T16:00:00Z')
const missing = projectCoordination(null, { nowMs: NOW, transport: 'ERROR' })
assert.equal(missing.counts.waiting, null, 'missing backend cannot count zero waiting work')
const stale = projectCoordination({ schema: 'N8nCoordinationProjection@v1', status: 'OK', as_of: '2026-10-18T15:00:00Z', items: [] }, { nowMs: NOW, stale: true, transport: 'RETAINED' })
assert.equal(stale.status, 'STALE', 'retained payload cannot retain healthy OK status')
console.log('coordination truth assertions passed')
const full = projectCoordination({ schema: 'N8nCoordinationProjection@v2', status: 'OK', as_of: '2026-10-18T16:00:00Z', count: 2, total_count: 600,
  items: [{ state: 'CONSUMED', idempotency_key: 'one' }, { state: 'CONSUMED', idempotency_key: 'two' }],
  summary: { by_state: { CONSUMED: 600 }, by_lane: { research: 600 } }, coverage: { aggregation_complete: true, items_truncated: true, since: '2026-09-01', through: '2026-10-18' } }, { nowMs: NOW })
assert.equal(full.counts.consumed, 600); assert.equal(full.rows.length, 2); assert.equal(full.totalCount, 600)
assert.match(full.coverageLabel, /600 retained/); assert.match(full.coverageLabel, /no 24h filter/)
const retainedFailure = projectCoordination({ schema: 'N8nCoordinationProjection@v2', status: 'OK', as_of: '2026-10-18T16:00:00Z', items: [] }, { nowMs: NOW, error: true, transport: 'RETAINED' })
assert.equal(retainedFailure.status, 'STALE'); assert.equal(retainedFailure.counts.waiting, null)
const legacy = projectCoordination({ schema: 'N8nCoordinationProjection@v1', status: 'OK', items: [{ state: 'CONSUMED' }] }, { nowMs: NOW })
assert.equal(legacy.counts.consumed, 1); assert.equal(legacy.totalCount, null); assert.match(legacy.coverageLabel, /Legacy sample/)
const wrongVersion = projectCoordination({ schema: 'N8nCoordinationProjection@v99', status: 'OK', items: [{ state: 'CONSUMED' }] }, { nowMs: NOW })
assert.equal(wrongVersion.status, 'UNAVAILABLE'); assert.equal(wrongVersion.counts.consumed, null)
const badTotal = projectCoordination({ schema: 'N8nCoordinationProjection@v2', status: 'OK', as_of: '2026-10-18T16:00:00Z', items: [], total_count: 600,
  summary: { by_state: { CONSUMED: 500 } }, coverage: { aggregation_complete: true } }, { nowMs: NOW })
assert.equal(badTotal.status, 'PARTIAL'); assert.equal(badTotal.counts.consumed, null)

// A capture timestamp cannot establish prior successful source observation.
for (const status of ['UNAVAILABLE', 'STALE', 'OK']) {
  const payload = { schema: 'N8nCoordinationProjection@v2', status, as_of: '2026-10-18T16:00:00Z', last_good_at: null }
  assert.equal(projectCoordination(payload, { nowMs: NOW }).lastGoodAgeMinutes, null, `${status} explicit null is never a last-good capture`)
  assert.equal(projectCoordination(payload, { nowMs: NOW, error: true }).lastGoodAgeMinutes, null, `${status} explicit null is never retained last-good on API error`)
}
