// Shell logic tests (client + renderState), plus the portfolio gates that need a compiled artifact: the
// Holdings fixture invariants and the Holdings freshness line. Plain node: `node --test scripts/tests/`.
// Synthetic fixtures only; shapes copied from cc-deepseek-7's measured envelopes (2026-11-14 2307Z),
// values invented.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createClient, HeavyReaderFromShell } from '../../src/api/client.ts'
import { specFor, READERS } from '../../src/api/readers.ts'
import { deriveRenderState, statusCue } from '../../src/components/renderState.ts'
import { price, money, moneyTone, signedMoney, toneClass, unavailable, lastKnownSentence, servedFreshnessLine } from '../../src/pages/portfolio/format.ts'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
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
  // The panel imports the approved package's stylesheet; the gate has no bundler, so it declares the module
  // shape and stubs the require extension below. Nothing else about the panel changes.
  const cssDecl = path.join(out, 'css-modules.d.ts')
  fs.writeFileSync(cssDecl, "declare module '*.css'\n")
  const args = [
    '--target', 'ES2020', '--module', 'commonjs', '--moduleResolution', 'node', '--strict', '--skipLibCheck',
    '--allowImportingTsExtensions', '--rewriteRelativeImportExtensions', '--jsx', 'react-jsx',
    '--typeRoots', path.join(APP, 'node_modules/@types'), '--types', 'node', '--outDir', out,
    path.join(APP, 'src/pages/portfolio/fixtureInvariants.ts'),
    path.join(APP, 'src/pages/portfolio/HoldingsTable.tsx'),
    path.join(APP, 'src/pages/portfolio/adapter.ts'),
    path.join(APP, 'src/pages/portfolio/analyticsAdapter.ts'),
    path.join(APP, 'src/pages/portfolio/presets.ts'),
    path.join(APP, 'src/pages/portfolio/AnalyticsPanel.tsx'),
    // RC3: the Allocation page renders its status strip in the panel's own vocabulary; it is compiled here so
    // that the render test executes the real page, not a copy of its string.
    path.join(APP, 'src/pages/allocation/AllocationPage.tsx'),
    // The phone card is a second surface that names the gain/loss measure; compiled here so the render test
    // below executes the real card, not a copy of its caption.
    path.join(APP, 'src/pages/portfolio/PositionCards.tsx'),
    // SPCX display-identity spec: the drawer eyebrow and the search predicate are two of the spec's surfaces, so
    // they are compiled here and driven by the tests below — the real functions, not copies of them.
    path.join(APP, 'src/pages/portfolio/detail.ts'),
    path.join(APP, 'src/pages/portfolio/search.ts'),
    cssDecl,
  ]
  const r = spawnSync(process.execPath, [tsc, ...args], { encoding: 'utf8' })
  if (r.status !== 0) {
    throw new Error(`tsc could not compile the portfolio gate modules (rc ${r.status}):\n${r.stdout ?? ''}${r.stderr ?? ''}`)
  }
  fs.writeFileSync(path.join(out, 'package.json'), '{"type":"commonjs"}')
  process.once('exit', () => fs.rmSync(out, { recursive: true, force: true }))
  // The panel's stylesheet is an asset the gate does not bundle: the compiled require needs the file to exist,
  // and an empty file is enough because nothing in this test reads it.
  const cssOut = path.join(out, 'pages/portfolio/analytics')
  fs.mkdirSync(cssOut, { recursive: true })
  fs.writeFileSync(path.join(cssOut, 'analytics.css'), '')
  // AllocationPage's own stylesheet, same loader fact.
  const allocOut = path.join(out, 'pages/allocation')
  fs.mkdirSync(allocOut, { recursive: true })
  fs.writeFileSync(path.join(allocOut, 'allocation.css'), '')
  // AllocationPage -> allocationView -> the approved selector, which is a `.mjs` the tsc emit does not copy.
  // Copy the SOURCE file to the path the emitted require names: still the repo's file, not a re-typed copy.
  fs.copyFileSync(
    path.join(APP, 'src/pages/portfolio/analytics/portfolio-analytics.mjs'),
    path.join(cssOut, 'portfolio-analytics.mjs'),
  )
  const load = createRequire(import.meta.url)
  // The stylesheet is a text asset: requiring it must not execute anything, and the panel's render is what is
  // under test. This stub is a loader fact, not a code path the page has.
  load.extensions['.css'] = () => {}
  gateModules = {
    fixtureInvariants: load(path.join(out, 'pages/portfolio/fixtureInvariants.js')),
    fixtures: load(path.join(out, 'pages/portfolio/fixtures.js')),
    holdingsTable: load(path.join(out, 'pages/portfolio/HoldingsTable.js')),
    adapter: load(path.join(out, 'pages/portfolio/adapter.js')),
    analyticsAdapter: load(path.join(out, 'pages/portfolio/analyticsAdapter.js')),
    presets: load(path.join(out, 'pages/portfolio/presets.js')),
    panel: load(path.join(out, 'pages/portfolio/AnalyticsPanel.js')),
    allocationPage: load(path.join(out, 'pages/allocation/AllocationPage.js')),
    positionCards: load(path.join(out, 'pages/portfolio/PositionCards.js')),
    displayIdentity: load(path.join(out, 'pages/portfolio/displayIdentity.js')),
    detail: load(path.join(out, 'pages/portfolio/detail.js')),
    search: load(path.join(out, 'pages/portfolio/search.js')),
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
  assert.equal(freshnessLine(41, 1800, true), 'Last available snapshot — 41 s old, past the 30 min limit. These values are not current.')
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
  const page = fs.readFileSync(path.join(APP, 'src/pages/portfolio/workspaceV2/Workspace.tsx'), 'utf8')
  // Current golden rule: sign colour describes the served historical reading; freshness is a separate explicit warning.
  assert.match(page, /notCurrent\(book\.freshness\)\?'PARTIAL · not current'/, 'historical signed readings retain a visible non-current warning')
  assert.match(page, /<SignedValue value=\{g\.pnl\.value\}/, 'movers carry the shared signed reading instead of implying freshness from colour')
  assert.match(page, /className=\{colour\(g\.pnl\.value\)\}/, 'the selected-period value carries its guarded tone')
  assert.match(page, /className=\{colour\(g\.unrealized\.value\)\}/, 'unrealized carries its guarded tone')
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
  assert.match(by.basis.reason, /no basis clock is served on this read/)
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

// ---- R1/R2/R3: the review 2026-11-15T1704Z delta on aa8be33e8 -------------------------------------------
// R1: basis must not borrow the VALUATION document clock. R2: no page copy may assert last-good without a
// validated receipt. R3: the route's two render requirements get guards that fail when the render is removed.

test('R1: a served VALUATION clock is never borrowed for basis — the basis line stays UNKNOWN with its own reason', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const { snapshotFor } = analyticsAdapter
  const withValuation = fixtures.FIXTURE_BOOK_VALUATION_CLOCK
  const snap = snapshotFor(withValuation)
  const by = Object.fromEntries(snap.clocks.map(c => [c.domain, c]))
  assert.equal(by.basis.label, 'Basis', 'the label names the domain, not a substituted role')
  assert.equal(by.basis.status, 'UNKNOWN', 'basis has no clock on the wire, so no served clock can make it KNOWN')
  assert.match(by.basis.reason, /no basis clock is served on this read/)
  assert.doesNotMatch(by.basis.reason, /VALUATION|generated_at/, 'the basis line never credits the valuation document clock')
  // The VALUATION instant is still a served fact: when the producer dates the book by it, "Data as of" uses it.
  const datedByValuation = { ...withValuation, asOf: '2026-11-15T03:30:30.069691+00:00', asOfClock: 'VALUATION' }
  assert.equal(snapshotFor(datedByValuation).dataAsOf, '2026-11-15T03:30:30.069691+00:00 (VALUATION clock)')
  // A role the read does not declare is named as absent, never guessed.
  assert.match(snapshotFor({ ...fixtures.FIXTURE_BOOK, asOfClock: 'STOPS' }).dataAsOf, /^Unknown \(no STOPS clock declared on this read\)$/)
})

