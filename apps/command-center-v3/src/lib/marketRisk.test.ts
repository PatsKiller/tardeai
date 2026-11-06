// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
  deepEqual(a: unknown, b: unknown, m?: string) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(m ?? `expected ${x} to deep-equal ${y}`) },
  match(s: string, re: RegExp, m?: string) { if (!re.test(s)) fail(m ?? `expected ${JSON.stringify(s)} to match ${re}`) },
}
import { plainEngineReason, unwrapMarketRisk, bannerVisible, factLine, tierTone, contributorsLine, pointsSum, episodeLine, fmtPct, shadowMarker, SHADOW_MARKER, CARRIED_MARKER,
  summaryVisible, summaryDefaultOpen, summaryModel, fmtPoints, budgetLabel, SUMMARY_PHONE_MAX_PX,
  actionableModel, verdictLine, fmtUsd, fmtSignedPct, hedgeModel, rotateModel, pointsToScore } from './marketRisk.ts'

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
assert.match(ml.notMeasured, /^Missing input: extended hours — the score may be understated\. /); n++
assert.match(ml.missingDetail ?? '', /^Extended hours: /, 'each missing input named with its reason (the (i) detail)'); n++
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
t(me.notMeasured.startsWith('Missing input: extended hours — the score may be understated.'), 'empty: only the missing-input line')
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
  assert.equal(a.sectors[1].why, 'no SPY comparison for this group on this run', 'no reason sent: still says what is missing')
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
  assert.equal(r.now, 'unavailable', 'legacy confirmed Friday close never masquerades as Now')
  assert.equal(r.vsExit, '—', 'missing current quote cannot borrow Friday percent')
  const currentQuote = { status: 'available', price: 12.34, source: 'market_quotes:alpaca', session: 'regular',
    session_date: '2031-03-10', expected_session_date: '2031-03-10', as_of: '2031-03-10T20:00:59.999999Z',
    pct_vs_exit: 23.4, pct_vs_sma20: 10 }
  const quoteRow = (quote: any, assessment = '2031-03-11T00:15:00Z') => actionableModel(unwrapMarketRisk({ ...base, as_of: assessment,
    reentry_watch: { NEWX: { ...base.reentry_watch.NEWX, current_quote: quote } } }))!.reentry[0]
  const freshRow = quoteRow(currentQuote)
  assert.equal(freshRow.now, '$12.34', 'Monday after-close quote wins display over confirmed Friday9.50')
  assert.equal(freshRow.vsExit, '+23.4%', 'current quote percent is kept coherent')
  assert.equal(freshRow.verdict, 'Still falling', 'display quote never changes the confirmed stage verdict')
  assert.match(freshRow.lookThrough, /Stored regular-session observation · fetched .*ET.*market_quotes:alpaca · trade time\/live freshness unverified/)
  for (const quote of [null, { ...currentQuote, price: Infinity }, { ...currentQuote, price: '12.34' },
    { ...currentQuote, session_date: '2031-03-07' }, { ...currentQuote, as_of: '2031-03-11T01:00:00Z' },
    { ...currentQuote, as_of: '2031-03-10T16:00:00' }, { ...currentQuote, session: 'premarket' }]) {
    assert.equal(quoteRow(quote).now, 'unavailable', 'invalid quote never falls back to Friday')
    assert.equal(quoteRow(quote).vsExit, '—')
  }
  // A normal closed-market prior close is context, never Now or a system failure.
  const fridayQuote = { ...currentQuote, price: 9.5, session_date: '2031-03-07', expected_session_date: '2031-03-07', as_of: '2031-03-07T21:00:59.999999Z' }
  for (const assessment of ['2031-03-10T12:00:00Z', '2031-03-08T17:00:00Z', '2031-03-09T17:00:00Z']) {
    const prior = quoteRow(fridayQuote, assessment)
    assert.equal(prior.now, '—', 'pre-open/weekend prior close cannot be labeled Now')
    assert.equal(prior.vsExit, '—', 'prior quote percent is not a current comparison')
    assert.match(prior.lookThrough, /Last stored regular-session observation \$9\.50 · 2031-03-07 · fetched .*ET · market_quotes:alpaca · trade time\/live freshness unverified/)
    assert.ok(!/Price unavailable|Price stale/.test(prior.lookThrough), 'normal prior close is not a system failure')
    assert.equal(prior.verdict, 'Still falling')
  }
  // FQ-094: with no verdict from the CIO, the card states that — it used to invent "Still falling".
  const noVerdict = actionableModel(unwrapMarketRisk({ ...base,
    reentry_watch: { NEWX: { symbol: 'NEWX', exit_date: '2031-03-07', exit_price: 10, stages: { last_close: 9.5, pct_vs_exit: -5 } } } }))!.reentry[0]
  assert.equal(noVerdict.verdict, 'no CIO verdict on record', 'a missing verdict is stated, never inferred from the price series')
  assert.ok(noVerdict.verdictTone !== 'danger', 'an absent verdict is not coloured as a bearish one')
  // LIVEFIX-R (operator 2026-11-06): the chip never says STILL FALLING over a measurement that contradicts it, and an
  // unmeasured stage is "not measured", never "0 of 5 — waiting: all met". The producer's verdict field is untouched.
  assert.equal(r.verdictShown, 'Still falling', 'below the exit, closes not up: the producer word stands')
  assert.equal(r.verdictNote, null)
  assert.equal(r.vsExitKnown, false, 'no current quote: vs exit needs a current price')
  assert.equal(r.priceWhy, 'no price feed for this symbol on this run')
  assert.match(r.lookThrough, /^No price feed for this symbol on this run · look-through: no fund or sector breakdown on file for this symbol/)
  assert.equal(r.lookThroughMissing, true)
  assert.equal(r.stagesPending, false)
  const lastPx = quoteRow({ ...currentQuote, status: 'unavailable', session: 'premarket', as_of: '2031-03-10T13:05:00Z' }, '2031-03-10T15:00:00Z')
  assert.match(lastPx.lookThrough, /^No current price — last price \$12\.34 at Mon 03\/10,? 09:05 ET · /)
  const staleQ = quoteRow({ ...currentQuote, stale: true, as_of: '2031-03-10T14:05:00Z' }, '2031-03-10T15:00:00Z')
  assert.match(staleQ.lookThrough, /^Price out of date — last price \$12\.34 at Mon 03\/10,? 10:05 ET · /)
  const noPx = quoteRow({ status: 'unavailable', price: null, as_of: '2031-03-09T21:00:00Z' }, '2031-03-10T15:00:00Z')
  assert.match(noPx.lookThrough, /^No price feed for this symbol since Sun 03\/09,? 17:00 ET · /)
  assert.match(noPx.priceWhy!, /^no price feed for this symbol since Sun 03\/09,? 17:00 ET$/)
  for (const row of [r, lastPx, staleQ, noPx]) assert.ok(!/not measured|canonical/i.test(row.lookThrough), 'no bare "not measured" in the price line')
  assert.equal(freshRow.verdictShown, 'Mixed', 'price above the exit contradicts "Still falling"')
  assert.equal(freshRow.verdictTone, 'warning')
  assert.match(freshRow.verdictNote!, /^Stage verdict from the closes is "Still falling", but the price now is \+23\.4% vs the exit\./)
  assert.equal(freshRow.vsExitKnown, true)
  const closeAbove = actionableModel(unwrapMarketRisk({ ...base, reentry_watch: { NEWX: { ...base.reentry_watch.NEWX,
    stages: { ...base.reentry_watch.NEWX.stages, last_close: 10.4, pct_vs_exit: 4 } } } }))!.reentry[0]
  assert.equal(closeAbove.verdictShown, 'Mixed', 'a confirmed close above the exit also contradicts it')
  assert.match(closeAbove.verdictNote!, /last close \$10\.40 is at or above the exit \$10\.00/)
  const trendUp = actionableModel(unwrapMarketRisk({ ...base, reentry_watch: { NEWX: { ...base.reentry_watch.NEWX,
    stages: { ...base.reentry_watch.NEWX.stages, trend: 'up' } } } }))!.reentry[0]
  assert.equal(trendUp.verdictShown, 'Mixed'); assert.match(trendUp.verdictNote!, /the closes trend up/)
  const noSession = actionableModel(unwrapMarketRisk({ ...base, reentry_watch: { NEWX: { symbol: 'NEWX', exit_date: '2031-03-07', exit_price: 10,
    stages: { verdict: 'Still falling', exit_price: 10, stage1: { met: 0, of: 5, conditions: [] }, stage2: { met: false, conditions: [] }, note: 'no session since the exit' } } } }))!.reentry[0]
  assert.equal(noSession.verdict, 'Still falling', 'producer field kept verbatim')
  assert.equal(noSession.verdictShown, 'Check after close')
  assert.equal(noSession.verdictTone, 'neutral')
  assert.equal(noSession.verdictNote, 'First re-entry check after the next stored daily close (exit Fri 03-07; no close stored since).')
  assert.ok(!/fall-back|Still falling/.test(noSession.verdictNote!), 'the producer fall-back sentence is gone (operator 2026-11-06)')
  assert.equal(noSession.stagesPending, true)
  assert.equal(noSession.stage1, 'not checked yet', 'never "0 of 5"')
  assert.equal(noSession.waiting, 'First re-entry check after the next stored daily close (exit Fri 03-07; no close stored since)', 'never "all met" when nothing was evaluated')
  assert.equal(noSession.stage2, 'checked after stage 1 (no close stored since the exit)')
  // exit on the evaluation day (ET): the operator's wording
  const today = actionableModel(unwrapMarketRisk({ ...base, as_of: '2031-03-10T18:00:00Z', reentry_watch: { NEWX: { symbol: 'NEWX', exit_date: '2031-03-10', exit_price: 10,
    stages: { verdict: 'Still falling', exit_price: 10, stage1: { met: 0, of: 5, conditions: [] }, stage2: { met: false, conditions: [] }, note: 'no session since the exit' } } } }))!.reentry[0]
  assert.equal(today.verdictShown.toUpperCase(), 'CHECK AFTER CLOSE')
  assert.equal(today.verdictNote, "First re-entry check after tonight's close (exit was today).")
  assert.equal(today.waiting, "First re-entry check after tonight's close (exit was today)")
  // another producer note is stated in plain words, never a bare "not measured"
  const otherNote = actionableModel(unwrapMarketRisk({ ...base, reentry_watch: { NEWX: { symbol: 'NEWX', exit_date: '2031-03-07', exit_price: 10,
    stages: { verdict: 'Still falling', stage1: { met: 0, of: 5, conditions: [] }, note: 'no basket bars' } } } }))!.reentry[0]
  assert.equal(otherNote.verdictShown, 'Not checked yet')
  assert.equal(otherNote.verdictNote, 'Re-entry stages not checked yet: no price history for this group.')
  assert.equal(otherNote.stage2, 'checked after stage 1 (no close stored since the exit)')
  const allMet = actionableModel(unwrapMarketRisk({ ...base, reentry_watch: { NEWX: { ...base.reentry_watch.NEWX,
    stages: { ...base.reentry_watch.NEWX.stages, verdict: 'Early setup', stage1: { met: 2, of: 2, conditions: [{ key: 'a', met: true, text: 'x' }, { key: 'b', met: true, text: 'y' }] } } } } }))!.reentry[0]
  assert.equal(allMet.stage1, '2 of 2'); assert.equal(allMet.waiting, 'all met'); assert.equal(allMet.verdictShown, 'Early setup')
  const unlisted = actionableModel(unwrapMarketRisk({ ...base, reentry_watch: { NEWX: { ...base.reentry_watch.NEWX,
    stages: { ...base.reentry_watch.NEWX.stages, verdict: 'Basing', stage1: { met: 3, of: 5, conditions: [] } } } } }))!.reentry[0]
  assert.equal(unlisted.stage1, '3 of 5'); assert.equal(unlisted.waiting, 'conditions not listed', '3 of 5 with no list is never "all met"')
  for (const quote of [
    { ...currentQuote, as_of: '2031-03-10T13:29:59Z' }, // before 09:30 after DST
    { ...currentQuote, as_of: '2031-03-10T20:01:00Z' }, // after 16:00 closing minute
    { ...currentQuote, as_of: '2031-03-09T17:00:00Z', session_date: '2031-03-09', expected_session_date: '2031-03-09' }, // Sunday
    { ...currentQuote, as_of: '2031-03-07T21:00:00Z' }, // timestamp/session mismatch
    { ...currentQuote, session_date: {} as any, expected_session_date: {} as any },
  ]) {
    assert.equal(quoteRow(quote).now, 'unavailable', 'nonregular or mismatched timestamp is not Now or prior-close context')
    assert.ok(!/Last stored regular-session observation/.test(quoteRow(quote).lookThrough))
  }
  assert.equal(quoteRow({ ...currentQuote, as_of: '2031-03-10T13:30:00Z' }).now, '$12.34', '09:30 ET is inside regular session')
  assert.equal(quoteRow({ ...currentQuote, as_of: '2031-03-10T16:00:59-04:00' }).now, '$12.34', 'explicit ET offset closing minute remains valid')
  assert.equal(quoteRow({ ...currentQuote, status: 'stale' }).now, 'stale')
  assert.equal(quoteRow({ ...currentQuote, stale: true }).now, 'stale')
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
    protect: { items: [{ symbol: 'DEMOA', account_label: 'A', kinds: ['stop_near'], text: 'stop 3.6% below last', usd: 500, to: '/risk?tab=exposure&symbol=DEMOA', pct_account: 88.0,
      consideration: 'stop 3.6% below last; one stock is 88% of the account, far above the 30% sector budget' }],
      more: [{ symbol: 'DEMOB', account_label: 'B', short: 'no stop', to: '/x' }] },
    hedge: { verdict: 'NOT_NOW', thesis_state: 'RED', candidates: ['SH', 'PSQ'], since: '2031-03-07', thresholds: { trigger_book_pct: 10, index_trigger_lagging_sectors: 4 },
      largest_weakening: { label: 'Technology', pct_invested: 5.5 }, lagging_count: 1, stressed_usd: 12345, stressed_pct_book: 2.5, stressed_pct_invested: 4.0,
      size_band: '2-5%', playbook: ['x'] },
    rotate: { as_of: '2031-03-07', groups: [{ key: 'fin', label: 'Financials', rs1: 1.03, rs5: 1.63, desk_state: 'LEADING', usd: 400 }] },
    sectors_folded: [{ key: 'ai', label: 'AI basket', state: 'STRESS', usd: 28 }, { key: 're', label: 'Real estate', state: 'UNKNOWN', usd: 1 }],
    glossary: { stress: { label: 'STRESS', text: 'x' } },
    segments_status: { DEMOS: { status: 'pending', groups: null }, DEMOT: { status: 'approved', groups: { ind: 0.6, tech: 0.4, ai: 0.8 }, source: 'DEMO 10-Q', as_of: '2031-01-31' } },
  }
  const mr = unwrapMarketRisk({ ok: true, data })!
  const a = actionableModel(mr)!
  assert.deepEqual(a.sectors.map(r => r.key), ['tech', 'fin', 'ind'], 'folded groups leave the table')
  assert.equal(a.foldLine, 'Also stressed, you hold under $100: AI basket ($28). No SPY comparison this run, you hold under $100: Real estate ($1).')
  assert.equal(a.foldHasUnknown, true)
  assert.equal(a.sectors.find(r => r.key === 'fin')!.chip, 'RESILIENT')
  assert.equal(a.sectors.find(r => r.key === 'ind')!.chip, 'HOLDING')
  assert.equal(a.protect!.items[0].pct, '88% of account')
  assert.equal(a.protect!.items[0].linkLabel, 'Review stop →')
  assert.equal(a.protect!.more, '+1 more: DEMOB · B (no stop)')
  assert.equal(a.hedge!.verdict, 'Not now')
  assert.equal(a.hedge!.line, '$12,345 (2.5% of book · 4.0% of invested) is in stressed groups. The Defense desk considers a hedge when one weakening sector is ≥ 10% of invested, or 4+ sectors lag — now Technology 5.5%, 1 sector lagging.')
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

