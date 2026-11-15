// Shell logic tests (client + renderState), plus the portfolio gates that need a compiled artifact: the
// Holdings fixture invariants and the Holdings freshness line. Plain node: `node --test scripts/tests/`.
// Synthetic fixtures only; shapes copied from cc-deepseek-7's measured envelopes (2026-11-14 2307Z),
// values invented.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createClient, HeavyReaderFromShell } from '../../src/api/client.ts'
import { specFor, READERS } from '../../src/api/readers.ts'
import { deriveRenderState, statusCue } from '../../src/components/renderState.ts'
import { price, money, moneyTone, signedMoney, toneClass, unavailable } from '../../src/pages/portfolio/format.ts'
import { barStatus, isBookRoute } from '../../src/pages/portfolio/bookView.ts'
import { accountDisplayLabel } from '../../src/pages/portfolio/accountLabel.ts'
import { ledgerLine } from '../../src/pages/portfolio/clockLedger.ts'

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

// ---- Portfolio gates: fixture invariants (F1) and the Holdings freshness line (F2) ------------------------
// Verdict VERDICT-HOLDINGS-R1b-cc-deepseek-8 §F1/§F2. `fixtureInvariants.ts` ran in no gate, so a broken fixture
// could ship green; `freshnessLine`'s R1b branches (unserved stale limit) had no committed test.
//
// Neither module is importable by the test runner as-is: fixtureInvariants resolves extensionless relative
// imports, and HoldingsTable.tsx carries JSX — node strips types but neither resolves those nor parses JSX. So the
// gate compiles both with the repo's OWN tsc into an ignored cache dir under node_modules and requires the emitted
// CJS. The code executed is the source under src/, not a copy, and a compile failure fails this test with tsc's
// stderr rather than passing silently.
const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const GATE_CACHE = path.join(APP, 'node_modules/.cache/wealth-gate-tests')

let gateModules = null
function compileGateModules() {
  if (gateModules !== null) return gateModules
  fs.mkdirSync(GATE_CACHE, { recursive: true })
  const out = fs.mkdtempSync(path.join(GATE_CACHE, 'run-'))
  const tsc = path.join(APP, 'node_modules/typescript/bin/tsc')
  const args = [
    '--target', 'ES2020', '--module', 'commonjs', '--moduleResolution', 'node', '--strict', '--skipLibCheck',
    '--allowImportingTsExtensions', '--rewriteRelativeImportExtensions', '--jsx', 'react-jsx',
    '--typeRoots', path.join(APP, 'node_modules/@types'), '--types', 'node', '--outDir', out,
    path.join(APP, 'src/pages/portfolio/fixtureInvariants.ts'),
    path.join(APP, 'src/pages/portfolio/HoldingsTable.tsx'),
    path.join(APP, 'src/pages/portfolio/adapter.ts'),
    path.join(APP, 'src/pages/portfolio/analyticsAdapter.ts'),
    path.join(APP, 'src/pages/portfolio/presets.ts'),
  ]
  const r = spawnSync(process.execPath, [tsc, ...args], { encoding: 'utf8' })
  if (r.status !== 0) {
    throw new Error(`tsc could not compile the portfolio gate modules (rc ${r.status}):\n${r.stdout ?? ''}${r.stderr ?? ''}`)
  }
  fs.writeFileSync(path.join(out, 'package.json'), '{"type":"commonjs"}')
  process.once('exit', () => fs.rmSync(out, { recursive: true, force: true }))
  const load = createRequire(import.meta.url)
  gateModules = {
    fixtureInvariants: load(path.join(out, 'pages/portfolio/fixtureInvariants.js')),
    fixtures: load(path.join(out, 'pages/portfolio/fixtures.js')),
    holdingsTable: load(path.join(out, 'pages/portfolio/HoldingsTable.js')),
    adapter: load(path.join(out, 'pages/portfolio/adapter.js')),
    analyticsAdapter: load(path.join(out, 'pages/portfolio/analyticsAdapter.js')),
    presets: load(path.join(out, 'pages/portfolio/presets.js')),
  }
  return gateModules
}

test('F1: the fixture invariants run here and report no violations', () => {
  const { fixtureInvariants, fixtures } = compileGateModules()
  // Not vacuous: the compiled module is the real fixture graph, and the book it checks is populated.
  assert.ok(fixtures.FIXTURE_BOOK.rows.length > 0, 'the compiled fixture book is empty — this gate would be vacuous')
  assert.deepEqual(fixtureInvariants.checkAllFixtures(), [])
})

