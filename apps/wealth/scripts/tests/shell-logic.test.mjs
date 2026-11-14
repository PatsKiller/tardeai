// Shell logic tests (client + renderState). Plain node: `node --test scripts/tests/`.
// Synthetic fixtures only; shapes copied from cc-deepseek-7's measured envelopes (2026-11-14 2307Z),
// values invented.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createClient, HeavyReaderFromShell } from '../../src/api/client.ts'
import { specFor, READERS } from '../../src/api/readers.ts'
import { deriveRenderState, statusCue } from '../../src/components/renderState.ts'

const NOW = Date.parse('2026-11-14T23:30:00Z')

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}
function env(path, body) {
  return { ok: true, status: 200, data: body, error: null, fetchedAt: new Date(NOW).toISOString(),
    lastGood: body, lastGoodAt: null, lastGoodAgeSeconds: 0, timedOut: false, spec: specFor(path) }
}

// ---- F-rot: outer ok true, nested unavailable -------------------------------------------
const F_ROT = { ok: true, data: { ok: false, generated_at: '2026-11-14T23:00:02.916Z',
  publication: { status: 'UNAVAILABLE', reasons: ['unbound_cache_inputs'], producer_ok: true }, sectors: [{ id: 'x' }] } }

test('F-rot: rotation with outer ok:true and data.ok:false renders UNKNOWN, never OK', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/rotation/summary', F_ROT), now: NOW })
  assert.equal(st.status, 'UNKNOWN')
  assert.match(st.reason, /data\.ok/)
  assert.equal(st.data, null, 'an unavailable read must not hand its lists to the page')
})

test('F-rot: publication UNAVAILABLE alone (data.ok missing) is still UNKNOWN', () => {
  const body = { ok: true, data: { generated_at: '2026-11-14T23:00:02.916Z', publication: { status: 'UNAVAILABLE' } } }
  assert.equal(deriveRenderState({ envelope: env('/api/v2/rotation/summary', body), now: NOW }).status, 'UNKNOWN')
})

// ---- F-rec: count 0 + state ok, no as_of -------------------------------------------------
const F_REC = { ok: true, data: { recovery_cases: { count: 0, state: 'ok', generated_at: '2026-11-14T23:29:59Z' }, items: [{ id: 1 }] } }

test('F-rec: recovery count 0 with state ok and no fresh as_of renders UNKNOWN, never EMPTY', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/recovery', F_REC), now: NOW,
    isEmpty: b => b.data.recovery_cases.count === 0 })
  assert.equal(st.status, 'UNKNOWN')
  assert.match(st.reason, /no as_of/)
})

test('EMPTY is reachable only with a fresh declared as_of', () => {
  const spec = { path: '/api/v2/x', timeoutMs: 1000, heavy: false, unavailableWhen: [], asOfAt: 'as_of', maxAgeHours: 2, note: 't' }
  const fresh = { as_of: '2026-11-14T23:00:00Z', rows: [] }
  const e = { ...env('/api/v2/x', fresh), spec }
  assert.equal(deriveRenderState({ envelope: e, now: NOW, isEmpty: b => b.rows.length === 0 }).status, 'EMPTY')
  const stale = { as_of: '2026-08-06T00:00:00Z', rows: [] }
  const st = deriveRenderState({ envelope: { ...e, data: stale }, now: NOW, isEmpty: b => b.rows.length === 0 })
  assert.equal(st.status, 'UNKNOWN')
  assert.match(st.reason, /stale/)
})

// Every canonical reader answers {"ok": true, "data": {...}} (cc-deepseek-7 captures 2026-11-14 23:00-23:27Z):
// fixtures below use that envelope, so a row whose path forgets the `data.` level cannot pass.
const wrap = d => ({ ok: true, data: d })

test('defense posture: fresh enveloped as_of reads OK (the row reads data.as_of, not a top-level as_of)', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/defense/posture', wrap({ ok: true, as_of: '2026-11-14T22:00:00Z', stale: false })), now: NOW })
  assert.equal(st.status, 'OK', st.reason)
  assert.equal(st.asOf, '2026-11-14T22:00:00Z')
})

test('defense posture: data.stale true → UNKNOWN naming data.stale', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/defense/posture', wrap({ ok: true, as_of: '2026-11-14T22:00:00Z', stale: true })), now: NOW })
  assert.equal(st.status, 'UNKNOWN')
  assert.match(st.reason, /data\.stale/)
})

