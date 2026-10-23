// node --experimental-strip-types src/lib/tradeJourneyModel.test.ts
// The TradeInView journey page model on the NAVN fixture — the trade_journey projection's own output
// (src/fixtures/tradeJourneys.fixture.ts, generated and drift-checked by tests/test_trade_journey_20261022.py).
declare const process: { exit(code?: number): never }
import { TRADE_JOURNEYS_FIXTURE as FIX } from '../fixtures/tradeJourneys.fixture.ts'
import {
  EXIT_TONE, FILTERS, TOOLTIPS, alertIntel, apiDetail, chartGeom, conditionsMet, drawers, etShort, exitText,
  filterCounts, filterJourneys, money, originBadge, pct, plText, px, spreadLabels, stopSegments, timelineTone, unwrap, unwrapDetail,
} from './tradeJourneyModel.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const P = unwrap(FIX)!
ok('payload unwraps', P && P.journeys.length === 3)
ok('unwrap accepts the {ok,data} envelope', unwrap({ ok: true, data: FIX }) !== null)
eq('unwrap rejects junk', unwrap({ ok: true }), null)
eq('interim is labelled', [P.interim, P.source_label], [true, 'interim — CIO prospect store not live'])
eq('detail unwraps', unwrapDetail({ ok: true, journey: P.journeys[0] })?.symbol, 'NAVN')
eq('detail path encodes the id', apiDetail('rt:a|NAVN|2026-10-19'), '/api/v3/data-broker/trade-journeys/rt%3Aa%7CNAVN%7C2026-10-19')

const navn = P.journeys.find(j => j.symbol === 'NAVN')!
eq('NAVN origin badge', originBadge(navn.origin), { text: 'INTERNAL · Home #4 · 86', tone: 'ai' })
eq('NAVN origin label', navn.origin.label, 'Home #4 · conviction 86 · CIO BUY_READY 10-16')
eq('NAVN exit cause', [navn.exit_cause.kind, exitText(navn)], ['trailing_ratchet', 'Trailing stop (ratchet)'])
eq('exit tone for a ratchet', EXIT_TONE[navn.exit_cause.kind], 'warning')
eq('NAVN stop path', navn.stop_path.map(s => s.level_ref), [24.31, 24.59, 24.7, 24.97, 25.51, 25.61, 26.02])
eq('NAVN P/L text', plText(navn), '+$189.73 (+1.5%)')
eq('timeline starts at origin, ends at exit', [navn.timeline[0].kind, navn.timeline[navn.timeline.length - 1].kind], ['origin', 'exit_fill'])
eq('exit event takes the cause tone', timelineTone(navn.timeline[navn.timeline.length - 1]), 'warning')
eq('re-entry conditions', conditionsMet(navn.re_entry), { met: 6, total: 8 })
eq('alert seed is the desk zone', alertIntel(navn.re_entry), { entryLow: 24.8, entryHigh: 25.1, price: 26.02, rsi: 61 })
ok('advisory is labelled', navn.review.advisory?.label.startsWith('Advisory'))

const own = P.journeys.find(j => j.symbol === 'BAH')!
eq('own pick badge', originBadge(own.origin), { text: 'YOUR PICK', tone: 'info' })
const v = P.journeys.find(j => j.symbol === 'V')!
eq('unknown origin badge', originBadge(v.origin), { text: 'ORIGIN ?', tone: 'neutral' })
eq('open trade exit text', exitText(v), 'open · stop $399.82')

// filters
eq('filter counts', filterCounts(P.journeys), { all: 3, attention: 1, open: 1, closed: 2, internal: 1, mine: 1 })
eq('attention = NAVN (a conflict)', filterJourneys(P.journeys, 'attention').map(j => j.symbol), ['NAVN'])
ok('every filter has a tooltip', FILTERS.every(f => f.tip.length > 20))
ok('every tooltip is a sentence', Object.values(TOOLTIPS).every(t => t.length > 40))

// formatting
eq('money', [money(13539.38, true), money(-5.5, true), money(null)], ['+$13,539', '−$5.50', '—'])
eq('px/pct', [px(26), pct(-2.4), pct(null)], ['$26.00', '−2.4%', '—'])
eq('ET short', etShort('2026-10-22T16:31:00+00:00'), '10-22 12:31')

// drawers
const d = drawers(P)
eq('drawer ids', d.map(x => x.id), ['conflicts', 'gaps', 'how'])
ok('conflict drawer names both sources', d[0].body.includes('cio_opportunity_projection') && d[0].body.includes('schwab_round_trips'))
ok('how drawer says no orders', d[2].body.includes('Nothing on this page sizes, places, moves or cancels an order'))

// chart geometry
const g = chartGeom(navn.chart!)!
ok('chart shows the trade plus 25 sessions before the entry', g && g.bars.length === 29 && g.bars[25].time === '2026-10-19')
ok('every mark is inside the band', [navn.chart!.marks.entry_ref, navn.chart!.marks.exit_ref, 24.31, 26.625].every(v2 => v2! >= g.lo && v2! <= g.hi))
ok('higher price is higher on screen', g.y(27) < g.y(25))
eq('entry date maps to a bar', g.xOf('2026-10-19') === g.bars[25].x, true)
const segs = stopSegments(g, navn.chart!.marks)
eq('one segment per stop level', segs.length, 7)
ok('untimed stops share the held span in order', !segs[0].timed && segs[0].x1 === g.xOf('2026-10-19') && Math.abs(segs[6].x2 - g.xOf('2026-10-22')!) < 1e-9)
ok('raised stops climb on screen', segs.every((sg, i) => i === 0 || sg.y < segs[i - 1].y))
eq('no bars → no chart', chartGeom({ ...navn.chart!, bars: [] }), null)

// chart labels never overlap
eq('labels spread', spreadLabels([{ key: 'a', y: 50 }, { key: 'b', y: 52 }, { key: 'c', y: 100 }], 11), { a: 50, b: 61, c: 100 })
eq('labels stay above the bottom', spreadLabels([{ key: 'a', y: 95 }, { key: 'b', y: 96 }], 11, 0, 100), { a: 89, b: 100 })

if (failed) { console.error(`${failed} tradeJourneyModel check(s) failed`); process.exit(1) }
console.log('tradeJourneyModel: all checks passed')
