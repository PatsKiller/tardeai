// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
  deepEqual(a: unknown, b: unknown, m?: string) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(m ?? `expected ${x} to deep-equal ${y}`) },
  match(s: string, re: RegExp, m?: string) { if (!re.test(s)) fail(m ?? `expected ${JSON.stringify(s)} to match ${re}`) },
}
import { unwrapMarketRisk, bannerVisible, factLine, tierTone, contributorsLine, pointsSum, episodeLine, fmtPct, shadowMarker, SHADOW_MARKER, CARRIED_MARKER,
  summaryVisible, summaryDefaultOpen, summaryModel, fmtPoints, budgetLabel, SUMMARY_PHONE_MAX_PX } from './marketRisk.ts'

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
// ── Design home/v004: the YELLOW summary card (synthetic shape of the live projection; names only, no real book) ──
let n = 0; const t = (cond: unknown, m: string) => { assert.ok(cond, m); n++ }
const yBase = { state: 'evaluated', tier: 'YELLOW', score: 59.744, as_of: '2026-11-01T14:07:00Z', age_hours: 0.2, stale: false, stale_after_hours: 1,
  contributors: [
    { name: 'Options flow', points: 34.42, detail: 'QQQ P/C OI 3.97 (3.85x median)', as_of: '2026-10-30T21:35:00Z' },
    { name: 'Technical', points: 25.32, detail: 'AI basket: 0% above 20-day', as_of: '2026-10-30T20:00:00Z' },
    { name: 'Breadth', points: 0, detail: 'calm' } ],
  categories: [ { name: 'Technical', state: 'STRESS' }, { name: 'Breadth', state: 'CALM' }, { name: 'Volatility', state: 'CALM' }, { name: 'Options flow', state: 'STRESS' },
    { name: 'Extended hours', state: 'UNKNOWN', detail: 'no extended-session print' } ],
  confirming: { n: 2, of: 9 }, deescalates_if: 'YELLOW -> BLUE if score below 40 (now 60)', uplift: null, episode: null,
  book: { vulnerability: 8.4, budgets: [ { budget: 'single_sector_pct', scope: 'account', breached: true }, { budget: 'growth_style_pct', scope: 'book', breached: true } ],
    positions: [ { symbol: 'DEMOA', stop_distance_pct: 4.5, note: null }, { symbol: 'DEMOB', stop_distance_pct: null }, { symbol: 'DEMOC', stop_distance_pct: null }, { symbol: 'DEMOD', stop_distance_pct: null }, { symbol: 'DEMOE', stop_distance_pct: null } ], note: 'components: …' },
  mode: 'live' }
