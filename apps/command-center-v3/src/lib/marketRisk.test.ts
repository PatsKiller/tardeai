// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
  deepEqual(a: unknown, b: unknown, m?: string) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(m ?? `expected ${x} to deep-equal ${y}`) },
  match(s: string, re: RegExp, m?: string) { if (!re.test(s)) fail(m ?? `expected ${JSON.stringify(s)} to match ${re}`) },
}
import { unwrapMarketRisk, bannerVisible, factLine, tierTone, contributorsLine, pointsSum, episodeLine, fmtPct, shadowMarker, SHADOW_MARKER, CARRIED_MARKER,
  summaryVisible, summaryDefaultOpen, summaryModel, fmtPoints, budgetLabel, SUMMARY_PHONE_MAX_PX,
  actionableModel, verdictLine, fmtUsd, fmtSignedPct, hedgeModel, rotateModel } from './marketRisk.ts'

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

// ── design home/v005: the actionable model ──
{
  const hm = (key: string, label: string, kind: string, state: string, rs1: number | null = null) => ({ key, label, kind, state, rs1, rs5: rs1 })
  const base = { state: 'evaluated', tier: 'YELLOW', score: 60, as_of: '2031-03-10T15:00:00Z', age_hours: 0.2, stale: false, contributors: [], categories: [],
    shock_type: { class: 'SECTOR' }, sectors: { sectors_measured: 3 }, card_config: { recent_sessions: 5, max_reentry_rows: 5 },
    heatmap: [hm('tech', 'Technology', 'sector', 'STRESS', -3.1), hm('fin', 'Financials', 'sector', 'RESILIENT', 1), hm('ind', 'Industrials', 'sector', 'RESILIENT', 0.2),
      hm('comm', 'Communications', 'sector', 'UNKNOWN'), hm('semis', 'Semis', 'theme', 'STRESS', -5)],
    book_exposure: { total_usd: 1000, reconciles: true, cash_usd: 400, invested_usd: 600, stressed_groups: ['tech'], stressed_usd: 60, stressed_pct_book: 6, stressed_pct_invested: 10, cash_pct_book: 40,
      largest_contributor: { symbol: 'DEMOF', account_label: 'A', group: 'tech', share: 0.09 },
      groups: { fin: { usd: 400, pct_book: 40 }, tech: { usd: 60, pct_book: 6 }, comm: { usd: 100, pct_book: 10 } }, unmapped: [], rows: [], more: { count: 0, usd: 0 }, zero_exposure_symbols: [] },
    review: [{ symbol: 'DEMOA', account_label: 'A', kinds: ['no_stop'], text: 'no stop', usd: 500, to: '/risk?tab=exposure&symbol=DEMOA' }],
    budgets_detail: [{ account_label: 'A', budget: 'unprotected_pct', limit: 10, actual: 46.6, unit: '%', actual_usd: 300, drivers: [{ name: 'X', usd: 200 }, { name: 'Y', usd: 50 }, { name: 'Z', usd: 30 }, { name: 'W', usd: 20 }] }],
    reentry_watch: {
      NEWX: { symbol: 'NEWX', exit_date: '2031-03-07', exit_price: 10, stages: { verdict: 'Still falling', last_close: 9.5, pct_vs_exit: -5, swing_low: 9.2, invalidation_level: 9.2,
        stage1: { met: 1, of: 5, conditions: [{ key: 'follow_through', met: false, text: 'higher low + 2 green closes' }, { key: 'tier_ok', met: true, text: '' }] }, stage2: { met: false, conditions: [{ key: 'above_exit', met: false, text: 'close above 10.00' }] } } },
      OLDX: { symbol: 'OLDX', exit_date: '2031-02-01', stages: { verdict: 'Confirmed' } },
    },
    reentry_detail: { NEWX: { exit_account_label: 'A', held_elsewhere_labels: ['B'], wash_sale: { state: 'occurred', account_label: 'B', rebuy_date: '2031-03-07', rebuy_price: 9.8, deferred_loss_usd: 100 } } },
  }
  const mr = unwrapMarketRisk({ ok: true, data: base })!
  assert.equal(verdictLine(mr), 'Sector selloff — Technology / Semis. Not market-wide: 2 of 3 sectors holding.')
  const a = actionableModel(mr)!
  assert.equal(a.exposure, "Your exposure: $60 (6.0% of book · 10.0% of invested) in stressed groups — mostly DEMOF's 9% technology. Cash 40%.")
  assert.equal(a.sectors[0].key, 'tech', 'stressed and held first')
  assert.equal(a.sectors[1].key, 'comm', 'then UNKNOWN groups you hold')
  assert.equal(a.sectors[1].chip, 'NOT MEAS.')
  assert.equal(a.topReview?.symbol, 'DEMOA')
  assert.equal(a.budgets[0].text, 'unprotected 46.6% ($300) vs 10% limit')
  assert.equal(a.budgets[0].drivers, 'X $200 · Y $50 · Z $30 · W $20', 'no config: nothing cut')
  assert.equal(a.reentry.length, 1, 'only recent exits are rows')
  assert.match(a.reentryMore, /^\+1 older exit/)
  const r = a.reentry[0]
  assert.match(r.head, /still held in B$/)
  assert.equal(r.wash?.tone, 'info')
  assert.match(r.wash!.text, /wash sale occurred, \$100 loss deferred into the new basis/)
  assert.equal(r.waiting, 'higher low + 2 green closes')
  assert.equal(r.invalidates, '$9.20')
  assert.equal(fmtUsd(12345.67), '$12,346'); assert.equal(fmtSignedPct(-3.11), '−3.1%')
  const bad = actionableModel(unwrapMarketRisk({ ok: true, data: { ...base, book_exposure: { ...base.book_exposure, reconciles: false } } }))!
  assert.equal(bad.exposure, null); assert.match(bad.exposureNote!, /does not reconcile/)
  assert.equal(actionableModel(unwrapMarketRisk({ ok: true, data: { ...base, stale: true, state: 'stale' } })), null, 'stale: no numbers')
  for (const s of [a.exposure!, ...a.review.map(x => x.text), ...a.reentry.map(x => x.waiting)]) assert.ok(!/\b(buy|sell) \d|shares to|set (a )?stop/i.test(s), 'no order/size text')
  const noStops = actionableModel(unwrapMarketRisk({ ok: true, data: { ...base, book_exposure: { ...base.book_exposure, stops_known: false } } }))!
  assert.equal(noStops.stopsKnown, false, 'stop read failed: stops unavailable, never no stop')
  const named = actionableModel(unwrapMarketRisk({ ok: true, data: { ...base, budgets_detail: [], book: { budgets: [{ budget: 'unprotected_pct', breached: true }] } } }))!
  assert.match(named.budgetsNote!, /1 budget breach: unprotected — budget numbers unavailable/)
  const limited = actionableModel(unwrapMarketRisk({ ok: true, data: { ...base, card_config: { max_review_items: 0, budget_drivers_shown: 1 } } }))!
  assert.equal(limited.review.length, 0); assert.equal(limited.budgets[0].drivers, 'X $200 +3')
  const carriedSent = unwrapMarketRisk({ ok: true, data: { ...base, mode: 'live', carried_only: true, alerts: { sends: 1, priorities: ['P3'] } } })
  assert.equal(shadowMarker(carriedSent), 'CARRIED · informational card sent (P3), no page')
  const carriedNone = unwrapMarketRisk({ ok: true, data: { ...base, mode: 'live', carried_only: true, alerts: { sends: 0, priorities: [] } } })
  assert.equal(shadowMarker(carriedNone), CARRIED_MARKER)
  console.log('marketRisk.test v005 actionable: ok')
}
{
  // design home/v006: Protect / Hedge / Rotate, folded groups, RESILIENT vs HOLDING, segment status, glossary
  const hm = (key: string, label: string, kind: string, state: string, rs1: number | null = null) => ({ key, label, kind, state, rs1, rs5: rs1 })
  const data: any = { state: 'evaluated', tier: 'YELLOW', score: 60, as_of: '2031-03-10T15:00:00Z', age_hours: 0.2, stale: false, contributors: [], categories: [],
    shock_type: { class: 'SECTOR' }, sectors: { sectors_measured: 3 }, card_config: { fold_below_usd: 100 },
    heatmap: [hm('tech', 'Technology', 'sector', 'STRESS', -3.1), hm('fin', 'Financials', 'sector', 'RESILIENT', 1), hm('ind', 'Industrials', 'sector', 'NEUTRAL', 0.2),
      hm('re', 'Real estate', 'sector', 'UNKNOWN'), hm('ai', 'AI basket', 'theme', 'STRESS', -3)],
    book_exposure: { total_usd: 1000, reconciles: true, cash_usd: 400, invested_usd: 600, stressed_groups: ['tech'], stressed_usd: 60, stressed_pct_book: 6, stressed_pct_invested: 10, cash_pct_book: 40,
      groups: { fin: { usd: 400, pct_book: 40 }, tech: { usd: 60, pct_book: 6 } }, unmapped: [], rows: [], more: { count: 0, usd: 0 }, zero_exposure_symbols: [] },
    review: [{ symbol: 'DEMOA', account_label: 'A', kinds: ['stop_near'], text: 'stop 3.6% below last', usd: 500, to: '/risk?tab=exposure&symbol=DEMOA' }],
    protect: { items: [{ symbol: 'DEMOA', account_label: 'A', kinds: ['stop_near'], text: 'stop 3.6% below last', usd: 500, to: '/risk?tab=exposure&symbol=DEMOA', pct_account: 96.3,
      consideration: 'stop 3.6% below last; one stock is 96% of the account, far above the 30% sector budget' }],
      more: [{ symbol: 'DEMOB', account_label: 'B', short: 'no stop', to: '/x' }] },
    hedge: { verdict: 'NOT_NOW', thesis_state: 'RED', candidates: ['SH', 'PSQ'], since: '2031-03-07', thresholds: { trigger_book_pct: 10, index_trigger_lagging_sectors: 4 },
      largest_weakening: { label: 'Technology', pct_invested: 4.8 }, lagging_count: 1, stressed_usd: 19241, stressed_pct_book: 1.54, stressed_pct_invested: 4.82,
      size_band: '2-5%', playbook: ['x'] },
    rotate: { as_of: '2031-03-07', groups: [{ key: 'fin', label: 'Financials', rs1: 1.03, rs5: 1.63, desk_state: 'LEADING', usd: 400 }] },
    sectors_folded: [{ key: 'ai', label: 'AI basket', state: 'STRESS', usd: 28 }, { key: 're', label: 'Real estate', state: 'UNKNOWN', usd: 1 }],
    glossary: { stress: { label: 'STRESS', text: 'x' } },
    segments_status: { DEMOS: { status: 'pending', groups: null }, DEMOT: { status: 'approved', groups: { ind: 0.6, tech: 0.4, ai: 0.8 }, source: 'DEMO 10-Q', as_of: '2031-01-31' } },
  }
  const mr = unwrapMarketRisk({ ok: true, data })!
  const a = actionableModel(mr)!
  assert.deepEqual(a.sectors.map(r => r.key), ['tech', 'fin', 'ind'], 'folded groups leave the table')
  assert.equal(a.foldLine, 'Also stressed, you hold under $100: AI basket ($28). Not measured, you hold under $100: Real estate ($1).')
  assert.equal(a.sectors.find(r => r.key === 'fin')!.chip, 'RESILIENT')
  assert.equal(a.sectors.find(r => r.key === 'ind')!.chip, 'HOLDING')
  assert.equal(a.protect!.items[0].pct, '96% of account')
  assert.equal(a.protect!.items[0].linkLabel, 'Review stop →')
  assert.equal(a.protect!.more, '+1 more: DEMOB · B (no stop)')
  assert.equal(a.hedge!.verdict, 'Not now')
  assert.equal(a.hedge!.line, '$19,241 (1.5% of book · 4.8% of invested) is in stressed groups. The Defense desk considers a hedge when one weakening sector is ≥ 10% of invested, or 4+ sectors lag — now Technology 4.8%, 1 sector lagging.')
  assert.match(a.hedge!.lane, /^Inverse lane SH · PSQ: no bearish thesis since /)
  assert.ok(!/2-5%|size|band|playbook/i.test(JSON.stringify(a.hedge)), 'never a hedge size band or playbook')
  assert.equal(a.rotate!.rows[0].rs1, '+1.0%'); assert.equal(a.rotate!.rows[0].desk, 'desk LEADING')
  assert.match(a.rotate!.foot, /not a buy list/)
  assert.equal(rotateModel({ groups: [], none_reason: null })!.none, 'No group is beating SPY on both 1 and 5 sessions today.')
  assert.equal(hedgeModel({ verdict: 'UNKNOWN', reason: 'no stoplight evaluation yet' } as any)!.line, 'Defense stoplight no stoplight evaluation yet — no verdict until it runs again.')
  const consider = hedgeModel({ verdict: 'CONSIDER', thesis_state: 'GREEN', candidates: ['PSQ'], thresholds: { trigger_book_pct: 10, bounce_day_pct: 0.75 },
    largest_weakening: { label: 'Technology', pct_invested: 11.2 }, entry: { inverse: 'PSQ', bench: 'QQQ', label: 'WAIT FOR BOUNCE DAY' } } as any)!
  assert.equal(consider.line, 'Technology is 11.2% of invested and weakening — above the 10% the Defense desk uses. PSQ: thesis green · entry wait for bounce day (bounce days of +0.75% on QQQ).')
  const seg = Object.fromEntries(a.segments.map(x => [x.symbol, x]))
  assert.match(seg.DEMOS.line, /^segment weights pending approval — counted as /)
  assert.equal(seg.DEMOT.status, 'approved')
  assert.deepEqual(seg.DEMOT.split.map(x => x.label), ['Industrials', 'Technology'], 'themes overlap and are not in the split')
  assert.match(seg.DEMOT.line, /AI basket theme 80% \(overlaps\)/)
  assert.equal(a.glossary.stress.label, 'STRESS')
  for (const s of [...a.protect!.items.map(x => x.consideration), a.hedge!.line, a.hedge!.lane]) assert.ok(!/\b(buy|sell|trim) /i.test(s), 'advisory text only')
  // a v005 projection (no v006 blocks) keeps working
  const v5 = actionableModel(unwrapMarketRisk({ ok: true, data: { ...data, protect: undefined, hedge: undefined, rotate: undefined, sectors_folded: undefined } }))!
  assert.equal(v5.protect, null); assert.equal(v5.hedge, null); assert.equal(v5.foldLine, '')
  console.log('marketRisk.test v006 actions: ok')
}
console.log('marketRisk.test ok')
