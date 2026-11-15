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

test('decision desk: freshness is data.freshness.resistance_generated_at (96 h), never computed_at (follows the request)', () => {
  const p = '/api/v2/reentry/decision-desk'
  const ok = deriveRenderState({ envelope: env(p, wrap({ ok: true, computed_at: '2026-11-14T23:29:59Z', freshness: { resistance_generated_at: '2026-11-13T21:40:02.768644+00:00' }, rows: [{}] })), now: NOW })
  assert.equal(ok.status, 'OK', ok.reason)
  assert.equal(ok.asOf, '2026-11-13T21:40:02.768644+00:00')
  const onlyRequestClock = deriveRenderState({ envelope: env(p, wrap({ ok: true, computed_at: '2026-11-14T23:29:59Z', rows: [{}] })), now: NOW })
  assert.equal(onlyRequestClock.status, 'UNKNOWN', 'computed_at alone proves nothing')
  const old = deriveRenderState({ envelope: env(p, wrap({ ok: true, freshness: { resistance_generated_at: '2026-11-10T21:40:02Z' } })), now: NOW })
  assert.equal(old.status, 'UNKNOWN', 'older than 96 h')
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
  for (const p of ['/api/v2/stops/reentry-watch', '/api/v2/journal/exit-intelligence', '/api/v2/time-exit-proposals']) {
    const s = specFor(p)
    assert.notEqual(s.note, 'default', `${p} has a row`)
    assert.equal(s.asOfAt, undefined, p)
    assert.equal(s.clock, 'none', p)
  }
})

test('clockless empty (time-exit proposals []) is UNKNOWN, never EMPTY', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/time-exit-proposals', wrap({ proposals: [], count: 0, note: 'paper-only' })), now: NOW, isEmpty: b => b.data.count === 0 })
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
  const good = { ok: true, data: { ok: true, generated_at: '2026-11-14T23:00:02Z', publication: { status: 'READY' } } }
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

test('protection-truth: heavy, timeout at least 2x the measured cold rebuild (3.0-3.7 s), data.status UNAVAILABLE → UNKNOWN', () => {
  const s = specFor('/api/v2/risk/protection-truth')
  assert.ok(s.heavy && s.timeoutMs >= 2 * 3700, String(s.timeoutMs))
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

// ---- r3: cc-deepseek-5 envelope classes (DELTA-G13 e7fd59f8): healthy spellings, stale typing, no-signal rows ----
test('staleFlag rule: true fires; false/missing do not; a non-boolean (e.g. 955, unit unconfirmed) fires as unreadable', async () => {
  const { ruleFires } = await import('../../src/api/readers.ts')
  const r = { at: 'data.stale', staleFlag: true }
  assert.equal(ruleFires(r, true), true)
  assert.equal(ruleFires(r, false), false)
  assert.equal(ruleFires(r, undefined), false)
  assert.equal(ruleFires(r, 955), true, 'a number is not a boolean flag; its unit is unconfirmed, so it cannot read as fresh')
  assert.equal(ruleFires(r, 0), true, 'even 0: we do not know the unit or the meaning')
  assert.equal(ruleFires(r, 'false'), true)
})

test('registry: no stale path is policed by equals:true (it misses non-boolean stale); all use staleFlag', () => {
  for (const s of READERS) for (const r of s.unavailableWhen) {
    if (/(^|\.)stale$/.test(r.at)) assert.ok(r.staleFlag === true && !('equals' in r), `${s.path} ${r.at}`)
  }
})

test('protection-truth: only status "OK" is real; DEGRADED or missing → UNKNOWN', () => {
  const p = '/api/v2/risk/protection-truth'
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ status: 'OK' })), now: NOW }).status, 'OK')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ status: 'DEGRADED' })), now: NOW }).status, 'UNKNOWN')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({})), now: NOW }).status, 'UNKNOWN')
})

test('market-risk: state must be "evaluated" and stale must not be true', () => {
  const p = '/api/v2/market-risk/latest', a = '2026-11-14T23:00:00Z'
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ state: 'evaluated', stale: false, as_of: a })), now: NOW }).status, 'OK')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ state: 'pending', stale: false, as_of: a })), now: NOW }).status, 'UNKNOWN')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ state: 'evaluated', stale: true, as_of: a })), now: NOW }).status, 'UNKNOWN')
})

test('reentry/status: state must be "POPULATED"; missing → UNKNOWN', () => {
  const p = '/api/v2/reentry/status'
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ state: 'POPULATED' })), now: NOW }).status, 'OK')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({})), now: NOW }).status, 'UNKNOWN')
})