/** The phrase §K reserves for a validated receipt. It must not appear in copy without one. */
const LAST_GOOD = /last[- ]known[- ]good|last good/i

test('R2: every pure copy producer the page prints refuses "last-good" without a receipt', () => {
  const { fixtures, holdingsTable } = compileGateModules()
  // The figure/table copy (HoldingsTable.freshnessLine), both stale branches.
  assert.doesNotMatch(holdingsTable.freshnessLine(41, 1800, true), LAST_GOOD)
  assert.doesNotMatch(holdingsTable.freshnessLine(41, null, true), LAST_GOOD)
  assert.match(holdingsTable.freshnessLine(41, 1800, true), /^Last available snapshot — /)
  // The producer-verdict line (format.servedFreshnessLine), stale branch.
  const staleVerdict = { status: 'STALE', stale: true, clock: 'positions', clockLabel: 'POSITIONS',
    asOf: null, ageSeconds: 5400, limitSeconds: 1800, gap: null }
  assert.doesNotMatch(servedFreshnessLine(staleVerdict), LAST_GOOD)
  assert.match(servedFreshnessLine(staleVerdict), /^Last available snapshot — /)
  // The alert sentence (format.lastKnownSentence): every branch, not just the one a fixture happens to reach.
  const verdicts = [
    { served: { ...staleVerdict, status: 'FRESH', stale: false }, ageSeconds: null, staleAfterSeconds: null, stale: false, withdrawn: false },
    { served: null, ageSeconds: 314400, staleAfterSeconds: 259200, stale: true, blockPresent: true, withdrawn: false },
    { served: { ...staleVerdict, status: 'UNKNOWN', gap: 'no source clock' }, ageSeconds: null, staleAfterSeconds: null, stale: true, withdrawn: false },
    { served: staleVerdict, ageSeconds: null, staleAfterSeconds: null, stale: true, withdrawn: false },
  ]
  for (const f of verdicts) {
    const sentence = lastKnownSentence(f)
    assert.doesNotMatch(sentence, LAST_GOOD, `the alert asserts a receipt it does not have: "${sentence}"`)
    assert.match(sentence, /last available snapshot/i)
  }
})

/**
 * Every string literal in the page's modules, comments skipped. A small scanner rather than a regex over the
 * whole file: an apostrophe in a comment must not open a "string" that swallows half the module.
 */
function stringLiterals(src) {
  const out = []
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (ch === '/' && src[i + 1] === '/') {
      while (i < src.length && src[i] !== '\n') i++
      continue
    }
    if (ch === '/' && src[i + 1] === '*') {
      i += 2
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2
      continue
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      const quote = ch
      let j = i + 1
      let buf = ''
      while (j < src.length) {
        if (src[j] === '\\') { buf += src[j] + (src[j + 1] ?? ''); j += 2; continue }
        if (src[j] === quote) break
        buf += src[j]
        j++
      }
      out.push({ text: buf, quoted: src.slice(i, j + 1) })
      i = j + 1
      continue
    }
    i++
  }
  return out
}

test('R2: page-wide — no string literal in the page modules asserts last-good except the receipt-gated line', () => {
  const dir = path.join(APP, 'src/pages/portfolio')
  const files = fs.readdirSync(dir).filter(f => /\.(ts|tsx)$/.test(f))
  assert.ok(files.length > 10, 'the scan found no page modules — it would be vacuous')
  // Two modules hold strings that never reach the page: the node-only harnesses `adapterTests.ts` (assertion
  // labels, run by this suite) and `fixtureInvariants.ts` (violation messages, compiled by it). Every other
  // module can print, so it is scanned — and the exclusion is proved rather than asserted: if any page module
  // ever imports a harness, the scan fails rather than silently skipping its copy.
  const NODE_ONLY = new Set(['adapterTests.ts', 'fixtureInvariants.ts'])
  const bad = []
  let receiptGated = 0
  for (const f of files) {
    const src = fs.readFileSync(path.join(dir, f), 'utf8')
    if (NODE_ONLY.has(f)) {
      assert.match(src, /no React|imports no React|node:/, `${f} is excluded from the copy scan; prove it is node-only`)
      continue
    }
    for (const other of NODE_ONLY) {
      if (new RegExp(`from\\s+['"]\\./${other.replace('.ts', '')}['"]`).test(src)) {
        assert.fail(`${f} imports ${other}; its strings can reach the page, so it is not safe to skip the scan`)
      }
    }
    for (const { text, quoted } of stringLiterals(src)) {
      if (!LAST_GOOD.test(text)) continue
      // The one permitted occurrence: the panel's last-good line is built from the receipt OBJECT it interpolates.
      if (f === 'analyticsAdapter.ts' && /\$\{(snapshot\.)?receipt\.at\}/.test(quoted)) {
        receiptGated++
        continue
      }
      bad.push(`${f}: ${text.slice(0, 90)}`)
    }
  }
  assert.deepEqual(bad, [], 'copy that asserts last-good without a validated receipt')
  assert.ok(receiptGated >= 1, 'the receipt-gated copies are found, not silently skipped')
})

