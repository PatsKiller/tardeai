// Combined Home regression set (operator controlling decision 2026-11-13, item 4): shared polling (two sections -> one
// fetch), stale products, overlapping requests deduped, hidden-tab pause, recovery after an error, and the
// /api/v2/products/home read while that route is not yet served. Synthetic values only.
import assert from 'node:assert/strict'
import { readShared } from './sharedRead.ts'
import { resetInFlight } from './inflightGet.ts'
import { noteLastGood, peekLastGood, resetLastGood, sharedPollAction, subscribeBody } from '../hooks/useApi.ts'
import { PRODUCTS_HOME_API, clockAt, productClock, productsFromBundle } from './productEnvelope.ts'

function fakeFetch(answers: Array<{ status: number; body?: string; delayMs?: number }>) {
  const calls: string[] = []
  const impl = (async (url: string) => {
    calls.push(String(url))
    const a = answers[Math.min(calls.length - 1, answers.length - 1)]
    if (a.delayMs) await new Promise(r => setTimeout(r, a.delayMs))
    return new Response(a.status === 304 ? null : (a.body ?? '{}'), { status: a.status })
  }) as unknown as typeof fetch
  return { impl, calls }
}
const reset = () => { resetInFlight(); resetLastGood() }
const T0 = Date.parse('2026-11-13T15:00:00Z')

// ── 1. shared polling: the classic hook polled the path; the operational section's read makes no request ─────────
reset()
{
  const path = '/api/v2/home/since-close'
  const f = fakeFetch([{ status: 200, body: '{"ok":true,"data":{"n":1}}' }])
  // classic section (SinceCloseCard's useApi) reads once: one GET, body recorded for every subscriber
  const classic = await readShared<{ n: number }>(path, { fetchImpl: f.impl, nowMs: () => T0 })
  const heard: unknown[] = []
  const off = subscribeBody(path, j => heard.push(j))
  // operational section mounts 20 s later
  const operational = await readShared<{ n: number }>(path, { fetchImpl: f.impl, nowMs: () => T0 + 20_000 })
  assert.equal(f.calls.length, 1, 'two sections, one path, one poll cycle: exactly one fetch')
  assert.deepEqual(classic.data, operational.data, 'both sections draw the same body')
  assert.equal(classic.at, operational.at, 'and the same receipt clock')
  // the classic hook's next poll body reaches the operational section without a request of its own
  noteLastGood(path, { ok: true, data: { n: 2 } }, T0 + 60_000)
  assert.deepEqual(heard, [{ ok: true, data: { n: 2 } }], 'the section is a passive subscriber: redraws from the poll body')
  off()
}
// a second polling subscriber of the same path inside its cadence reuses, never re-reads
assert.equal(sharedPollAction({ held: { at: T0 }, nowMs: T0 + 30_000, intervalMs: 60_000, manual: false, visible: true, reason: 'tick' }), 'reuse')

// ── 2. overlapping identical requests are deduped ──────────────────────────────────────────────────────────────
reset()
{
  const f = fakeFetch([{ status: 200, body: '{"x":1}', delayMs: 10 }])
  const rs = await Promise.all(Array.from({ length: 5 }, () => readShared<{ x: number }>('/api/v2/home' + '/approvals/summary', { fetchImpl: f.impl })))
  assert.equal(f.calls.length, 1, 'five overlapping reads of one path: one request')
  for (const r of rs) assert.equal(r.state, 'OK')
}

// ── 3. hidden tab pauses polling; visible-again reads once ─────────────────────────────────────────────────────
for (let i = 0; i < 10; i++) {
  assert.equal(sharedPollAction({ held: { at: T0 }, nowMs: T0 + i * 60_000, intervalMs: 60_000, manual: false, visible: false, reason: 'tick' }), 'paused',
    `hidden tab, tick ${i}: no request`)
}
assert.equal(sharedPollAction({ held: { at: T0 }, nowMs: T0 + 600_000, intervalMs: 60_000, manual: false, visible: true, reason: 'visible' }), 'fetch',
  'visible again with a 10-minute-old body: one read at once')

