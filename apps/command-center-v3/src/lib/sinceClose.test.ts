import assert from 'node:assert/strict'
import { sinceCloseModel, pctText, usdText, type SinceCloseWire, type SinceCloseMove } from './sinceClose.ts'

const mv = (o: Partial<SinceCloseMove>): SinceCloseMove => ({ symbol: 'AAA', held: true, price: 10, change_pct: 8.6, week_pct: 2, dollar_impact: 86, close_tag: 'Mon close', big_move: true, news: [], no_news: false, ...o })
const wire = (o: Partial<SinceCloseWire> = {}): SinceCloseWire => ({
  status: 'ok', window_now: { label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2026-11-09', session_open: false },
  moves: [mv({}), mv({ symbol: 'WWW', held: false, change_pct: -18.2, dollar_impact: null, no_news: true }), mv({ symbol: 'ZZZ', held: false, change_pct: 0.2, big_move: false })],
  macro: { headlines: [{ title: 'Wall Street swoons', source: 'CNBC' }], futures: { status: 'pending', label: 'futures feed pending', quotes: [] } },
  summary: { source: 'deterministic', text: null, lines: ['AAA +8.6% (Mon close)'], reason: 'llm_unavailable' },
  freshness: { age_seconds: 300, stale: false, window_current: true }, ...o,
})

// overnight: full card, label names the window, futures pending is stated, never blank
const m = sinceCloseModel(wire())
assert.equal(m.state, 'full'); assert.equal(m.label, 'Since Mon 4:00 PM')
assert.equal(m.futuresText, 'futures feed pending')
assert.deepEqual(m.summaryLines, ['AAA +8.6% (Mon close)'])   // no LLM text → deterministic list, not empty
assert.equal(m.held.length, 1); assert.deepEqual(m.watch.map(x => x.symbol), ['WWW']) // small unreported mover hidden
assert.equal(m.freshnessText, 'built 5 min ago')

// 09:30-16:00: one line, not removed
assert.equal(sinceCloseModel(wire({ window_now: { label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2026-11-09', session_open: true } })).state, 'collapsed')

// LLM text replaces the lines
const t = sinceCloseModel(wire({ summary: { source: 'llm', text: 'Four sentences.', lines: ['x'] } }))
assert.equal(t.summaryText, 'Four sentences.'); assert.deepEqual(t.summaryLines, [])

// futures available
const f = sinceCloseModel(wire({ macro: { headlines: [], futures: { status: 'available', quotes: [{ symbol: 'ES', change_pct: -0.4 }] } } }))
assert.equal(f.futuresText, 'ES -0.4%')

// no snapshot: still a card with a label, honest freshness
const n = sinceCloseModel({ status: 'no_snapshot', window: { label: 'Since Fri 4:00 PM', close_tag: 'Fri close', session_date: '2026-11-06', session_open: false } })
assert.equal(n.state, 'none'); assert.equal(n.label, 'Since Fri 4:00 PM'); assert.equal(n.freshnessText, 'not built yet')
assert.equal(sinceCloseModel(null).state, 'none')

// a stale window is called out
assert.match(sinceCloseModel(wire({ freshness: { age_seconds: 20000, stale: true, window_current: false } })).freshnessText, /built 6 h ago · a newer window/)

// amendment 2: feed, week ahead, CIO brief
const a2 = sinceCloseModel(wire({
  feed: [{ title: 'AAA news', source: 'yahoo', kind: 'holding', exposure: 1086, so_what: 'You hold $1,086 here.', holdings: [] }],
  week_ahead: { events: [{ date: '2026-11-10', kind: 'macro', label: 'Consumer Price Index', time_et: '08:30', symbols: [] }] },
  cio_brief: { status: 'available', summary: 'Risk is YELLOW.', risk_tier: 'YELLOW', actions: [{ symbol: 'AAA', action: 'raise stop', reason: 'gap up' }] },
}))
assert.equal(a2.feed.length, 1); assert.equal(a2.weekAhead[0].label, 'Consumer Price Index')
assert.equal(a2.cio.pending, false); assert.equal(a2.cio.tier, 'YELLOW'); assert.deepEqual(a2.cio.actions, [{ symbol: 'AAA', text: 'raise stop — gap up' }])
assert.equal(m.cio.pending, true); assert.equal(m.cio.label, 'CIO brief pending'); assert.equal(m.fedSpeakersText, 'no feed — not listed')

// LQ-1260: intraday
const NOW = Date.parse('2026-11-10T15:45:00Z')
const openW = { label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2026-11-09', session_open: true }
const upd = { at: '2026-11-10T15:30:00Z', at_et: '10:30 ET', reason: 'new AAA article', kind: 'news' as const, symbol: 'AAA', headline: 'AAA names a new CFO' }
const intra = sinceCloseModel(wire({ window_now: openW, updated: upd, today: { label: 'Today so far', basis: 'move vs prior close', since: '2026-11-10T14:30:00Z', moves: [mv({})], news: [] } }), NOW)
assert.equal(intra.state, 'collapsed'); assert.equal(intra.collapsedNote, 'New: AAA AAA names a new CFO')
assert.equal(intra.updatedText, 'updated 10:30 ET — new AAA article'); assert.equal(intra.today?.label, 'Today so far')
// yesterday's "new" is not today's news; a first build says nothing
assert.equal(sinceCloseModel(wire({ window_now: openW, updated: upd }), Date.parse('2026-11-11T15:45:00Z')).collapsedNote, null)
assert.equal(sinceCloseModel(wire({ updated: { ...upd, kind: 'first', reason: 'first build' } }), NOW).updatedText, null)
assert.equal(sinceCloseModel(wire({ window_now: openW, updated: { ...upd, kind: 'move', symbol: 'BBB', reason: 'BBB +3.4%' } }), NOW).collapsedNote, null)
// CIO brief aliases (LQ-1257 shape unconfirmed): nothing invented when a field is missing
const c1 = sinceCloseModel(wire({ cio_brief: { status: 'available', overview: 'Calm.', risk: { level: 'GREEN' }, holding_actions: [{ ticker: 'AAA', recommendation: 'hold stop', rationale: 'no change' }, { ticker: 'BBB' }] } })).cio
assert.equal(c1.summary, 'Calm.'); assert.equal(c1.tier, 'GREEN'); assert.deepEqual(c1.actions, [{ symbol: 'AAA', text: 'hold stop — no change' }])
assert.equal(sinceCloseModel(wire({ cio_brief: { status: 'available' } })).cio.tier, null)

assert.equal(pctText(-18.24), '-18.2%'); assert.equal(pctText(null), '—'); assert.equal(usdText(-1234.4), '−$1,234'); assert.equal(usdText(86), '+$86')
console.log('sinceClose tests passed')