test('R2: the rendered panel says "freshness unverified" on a stale book and never dresses it as good', () => {
  const { fixtures, analyticsAdapter, panel } = compileGateModules()
  const rows = analyticsAdapter.normalizeBook(fixtures.FIXTURE_BOOK_STALE)
  const view = derivePortfolioView(rows, { account: '', sector: '', query: '', currency: null },
    analyticsAdapter.snapshotFor(fixtures.FIXTURE_BOOK_STALE))
  const html = renderPanel(panel.AnalyticsPanel, view, rows, analyticsAdapter.accountOptions)
  assert.match(html, /Last available snapshot · freshness unverified/)
  assert.doesNotMatch(html, LAST_GOOD)
  // N1: the warning is followed by a separator, not glued to the coverage count ("…valued Last available…").
  assert.doesNotMatch(html, /valued</, 'the warning is glued to the coverage count with no separator')
  // A fresh book has no warning line at all.
  const freshRows = analyticsAdapter.normalizeBook(fixtures.FIXTURE_BOOK)
  const freshView = derivePortfolioView(freshRows, { account: '', sector: '', query: '', currency: null },
    analyticsAdapter.snapshotFor(fixtures.FIXTURE_BOOK))
  assert.doesNotMatch(renderPanel(panel.AnalyticsPanel, freshView, freshRows, analyticsAdapter.accountOptions), /wm-pa-warning/)
})

/** Render the panel with the props HoldingsPage passes, so the guard exercises the real markup. */
function renderPanel(Panel, view, rows, accountOptions) {
  const noop = () => {}
  return renderToStaticMarkup(Panel({
    view, accounts: accountOptions(rows), scope: 'ALL', sector: '', query: '', currency: null, announcement: '',
    onAccount: noop, onSector: noop, onSearch: noop, onCurrency: noop, onReset: noop, onOpenHolding: noop,
  }))
}

test('R3(a): the excluded rows are NAMED in the rendered panel — removing that render fails here', () => {
  const { fixtures, analyticsAdapter, panel } = compileGateModules()
  const rows = analyticsAdapter.normalizeBook(fixtures.FIXTURE_BOOK)
  const view = derivePortfolioView(rows, { account: '', sector: '', query: '', currency: null },
    analyticsAdapter.snapshotFor(fixtures.FIXTURE_BOOK))
  const copy = analyticsAdapter.gainLossMeasureCopy(view)
  assert.ok(copy.excluded.length >= 2, 'the fixture must exclude rows or this render guard is vacuous')
  const html = renderPanel(panel.AnalyticsPanel, view, rows, analyticsAdapter.accountOptions)
  assert.match(html, /Not included:/)
  for (const x of copy.excluded) {
    assert.ok(html.includes(x.label), `${x.label} is not named in the rendered measure`)
    assert.ok(html.includes(x.reason), `${x.label}'s own reason is not rendered`)
  }
})