test('F2: an unserved stale limit renders as "limit not served", never 0 s', () => {
  const { freshnessLine } = compileGateModules().holdingsTable
  assert.equal(freshnessLine(41, null, false), '41 s old · stale after limit not served')
  assert.match(freshnessLine(41, null, true), /limit not served/)
  assert.doesNotMatch(freshnessLine(41, null, true), /\b0 s\b/, 'an absent clock must not print an invented 0 s limit')
  assert.match(freshnessLine(null, null, true), /age not served/, 'the age branch is unchanged')
})

test('F2: a served 0.5 h limit is still 1800 s and keeps its wording', () => {
  const { freshnessLine } = compileGateModules().holdingsTable
  assert.equal(freshnessLine(41, 1800, false), '41 s old · stale after 30 min')
  assert.equal(freshnessLine(41, 1800, true), 'Last known good — 41 s old, past the 30 min limit. These values are not current.')
})

// ---- P: a served price is not a dollar amount (lead-approved 2026-11-15T04:35Z, option 1) -----
// SRNE served 0.0003 on the live book and printed "$0.00" — a non-zero value rendering as the one
// string the page reserves for a served zero. `price()` is fixed; `money()` is deliberately not.

test('P-1: a served sub-cent price keeps its magnitude and never prints $0.00', () => {
  assert.equal(price(0.0003), '$0.0003', 'the measured live row')
  assert.equal(price(0.00004), '<$0.0001', 'below the format floor the honest rendering is a bound, not zero')
  assert.notEqual(price(0.0003), '$0.00', 'a non-zero price must not print as zero')
})

test('P-2: two decimals stay the rule at and above one dollar, and a served zero is still $0.00', () => {
  assert.equal(price(1), '$1.00')
  assert.equal(price(12.345), '$12.35', 'display rounding only; the contract value is untouched')
  assert.equal(price(0), '$0.00', 'a served zero IS zero; this is the branch $0.00 is reserved for')
  assert.equal(price(0.3), '$0.30', 'a sub-dollar price that cents CAN express keeps two decimals')
  assert.equal(price(null), unavailable('no price served'), 'null is a reason, never a zero')
})

test('P-3: money() still expresses a dollar amount in cents', () => {
  assert.equal(money(0.0003), '$0.00', 'money() is out of scope by decision, not by oversight')
  assert.equal(money(1255586.37), '$1,255,586.37')
  assert.equal(money(null), unavailable('not served'))
})

// ---- V: the semantic colour and sign policy (operator route 2026-11-15T1555Z) ------------------------
// The operator reload of the LIVE page showed the header estimate WHITE and printed "$-1,841.22", warnings in
// neutral blue, and two-letter identity chips. These tests pin the three fixes that a tidy could silently undo:
// the sign formatter, the tone decision (an UNKNOWN is never a direction), and the class that carries the colour.

test('V-1: the sign precedes the currency symbol — "-$1,841.22", never "$-1,841.22"', () => {
  assert.equal(money(-1841.22), '-$1,841.22', 'the measured live header value')
  assert.equal(money(-1255586.37), '-$1,255,586.37')
  assert.equal(money(1841.22), '$1,841.22', 'a positive amount is unchanged')
  assert.equal(signedMoney(-1841.22), '-$1,841.22', 'signedMoney already led with the sign and must stay so')
  assert.equal(signedMoney(1841.22), '+$1,841.22')
  assert.equal(price(-0.0003), '-$0.0003', 'a negative sub-cent price keeps the same convention')
  assert.equal(money(-0), '$0.00', 'a served negative zero is zero, not a loss')
})

test('V-2: a tone is a direction the wire served — unknown is never gain or loss', () => {
  assert.equal(moneyTone(null), 'unknown')
  assert.equal(moneyTone(Number.NaN), 'unknown')
  assert.equal(moneyTone(-1841.22), 'loss')
  assert.equal(moneyTone(349.6), 'gain')
  assert.equal(moneyTone(0), 'flat', 'a served zero is a measurement, but not a direction')
  assert.equal(toneClass('unknown'), 'money-unknown')
  assert.equal(toneClass('loss'), 'money-loss')
  assert.equal(toneClass('gain'), 'money-gain')
  assert.equal(toneClass('flat'), '', 'flat keeps the surrounding ink')
})

