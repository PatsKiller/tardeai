// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
  deepEqual(a: unknown, b: unknown, m?: string) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(m ?? `expected ${x} to deep-equal ${y}`) },
  match(s: string, re: RegExp, m?: string) { if (!re.test(s)) fail(m ?? `expected ${JSON.stringify(s)} to match ${re}`) },
}
import { unwrapMarketRisk, bannerVisible, factLine, tierTone, contributorsLine, pointsSum, episodeLine, fmtPct, shadowMarker, SHADOW_MARKER, CARRIED_MARKER } from './marketRisk.ts'

const notEval = unwrapMarketRisk({ ok: true, data: { state: 'not_evaluated', tier: 'NOT_EVALUATED', score: null, as_of: null, age_hours: null, stale: false,
  reason: 'engine not live', contributors: [], categories: [], sources: { options_flow: { findings: [{ symbol: 'QQQ', state: 'STRESS', pc_vol_ratio: 3.309 }] } } } })
assert.ok(notEval && notEval.state === 'not_evaluated')
assert.equal(bannerVisible(notEval), false, 'nothing evaluated: no banner')
assert.deepEqual(factLine(notEval), { value: 'NOT EVALUATED', sub: 'options flow stress: QQQ put/call vol 3.31', tone: 'warning' })

const red = unwrapMarketRisk({ state: 'evaluated', tier: 'RED', score: 83, as_of: '2026-10-29T22:15:00Z', age_hours: 0.2, stale: false,
  contributors: [{ name: 'Futures / extended hours', points: 18, detail: 'NQ −1.6%' }, { name: 'Event cluster', points: 17 }, { name: 'Options flow', points: 15 }, { name: 'Breadth', points: 14 }, { name: 'Semiconductors', points: 11 }, { name: 'extra', points: 99 }],
  categories: [], episode: { id: 'EP-1', tier: 'RED', opened_at: '2026-10-29T22:15:00Z', repeats: 3, max_repeats: 12, acknowledged_at: null } })
assert.equal(bannerVisible(red), true)
assert.equal(tierTone(red!.tier), 'danger')
assert.equal(factLine(red).value, 'RED 83')
assert.equal(factLine(red).sub, 'futures / extended hours · NQ −1.6%')
assert.equal(contributorsLine(red), 'Futures / extended hours +18 · Event cluster +17 · Options flow +15 · Breadth +14 · Semiconductors +11', 'five contributors, never six')
assert.equal(pointsSum(red), 18 + 17 + 15 + 14 + 11 + 99, 'the sum is computed, so a mismatch with the score is visible')
assert.match(episodeLine(red), /repeat 3 of 12 · not acknowledged/)

const staleRed = unwrapMarketRisk({ ...red, state: 'stale', stale: true })
assert.equal(bannerVisible(staleRed), false, 'a stale episode never shows a live banner')
assert.match(factLine(staleRed).sub, /^stale — last evaluation /)

const green = unwrapMarketRisk({ state: 'evaluated', tier: 'GREEN', score: 18, as_of: '2026-11-10T13:30:00Z', age_hours: 0.1, stale: false, contributors: [{ name: 'Breadth', points: 6, detail: 'broadening' }], categories: [] })
assert.equal(bannerVisible(green), false)
assert.equal(factLine(green).tone, 'success')
assert.equal(tierTone('ORANGE'), 'elevated'); assert.equal(tierTone('BLUE'), 'info'); assert.equal(tierTone('bogus'), 'neutral')
assert.equal(fmtPct(0.61), '61%'); assert.equal(fmtPct(61), '61%'); assert.equal(fmtPct(null), '—')
assert.equal(unwrapMarketRisk({ ok: false }), null)
// Shadow mode (review of #2415 round 2, R2-2): a tier from `--shadow` carries mode 'shadow' and every surface says so.
const sh = unwrapMarketRisk({ state: 'evaluated', tier: 'YELLOW', score: 59.7, as_of: '2026-11-01T00:38:00Z', age_hours: 0.1, stale: false,
  contributors: [{ name: 'Options flow', points: 34 }], categories: [], mode: 'shadow' })
assert.equal(sh?.mode, 'shadow')
assert.equal(shadowMarker(sh), SHADOW_MARKER)
assert.match(factLine(sh).sub, /^SHADOW · not alerting · options flow/)
assert.equal(factLine(sh).value, 'YELLOW 60')
const live = unwrapMarketRisk({ state: 'evaluated', tier: 'YELLOW', score: 59.7, as_of: null, age_hours: 0.1, stale: false, contributors: [], categories: [], mode: 'live' })
assert.equal(live?.mode, 'live'); assert.equal(shadowMarker(live), ''); assert.ok(!factLine(live).sub.includes('SHADOW'))
assert.equal(unwrapMarketRisk({ state: 'evaluated', tier: 'BLUE', score: 30, contributors: [], categories: [], mode: 'bogus' })?.mode, null)
assert.equal(shadowMarker(notEval), '', 'not evaluated: no shadow marker')
// a live episode never rides on a shadow tier (the API drops it; the model keeps whatever arrives, so check the shape)
assert.equal(unwrapMarketRisk({ state: 'evaluated', tier: 'RED', score: 80, contributors: [], categories: [], mode: 'shadow', episode: null })?.episode, null)
// CARRIED-ONLY (PR 2431): a live tier resting only on data carried across a closure is labelled, never alerted
const carried = unwrapMarketRisk({ state: 'evaluated', tier: 'YELLOW', score: 59.7, contributors: [{ name: 'Options flow', points: 34 }], categories: [], mode: 'live', carried_only: true })
assert.equal(carried?.carried_only, true); assert.equal(shadowMarker(carried), CARRIED_MARKER)
assert.match(factLine(carried).sub, /^CARRIED · not alerting · options flow/)
assert.equal(shadowMarker(unwrapMarketRisk({ state: 'evaluated', tier: 'YELLOW', score: 59.7, contributors: [], categories: [], mode: 'shadow', carried_only: true })), SHADOW_MARKER)
console.log('marketRisk.test ok')