// LIVEFIX-R problem 4: a contributor badge carries its unit — never a bare "+31".
assert.equal(pointsToScore(31), '+31 pts to score')
assert.equal(pointsToScore(4.6), '+5 pts to score')
assert.equal(pointsToScore(-2.4), '-2 pts to score')
assert.equal(pointsToScore(34.44, 1), '+34.4 pts to score')
assert.equal(pointsToScore(0), '+0 pts to score')
assert.equal(pointsToScore(null), 'no points sent by the engine')
// operator 2026-11-06: an engine reason_unknown in plain words, never dropped
assert.equal(plainEngineReason('insufficient history'), 'not enough price history yet to compare with SPY (needs 60 trading days)')
assert.equal(plainEngineReason('insufficient history: 41 SPY sessions with a close (need 60)'), 'only 41 of the 60 trading days of prices needed to compare with SPY')
assert.equal(plainEngineReason('stale: last close 2031-03-05, SPY 2031-03-07'), "prices are behind SPY's: last close Wed 03-05, SPY has Fri 03-07")
assert.equal(plainEngineReason('gaps: 4 of the last 60 SPY sessions missing (limit 3)'), '4 of the last 60 trading days have no price (at most 3 allowed)')
assert.equal(plainEngineReason('no bars for 0/3'), 'no price history for this group')
assert.equal(plainEngineReason('carried across a closure'), 'last reading is from before the market closed, so it is not reused')
assert.equal(plainEngineReason('ValueError: bad frame'), 'the check failed on its last run')
assert.equal(plainEngineReason('something new'), 'something new', 'an unknown engine sentence is shown as written')
assert.equal(plainEngineReason(null), 'the engine gave no reason')
assert.equal(summaryModel(unwrapMarketRisk({ ok: true, data: yBase }))!.contributors[0].pointsLabel, `${summaryModel(unwrapMarketRisk({ ok: true, data: yBase }))!.contributors[0].points} pts to score`)
console.log('marketRisk LIVEFIX-R ok')