test('V-3: the classes exist in one sheet and use the shell tokens', () => {
  const css = fs.readFileSync(path.join(APP, 'src/pages/portfolio/semantic.css'), 'utf8')
  // Anchored at the start of a line: the POLICY rule, not a later qualified restatement of it.
  // A `.session strong.money-loss` rule alone must not satisfy this test — otherwise deleting the base
  // class (the one every row and the header carry) would leave the suite green. Measured: it did.
  const rule = name => {
    const m = css.match(new RegExp(`^\\.${name}\\s*\\{([^}]*)\\}`, 'm'))
    assert.ok(m, `.${name} must be defined as its own rule in semantic.css`)
    return m[1]
  }
  assert.match(rule('money-loss'), /var\(--red\)/, 'a loss is the shell red token')
  assert.match(rule('money-gain'), /var\(--green\)/, 'a gain is the shell green token')
  assert.match(rule('money-unknown'), /var\(--muted\)/, 'unknown is muted, never a direction')
  assert.match(rule('note\\.warn'), /var\(--gold\)/, 'a warning is the gold token, not neutral blue')
  assert.ok(!/#[0-9a-f]{3,8}\b/i.test(css), 'this sheet introduces no hex palette of its own')
})

test('V-4: the header and the page apply the tone class (deleting it fails here)', () => {
  const top = fs.readFileSync(path.join(APP, 'src/pages/portfolio/TopBar.tsx'), 'utf8')
  assert.match(top, /className=\{toneClass\(tone\)/, 'the top bar value must carry the tone class')
  assert.match(top, /signed && !notCurrent\(book\.freshness\) \? moneyTone\(m\.valueUsd\)/, 'a direction only from a current read')
  const page = fs.readFileSync(path.join(APP, 'src/pages/portfolio/HoldingsPage.tsx'), 'utf8')
  assert.match(page, /className=\{toneClass\(priceMoveTone\)/, 'the page price-move value must carry the tone class')
  const table = fs.readFileSync(path.join(APP, 'src/pages/portfolio/HoldingsTable.tsx'), 'utf8')
  assert.match(table, /toneClass\(moneyTone\(row\.gainLoss\)\)/, 'the unrealized column must carry the tone class')
})

// ---- N: the book snapshot does not outlive its route (cc-deepseek-3 verdict 2026-11-15T04:48Z §8) --------
// The measured failure: load Portfolio › Holdings, click Home client-side, and the bar kept both bound values
// and the clock — the "not read on this page" state existed only on a cold load. `barStatus` is the route-aware
// guard, and it answers from the PATHNAME, never from "a snapshot happens to exist". A cold-load check cannot
// make this assertion; these tests do, because the failing input is exactly "published props + another route".

const PUBLISHED = { book: { rows: [], measures: { measures: {} } }, loading: false, error: null, notice: null }

test('N-1: a published book is shown only on the route whose page read it', () => {
  assert.equal(isBookRoute('/portfolio/holdings'), true)
  assert.equal(isBookRoute('/portfolio/holdings/'), true, 'a trailing slash names the same route')
  assert.equal(isBookRoute('/home/today'), false)
  assert.equal(isBookRoute('/portfolio'), false, 'the section root is not the reader route')
  assert.deepEqual(barStatus('/portfolio/holdings', PUBLISHED), { kind: 'book' })
})

test('N-2: after a client-side navigation the bar says not read, even with a snapshot still in state', () => {
  assert.deepEqual(barStatus('/home/today', PUBLISHED), { kind: 'not-read' })
  assert.deepEqual(barStatus('/portfolio/protection', PUBLISHED), { kind: 'not-read' })
  assert.deepEqual(barStatus('/portfolio/holdings', null), { kind: 'not-read' }, 'nothing published yet')
})

test('N-3: on the reader route the structural states still say what they say', () => {
  const R = '/portfolio/holdings'
  assert.deepEqual(barStatus(R, { book: null, loading: true, error: null, notice: null }), { kind: 'loading' })
  assert.deepEqual(barStatus(R, { book: null, loading: false, error: 'read failed', notice: null }), { kind: 'error', reason: 'read failed' })
})

// --- Account display label (lead finding 2026-11-15T05:09Z: raw keys in the Account table) ---
// The served reconciliation block carries the KEY and no label; the holdings rows of the same payload carry
// the label. The join happens in adapter.ts; this is the pure choice it makes, testable without a DOM.

test('accountLabel: the live case — a served row label replaces the raw key', () => {
  assert.equal(accountDisplayLabel('schwab_rollover_ira', null, 'Schwab Rollover IRA'), 'Schwab Rollover IRA')
  assert.equal(accountDisplayLabel('alpaca_taxable_live', null, 'Alpaca Individual'), 'Alpaca Individual')
})

test('accountLabel: a label served on the reconciliation block itself wins over the row copy', () => {
  assert.equal(accountDisplayLabel('schwab_roth_ira', 'Schwab Roth IRA', 'ROTH (row copy)'), 'Schwab Roth IRA')
})

test('accountLabel: a served label that merely repeats the key is not a label', () => {
  // Some producers echo the key into account_label. Rendering that passes the key off as a label and hides
  // the fact that no display name was served; the row copy is still a real chance to get one.
  assert.equal(accountDisplayLabel('schwab_taxable', 'schwab_taxable', 'Schwab Taxable'), 'Schwab Taxable')
  assert.equal(accountDisplayLabel('schwab_taxable', 'schwab_taxable', null), 'schwab_taxable')
})

test('accountLabel: nothing served anywhere leaves the key unchanged, and blank is nothing', () => {
  assert.equal(accountDisplayLabel('moomoo_taxable_live', null, null), 'moomoo_taxable_live')
  assert.equal(accountDisplayLabel('moomoo_taxable_live', '   ', ''), 'moomoo_taxable_live')
  assert.equal(accountDisplayLabel('moomoo_taxable_live', null, '  Alpaca Individual  '), 'Alpaca Individual')
})

// ---- The label JOIN preference, through the adapter itself (cc-deepseek-3 §1, mutant M-B) -----------
// The helper tests above pin `accountDisplayLabel`; they cannot pin which field the join KEYS on, because
// that choice lives in `accountsFrom`. -3's mutant M-B — `rowKey = str(row.account) ?? str(row.account_key)`
// — kept 62/62 green and, served on the live payload, rendered the Schwab Roth row as the raw key with
// "no display label served" while the other four were right: on that payload the rows' `account` is
// `schwab_roth` and only `account_key` is `schwab_roth_ira`, the key the reconciliation block publishes.
// This case runs the real adapter over that shape, so the mutant dies here.

test('accountLabel: the join keys on account_key, so a row whose two keys differ still gets its label', () => {
  const { accountsFrom } = compileGateModules().adapter
  const wire = {
    reconciliation: {
      accounts: [{ account: 'schwab_roth_ira', end_equity: { value_usd: 57147.66 } }],
    },
    holdings: [
      { account: 'schwab_roth', account_key: 'schwab_roth_ira', account_label: 'Schwab Roth IRA', symbol: 'VTI', shares: 1 },
      { account: 'alpaca_taxable_live', account_key: 'alpaca_taxable_live', account_label: 'Alpaca Individual', symbol: 'VTI', shares: 1 },
    ],
  }
  const out = accountsFrom(wire)
  assert.ok(out && out.length === 1, 'one reconciliation account renders one row')
  assert.equal(out[0].accountKey, 'schwab_roth_ira')
  assert.equal(out[0].accountLabel, 'Schwab Roth IRA',
    'the label is joined on account_key; keying on `account` leaves the raw key, which is exactly mutant M-B')
  assert.notEqual(out[0].accountLabel, out[0].accountKey, 'a label equal to the key is not a label')
})

test('accountLabel: through the adapter, nothing served anywhere still renders the key, never a guess', () => {
  const { accountsFrom } = compileGateModules().adapter
  const out = accountsFrom({
    reconciliation: { accounts: [{ account: 'moomoo_taxable_live', end_equity: { value_usd: 521.66 } }] },
    holdings: [{ account: 'moomoo_taxable_live', account_key: 'moomoo_taxable_live', symbol: 'VTI' }],
  })
  assert.equal(out[0].accountLabel, 'moomoo_taxable_live')
})

// --- The withheld-datum ledger line (cc-deepseek-3 rev-6 verdict, F1) -------------------------------
// The line is rendered-proven (§5.3 on a synthetic payload) but was not pinned: deleting the fragment left
// 64/64 and the design gate green. The sentence now has ONE source, `ledgerLine`, and BOTH of its conditions
// are decided there — so both directions fail a named test when lost. Design-gate rule 8 pins the call site.

const STOP_CLOCK = { role: 'STOPS', at: null, source: 'stops_clock', isBuildClock: false }

test('clockLedger: a withheld datum with no standing clock prints under its own label, byte-exact', () => {
  assert.equal(
    ledgerLine({ ...STOP_CLOCK, withheldAsOf: '2026-11-15T00:29:00Z' }),
    " · last stop read 2026-11-15T00:29:00Z — not the book's clock",
    'the leading space belongs to the line (it renders after the source); the §5.3 sentence is byte-pinned here',
  )
})

test('clockLedger: when the clock stands the withheld datum prints NOTHING — diagnosis never displaces a clock', () => {
  assert.equal(ledgerLine({ ...STOP_CLOCK, at: '2026-11-14T01:55:11.096798+00:00', withheldAsOf: '2026-11-15T00:29:00Z' }), null)
  assert.equal(ledgerLine({ role: 'POSITIONS', at: '2026-11-15T03:30:06.529835Z', source: 'positions', isBuildClock: false, withheldAsOf: '2026-11-15T00:29:00Z' }), null)
})

test('clockLedger: nothing withheld, or a blank datum, prints nothing — blank is not a timestamp', () => {
  assert.equal(ledgerLine(STOP_CLOCK), null)
  assert.equal(ledgerLine({ ...STOP_CLOCK, withheldAsOf: null }), null)
  assert.equal(ledgerLine({ ...STOP_CLOCK, withheldAsOf: '   ' }), null)
})

// ---- v0.5 selected view: approved-selector parity, the r6 §5 sector binding, and the exported CSV ------------
// Route 2026-11-15T1500Z ports the approved package as-is. These pin (a) the operator addendum's parity numbers
// against the package's own six synthetic preview rows (fixtures a–f), (b) the sector rule over fields served
// today, and (c) the export rule: the CSV IS the visible table — same rows, same preset, same cell walker.
const { derivePortfolioView } = await import('../../src/pages/portfolio/analytics/portfolio-analytics.mjs')

const PARITY_SNAPSHOT = {
  id: 'synthetic-2026-11-15T15:00:00Z',
  currency: 'USD',
  session: 'Session known',
  observedAt: '2026-11-15T15:00:00Z',
  status: 'fresh',
}
function parityRow(rowId, accountId, securityId, sector, marketValue, unrealizedPnl, isCash = false) {
  return {
    rowId,
    accountId,
    accountName: accountId === 'tax' ? 'Taxable' : 'IRA',
    securityId,
    symbol: securityId,
    name: securityId,
    snapshotId: PARITY_SNAPSHOT.id,
    currency: 'USD',
    isCash,
    sector,
    marketValue,
    unrealizedPnl,
  }
}
// The package's six preview rows. D-INC carries no sector, which is the Unclassified case; cash rows carry none.
const PARITY_ROWS = [
  parityRow('ira:D-AUR', 'ira', 'D-AUR', 'Technology', 250000, 50000),
  parityRow('ira:D-NOV', 'ira', 'D-NOV', 'Technology', 300000, -20000),
  parityRow('tax:D-ORB', 'tax', 'D-ORB', 'Health Care', 100000, 10000),
  parityRow('ira:D-INC', 'ira', 'D-INC', '', 350000, 15000),
  parityRow('ira:CASH', 'ira', 'CASH', '', 175000, null, true),
  parityRow('tax:CASH', 'tax', 'CASH', '', 75000, null, true),
]
const parityView = over =>
  derivePortfolioView(PARITY_ROWS, { account: '', sector: '', query: '', currency: null, ...over }, PARITY_SNAPSHOT)

test('v0.5 parity: Taxable is 2 rows, 175000 value, 75000 cash, 10000 unrealized', () => {
  const v = parityView({ account: 'tax' })
  assert.equal(v.rows.length, 2)
  assert.equal(v.total, 175000)
  assert.equal(v.cash, 75000)
  assert.equal(v.pnl, 10000)
  assert.equal(v.currencyValid, true, 'one served currency is valid, not an unknown one')
})

test('v0.5 parity: Health Care is 1 row and 100000; reset is all 6 rows', () => {
  const health = parityView({ sector: 'Health Care' })
  assert.equal(health.rows.length, 1)
  assert.equal(health.total, 100000)
  const all = parityView()
  assert.equal(all.rows.length, 6, 'reset shows every row')
  assert.equal(all.total, 1250000, 'the six published values summed — a display aggregate of published values')
})

test('v0.5 parity: searching D-NOV is 1 row, 300000, −20000', () => {
  const v = parityView({ query: 'D-NOV' })
  assert.equal(v.rows.length, 1)
  assert.equal(v.total, 300000)
  assert.equal(v.pnl, -20000)
})

// A sector decision needs only the fields this read serves: kind, asset_type, profile_source, the carried label.
const sectorRow = over => ({
  kind: 'SECURITY',
  assetType: 'EQUITY',
  profileSource: 'yfinance',
  fundamentals: { sector: 'Technology' },
  ...over,
})

test('r6 §5: cash and fund rows are one displayed bucket under the selector’s own cash key', () => {
  const { sectorDisplayLabel, selectorSector, displaySectorKey, CASH_BUCKET_KEY, SECTOR_FUNDS } = compileGateModules().analyticsAdapter
  const cash = sectorRow({ kind: 'CASH', assetType: 'CASH', fundamentals: null })
  assert.equal(sectorDisplayLabel(cash), SECTOR_FUNDS)
  assert.equal(selectorSector(cash), CASH_BUCKET_KEY)
  assert.equal(displaySectorKey(CASH_BUCKET_KEY), SECTOR_FUNDS, 'the internal key never reaches the reader')
  assert.equal(sectorDisplayLabel(sectorRow({ assetType: 'ETF' })), SECTOR_FUNDS, 'an ETF is the fund, never look-through')
  assert.equal(selectorSector(sectorRow({ assetType: 'MUTUAL_FUND' })), CASH_BUCKET_KEY)
  assert.equal(sectorDisplayLabel(sectorRow({ assetType: null })), 'Technology', 'only a served fund asset type is a fund')
})

test('r6 §5: an unavailable profile prints the sentence, never the carried label', () => {
  const { sectorDisplayLabel, selectorSector, SECTOR_UNAVAILABLE } = compileGateModules().analyticsAdapter
  const row = sectorRow({ profileSource: 'unavailable', fundamentals: { sector: 'Technology' } })
  assert.equal(sectorDisplayLabel(row), SECTOR_UNAVAILABLE)
  assert.doesNotMatch(sectorDisplayLabel(row), /Technology/, 'provenance outranks the stale carried text')
  assert.equal(selectorSector(row), SECTOR_UNAVAILABLE, 'no real Technology bucket absorbs an unsourced row')
})

test('r6 §5: null or blank classification is Unclassified, not a category the provider chose', () => {
  const { sectorDisplayLabel, SECTOR_UNCLASSIFIED } = compileGateModules().analyticsAdapter
  assert.equal(sectorDisplayLabel(sectorRow({ fundamentals: null })), SECTOR_UNCLASSIFIED)
  assert.equal(sectorDisplayLabel(sectorRow({ fundamentals: { sector: '   ' } })), SECTOR_UNCLASSIFIED)
  assert.equal(sectorDisplayLabel(sectorRow({ fundamentals: { sector: ' Health Care ' } })), 'Health Care')
})

test('the adapter normalizes the fixture book into a valid selected view', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const { normalizeBook, snapshotFor, selectorSector } = analyticsAdapter
  const rows = normalizeBook(fixtures.FIXTURE_BOOK)
  assert.equal(rows.length, fixtures.FIXTURE_BOOK.rows.length)
  for (const r of rows) {
    assert.equal(r.rowId, `${r.holding.accountKey}:${r.holding.symbol}`)
    assert.equal(r.currency, 'USD', 'no per-row currency is served; the page’s declared USD is the stated adaptation')
    assert.equal(r.snapshotId, fixtures.FIXTURE_BOOK.asOf)
    assert.equal(r.isCash, r.holding.kind === 'CASH')
    assert.equal(r.sector, selectorSector(r.holding))
    assert.equal(r.unrealizedPnl, r.holding.gainLoss, 'unrealized is passed through, never recomputed')
  }
  const v = derivePortfolioView(rows, { account: '', sector: '', query: '', currency: null }, snapshotFor(fixtures.FIXTURE_BOOK))
  assert.equal(v.rows.length, rows.length)
  assert.equal(v.currencyValid, true)
  assert.equal(snapshotFor(fixtures.FIXTURE_BOOK).status, 'fresh')
  // §K: the wire serves NO validated last-success receipt, so a stale book is 'unverified' — never 'last-good'.
  assert.equal(snapshotFor(fixtures.FIXTURE_BOOK_STALE).status, 'unverified')
  assert.match(snapshotFor(fixtures.FIXTURE_BOOK_STALE).reason, /freshness unverified/)
})

test('§L: the gain/loss label counts N of M from the rows in the CURRENT filter, never a constant', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const { normalizeBook, snapshotFor, gainLossMeasureCopy } = analyticsAdapter
  const rows = normalizeBook(fixtures.FIXTURE_BOOK)
  const snapshot = snapshotFor(fixtures.FIXTURE_BOOK)
  const measure = scope =>
    gainLossMeasureCopy(derivePortfolioView(rows, { account: '', sector: '', query: '', currency: null, ...scope }, snapshot))
  // Three different filters over the same fixture book: three different counts. A hardcoded "6 of 8" (or any
  // other constant) makes at least one of these three assertions fail.
  const all = measure({})
  const taxable = measure({ account: 'SYN_TAX' })
  const health = measure({ sector: 'Health care' })
  assert.deepEqual([all.published, all.held], [6, 8])
  assert.deepEqual([taxable.published, taxable.held], [2, 3])
  assert.deepEqual([health.published, health.held], [1, 1])
  assert.match(taxable.subtext, /2 of 3 have published gain\/loss/)
  assert.match(health.subtext, /1 of 1 have published gain\/loss/)
  assert.doesNotMatch(taxable.subtext, /6 of 8/)
  assert.equal(all.partial, true)
  assert.match(all.title, /^Open-position gain\/loss vs\. cost — partial$/)
  assert.equal(health.partial, false)
  assert.equal(health.title, 'Open-position gain/loss vs. cost', 'a complete filter is not labelled partial')
  assert.match(all.subtext, /not today\/YTD profit/)
  assert.doesNotMatch(all.subtext, /period profit/i)
})

test('§L: each excluded row is named with the reason from its OWN coverage', () => {
  const { gainLossMeasureCopy } = compileGateModules().analyticsAdapter
  const row = (rowId, pnl, avgCost, cash = false) => ({
    rowId, symbol: rowId, name: rowId, securityId: rowId, isCash: cash,
    unrealizedPnl: pnl, holding: { avgCost },
  })
  const copy = gainLossMeasureCopy({
    rows: [
      row('A:Q1', 25, 10),
      row('A:Q2', null, null),
      row('A:Q3', null, 12),
      row('A:CASH', null, null, true),
    ],
    coverage: { pnl: 1, nonCash: 3 },
  })
  assert.deepEqual(copy.excluded.map(x => [x.rowId, x.reason]), [
    ['A:Q2', 'no basis served'],
    ['A:Q3', 'no gain/loss served'],
  ])
  assert.equal(copy.excluded.some(x => x.rowId === 'A:CASH'), false, 'cash is not an investment row with a missing gain/loss')
  // A row with a published gain/loss stays in the subtotal whatever its basis representation — the exclusion test
  // is "no published gain/loss", never a basis-provenance veto.
  assert.equal(copy.excluded.some(x => x.rowId === 'A:Q1'), false, 'a published row is never excluded for its basis provenance')
})

test('§K: a stale book says "freshness unverified" — last-good needs a validated receipt', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const { snapshotFor, freshnessCopy } = analyticsAdapter
  const stale = snapshotFor(fixtures.FIXTURE_BOOK_STALE)
  assert.equal(stale.status, 'unverified')
  assert.equal(stale.receipt, undefined)
  const line = 'Last available snapshot · freshness unverified'
  assert.equal(freshnessCopy(stale).line, line)
  // Fail-closed at the render layer: even a hand-set last-good status with no receipt is not dressed as good.
  assert.equal(freshnessCopy({ ...stale, status: 'last-good', reason: 'forged' }).line, line)
  // With a receipt the copy is built from the receipt object, not from the status string.
  const good = snapshotFor(fixtures.FIXTURE_BOOK_STALE, { at: '2026-11-14T20:00:00Z', source: 'fixture last-success receipt' })
  assert.equal(good.status, 'last-good')
  assert.equal(freshnessCopy(good).line, 'Last known good 2026-11-14T20:00:00Z · fixture last-success receipt')
  // A current book prints no warning line at all.
  assert.equal(freshnessCopy(snapshotFor(fixtures.FIXTURE_BOOK)).line, '')
})

