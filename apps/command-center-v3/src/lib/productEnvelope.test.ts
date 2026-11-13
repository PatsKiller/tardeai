// Stored-product envelopes on the combined Home (operator controlling decision 2026-11-13). Pins: source time and build
// time are separate fields; BUILDING / UNKNOWN / 503 / no envelope read UNKNOWN with a reason, never OK; a route that
// is not a stored product says so; two different versions of one path are a DEFECT. Synthetic values only.
import assert from 'node:assert/strict'
import { productClock, versionMismatch } from './productEnvelope.ts'

function env(status: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
  product: 'home.demo', scope: 'global', status, as_of: '2026-11-13T14:00:00Z', built_at: '2026-11-13T14:05:00Z',
  next_refresh_at: '2026-11-13T14:10:00Z', stale_after_s: 600, hard_expiry_s: 3600, age_s: 300, seq: 41, etag: 'e41',
  reason: null, data: { x: 1 }, served_from: 'pg', ...extra,
  }
}

{
  const c = productClock(env('OK'))
  assert.equal(c.verdict, 'OK')
  assert.equal(c.asOf, '2026-11-13T14:00:00Z', 'source time')
  assert.equal(c.builtAt, '2026-11-13T14:05:00Z', 'build time, kept apart from the source time')
  assert.equal(c.version, 'seq 41')
  assert.equal(c.staleAfterS, 600); assert.equal(c.hardExpiryS, 3600)
}
{
  // a fresh build over a stale source stays STALE (the producer decides from as_of; the reader keeps it)
  const c = productClock(env('STALE', { reason: 'stale: age 900s past stale_after 600s', built_at: '2026-11-13T19:00:00Z' }))
  assert.equal(c.verdict, 'STALE')
  assert.match(c.reason || '', /stale/)
}
for (const s of ['BUILDING', 'UNKNOWN', 'weird']) {
  const c = productClock(env(s, { reason: null, data: null }))
  assert.equal(c.verdict, 'UNKNOWN', `${s} is UNKNOWN`)
  assert.ok(c.reason, `${s} carries a reason, never blank`)
}
{
  const c = productClock({ status: 'BUILDING', reason: 'not built yet' }, 503)
  assert.equal(c.verdict, 'UNKNOWN'); assert.match(c.reason || '', /HTTP 503 — not built yet/)
}
{
  // { ...page, _product } shape (cio_pages_route)
  const c = productClock({ sections: [], _product: { status: 'OK', as_of: 'A', built_at: 'B', seq: 7, served_from: 'computed' } })
  assert.equal(c.status, 'OK'); assert.equal(c.version, 'seq 7'); assert.equal(c.servedFrom, 'computed')
}
{
  const c = productClock({ as_of: '2026-11-13T14:00:00Z', rows: [] })
  assert.equal(c.status, 'NOT A PRODUCT', 'a request-time route is named as such')
  assert.equal(c.verdict, 'UNKNOWN', 'no stored-product proof: UNKNOWN, never an all-clear')
  assert.equal(c.asOf, '2026-11-13T14:00:00Z', 'its own as_of is still shown')
  assert.equal(c.builtAt, null)
}
assert.equal(versionMismatch('/p', productClock(env('OK')), productClock(env('OK'))), null)
assert.match(versionMismatch('/p', productClock(env('OK')), productClock(env('OK', { seq: 42 })))!, /DEFECT: \/p drawn from two product versions \(seq 41 vs seq 42\)/)
assert.equal(versionMismatch('/p', productClock({}), productClock(env('OK'))), null, 'no version on one side: nothing to compare')
console.log('productEnvelope: ok')
