import { projectionReadPath, type ProjectionRead } from './projectionReadProtocol.ts'
const assert = {
  equal(a: unknown, b: unknown) { if (a !== b) throw new Error(`${String(a)} !== ${String(b)}`) },
  ok(value: unknown) { if (!value) throw new Error('expected truthy value') },
  notEqual(a: unknown, b: unknown) { if (a === b) throw new Error('expected distinct values') },
  throws(fn: () => unknown, pattern: RegExp) {
    let refused = false
    try { fn() } catch (error) { refused = pattern.test(String(error)) }
    if (!refused) throw new Error('expected refusal')
  },
}

for (const kind of ['today', 'events', 'runs', 'outbox'] as ProjectionRead[]) {
  const path = projectionReadPath(kind)
  const url = new URL(path, 'https://fixture.invalid')
  assert.equal(url.searchParams.get('projection_version'), '2')
  assert.equal(url.searchParams.getAll('projection_version').length, 1)
  assert.ok(path.startsWith('/api/v2/coordination/'))
  assert.notEqual(path, path.replace(/[?&]projection_version=2/, ''))
}
assert.equal(new URL(projectionReadPath('runs'), 'https://fixture.invalid').searchParams.get('source'), 'runs')
assert.throws(() => projectionReadPath('broker' as ProjectionRead), /unsupported projection/)
console.log('projectionReadProtocol: explicit major, separate URL cache keys and closed read catalogue passed')