test('§K: each domain clock is reported on its own; a stop-read gap is never the quote clock’s fault', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const { snapshotFor } = analyticsAdapter
  const snap = snapshotFor(fixtures.FIXTURE_BOOK)
  assert.deepEqual(snap.clocks.map(c => c.domain), ['quote', 'positions', 'basis', 'protection'])
  const by = Object.fromEntries(snap.clocks.map(c => [c.domain, c]))
  assert.equal(by.quote.status, 'KNOWN')
  assert.equal(by.quote.at, '2026-11-14T21:00:00Z')
  assert.equal(by.positions.status, 'KNOWN')
  assert.equal(by.basis.status, 'UNKNOWN')
  assert.match(by.basis.reason, /VALUATION clock declared on this read/)
  assert.equal(by.protection.status, 'UNKNOWN')
  assert.match(by.protection.reason, /STOPS clock declared on this read/)
  assert.notEqual(by.basis.reason, by.protection.reason, 'two gaps, two named reasons')
  assert.equal(snap.dataAsOf, '2026-11-14T21:00:00Z (QUOTE clock)')
  assert.equal(snap.overall, 'PARTIAL', 'two of four domain clocks are UNKNOWN')
  for (const c of snap.clocks) assert.doesNotMatch(c.reason, /Error|\bMB\b|\bKB\b|\bat .*:\d+\b/, 'no traceback or size prose')
  // A clock role present without an instant dates nothing: the label says Unknown and why.
  const undated = {
    ...fixtures.FIXTURE_BOOK,
    clocks: fixtures.FIXTURE_BOOK.clocks.map(c => (c.role === 'QUOTE' ? { ...c, at: null } : c)),
  }
  assert.equal(snapshotFor(undated).dataAsOf, 'Unknown (QUOTE clock declared without an instant)')
})