test('rotation and market-event: stale true → UNKNOWN', () => {
  const rot = wrap({ ok: true, stale: true, generated_at: '2026-11-14T23:00:00Z', publication: { status: 'READY' } })
  const rst = deriveRenderState({ envelope: env('/api/v2/rotation/summary', rot), now: NOW })
  assert.equal(rst.status, 'UNKNOWN')
  assert.match(rst.reason, /data\.stale/)
  assert.equal(deriveRenderState({ envelope: env('/api/v2/market-event/active', wrap({ stale: true, events: [] })), now: NOW }).status, 'UNKNOWN')
  assert.equal(deriveRenderState({ envelope: env('/api/v2/market-event/active', wrap({ stale: false, inputs_as_of: { market_risk: '2026-11-14T23:00:02.55Z' }, events: [{ id: 1 }] })), now: NOW }).status, 'OK')
})

test('no-signal rows (no health rule, no producer clock) read OK only with health UNKNOWN attached, never calm', async () => {
  const { healthCue } = await import('../../src/components/renderState.ts')
  for (const p of ['/api/v2/stops/reentry-watch', '/api/v2/time-exit-proposals']) {
    const st = deriveRenderState({ envelope: env(p, wrap({ rows: [{ id: 1 }] })), now: NOW })
    assert.equal(st.status, 'OK', p)
    assert.match(st.healthUnproven ?? '', /no health flag and no producer clock/, p)
    const c = healthCue(st)
    assert.equal(c.level, 'NEUTRAL'); assert.match(c.label, /UNKNOWN/)
  }
  const ok = deriveRenderState({ envelope: env('/api/v2/risk/protection-truth', wrap({ status: 'OK' })), now: NOW })
  assert.equal(ok.healthUnproven, null, 'a row with a health rule is not flagged')
  assert.equal(healthCue(ok), null)
})

// ---- r4: cc-deepseek-7 ADDENDUM v2a (0ab2c54a) supersedes P5/P6/R3/R6 ----
test('time-exit: the served route is /api/v2/time-exit-proposals; the 404 spelling has no row', () => {
  assert.equal(specFor('/api/v2/time-exit-proposals').path, '/api/v2/time-exit-proposals')
  assert.notEqual(specFor('/api/v2/time-exit-proposals').note, 'default')
  assert.ok(!READERS.some(r => r.path === '/api/v2/time-exit/proposals'), 'the 404 path must not be registered')
  assert.ok(!READERS.some(r => r.path.includes('/decide')), 'the decide route is never a reader')
})

test('market-risk: producer calls 1.0 h stale; older than 1 h → UNKNOWN', () => {
  const p = '/api/v2/market-risk/latest'
  assert.equal(specFor(p).maxAgeHours, 1)
  const st = deriveRenderState({ envelope: env(p, wrap({ state: 'evaluated', stale: false, as_of: '2026-11-14T22:00:02Z' })), now: NOW })
  assert.equal(st.status, 'UNKNOWN'); assert.match(st.reason, /^stale/)
})

test('market-event: freshness is data.inputs_as_of.market_risk (producer), limit 26 h = market_event_api STALE_SNAPSHOT_HOURS', () => {
  const p = '/api/v2/market-event/active', s = specFor(p)
  assert.equal(s.asOfAt, 'data.inputs_as_of.market_risk'); assert.equal(s.clock, 'producer')
  assert.equal(s.maxAgeHours, 26, 'a reader stricter than the producer contradicts the payload on its own clock')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ stale: false, inputs_as_of: { market_risk: '2026-11-14T21:00:00Z' } })), now: NOW }).status, 'OK', '2.5 h is fresh by the producer rule')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ stale: false, inputs_as_of: { market_risk: '2026-11-13T20:00:00Z' } })), now: NOW }).status, 'UNKNOWN', '27.5 h')
  assert.equal(deriveRenderState({ envelope: env(p, wrap({ stale: false, computed_at: '2026-11-14T23:29:59Z' })), now: NOW }).status, 'UNKNOWN', 'computed_at follows the request; not a clock')
})

// ---- r5: cc-deepseek-7 v2b (dc7bcb5a): producer numbers, strict boundary, SWR cache fields ----
test('market-risk: age exactly 1.0 h reads fresh (producer compares strictly, age > 1.0)', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/market-risk/latest', wrap({ state: 'evaluated', stale: false, as_of: '2026-11-14T22:30:00Z' })), now: NOW })
  assert.equal(st.status, 'OK', st.reason)
})

test('no row gates on the SWR cache annotations (cache_stale / cache_as_of / cache_age_s are not engine freshness)', () => {
  for (const r of READERS) {
    for (const u of r.unavailableWhen) assert.ok(!/cache_(stale|as_of|age_s)/.test(u.at), `${r.path} ${u.at}`)
    assert.ok(!/cache_(as_of|age_s)/.test(r.asOfAt ?? ''), r.path)
  }
})

