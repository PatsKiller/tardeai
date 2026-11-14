// Stored-product envelopes on the combined Home (operator controlling decision 2026-11-13). Pins: source time and build
// time are separate fields; BUILDING / UNKNOWN / 503 / no envelope read UNKNOWN with a reason, never OK; a route that
// is not a stored product says so; two different versions of one path are a DEFECT. Synthetic values only.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { clockCells, productClock, versionMismatch } from './productEnvelope.ts'

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
// LQ-3136 (operator data contract): a build-time as_of is labelled "Built", never "as of"; no source time says so.
{
  const fmt = (iso: string) => `T(${iso})`
  const bt = productClock(env('OK', { as_of_basis: 'build_time', source_as_of: null, source_time_reason: 'source time unavailable: x' }))
  assert.equal(bt.asOfBasis, 'build_time'); assert.equal(bt.sourceAsOf, null)
  assert.equal(bt.sourceTimeReason, 'source time unavailable: x')
  const cb = clockCells(bt, fmt)
  assert.equal(cb.source, 'Source time unavailable', 'no source clock: said explicitly')
  assert.equal(cb.built, 'Built T(2026-11-13T14:00:00Z)', 'a build-time as_of is drawn as Built <time>')
  assert.doesNotMatch(`${cb.source} ${cb.built}`, /as of|updated/i, 'a build time is never worded as of / updated')
  // the basis may also sit in the bundle entry's source_watermarks._product
  const wm = productClock(env('OK', { source_watermarks: { _product: { as_of_basis: 'build_time', source_as_of: null } } }))
  assert.equal(wm.asOfBasis, 'build_time'); assert.equal(clockCells(wm, fmt).source, 'Source time unavailable')
  assert.match(wm.sourceTimeReason!, /source time unavailable/)
  // a real source time next to a build-time as_of is shown as the source
  const both = clockCells(productClock(env('OK', { as_of_basis: 'build_time', source_as_of: '2026-11-13T13:00:00Z' })), fmt)
  assert.equal(both.source, 'T(2026-11-13T13:00:00Z)'); assert.match(both.built, /^Built /)
  // source_clock basis and an envelope with no basis keep the old cells (source = as_of, built = built_at)
  for (const e of [env('OK', { as_of_basis: 'source_clock', source_as_of: '2026-11-13T14:00:00Z' }), env('OK')]) {
    const c = clockCells(productClock(e), fmt)
    assert.equal(c.source, 'T(2026-11-13T14:00:00Z)'); assert.equal(c.built, 'T(2026-11-13T14:05:00Z)')
  }
  assert.equal(productClock(env('OK')).asOfBasis, null); assert.equal(productClock(env('OK')).sourceTimeReason, null)
  // a basis-less envelope never invents a source time or reason from a stray field
  assert.equal(productClock(env('OK', { source_as_of: '2026-11-13T09:00:00Z' })).sourceAsOf, null)
  // the Home table draws its two clock cells through clockCells, not by formatting as_of directly
  const page = readFileSync(new URL('../pages/HomeCombined.tsx', import.meta.url), 'utf8')
  assert.match(page, /clockCells\(c, iso => etTime\(iso, true\)\)/)
  assert.doesNotMatch(page, /\{t\(r\.clock\.asOf\)\}/, 'the source cell must not format a build-time as_of as a source time')
}
console.log('productEnvelope: ok')