test('defense posture: engine_gaps [] last checked 100 days ago is not all-clear (stale → UNKNOWN)', () => {
  const body = wrap({ as_of: '2026-08-06T00:00:00Z', stale: false, engine_gaps: { gaps: [], last_check: '2026-08-06' } })
  const st = deriveRenderState({ envelope: env('/api/v2/defense/posture', body), now: NOW, isEmpty: b => b.data.engine_gaps.gaps.length === 0 })
  assert.equal(st.status, 'UNKNOWN')
  assert.match(st.reason, /^stale/)
})

test('decision desk: freshness comes from data.computed_at (a projection clock)', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/reentry/decision-desk', wrap({ ok: true, computed_at: '2026-11-14T23:01:04Z', rows: [{}] })), now: NOW })
  assert.equal(st.status, 'OK', st.reason)
  assert.equal(st.asOf, '2026-11-14T23:01:04Z')
})

test('defense recommendations: clock is recommendations.generated_at, never the date-only as_of; mode SHADOW noted', () => {
  const s = specFor('/api/v2/defense/recommendations')
  assert.equal(s.asOfAt, 'data.recommendations.generated_at')
  assert.equal(s.clock, 'producer')
  assert.match(s.note, /SHADOW/)
  const body = wrap({ ok: true, recommendations: { as_of: '2026-11-13', generated_at: '2026-11-13T22:50:02.391865+00:00', mode: 'SHADOW' } })
  assert.equal(deriveRenderState({ envelope: env('/api/v2/defense/recommendations', body), now: NOW }).status, 'OK')
})

test('request-time clocks are never declared as freshness', () => {
  for (const p of ['/api/v2/risk/protection-truth', '/api/v2/reentry/status', '/api/v2/cio/capital-plan', '/api/v2/redeploy/capital-pools']) {
    const s = specFor(p)
    assert.notEqual(s.note, 'default', `${p} has a row`)
    assert.equal(s.asOfAt, undefined, p)
    assert.equal(s.clock, 'request-time', p)
  }
  for (const p of ['/api/v2/stops/reentry-watch', '/api/v2/journal/exit-intelligence', '/api/v2/time-exit/proposals', '/api/v2/market-event/active']) {
    const s = specFor(p)
    assert.notEqual(s.note, 'default', `${p} has a row`)
    assert.equal(s.asOfAt, undefined, p)
    assert.equal(s.clock, 'none', p)
  }
})

test('clockless empty (time-exit proposals []) is UNKNOWN, never EMPTY', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/time-exit/proposals', wrap({ proposals: [], count: 0, note: 'paper-only' })), now: NOW, isEmpty: b => b.data.count === 0 })
  assert.equal(st.status, 'UNKNOWN')
})

test('registry rows: every declared path is under data. and asOfAt is set exactly when clock is producer', () => {
  for (const r of READERS) {
    assert.ok(r.clock, `${r.path} declares its clock`)
    assert.equal(!!r.asOfAt, r.clock === 'producer', r.path)
    for (const p of [r.asOfAt, ...r.unavailableWhen.map(u => u.at)].filter(Boolean)) assert.match(p, /^data\./, `${r.path}: ${p}`)
  }
})

test('notEquals rule: anything but the healthy value (or a missing value) is UNKNOWN', () => {
  const spec = { path: '/api/v2/x', timeoutMs: 1000, heavy: false, clock: 'none', unavailableWhen: [{ at: 'data.status', notEquals: 'OK' }], note: 't' }
  const mk = d => ({ ...env('/api/v2/x', wrap(d)), spec })
  assert.equal(deriveRenderState({ envelope: mk({ status: 'OK' }), now: NOW }).status, 'OK')
  const deg = deriveRenderState({ envelope: mk({ status: 'DEGRADED' }), now: NOW })
  assert.equal(deg.status, 'UNKNOWN')
  assert.match(deg.reason, /data\.status = "DEGRADED".*not "OK"/)
  assert.equal(deriveRenderState({ envelope: mk({}), now: NOW }).status, 'UNKNOWN')
})

test('readPath indexes arrays by position', async () => {
  const { readPath } = await import('../../src/api/readers.ts')
  assert.equal(readPath(wrap({ w: [{ as_of: 'a' }, { as_of: 'b' }] }), 'data.w.1.as_of'), 'b')
  assert.equal(readPath(wrap({ w: [] }), 'data.w.0.as_of'), undefined)
})

