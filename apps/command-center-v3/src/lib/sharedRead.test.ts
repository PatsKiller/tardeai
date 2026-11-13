// Combined Home: the operational section's one-shot reads share the page's polling hooks (lib/sharedRead.ts).
// Pins: a body a hook holds inside maxAgeMs is used with NO request; concurrent readers of one path issue ONE request
// (overlapping refetch dedupe); a 304 answers from the recorded body or is UNKNOWN; a failure is UNKNOWN / TIMED OUT,
// never OK; a body read here is handed to the path's subscribers. Synthetic values only.
import assert from 'node:assert/strict'
import { readShared, readFromBody } from './sharedRead.ts'
import { resetInFlight } from './inflightGet.ts'
import { noteLastGood, peekLastGood, resetLastGood, subscribeBody } from '../hooks/useApi.ts'

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

// ── a held body inside maxAgeMs: no request at all ───────────────────────────────────────────────────
reset()
{
  noteLastGood('/api/a', { ok: true, data: { n: 1 } }, 10_000)
  const f = fakeFetch([{ status: 200 }])
  const r = await readShared<{ n: number }>('/api/a', { fetchImpl: f.impl, nowMs: () => 40_000 })
  assert.equal(f.calls.length, 0, 'the hook already read this path 30 s ago: no second GET')
  assert.equal(r.state, 'OK')
  assert.deepEqual(r.data, { n: 1 })
  assert.equal(r.at, new Date(10_000).toISOString(), 'the clock is the receipt time of the shared body, not now')
}
// ── too old: one request ─────────────────────────────────────────────────────────────────────────────
reset()
{
  noteLastGood('/api/a', { n: 1 }, 0)
  const f = fakeFetch([{ status: 200, body: '{"n":2}' }])
  const r = await readShared<{ n: number }>('/api/a', { fetchImpl: f.impl, nowMs: () => 61_000 })
  assert.equal(f.calls.length, 1)
  assert.deepEqual(r.data, { n: 2 })
  assert.deepEqual(peekLastGood('/api/a')?.json, { n: 2 }, 'the new body is recorded for the hooks')
}
// ── overlapping reads of one path: one request ───────────────────────────────────────────────────────
reset()
{
  const f = fakeFetch([{ status: 200, body: '{"n":3}', delayMs: 5 }])
  const heard: unknown[] = []
  const off = subscribeBody('/api/b', j => heard.push(j))
  const [a, b, c] = await Promise.all([1, 2, 3].map(() => readShared<{ n: number }>('/api/b', { fetchImpl: f.impl })))
  assert.equal(f.calls.length, 1, 'a second and third refetch while one is in flight issue no request')
  for (const r of [a, b, c]) assert.deepEqual(r.data, { n: 3 })
  assert.ok(heard.length >= 1, 'the path subscribers (the polling hooks) receive the body')
  off()
}
// ── 304 with and without a recorded body ─────────────────────────────────────────────────────────────
reset()
{
  const f = fakeFetch([{ status: 304 }])
  const r = await readShared('/api/c', { fetchImpl: f.impl })
  assert.equal(r.state, 'UNKNOWN', 'a 304 with nothing recorded is UNKNOWN, never OK')
  noteLastGood('/api/c', { n: 4 }, 0)
  const f2 = fakeFetch([{ status: 304 }])
  const r2 = await readShared<{ n: number }>('/api/c', { fetchImpl: f2.impl, nowMs: () => 120_000 })
  assert.equal(r2.state, 'OK')
  assert.deepEqual(r2.data, { n: 4 })
}
// ── failures are never OK ────────────────────────────────────────────────────────────────────────────
reset()
{
  const r503 = await readShared('/api/d', { fetchImpl: fakeFetch([{ status: 503, body: '{"status":"BUILDING"}' }]).impl })
  assert.equal(r503.state, 'UNKNOWN'); assert.match(r503.error || '', /HTTP 503/)
  const bad = await readShared('/api/e', { fetchImpl: fakeFetch([{ status: 200, body: 'not json' }]).impl })
  assert.equal(bad.state, 'UNKNOWN')
  const slow = await readShared('/api/f', { fetchImpl: fakeFetch([{ status: 200, delayMs: 50 }]).impl, timeoutMs: 5 })
  assert.equal(slow.state, 'TIMED OUT')
  assert.equal(readFromBody('/x', { ok: false, reason: 'building' }, 'T').state, 'UNKNOWN', 'ok:false is UNKNOWN with its reason')
  assert.equal(readFromBody('/x', { ok: false, reason: 'building' }, 'T').error, 'building')
}
reset()
console.log('sharedRead: ok')