// ---- r5b: cc-deepseek-5 check: absence of every health field must not read calm ----
test('a non-producer row whose health fields are all absent from the payload reads Health UNKNOWN, not calm', () => {
  const spec = { path: '/api/v2/synthetic', timeoutMs: 1000, heavy: false, clock: 'none', unavailableWhen: [{ at: 'data.stale', staleFlag: true }], note: 't' }
  const missing = deriveRenderState({ envelope: env('/api/v2/synthetic', wrap({ rows: [{ id: 1 }] })), spec, now: NOW })
  assert.equal(missing.status, 'OK')
  assert.match(missing.healthUnproven ?? '', /no health flag/)
  const present = deriveRenderState({ envelope: env('/api/v2/synthetic', wrap({ stale: false, rows: [{ id: 1 }] })), spec, now: NOW })
  assert.equal(present.healthUnproven, null, 'stale present and false: signal exists')
})

test('an unregistered path (default spec) inherits Health UNKNOWN, never calm by omission', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/watchpool', wrap({ items: [{ id: 1 }] })), now: NOW })
  assert.equal(specFor('/api/v2/watchpool').note, 'default')
  assert.equal(st.status, 'OK')
  assert.ok(st.healthUnproven, 'no row, no flag, no clock')
})

// ---- r6: cc-deepseek-5 FINDING-RISK-GREYED (88723f18). Producer statuses: OK / STALE / UNKNOWN(greyed) / BUILDING
//      (scripts/lib/cc_products/product_route.py); FAILED is never emitted. A clock proves build time, not fitness. ----
test('/risk: only _product.status OK with greyed false is current; UNKNOWN+greyed, BUILDING, STALE, missing → UNKNOWN', () => {
  const p = '/api/v2/risk', fresh = '2026-11-14T23:00:00Z'
  const st = prod => deriveRenderState({ envelope: env(p, wrap({ truth: { stale: false }, _product: { as_of: fresh, ...prod } })), now: NOW }).status
  assert.equal(st({ status: 'OK', greyed: false }), 'OK')
  assert.equal(st({ status: 'UNKNOWN', greyed: true }), 'UNKNOWN', 'last good past hard expiry: never shown as current')
  assert.equal(st({ status: 'OK', greyed: true }), 'UNKNOWN', 'greyed alone is enough')
  assert.equal(st({ status: 'BUILDING', greyed: false }), 'UNKNOWN')
  assert.equal(st({ status: 'STALE', greyed: false }), 'UNKNOWN', 'soft-stale: same verdict as the 2.5 h clock')
  assert.equal(st({ greyed: false }), 'UNKNOWN', 'status missing')
})

test('/risk: no rule relies on a status value the producer never emits (FAILED)', () => {
  for (const r of specFor('/api/v2/risk').unavailableWhen) assert.notEqual(r.equals, 'FAILED', r.at)
})

test('protection-truth note does not advertise the withdrawn 3.653 s tail ratio', () => {
  assert.doesNotMatch(specFor('/api/v2/risk/protection-truth').note, /3\.653|2\.2x/)
})

// ---- r7: cc-deepseek-7 (v2c 920accda): an equals rule that cannot read its field must not assert health ----
test('equals rule: a missing field fires (cannot confirm it is not the unavailable value); staleFlag is the only absent-is-no-signal kind', async () => {
  const { ruleFires } = await import('../../src/api/readers.ts')
  assert.equal(ruleFires({ at: 'data.ok', equals: false }, undefined), true)
  assert.equal(ruleFires({ at: 'data.ok', equals: false }, true), false)
  assert.equal(ruleFires({ at: 'data.ok', equals: false }, false), true)
})

test('rotation with data.publication dropped → UNKNOWN naming the missing field', () => {
  const body = wrap({ ok: true, stale: false, generated_at: '2026-11-14T23:00:00Z' })
  const st = deriveRenderState({ envelope: env('/api/v2/rotation/summary', body), now: NOW })
  assert.equal(st.status, 'UNKNOWN')
  assert.match(st.reason, /data\.publication\.status.*missing/)
})

test('rotation publication siblings (cc-deepseek-5): null status and renamed key → UNKNOWN; a healthy publication still reaches OK', () => {
  const base = { ok: true, stale: false, generated_at: '2026-11-14T23:00:00Z' }
  const rs = pub => deriveRenderState({ envelope: env('/api/v2/rotation/summary', wrap({ ...base, publication: pub })), now: NOW })
  assert.equal(rs({ status: null }).status, 'UNKNOWN')
  assert.match(rs({ status: null }).reason, /data\.publication\.status/)
  assert.equal(rs(null).status, 'UNKNOWN')
  assert.equal(rs({ state: 'PUBLISHED' }).status, 'UNKNOWN')
  assert.equal(rs({ status: 'READY' }).status, 'OK')
})