test('OK only when no rule fires; UNKNOWN cue is NEUTRAL with the word UNKNOWN (never green)', () => {
  const good = { ok: true, data: { ok: true, generated_at: '2026-11-14T23:00:02Z', publication: { status: 'PUBLISHED' } } }
  const ok = deriveRenderState({ envelope: env('/api/v2/rotation/summary', good), now: NOW })
  assert.equal(ok.status, 'OK')
  const unk = deriveRenderState({ envelope: env('/api/v2/rotation/summary', F_ROT), now: NOW })
  const cue = statusCue(unk)
  assert.equal(cue.level, 'NEUTRAL')
  assert.equal(cue.label, 'UNKNOWN')
  assert.ok(cue.tooltip.length > 0)
})

test('no registry rule reads the outer ok', () => {
  for (const r of READERS) for (const u of r.unavailableWhen) assert.notEqual(u.at, 'ok', r.path)
})

// ---- client --------------------------------------------------------------------------------
test('single-flight: concurrent reads of one path share one request', async () => {
  let calls = 0
  let release
  const gate = new Promise(r => { release = r })
  const c = createClient({ now: () => NOW, fetchImpl: async () => { calls++; await gate; return jsonResponse({ a: 1 }) } })
  const p1 = c.get('/api/v2/x'), p2 = c.get('/api/v2/x')
  assert.equal(c.inflightCount(), 1)
  release()
  const [a, b] = await Promise.all([p1, p2])
  assert.equal(calls, 1)
  assert.deepEqual(a.data, { a: 1 })
  assert.equal(a, b)
  assert.equal(c.inflightCount(), 0)
})

test('last good with age survives a failed read', async () => {
  let t = NOW, n = 0
  const c = createClient({ now: () => t, fetchImpl: async () => (++n === 1 ? jsonResponse({ v: 1 }) : jsonResponse({ e: 1 }, 503)) })
  await c.get('/api/v2/x')
  t = NOW + 90_000
  const e = await c.get('/api/v2/x')
  assert.equal(e.ok, false)
  assert.equal(e.data, null)
  assert.deepEqual(e.lastGood, { v: 1 })
  assert.equal(e.lastGoodAgeSeconds, 90)
  const st = deriveRenderState({ envelope: e, now: t })
  assert.equal(st.status, 'ERROR')
  assert.deepEqual(st.lastGood, { v: 1 })
})

test('per-reader timeout: a slow 200 is cut off at the registry timeout', async () => {
  const registry = [{ path: '/api/v2/slow', timeoutMs: 30, heavy: false, unavailableWhen: [], note: 't' }]
  const c = createClient({ registry, fetchImpl: (_p, init) => new Promise((resolve, reject) => {
    const t = setTimeout(() => resolve(jsonResponse({ late: true })), 2000)
    init.signal.addEventListener('abort', () => { clearTimeout(t); reject(new Error('aborted')) })
  }) })
  const t0 = Date.now()
  const e = await c.get('/api/v2/slow')
  assert.ok(Date.now() - t0 < 1000, 'timeout did not fire')
  assert.equal(e.timedOut, true)
  assert.equal(e.data, null)
  assert.match(e.error, /timed out after 30 ms/)
})

test('heavy readers refuse a shell-originated read; pages may read them', async () => {
  const c = createClient({ fetchImpl: async () => jsonResponse({ ok: 1 }) })
  for (const p of ['/api/v2/defense/posture', '/api/v2/reentry/decision-desk', '/api/v2/risk/protection-truth']) {
    assert.throws(() => c.get(p, { from: 'shell' }), HeavyReaderFromShell, p)
  }
  const e = await c.get('/api/v2/defense/posture', { from: 'page' })
  assert.equal(e.ok, true)
})

test('protection-truth: heavy, timeout at least 2x the measured 3.653 s tail, data.status UNAVAILABLE → UNKNOWN', () => {
  const s = specFor('/api/v2/risk/protection-truth')
  assert.ok(s.heavy && s.timeoutMs >= 2 * 3653, String(s.timeoutMs))
  const st = deriveRenderState({ envelope: env('/api/v2/risk/protection-truth', wrap({ status: 'UNAVAILABLE', as_of: '2026-11-14T23:29:59Z' })), now: NOW })
  assert.equal(st.status, 'UNKNOWN')
})

test('client is GET-only and refuses non-/api/ paths', async () => {
  let seen
  const c = createClient({ fetchImpl: async (_p, init) => { seen = init; return jsonResponse({}) } })
  await c.get('/api/v2/x')
  assert.equal(seen.method, 'GET')
  assert.throws(() => c.get('/v3/'), /canonical \/api\//)
})