const yLive = unwrapMarketRisk({ ok: true, data: yBase })
const yShadow = unwrapMarketRisk({ ...yBase, mode: 'shadow' })
const yStale = unwrapMarketRisk({ ...yBase, state: 'stale', stale: true, age_hours: 3, mode: 'shadow' })
const yEmpty = unwrapMarketRisk({ ...yBase, contributors: [], book: null })
const yNoBook = unwrapMarketRisk({ ...yBase, book: null })
// visibility: YELLOW only (fresh or stale); ORANGE/RED keep the v002 banner; nothing else shows a card
t(summaryVisible(yLive) && summaryVisible(yShadow) && summaryVisible(yStale), 'YELLOW live, shadow and stale show the card')
t(!bannerVisible(yLive) && !bannerVisible(yShadow), 'YELLOW never shows the ORANGE/RED banner')
t(!summaryVisible(notEval) && summaryModel(notEval) === null, 'not evaluated: no card (v002 unchanged)')
t(!summaryVisible(green) && !summaryVisible(unwrapMarketRisk({ ...yBase, tier: 'BLUE' })), 'GREEN/BLUE: nothing in the slot')
t(!summaryVisible(red) && bannerVisible(red), 'RED: the v002 banner, never the YELLOW card')
const orange = unwrapMarketRisk({ ...yBase, tier: 'ORANGE', score: 68, episode: { id: 'EP-2', tier: 'ORANGE', opened_at: '2026-11-01T14:00:00Z' } })
t(!summaryVisible(orange) && bannerVisible(orange) && summaryModel(orange) === null, 'ORANGE: the v002 banner unchanged, no card')
t(!summaryVisible(null) && summaryModel(null) === null, 'load error: no card')
// default open: collapsed on phone (≤820), open on desktop, stale collapsed everywhere; the stored choice wins when fresh
t(SUMMARY_PHONE_MAX_PX === 820, 'phone breakpoint is design rule 5 (≤820 px)')
t(summaryDefaultOpen({ phone: true, stale: false, stored: null }) === false, 'phone: collapsed by default')
t(summaryDefaultOpen({ phone: false, stale: false, stored: null }) === true, 'desktop: expanded by default')
t(summaryDefaultOpen({ phone: false, stale: true, stored: true }) === false, 'stale: collapsed on every width, stored choice ignored')
t(summaryDefaultOpen({ phone: true, stale: false, stored: true }) === true && summaryDefaultOpen({ phone: false, stale: false, stored: false }) === false, 'the remembered choice applies')
// YELLOW live
const ml = summaryModel(yLive)!
t(ml.score === '60' && !ml.stale, 'score rounds to 60')
assert.equal(ml.contributors.length, 2, 'only categories with points above 0'); n++
assert.deepEqual(ml.contributors.map(c => c.points), ['+34.4', '+25.3'], 'points with one decimal'); n++
t(ml.contributors[0].detail.includes('QQQ P/C OI 3.97') && / ET$/.test(ml.contributors[0].detail), 'contributor line: the number behind it and its ET time')
assert.match(ml.line, /^Options flow \+34\.4 · Technical \+25\.3 · 2 of 9 confirm · evaluated .* ET$/); n++
assert.equal(ml.confirm, '2 of 9 categories confirm'); n++
assert.match(ml.notMeasured, /^Not measured: extended hours\. /); n++
assert.match(ml.notMeasured, /Breadth and volatility add 0\.$/); n++
assert.equal(ml.deescalates, 'YELLOW -> BLUE if score below 40 (now 60)'); n++
assert.equal(ml.footer, 'YELLOW never pages and has nothing to acknowledge.', 'live: no shadow sentence'); n++
assert.equal(shadowMarker(yLive), '', 'live: no SHADOW label'); n++
assert.deepEqual(ml.links.map(l => [l.label, l.to]), [['Open Risk →', '/risk?tab=market-risk'], ['Review stops →', '/risk?tab=exposure']]); n++
// no Acknowledge at YELLOW: the model carries no acknowledge action and no link names one
t(!('ack' in ml) && !('acknowledge' in ml) && !ml.links.some(l => /ack/i.test(l.label + l.to)), 'no Acknowledge at YELLOW')
// Your book: from the API's book (projected from the portfolio/vulnerability fields); hidden when absent
t(ml.book && ml.book.vulnerability === '8/100', 'vulnerability /100')
assert.deepEqual(ml.book!.breaches, ['single sector (one account)', 'growth style'], 'budget names (the projection carries no actual/limit)'); n++
assert.deepEqual(ml.book!.nearStop, ['DEMOA stop 4.5% below'], 'near a stop: symbol + distance only'); n++
assert.equal(ml.book!.otherDrivers, 'DEMOB, DEMOC, DEMOD +1 more', 'first three, then +N more'); n++
t(/No order, size or stop level is implied/.test(ml.book!.note), 'advisory line')
t(!/\$|\bbuy\b|\bsell\b|\bshares?\b/i.test(JSON.stringify(ml.book)), 'never a size, dollar amount or instruction')
t(summaryModel(yNoBook)!.book === null, 'no book in the API: Your book hidden')
t(summaryModel(unwrapMarketRisk({ ...yBase, book: { budgets: [], positions: [] } }))!.book === null, 'an empty book is hidden too')
const withVs = summaryModel(unwrapMarketRisk({ ...yBase, book: { vulnerability: 40, budgets: [{ budget: 'Growth style', actual: 85, limit: 50, unit: '%', breached: true }] } }))!
assert.deepEqual(withVs.book!.breaches, ['Growth style 85% vs 50%'], 'actual vs limit when the API carries them'); n++
// YELLOW shadow
const ms = summaryModel(yShadow)!
assert.equal(shadowMarker(yShadow), SHADOW_MARKER); n++
assert.equal(ms.footer, 'YELLOW never pages and has nothing to acknowledge. Shadow mode: no alert was sent for this tier.'); n++
// stale: numbers hidden
const mst = summaryModel(yStale)!
t(mst.stale && mst.score === null && mst.contributors.length === 0 && mst.book === null && mst.deescalates === null && mst.notMeasured === '', 'stale hides score, contributors, book and de-escalation')
assert.match(mst.line, /^stale — last evaluation .* ET\. Numbers hidden until the engine runs again\.$/); n++
t(!/60|34\.4|25\.3/.test(mst.line + mst.footer), 'stale shows no number from the old evaluation')
assert.equal(mst.links.length, 2, 'stale keeps the two links'); n++
// contributors empty
const me = summaryModel(yEmpty)!
assert.match(me.line, /^no category above 0 points · 2 of 9 confirm · /); n++
assert.equal(me.contributors.length, 0); n++
t(me.notMeasured.startsWith('Not measured: extended hours.'), 'empty: only the not-measured line')
// helpers
assert.equal(fmtPoints(34.42), '+34.4'); assert.equal(fmtPoints(-2), '-2.0'); assert.equal(fmtPoints(null), '—'); n += 3
assert.equal(budgetLabel('unprotected_pct'), 'unprotected'); n++
console.log(`marketRisk.test v004 summary: ${n} checks ok`)
console.log('marketRisk.test ok')