// ── 4. recovery after an error ─────────────────────────────────────────────────────────────────────────────────
reset()
{
  const path = '/api/v2/home/status'
  const f = fakeFetch([{ status: 500, body: '{"error":"boom"}' }, { status: 200, body: '{"ok":true,"data":{"gates":[]}}' }])
  const heard: unknown[] = []
  const off = subscribeBody(path, j => heard.push(j))
  const bad = await readShared(path, { fetchImpl: f.impl, nowMs: () => T0 })
  assert.equal(bad.state, 'UNKNOWN', 'a 500 is UNKNOWN, never OK')
  assert.equal(bad.error, 'HTTP 500')
  assert.equal(peekLastGood(path), null, 'a failed read records no body: nothing fabricated for the other section')
  assert.equal(heard.length, 0)
  const good = await readShared<{ gates: unknown[] }>(path, { fetchImpl: f.impl, nowMs: () => T0 + 5_000 })
  assert.equal(f.calls.length, 2, 'the failure was not cached: the next read reaches the server')
  assert.equal(good.state, 'OK', 'recovered')
  assert.equal(heard.length, 1, 'the recovered body reaches every subscriber')
  off()
}
reset()
{
  const f = fakeFetch([{ status: 200, body: 'not json' }, { status: 200, body: '{"ok":true,"data":{"y":1}}' }])
  assert.equal((await readShared('/api/z', { fetchImpl: f.impl })).state, 'UNKNOWN', 'an unparseable body is UNKNOWN')
  assert.equal((await readShared('/api/z', { fetchImpl: f.impl })).state, 'OK', 'and the next read recovers')
}

// ── 5. stale products: shown as stale, expired as UNKNOWN, a fresh build never freshens a stale source ─────────
{
  const env = {
    product: 'home.since_close', scope: 'global', status: 'OK', as_of: '2026-11-13T15:00:00Z', built_at: '2026-11-13T15:00:30Z',
    next_refresh_at: '2026-11-13T15:05:00Z', stale_after_s: 300, hard_expiry_s: 1800, age_s: 30, seq: 7, reason: null, data: {},
  }
  const c = productClock(env)
  assert.equal(clockAt(c, T0 + 60_000).verdict, 'OK', '60 s old source: current')
  const stale = clockAt(c, T0 + 301_000)
  assert.equal(stale.verdict, 'STALE', 'past stale_after_s on an open tab: STALE without a new body')
  assert.match(stale.reason || '', /stale after 300s/)
  const expired = clockAt(c, T0 + 1_801_000)
  assert.equal(expired.verdict, 'UNKNOWN', 'past hard expiry: UNKNOWN, never drawn as current')
  // source 20 min old, rebuilt a second ago: the source clock decides
  const rebuilt = productClock({ ...env, as_of: '2026-11-13T14:40:00Z', built_at: '2026-11-13T14:59:59Z' })
  assert.equal(clockAt(rebuilt, T0).verdict, 'STALE', 'a fresh BUILD of a stale SOURCE stays stale')
  // a served STALE is never upgraded by the client
  assert.equal(clockAt(productClock({ ...env, status: 'STALE' }), T0 + 1_000).verdict, 'STALE')
  assert.equal(clockAt(productClock({ ...env, status: 'BUILDING', data: null }), T0).verdict, 'UNKNOWN', 'BUILDING is UNKNOWN')
}

// ── 6. /api/v2/products/home: not served yet -> UNKNOWN with the reason; bundle shapes parse ───────────────────
reset()
{
  const f = fakeFetch([{ status: 404, body: '{"error":"not found"}' }])
  const r = await readShared(PRODUCTS_HOME_API, { fetchImpl: f.impl })
  assert.equal(r.state, 'UNKNOWN')
  assert.equal(r.error, 'HTTP 404')
  const c = productClock(null, 404)
  assert.equal(c.verdict, 'UNKNOWN')
  assert.match(c.reason || '', /HTTP 404/)
}
{
  const e = (product: string, status: string) => ({ product, status, as_of: '2026-11-13T15:00:00Z', built_at: '2026-11-13T15:00:10Z', seq: 1, data: {} })
  const arr = productsFromBundle({ products: [e('home.a', 'OK'), e('home.b', 'STALE')] })
  assert.deepEqual(arr.map(p => [p.id, p.clock.verdict]), [['home.a', 'OK'], ['home.b', 'STALE']])
  const map = productsFromBundle({ ok: true, data: { products: { 'home.c': e('home.c', 'BUILDING'), 'home.d': { nope: 1 } } } })
  assert.deepEqual(map.map(p => [p.id, p.clock.verdict]), [['home.c', 'UNKNOWN'], ['home.d', 'UNKNOWN']], 'BUILDING and a bare entry are UNKNOWN')
  assert.equal(productsFromBundle(e('home.e', 'OK'))[0].id, 'home.e', 'a single envelope is one product')
  const junk = productsFromBundle({ hello: 'world' })
  assert.equal(junk.length, 1); assert.equal(junk[0].clock.verdict, 'UNKNOWN', 'unrecognised body: UNKNOWN, never an empty all-clear')
}

console.log('homeCombinedRegression: ok')