test('R3(b): a published legacy row at zero market value stays in the subtotal', () => {
  const { fixtures, analyticsAdapter } = compileGateModules()
  const book = fixtures.FIXTURE_BOOK_LEGACY_PUBLISHED
  const legacy = book.rows.find(r => r.symbol === 'QZLGC')
  assert.equal(legacy.marketValue, 0)
  assert.equal(legacy.gainLoss, -500)
  const selection = { account: '', sector: '', query: '', currency: null }
  const snapshot = analyticsAdapter.snapshotFor(book)
  const rows = analyticsAdapter.normalizeBook(book)
  const view = derivePortfolioView(rows, selection, snapshot)
  const copy = analyticsAdapter.gainLossMeasureCopy(view)
  assert.equal(copy.excluded.some(x => x.rowId === 'SYN_ROLL:QZLGC'), false, 'the legacy row is published, so it is never excluded')
  // Removing the row changes the subtotal: it is inside the measure, not merely listed in the table. This row is
  // the only zero-market-value row with a published gain/loss, so a rule that drops zero-value rows (instead of
  // rows with no published gain/loss) changes the sum — and is killed here rather than incidentally.
  const without = derivePortfolioView(rows.filter(r => r.rowId !== 'SYN_ROLL:QZLGC'), selection, snapshot)
  assert.notEqual(without.pnl, view.pnl, 'the zero-value published row contributes to the subtotal')
  assert.equal(view.pnl - without.pnl, -500)
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

/**
 * C (lead route 2026-11-15T1722Z): the operator saw a PROTECTED row's tooltip say "Resting GTC stop, pending
 * activation" AND "no resting stop" AND "a resting stop is served". The stop sentence is now derived from the
 * STATE: pending-GTC-with-no-served-price says exactly that, "no resting stop" is true only of a GAP, and an
 * UNKNOWN read is neither. Both cells (the chip's tooltip and the Stop column) print the one sentence.
 */
test('C: a PROTECTED row with no served stop price never says "no resting stop"', () => {
  const { fixtures, holdingsTable } = compileGateModules()
  const preset = {
    id: 'holdings', label: 'protection', methodNote: '', limits: [],
    columns: [{ key: 'protection', header: 'Protection' }, { key: 'stop', header: 'Stop' }],
  }
  const base = fixtures.FIXTURE_BOOK.rows[0]
  const render = protection => renderToStaticMarkup(
    holdingsTable.HoldingsTable({ rows: [{ ...base, protection }], preset, onRowOpen: () => {} }),
  )
  const strip = (s) => s.replace(/&amp;/g, '&')
  const count = (hay, needle) => (hay.match(new RegExp(needle, 'gi')) || []).length

  // PROTECTED, the wire states a resting GTC stop, no price served. The row is stale in its own right.
  const pending = render({
    state: 'PROTECTED', stop: null, basis: 'resting broker stop (GTC)', asOf: '2026-11-15T12:00:00Z', stale: true,
    reason: 'Resting GTC stop, pending activation', nextStep: 'None — protection is in place.',
  })
  assert.match(strip(pending), /resting GTC stop, pending activation — stop price not served \(stale\)/)
  assert.doesNotMatch(strip(pending), /no resting stop/i, 'a protected row is not an unprotected one')
  assert.equal(
    count(strip(pending), 'resting GTC stop, pending activation'),
    count(strip(pending), 'stop price not served'),
    "the producer's own reason is not echoed beside the sentence that repeats it",
  )

  // PROTECTED with a served price keeps the price, and claims no pending activation.
  const priced = render({ state: 'PROTECTED', stop: 68.0, basis: 'resting broker stop (GTC)', asOf: '2026-11-15T12:00:00Z', stale: false,
    reason: 'a resting stop is recorded for this position', nextStep: 'None — protection is in place.' })
  assert.match(strip(priced), /stop \$68\.00/)
  assert.doesNotMatch(strip(priced), /pending activation/i)

  // A GAP is the only state that says there is no resting stop.
  const gap = render({ state: 'GAP', stop: null, basis: null, asOf: null, stale: null,
    reason: 'no resting stop and no recorded decision to hold unprotected', nextStep: 'Set a protective stop.' })
  assert.match(strip(gap), /no resting stop/)
  assert.doesNotMatch(strip(gap), /pending activation/i)

  // An UNKNOWN read is neither "none" nor "pending": it says the row was not read.
  const unknown = render({ state: 'UNKNOWN', stop: null, basis: null, asOf: null, stale: null,
    reason: 'no broker stop read for a delisted zero-value identifier', nextStep: 'Record the write-off decision.' })
  assert.match(strip(unknown), /stop state unknown: this row has no stop read/)
  assert.doesNotMatch(strip(unknown), /no resting stop/i)
})

/**
 * C/RC1 (review 2026-11-15T1745Z): the default next step the ADAPTER chooses may not claim a stop "is served" on a
 * row whose wire served no stop price. The defect was at adapter.ts:109-111 and only visible through the real
 * adapter: a PROTECTED row with no `cause` and no `stop` got "none — a resting stop is served for this row", which
 * the page then printed beside the Stop column's "pending activation — stop price not served" on 8/30 live rows.
 * This builds the row through `adaptHoldings` from a synthetic wire body (never a hand-built Protection) and would
 * fail on the old single-string default.
 */
test('C/RC1: a PROTECTED row served without a stop price never claims a stop "is served" (real adapter)', () => {
  const { adapter, fixtures, holdingsTable } = compileGateModules()
  const wireRow = (protection) => ({
    symbol: 'SYNPX', name: 'Synthetic Pending Stop', account: 'acct_a', account_key: 'acct_a',
    account_label: 'Synthetic A', is_cash: false, asset_type: 'EQUITY',
    shares: 100, price: 150, price_as_of: '2026-11-15T12:00:00Z', market_value: 15000,
    portfolio_pct: 100, avg_cost: 120, cost_basis_source: 'broker_avg_price', cost_basis_total: 12000,
    gain_loss: 3000, gain_loss_pct: 25, protection_state: 'PROTECTED', protection,
  })
  const body = (protection) => ({
    ok: true,
    _swr: { stale: false, age_s: 0 },
    data: {
      count: 1,
      holdings: [wireRow(protection)],
      truth: { source: 'synthetic', as_of: '2026-11-15T12:00:00-05:00', stale: false, gap: null },
      clock_provenance: { quote: { source_field: 'last_repriced', as_of: '2026-11-15T12:00:00-05:00', gap: null } },
      scope_coverage: { min_position_usd: 100, scopes: { 'holdings.all_rows': 1, 'holdings.non_cash': 1, 'holdings.cash': 0 } },
    },
  })
  const pendingProtection = {
    state: 'PROTECTED', source: 'stops', as_of: '2026-11-15T14:15:00Z', cause: null, counted: true,
    reason: 'Resting GTC stop, pending activation',
  }

  // The wire serves the state but NO price: stops_read publishes counts only.
  const res = adapter.adaptHoldings(body(pendingProtection))
  assert.ok(res.book !== null, `the synthetic body must adapt: ${res.error ?? ''}`)
  const row = res.book.rows[0]
  assert.equal(row.protection.state, 'PROTECTED')
  assert.equal(row.protection.stop, null)
  assert.doesNotMatch(row.protection.nextStep, /a resting stop is served/i,
    'the adapter may not claim a stop is served when the wire served no stop price')
  assert.match(row.protection.nextStep, /its price is not served/)

  // Rendered through the real table, the two clauses agree instead of contradicting.
  const preset = {
    id: 'holdings', label: 'protection', methodNote: '', limits: [],
    columns: [{ key: 'protection', header: 'Protection' }, { key: 'stop', header: 'Stop' }],
  }
  const markup = renderToStaticMarkup(holdingsTable.HoldingsTable({ rows: [row], preset, onRowOpen: () => {} }))
  const strip = (s) => s.replace(/&amp;/g, '&')
  assert.match(strip(markup), /resting GTC stop, pending activation — stop price not served/)
  assert.doesNotMatch(strip(markup), /a resting stop is served/i, 'the next step must not contradict the stop sentence')
  assert.doesNotMatch(strip(markup), /no resting stop/i, 'a protected row is not an unprotected one')

  // A SERVED price keeps the served wording: the fix follows the state, it does not forbid the sentence.
  const priced = adapter.adaptHoldings(body({ ...pendingProtection, stop: 68 }))
  assert.ok(priced.book !== null, `the priced synthetic body must adapt: ${priced.error ?? ''}`)
  assert.equal(priced.book.rows[0].protection.stop, 68)
  assert.equal(priced.book.rows[0].protection.nextStep, 'none — a resting stop is served for this row')
  const pricedMarkup = renderToStaticMarkup(
    holdingsTable.HoldingsTable({ rows: [priced.book.rows[0]], preset, onRowOpen: () => {} }),
  )
  assert.match(strip(pricedMarkup), /stop \$68\.00/)
  // The state sentence is the price alone; the producer's own reason is still echoed beside it, but the
  // pending-activation STOP SENTENCE (the no-price wording) is gone.
  assert.doesNotMatch(strip(pricedMarkup), /pending activation — stop price not served/)
})

/**
 * RC3 (lead route 2026-11-15T1754Z; reviewer 1805Z §3): the Allocation page's status strip printed
 * `view.snapshot.status · view.snapshot.reason` — on a non-current read without a receipt that was literally
 * `unverified · freshness unverified`, and the page never said "Last available snapshot". The strip now renders
 * `freshnessCopy(snapshot).line`, the same receipt-gated function the panel uses: without a validated receipt it
 * reads exactly `Last available snapshot · freshness unverified`, and `Last known good <at> · <source>` only ever
 * comes from a receipt object. This renders the REAL AllocationPage on a stale synthetic book built by the REAL
 * adapter; restoring the status/reason interpolation must fail it.
 */
test('RC3: the Allocation strip says "Last available snapshot · freshness unverified" with no receipt', () => {
  const { adapter, allocationPage } = compileGateModules()
  const row = (symbol, mv, basis, price) => ({
    symbol, name: `Synthetic ${symbol}`, account: 'acct_a', account_key: 'acct_a', account_label: 'Synthetic A',
    is_cash: false, asset_type: 'EQUITY', market_session: 'REGULAR',
    shares: 10, price, price_as_of: '2026-11-15T12:00:00Z', market_value: mv, portfolio_pct: 50,
    avg_cost: basis / 10, cost_basis_source: 'broker_avg_price', cost_basis_total: basis,
    gain_loss: mv - basis, gain_loss_pct: ((mv - basis) / basis) * 100,
    protection_state: 'GAP',
  })
  const body = {
    ok: true,
    // A stale response: no produced verdict, no receipt — the fail-closed case the strip must voice honestly.
    _swr: { stale: true, age_s: 3600 },
    data: {
      count: 2,
      holdings: [row('SYNAA', 12500, 10000, 125), row('SYNBB', 7500, 5000, 75)],
      truth: { source: 'synthetic', as_of: '2026-11-15T12:00:00-05:00', stale: true, gap: null },
      scope_coverage: { min_position_usd: 100, scopes: { 'holdings.all_rows': 2, 'holdings.non_cash': 2, 'holdings.cash': 0 } },
    },
  }
  const res = adapter.adaptHoldings(body)
  assert.ok(res.book !== null, `the synthetic stale body must adapt: ${res.error ?? ''}`)

  // AllocationPage holds state (filter selects), so it must be rendered as an ELEMENT: calling the component
  // directly would run its hooks outside a renderer.
  const html = renderToStaticMarkup(createElement(allocationPage.AllocationPage, { book: res.book, loading: false, error: null, notice: null }))
  const strip = html.replace(/&amp;/g, '&')

  // The literal, as its own rendered span — not a substring of a longer sentence.
  assert.match(strip, /<span class="wm-pa-warning">Last available snapshot · freshness unverified<\/span>/)
  // No receipt exists anywhere in this render, so no spelling of last-known-good may appear.
  assert.doesNotMatch(strip, /last[- ]known[- ]good/i, 'an unverified read must never be dressed as last-known-good')
  assert.doesNotMatch(strip, /Last known good/i)
  // The overall verdict and the data's as-of stay beside the line (the header clock), as the panel prints them.
  assert.match(strip, /Data as of /)
  assert.match(strip, /freshness (COMPLETE|PARTIAL)/)
})

test('W1/KPI: the Allocation gain/loss KPI says the SHARED §L label, "— partial" only when partial', () => {
  const { adapter, allocationPage, analyticsAdapter } = compileGateModules()
  // `basis === null` omits every cost_basis_* field: the row publishes no gain/loss (the "no basis served" absence).
  const row = (symbol, mv, price, basis) => ({
    symbol, name: `Synthetic ${symbol}`, account: 'acct_a', account_key: 'acct_a', account_label: 'Synthetic A',
    is_cash: false, asset_type: 'EQUITY', market_session: 'REGULAR',
    shares: 10, price, price_as_of: '2026-11-15T12:00:00Z', market_value: mv, portfolio_pct: 50,
    protection_state: 'GAP',
    ...(basis === null
      ? {}
      : {
          avg_cost: basis / 10, cost_basis_source: 'broker_avg_price', cost_basis_total: basis,
          gain_loss: mv - basis, gain_loss_pct: ((mv - basis) / basis) * 100,
        }),
  })
  const body = rows => ({
    ok: true,
    data: {
      count: rows.length,
      holdings: rows,
      truth: { source: 'synthetic', as_of: '2026-11-15T12:00:00-05:00', stale: false, gap: null },
      scope_coverage: {
        min_position_usd: 100,
        scopes: { 'holdings.all_rows': rows.length, 'holdings.non_cash': rows.length, 'holdings.cash': 0 },
      },
    },
  })
  // The rendered KPI title, as its own span — the page is rendered as an ELEMENT (it holds state).
  const render = rows => {
    const res = adapter.adaptHoldings(body(rows))
    assert.ok(res.book !== null, `the synthetic body must adapt: ${res.error ?? ''}`)
    return renderToStaticMarkup(
      createElement(allocationPage.AllocationPage, { book: res.book, loading: false, error: null, notice: null }),
    )
  }
  const kpiLabel = html => {
    const m = html.replace(/&amp;/g, '&').match(/<span>([^<]*gain\/loss[^<]*)<\/span>/)
    assert.ok(m !== null, 'the Allocation gain/loss KPI label span must be present')
    return m[1]
  }

  // One of two non-cash rows publishes no gain/loss → the measure is partial, and the label carries "— partial"
  // INSIDE it, not as a " · partial" suffix this page appends.
  const partialHtml = render([row('SYNAA', 12500, 125, 10000), row('SYNBB', 7500, 75, null)])
  assert.equal(kpiLabel(partialHtml), 'Open-position gain/loss vs. cost — partial')
  // ...and that string is the shared label, not a page-local literal that happens to agree today.
  assert.equal(kpiLabel(partialHtml), analyticsAdapter.gainLossMeasureLabel(true))
  // The old page-local wording is gone from the rendered page.
  assert.doesNotMatch(partialHtml, /Unrealized gain \/ loss/)

  // Both rows publish → no partial suffix; still the shared label (a literal duplicated in the page would drift here).
  const completeHtml = render([row('SYNAA', 12500, 125, 10000), row('SYNBB', 7500, 75, 5000)])
  assert.equal(kpiLabel(completeHtml), 'Open-position gain/loss vs. cost')
  assert.equal(kpiLabel(completeHtml), analyticsAdapter.gainLossMeasureLabel(false))
})

test('CARD: the Holdings phone card names the SHARED §L measure on every row that has one', () => {
  const { adapter, positionCards, analyticsAdapter } = compileGateModules()
  // Two priced positions with basis + one cash row, adapted through the REAL adapter (the card reads HoldingsRow).
  const row = (symbol, mv, basis) => ({
    symbol, name: `Synthetic ${symbol}`, account: 'acct_a', account_key: 'acct_a', account_label: 'Synthetic A',
    is_cash: false, asset_type: 'EQUITY', market_session: 'REGULAR',
    shares: 10, price: mv / 10, price_as_of: '2026-11-15T12:00:00Z', market_value: mv, portfolio_pct: 50,
    avg_cost: basis / 10, cost_basis_source: 'broker_avg_price', cost_basis_total: basis,
    gain_loss: mv - basis, gain_loss_pct: ((mv - basis) / basis) * 100,
    protection_state: 'GAP',
  })
  const cash = {
    symbol: 'CASHA', name: 'Synthetic cash', account: 'acct_a', account_key: 'acct_a', account_label: 'Synthetic A',
    is_cash: true, asset_type: 'CASH', shares: 1, market_value: 5000, portfolio_pct: 20,
  }
  const res = adapter.adaptHoldings({
    ok: true,
    data: {
      count: 3,
      holdings: [row('SYNAA', 12500, 10000), row('SYNBB', 7500, 5000), cash],
      truth: { source: 'synthetic', as_of: '2026-11-15T12:00:00-05:00', stale: false, gap: null },
      scope_coverage: { min_position_usd: 100, scopes: { 'holdings.all_rows': 3, 'holdings.non_cash': 2, 'holdings.cash': 1 } },
    },
  })
  assert.ok(res.book !== null, `the synthetic body must adapt: ${res.error ?? ''}`)

  const html = renderToStaticMarkup(createElement(positionCards.PositionCards, { rows: res.book.rows }))
  const shared = analyticsAdapter.gainLossMeasureLabel(false)
  // The caption is the shared label, once per non-cash card — not a second wording and not a per-row "partial".
  assert.equal(shared, 'Open-position gain/loss vs. cost')
  const captions = [...html.matchAll(/<small>([^<]*)<\/small>/g)].map(m => m[1]).filter(t => /gain\/loss/i.test(t))
  assert.equal(captions.length, 2, `one caption per non-cash card, got ${JSON.stringify(captions)}`)
  assert.deepEqual([...new Set(captions)], [shared])
  // The old card-local wording is gone from the rendered cards.
  assert.doesNotMatch(html, /Unrealized gain \/ loss/)
  // The cash card keeps its own single-line treatment and carries no gain/loss caption.
  assert.match(html, /Cash &amp; sweep · Synthetic A/)
})


// ---------------------------------------------------------------------------------------------------------------
// SPCX display-identity spec Rev 3 (inbox/claude-lead/READY-SPEC-SPCX-DISPLAY-IDENTITY-R3-cc-deepseek-5-...).
// Synthetic symbols (QZ*) and a synthetic identifier only: no real issuer, ticker, CUSIP or account appears here.
// The measured defect these tests pin: one symbol held in two accounts printed two identities, because the second
// line read the per-row `name` (one row's name is the ticker, the other's is empty).

// A synthetic wire row: `name` and `company` are the two raw sources the ladder reads; `identity` is the
// server-resolved block a route MAY serve (spec R5). `spcxBody` wraps rows in the envelope the adapter reads.
const spcxRow = (over = {}) => ({
  symbol: 'QZSP', name: '', company: null, account: 'acct_a', account_key: 'acct_a',
  account_label: 'Synthetic A', is_cash: false, asset_type: 'EQUITY', market_session: 'REGULAR',
  shares: 10, price: 100, price_as_of: '2026-11-15T12:00:00Z', market_value: 1000, portfolio_pct: 50,
  avg_cost: 80, cost_basis_source: 'broker_avg_price', cost_basis_total: 800,
  gain_loss: 200, gain_loss_pct: 25, protection_state: 'GAP',
  ...over,
})
const spcxBody = rows => ({
  ok: true,
  data: {
    count: rows.length,
    holdings: rows,
    truth: { source: 'synthetic', as_of: '2026-11-15T12:00:00-05:00', stale: false, gap: null },
    scope_coverage: {
      min_position_usd: 100,
      scopes: { 'holdings.all_rows': rows.length, 'holdings.non_cash': rows.length, 'holdings.cash': 0 },
    },
  },
})
const spcxAdapt = (adapter, rows) => {
  const res = adapter.adaptHoldings(spcxBody(rows))
  assert.ok(res.book !== null, `the synthetic body must adapt: ${res.error ?? ''}`)
  return res.book
}
const SECURITY_PRESET = { id: 'spcx', label: 'identity', methodNote: '', limits: [], columns: [{ key: 'security', header: 'Security' }] }
const decode = s => s.replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
const securityCells = markup => {
  const cells = [...decode(markup).matchAll(/<small style="[^"]*" title="([^"]*)">([\s\S]*?)<\/small>/g)]
  return cells.map(m => ({ title: m[1], text: m[2].replace(/<[^>]+>/g, '') }))
}
const securityCellText = book => securityCells(
  renderToStaticMarkup(compileGateModules().holdingsTable.HoldingsTable({ rows: book.rows, preset: SECURITY_PRESET, onRowOpen: () => {} })),
)

test('SPCX/T1+T2: one symbol prints ONE name and ONE label, in the cell text AND its title', () => {
  const { adapter, holdingsTable, displayIdentity } = compileGateModules()
  const LABEL = displayIdentity.IDENTITY_UNVERIFIED_LABEL
  assert.equal(LABEL, 'identity unverified (ticker-keyed)')
  // The measured live shape, synthetic: row A's `name` IS the ticker, row B's is empty, both carry the same
  // enrichment company.
  const book = spcxAdapt(adapter, [
    spcxRow({ name: 'QZSP', company: 'Qzeta Space Holdings' }),
    spcxRow({ name: '', company: 'Qzeta Space Holdings', account: 'acct_b', account_key: 'acct_b', account_label: 'Synthetic B' }),
  ])
  assert.equal(book.rows.length, 2)
  // R7: today's per-row name is untouched — search still reads exactly these values.
  assert.equal(book.rows[0].name, 'QZSP')
  assert.equal(book.rows[1].name, 'Qzeta Space Holdings')
  // A ticker-as-name row is NOT 'carried': the ladder rejects it and both rows land on the company source.
  assert.equal(book.rows[0].nameSource, 'company')
  assert.equal(book.rows[1].nameSource, 'company')
  // T1: one resolution per symbol, identical on both rows.
  assert.deepEqual(book.rows[0].identity, {
    nameText: 'Qzeta Space Holdings', status: 'UNVERIFIED', label: LABEL, source: 'company',
  })
  assert.deepEqual(book.rows[1].identity, book.rows[0].identity)
  // ...rendered per row, asserted as the EXACT cell string, not an enum token.
  const cells = securityCells(
    renderToStaticMarkup(holdingsTable.HoldingsTable({ rows: book.rows, preset: SECURITY_PRESET, onRowOpen: () => {} })),
  )
  assert.deepEqual(cells.map(c => c.text), [
    `Qzeta Space Holdings · ${LABEL} · Synthetic A`,
    `Qzeta Space Holdings · ${LABEL} · Synthetic B`,
  ])
  // T2: the title carries the same string — the accessible name may not drop the caveat the visible line prints.
  assert.equal(cells[0].title, `Qzeta Space Holdings · ${LABEL} · Synthetic A · account acct_a`)
  assert.equal(cells[1].title, `Qzeta Space Holdings · ${LABEL} · Synthetic B · account acct_b`)
})

test('SPCX/T3: a ticker-as-name never wins, a carried name carries no label, and R4b never prints the ticker twice', () => {
  const { adapter, displayIdentity } = compileGateModules()
  const LABEL = displayIdentity.IDENTITY_UNVERIFIED_LABEL
  const book = spcxAdapt(adapter, [
    // A carried broker name wins over the enrichment company, and carries NO caveat label.
    spcxRow({ symbol: 'QZCA', name: 'Qzeta Carried Corp', company: 'Qzeta Fallback Co' }),
    // The ticker written as the name never wins the ladder...
    spcxRow({ symbol: 'QZTT', name: 'QZTT', company: 'Qzeta Ticker Co', account: 'acct_b', account_key: 'acct_b', account_label: 'Synthetic B' }),
    // ...and with no other source the row resolves to its symbol alone (R8).
    spcxRow({ symbol: 'QZSL', name: '', company: null, account: 'acct_c', account_key: 'acct_c', account_label: 'Synthetic C' }),
  ])
  const bySym = s => book.rows.find(r => r.symbol === s)
  assert.deepEqual(bySym('QZCA').identity, {
    nameText: 'Qzeta Carried Corp', status: 'UNVERIFIED', label: null, source: 'carried',
  })
  assert.deepEqual(bySym('QZTT').identity, {
    nameText: 'Qzeta Ticker Co', status: 'UNVERIFIED', label: LABEL, source: 'company',
  })
  assert.deepEqual(bySym('QZSL').identity, {
    nameText: 'QZSL', status: 'UNVERIFIED', label: null, source: 'symbol',
  })
  const cells = securityCellText(book)
  // The carried row: its own name, no label, in text and title alike.
  assert.equal(cells[0].text, 'Qzeta Carried Corp · Synthetic A')
  assert.equal(cells[0].title, 'Qzeta Carried Corp · Synthetic A · account acct_a')
  assert.doesNotMatch(cells[0].text + cells[0].title, /identity unverified/)
  // R4b: the symbol-only row carries the account label ALONE — no second ticker, no dangling separator.
  assert.equal(cells[2].text, 'Synthetic C')
  assert.equal(cells[2].title, 'Synthetic C · account acct_c')
  assert.doesNotMatch(cells[2].text, /QZSL/)
})

test('SPCX/T4: only a well-formed SERVER-RESOLVED identity opens the confirmed branch; nothing is matched here', () => {
  const { adapter, holdingsTable, displayIdentity } = compileGateModules()
  const LABEL = displayIdentity.IDENTITY_UNVERIFIED_LABEL
  const served = (over = {}) => ({
    status: 'CONFIRMED', name: 'Qzeta Confirmed Instruments', basis: 'cusip', identifier: 'QZ1234567', ...over,
  })
  const one = extra => spcxAdapt(adapter, [
    spcxRow({ symbol: 'QZCF', name: 'QZCF', company: 'Qzeta Confirmed Co', ...extra }),
  ]).rows[0]
  // The server's verdict is read, not re-derived: a confirmed, cusip-basis block with a name and a 9-character
  // identifier names the instrument, with no unverified label anywhere.
  const confirmed = one({ identity: served() })
  assert.deepEqual(confirmed.identity, {
    nameText: 'Qzeta Confirmed Instruments', status: 'CONFIRMED', label: null, source: 'carried',
  })
  const confirmedHtml = decode(renderToStaticMarkup(
    holdingsTable.HoldingsTable({ rows: [confirmed], preset: SECURITY_PRESET, onRowOpen: () => {} }),
  ))
  assert.doesNotMatch(confirmedHtml, /identity unverified/)
  assert.match(confirmedHtml, /Qzeta Confirmed Instruments/)
  // Everything else renders R4's label: malformed is not confirmed, and the client performs no match to change it.
  const cases = [
    ['UNVERIFIED', { identity: served({ status: 'UNVERIFIED' }) }],
    ['a malformed identifier (8 chars — no CUSIP shape)', { identity: served({ identifier: 'QZ123456' }) }],
    ['a served name with no identifier', { identity: served({ identifier: null }) }],
    ['no identity field at all', {}],
    ['a symbol-keyed security_guid only', {
      security_guid: 'qzeta-synthetic-guid', security_guid_source: 'CIO InstrumentRecord company_facts',
    }],
  ]
  for (const [why, extra] of cases) {
    const row = one(extra)
    assert.equal(row.identity.label, LABEL, why)
    assert.equal(row.identity.nameText, 'Qzeta Confirmed Co', why)
    assert.equal(row.identity.status, 'UNVERIFIED', why)
    // A symbol-keyed guid is not an identity basis and the adapter does not carry it (R5).
    assert.ok(!('security_guid' in row), `${why}: the adapter carries no security_guid`)
  }
})

test('SPCX/T5+T6: identity is read-time only (fixture source unchanged), and table, card and drawer agree', () => {
  const { adapter, fixtures, holdingsTable, positionCards, detail, displayIdentity } = compileGateModules()
  const FIXTURE_SRC = path.join(APP, 'src/pages/portfolio/fixtures.ts')
  const sha = () => createHash('sha256').update(fs.readFileSync(FIXTURE_SRC)).digest('hex')
  const before = sha()

  // T6: one synthetic company-sourced row, rendered through the three surfaces the spec names.
  const book = spcxAdapt(adapter, [spcxRow({ symbol: 'QZPR', name: 'QZPR', company: 'Qzeta Parity Holdings' })])
  const row = book.rows[0]
  const line = displayIdentity.identitySecondLine(row.identity, row.symbol, row.accountLabel)
  assert.equal(line, `Qzeta Parity Holdings · ${displayIdentity.IDENTITY_UNVERIFIED_LABEL} · Synthetic A`)
  const cellText = securityCells(
    renderToStaticMarkup(holdingsTable.HoldingsTable({ rows: [row], preset: SECURITY_PRESET, onRowOpen: () => {} })),
  )[0].text
  assert.equal(cellText, line)
  const cardHtml = decode(renderToStaticMarkup(createElement(positionCards.PositionCards, { rows: [row] })))
  const cardLine = cardHtml.match(/<small class="muted">([\s\S]*?)<\/small>/)
  assert.ok(cardLine !== null, 'the card must render its identity line')
  assert.equal(cardLine[1].replace(/<[^>]+>/g, ''), line)
  assert.equal(detail.detailHeading(row).eyebrow, `${line} · ${row.accountKey}`)

  // The fixture book is authored to the same shape, so its names still render (never a symbol-only book).
  assert.ok(fixtures.FIXTURE_BOOK.rows.every(r => r.identity), 'every fixture row carries a resolved identity')
  assert.equal(fixtures.FIXTURE_BOOK.rows.find(r => r.symbol === 'QZTA').identity.nameText, 'Qzeta Alpha Corp')
  renderToStaticMarkup(createElement(positionCards.PositionCards, { rows: fixtures.FIXTURE_BOOK.rows }))
  renderToStaticMarkup(holdingsTable.HoldingsTable({ rows: fixtures.FIXTURE_BOOK.rows, preset: SECURITY_PRESET, onRowOpen: () => {} }))

  // T5: a full render writes nothing — the fixture source is byte-identical afterwards.
  assert.equal(sha(), before, 'the fixture source changed across a render: identity must be read-time only')
})

test('SPCX/T9: search keeps today results — company-only found by company, ticker-as-name by ticker ONLY', () => {
  const { adapter, search } = compileGateModules()
  const wires = [
    spcxRow({ symbol: 'QZCN', name: '', company: 'Qzeta Naming Corp' }),
    spcxRow({ symbol: 'QZTN', name: 'QZTN', company: 'Qzeta Ticker Name Co', account: 'acct_b', account_key: 'acct_b', account_label: 'Synthetic B' }),
  ]
  const book = spcxAdapt(adapter, wires)
  // R7 parity: `row.name` is byte-equal to today's `str(name) ?? str(company) ?? symbol` on every row.
  for (const [i, wire] of wires.entries()) {
    const expected = wire.name !== '' ? wire.name : wire.company !== null ? wire.company : wire.symbol
    assert.equal(book.rows[i].name, expected)
  }
  const find = q => book.rows.filter(r => search.rowMatchesQuery(r, q)).map(r => r.symbol)
  assert.deepEqual(find('Qzeta Naming Corp'), ['QZCN']) // (i) a company-only row is found by its company name
  assert.deepEqual(find('qztn'), ['QZTN']) // (ii) a ticker-as-name row is found by its ticker (case-insensitive)
  // (iii) ...and NOT by its company name. This is today's limitation, asserted so a future change to search is a
  // decision rather than an accident — R7 forbids fixing it by changing search's results.
  assert.deepEqual(find('Qzeta Ticker Name Co'), [])
  assert.deepEqual(find('   '), ['QZCN', 'QZTN']) // an empty query narrows nothing
  // The display identity does not enter search: the resolved company name is not a match field.
  assert.equal(book.rows[1].identity.nameText, 'Qzeta Ticker Name Co')
})

test('SPCX/CSV: the exported Security field is the identity line, so two accounts of one symbol stay distinguishable', () => {
  const { adapter, holdingsTable, displayIdentity } = compileGateModules()
  const LABEL = displayIdentity.IDENTITY_UNVERIFIED_LABEL
  // The export is the Blob's own text: `csvFor` is the page's Export CSV call, unrendered. It is NOT built from
  // the rendered DOM — `rawText` cannot see a component element, which is why the security column had silently
  // collapsed to the symbol alone (review 2026-11-15T1906Z P2, measured on a real export capture).
  const book = spcxAdapt(adapter, [
    spcxRow({ symbol: 'QZSP', name: 'QZSP', company: 'Qzeta Space Holdings' }),
    spcxRow({ symbol: 'QZSP', name: '', company: 'Qzeta Space Holdings', account: 'acct_b', account_key: 'acct_b', account_label: 'Synthetic B' }),
    spcxRow({ symbol: 'QZCA', name: 'Qzeta Carried Corp', account: 'acct_c', account_key: 'acct_c', account_label: 'Synthetic C' }),
    spcxRow({ symbol: 'QZSL', name: '', company: null, account: 'acct_d', account_key: 'acct_d', account_label: 'Synthetic D' }),
  ])
  const preset = {
    id: 'csv-identity', label: 'identity', methodNote: '', limits: [],
    columns: [{ key: 'security', header: 'Security / account' }],
  }
  const fields = holdingsTable.csvFor(book.rows, preset).trim().split('\r\n').slice(1)
  assert.deepEqual(fields, [
    `QZSP Qzeta Space Holdings · ${LABEL} · Synthetic A`,
    `QZSP Qzeta Space Holdings · ${LABEL} · Synthetic B`,
    'QZCA Qzeta Carried Corp · Synthetic C',
    'QZSL Synthetic D',
  ])
  // (a) one symbol in two accounts: the file keeps the account label, so the rows are distinguishable...
  assert.notEqual(fields[0], fields[1])
  assert.match(fields[0], /· Synthetic A$/)
  assert.match(fields[1], /· Synthetic B$/)
  // (b) ...and a company-sourced name carries R4's caveat in the export, exactly as it does on screen.
  assert.ok(fields[0].includes(LABEL) && fields[1].includes(LABEL))
  assert.doesNotMatch(fields[2], /identity unverified/)
  // The file's text IS the screen's line — one function, no second wording that could drift.
  assert.equal(fields[0], `QZSP ${displayIdentity.identitySecondLine(book.rows[0].identity, 'QZSP', 'Synthetic A')}`)
  assert.equal(fields[3], `QZSL ${displayIdentity.identitySecondLine(book.rows[3].identity, 'QZSL', 'Synthetic D')}`)
})
