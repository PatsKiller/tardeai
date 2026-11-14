// Combined Home item 1 (operator controlling decision 2026-11-13 §2): absolute source / build / check times with
// relative ages COMPUTED AT RENDER; a fresh build never makes a stale source look fresh; each slice ages from its own
// source clock. Synthetic envelopes only. (productEnvelope.test.ts is held by the release integrator; this file adds
// the render-time clock cases without touching it.)
import assert from 'node:assert/strict'
import { clockAges, clockAt, productClock } from './productEnvelope.ts'

const NOW = Date.parse('2026-11-13T14:00:00Z')

function env(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    product: 'home.demo', scope: 'global', status: 'OK', as_of: '2026-11-13T12:00:00Z',
    built_at: '2026-11-13T14:00:00Z', next_refresh_at: '2026-11-13T14:10:00Z',
    stale_after_s: 600, hard_expiry_s: 7200, age_s: 60, seq: 41, etag: 'e41', reason: null,
    data: { x: 1 }, served_from: 'pg', ...extra,
  }
}

// 1. The age comes from as_of and the CLIENT clock, not the served age_s (which said 60 s).
{
  const c = clockAt(productClock(env()), NOW)
  assert.equal(c.ageS, 7200, '2 h from as_of at the render clock, not the stored age_s of 60')
  assert.equal(c.status, 'STALE', 'a served OK whose source is 2 h old is stale at render')
  assert.match(c.reason || '', /source 7200s old > stale after 600s/)
}

// 2. The same payload rendered later ages further: nothing about the relative age was stored.
{
  const a = clockAt(productClock(env()), NOW)
  const b = clockAt(productClock(env()), NOW + 3_600_000)
  assert.equal(b.ageS, (a.ageS ?? 0) + 3600, 'one hour of client time moves the age by one hour')
}

// 3. A FRESH BUILD never makes a stale source look fresh: built_at is NOW, as_of is two hours old.
{
  const c = clockAt(productClock(env({ built_at: '2026-11-13T14:00:00Z' })), NOW)
  assert.equal(c.status, 'STALE')
  const ages = clockAges(c, NOW)
  assert.equal(ages.source, '2 h 0 m old', 'source age is drawn from as_of')
  assert.equal(ages.built, '<1 m ago', 'build age is drawn separately from built_at')
}

// 4. as_of_basis=build_time (LQ-3136): freshness is judged from source_as_of, never from the build-time as_of.
{
  const c = clockAt(productClock(env({ as_of_basis: 'build_time', as_of: '2026-11-13T14:00:00Z', source_as_of: '2026-11-13T12:00:00Z' })), NOW)
  assert.equal(c.status, 'STALE', 'a build clock of NOW cannot rescue a source clock of 12:00')
  assert.equal(c.ageS, 7200)
  const ages = clockAges(c, NOW)
  assert.equal(ages.source, '2 h 0 m old')
  assert.equal(ages.built, '<1 m ago')
}

// 5. as_of_basis=build_time with NO source clock: no age is invented from the build clock; the served verdict stands.
{
  const c = clockAt(productClock(env({ as_of_basis: 'build_time', as_of: '2026-11-13T14:00:00Z', source_as_of: null })), NOW)
  assert.equal(c.ageS, null, 'a build time is not a source age')
  assert.equal(c.verdict, 'OK', 'without a source clock this page cannot re-judge freshness')
  assert.match(c.reason || '', /source time unavailable/)
  assert.equal(clockAges(c, NOW).source, '', 'the source age cell stays empty (Source time unavailable is in the cell)')
  assert.equal(clockAges(c, NOW).built, '<1 m ago')
}

// 6. A request-time route still ages its own as_of at render.
{
  const c = clockAt(productClock({ as_of: '2026-11-13T12:00:00Z', rows: [] }), NOW)
  assert.equal(c.status, 'NOT A PRODUCT')
  assert.equal(c.ageS, 7200)
  assert.equal(clockAges(c, NOW).source, '2 h 0 m old')
}

// 7. Hard expiry is judged on the source clock too.
{
  const c = clockAt(productClock(env({ hard_expiry_s: 3600 })), NOW)
  assert.equal(c.verdict, 'UNKNOWN')
  assert.match(c.reason || '', /past hard expiry/)
}

// 8. A stamp slightly ahead of the client clock reads "<1 m old", never a negative age.
{
  const c = clockAt(productClock(env({ as_of: '2026-11-13T14:05:00Z', stale_after_s: 600 })), NOW)
  assert.equal(c.ageS, 0)
  assert.equal(clockAges(c, NOW).source, '<1 m old')
}

// 9. source_clock basis (or no basis) keeps as_of as the source cell and built_at as the build cell.
{
  const c = clockAt(productClock(env({ as_of_basis: 'source_clock', source_as_of: '2026-11-13T12:00:00Z' })), NOW)
  assert.equal(c.ageS, 7200)
  const ages = clockAges(c, NOW)
  assert.equal(ages.source, '2 h 0 m old')
  assert.equal(ages.built, '<1 m ago')
}

console.log('productEnvelope.clock: ok')