test('rotation publication: only the producer healthy value READY reaches OK (rotation_publication.py:380, read gate :409)', () => {
  const base = { ok: true, stale: false, generated_at: '2026-11-14T23:00:00Z' }
  const rs = status => deriveRenderState({ envelope: env('/api/v2/rotation/summary', wrap({ ...base, publication: { status } })), now: NOW }).status
  assert.equal(rs('READY'), 'OK')
  for (const v of ['STALE', 'UNAVAILABLE', 'DEGRADED', 'ready', 'PUBLISHED']) assert.equal(rs(v), 'UNKNOWN', v)
})

// Recovery's real top-level shape (scripts/api_v2.py _recovery_dashboard ~:25311; cc-deepseek-7 probe 23:56Z):
// data has NO `ok` key. Its health field is recovery_cases.state: "ok" (:25445) or "unavailable" (:25400/:25416/:25430).
const recReal = cases => wrap({ recovery_cases: cases, items: [{ id: 1 }], relist_events: [], history: [],
  summary: { total_active: 1 }, classification_legend: {}, sector_context: {}, llm_analysis: { generated_at: '2026-11-10T08:15:00Z' } })
test('recovery real shape (no data.ok) with recovery_cases.state "ok" is NOT unavailable', () => {
  const st = deriveRenderState({ envelope: env('/api/v2/recovery', recReal({ state: 'ok', count: 1, cases: [{}] })), now: NOW })
  assert.equal(st.status, 'OK')
  assert.equal(st.healthUnproven, null)
})
test('recovery: recovery_cases.state "unavailable", missing state, or missing recovery_cases → UNKNOWN', () => {
  for (const c of [{ state: 'unavailable', reason: 'recovery case store not reachable', count: null, cases: [] }, { count: 1 }, undefined]) {
    assert.equal(deriveRenderState({ envelope: env('/api/v2/recovery', recReal(c)), now: NOW }).status, 'UNKNOWN')
  }
})
test('no registry row keys on data.ok for /api/v2/recovery (its healthy payload has no such field)', () => {
  const row = READERS.find(r => r.path === '/api/v2/recovery')
  assert.ok(!row.unavailableWhen.some(r => r.at === 'data.ok'))
})

test('/risk with data._product dropped → UNKNOWN (pins the notEquals path)', () => {
  assert.equal(deriveRenderState({ envelope: env('/api/v2/risk', wrap({ truth: { stale: false } })), now: NOW }).status, 'UNKNOWN')
})

// R-1 (cc-deepseek-3, verdict 6ce7b9f9f 00:12Z): a producer-clocked row whose declared staleFlag is absent or null
// reached OK with no badge. ruleFires is unchanged (absence does not fire); only the derived health flag moves.
const R1_SPEC = { path: '/api/v2/synthetic-r1', timeoutMs: 1000, heavy: false, clock: 'producer',
  unavailableWhen: [{ at: 'data.stale', staleFlag: true }], asOfAt: 'data.as_of', maxAgeHours: 2, note: 't' }
const r1 = d => deriveRenderState({ envelope: { ...env('/api/v2/synthetic-r1', wrap({ as_of: '2026-11-14T23:00:00Z', rows: [1], ...d })), spec: R1_SPEC }, now: NOW })
test('R-1: producer-clocked row with its staleFlag absent or null → OK + Health UNKNOWN badge', async () => {
  const { healthCue } = await import('../../src/components/renderState.ts')
  for (const d of [{}, { stale: null }]) {
    const st = r1(d)
    assert.equal(st.status, 'OK')
    assert.equal(healthCue(st)?.label, 'Health UNKNOWN', JSON.stringify(d))
    assert.match(st.healthUnproven, /data\.stale/)
  }
  const risk = deriveRenderState({ envelope: env('/api/v2/risk', wrap({ truth: { stale: false },
    _product: { status: 'OK', as_of: '2026-11-14T23:00:00Z' } })), now: NOW })
  assert.equal(risk.status, 'OK')
  assert.equal(healthCue(risk)?.label, 'Health UNKNOWN')
})
test('R-1: staleFlag literally false → no badge', async () => {
  const { healthCue } = await import('../../src/components/renderState.ts')
  const st = r1({ stale: false })
  assert.equal(st.status, 'OK')
  assert.equal(st.healthUnproven, null)
  assert.equal(healthCue(st), null)
})
