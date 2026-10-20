import { rotationAvailability } from './rotationPublication.ts'
const assert = { equal(actual: unknown, expected: unknown) {
  if (!Object.is(actual, expected)) throw new Error(`Expected ${String(expected)}, received ${String(actual)}`)
} }

const now = Date.parse('2026-10-18T22:00:00Z')
const at = '2026-10-18T21:59:00Z'
const valid = { ok: true, publication: {
  schema: 'RotationPublication@v1', status: 'READY', reasons: [], checked_at: at,
  source_as_of: at, cache_generated_at: at, input_sha256: 'a'.repeat(64), producer_ok: true,
  source_as_of_basis: 'oldest_required_position_or_account_timestamp',
  coverage: { required_positions: 1, dated_positions: 1, accounts: 1, dated_accounts: 1 },
  accounts: [{ account_key: 'fixture', state: 'LIVE', source_as_of: at }],
} }
assert.equal(rotationAvailability(valid, null, now).ready, true)
assert.equal(rotationAvailability(valid, 'HTTP 503', now).status, 'UNAVAILABLE')
assert.equal(rotationAvailability(valid, 'HTTP 503', now).sourceAsOf, at)
for (const status of ['STALE', 'UNAVAILABLE']) {
  const observation = rotationAvailability({ ...valid, publication: { ...valid.publication, status, reasons: ['account_stale'] } }, null, now)
  assert.equal(observation.ready, false)
  assert.equal(observation.status, status)
}
for (const schema of [undefined, 'RotationPublication@v0', 'RotationPublication@v2']) {
  assert.equal(rotationAvailability({ ...valid, publication: { ...valid.publication, schema } }, null, now).status, 'UNAVAILABLE')
}
for (const status of [['READY'], { toString: null }, null, true, 1]) {
  const observation = rotationAvailability({ ...valid, publication: { ...valid.publication, status } }, null, now)
  assert.equal(observation.ready, false)
  assert.equal(observation.status, 'UNAVAILABLE')
}
assert.equal(rotationAvailability({ ...valid, publication: { ...valid.publication, checked_at: '2026-10-18T21:44:59Z' } }, null, now).status, 'STALE')
assert.equal(rotationAvailability({ ...valid, publication: { ...valid.publication, checked_at: '2026-10-18T22:01:00Z' } }, null, now).status, 'UNAVAILABLE')
for (const override of [{ accounts: [] }, { input_sha256: 'fake' }, { reasons: ['unsupported_stop_claim'] }, { producer_ok: false }, { source_as_of: null }, { cache_generated_at: null }, { checked_at: '2026-10-18 21:59:00' }, { coverage: null }, { coverage: { required_positions: 2, dated_positions: 1, accounts: 1, dated_accounts: 1 } }, { source_as_of_basis: 'loader_clock' }]) {
  assert.equal(rotationAvailability({ ...valid, publication: { ...valid.publication, ...override } }, null, now).ready, false)
}
assert.equal(rotationAvailability({ ...valid, ok: false }, null, now).ready, false)
assert.equal(rotationAvailability(null, null, now).status, 'UNAVAILABLE')
assert.equal(rotationAvailability({ ...valid, publication: { ...valid.publication, cache_generated_at: '2026-10-18T21:44:59Z' } }, null, now).status, 'STALE')
assert.equal(rotationAvailability({ ...valid, publication: { ...valid.publication, cache_generated_at: '2026-10-18T22:01:00Z' } }, null, now).status, 'UNAVAILABLE')
console.log('rotation publication display contract: passed')