test('an unkeepable row identity is rejected by the selector, never charted', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const book = { ...fixtures.FIXTURE_BOOK, rows: [{ ...fixtures.FIXTURE_BOOK.rows[0], accountKey: '' }] }
  const rows = analyticsAdapter.normalizeBook(book)
  assert.throws(
    () => derivePortfolioView(rows, { account: '', sector: '', query: '', currency: null }, analyticsAdapter.snapshotFor(book)),
    /canonical row, account and security identity/,
    'the page catches this and says so; it does not print a total over a row it cannot identify',
  )
})

/** A minimal RFC 4180 field splitter for the assertions below: quotes protect commas, doubled quotes unescape. */
function csvFields(line) {
  const out = []
  let field = ''
  let quoted = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        field += '"'
        i++
      } else if (ch === '"') quoted = false
      else field += ch
    } else if (ch === '"') quoted = true
    else if (ch === ',') {
      out.push(field)
      field = ''
    } else field += ch
  }
  out.push(field)
  return out
}

test('CSV: header, row count and field count come from the preset and the visible rows', () => {
  const { fixtures, holdingsTable, presets } = compileGateModules()
  const overview = presets.PRESETS.find(p => p.id === 'holdings')
  const rows = fixtures.FIXTURE_BOOK.rows.slice(0, 4)
  const csv = holdingsTable.csvFor(rows, overview)
  assert.ok(csv.endsWith('\r\n'), 'RFC 4180 records; the final record is terminated')
  const lines = csv.slice(0, -2).split('\r\n')
  assert.equal(lines.length, rows.length + 1, 'one header record and one record per visible row')
  assert.equal(lines[0], overview.columns.map(c => c.header).join(','), 'the header is the preset’s own')
  for (const line of lines.slice(1)) assert.equal(csvFields(line).length, overview.columns.length)
})

test('CSV: a protection chip exports its label — the same text the table prints', () => {
  const { holdingsTable } = compileGateModules()
  const preset = { id: 'holdings', label: 'protection', columns: [{ key: 'protection', header: 'Protection' }], methodNote: '', limits: [] }
  const gap = {
    kind: 'SECURITY',
    protection: { state: 'GAP', reason: 'no resting stop', stop: null, basis: null, asOf: null, stale: null, nextStep: 'record a stop' },
  }
  assert.equal(holdingsTable.csvFor([gap], preset), 'Protection\r\nGap\r\n')
})
