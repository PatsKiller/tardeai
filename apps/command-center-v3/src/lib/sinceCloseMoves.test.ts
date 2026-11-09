// LQ-20261107-1282 — the chip model: a close value AND a "now" value, and never a percentage the producer did not
// compute. Fixtures are synthetic; the shape is the one scripts/lib/since_close_card.py writes.
import assert from 'node:assert/strict'
import { arrowFor, movesModel } from './sinceCloseMoves.ts'
import type { SinceCloseWire, SinceCloseMove } from './sinceClose.ts'

const mv = (o: Partial<SinceCloseMove>): SinceCloseMove => ({
  symbol: 'AAA', held: true, price: 10, change_pct: 8.6, week_pct: 2, dollar_impact: 860, close_tag: 'Fri close',
  big_move: true, news: [], no_news: false, ...o,
})
const wire = (o: Partial<SinceCloseWire> = {}): SinceCloseWire => ({
  status: 'ok',
  window_now: { label: 'Since Fri 4:00 PM', close_tag: 'Fri close', session_date: '2026-11-06', session_open: false },
  moves: [mv({}), mv({ symbol: 'BBB', held: false, change_pct: -4.4, dollar_impact: null })],
  freshness: { age_seconds: 60, stale: false, window_current: true },
  ...o,
})

assert.equal(arrowFor(1.2), '▲')
assert.equal(arrowFor(-0.1), '▼')
assert.equal(arrowFor(0), '–')
assert.equal(arrowFor(null), '–')
assert.equal(arrowFor(Number.NaN), '–')

// --- a name with no print since the close: one value, and the reason it has one
{
  const m = movesModel(wire())
  const a = m.held[0]
  assert.equal(a.closeText, '+8.6%')
  assert.equal(a.closeArrow, '▲')
  assert.equal(a.ext, null)
  assert.equal(a.note, 'no print since Fri', 'the close tag names the day, the note repeats it')
  assert.equal(m.levelsStatus, 'pending')
  assert.equal(m.pendingText, 'futures feed pending — no print from the extended-hours lane yet')
}

// --- an overnight print dated to this close: a second value, the session named, the arrow the same as the chips
{
  const m = movesModel(wire({
    moves: [mv({
      extended: {
        state: 'print', session: 'overnight', session_label: 'overnight', price: 10.4, change_pct: 3.0,
        printed_text: 'Sun 10:00 PM ET', reference_date: '2026-11-06',
      },
      move_now_pct: 3.0, dollar_impact_now: 300,
    })],
  }))
  const e = m.held[0].ext!
  assert.equal(e.state, 'print')
  assert.equal(e.label, 'overnight')
  assert.equal(e.pctText, '+3.0%')
  assert.equal(e.arrow, '▲')
  assert.equal(e.basisText, 'vs Fri close')
  assert.equal(e.printText, 'Sun 10:00 PM ET')
  assert.equal(m.held[0].note, null)
}

// --- a level-only print: the price is shown, the percentage is NOT invented, and the basis says why
{
  const m = movesModel(wire({
    moves: [mv({
      extended: {
        state: 'level_only', session: 'premarket', session_label: 'pre-market', price: 9.5, change_pct: null,
        printed_text: 'Tue 5:00 AM ET', reference_date: '2026-11-03',
      },
      move_now_pct: 8.6, dollar_impact_now: 860,
    })],
  }))
  const e = m.held[0].ext!
  assert.equal(e.state, 'level_only')
  assert.equal(e.pct, null)
  assert.equal(e.pctText, '')
  assert.equal(e.arrow, '–')
  assert.equal(e.priceText, '$9.50')
  assert.equal(e.basisText, 'level only (reference 2026-11-03)')
}

// --- held chips sort by |$ in the newest print|, not by the Friday order
{
  const m = movesModel(wire({
    moves: [
      mv({ symbol: 'SMALL', dollar_impact_now: 12, dollar_impact: 12 }),
      mv({ symbol: 'BIG', dollar_impact_now: 4000, dollar_impact: 10 }),
      mv({ symbol: 'WATCH', held: false, change_pct: -1, dollar_impact: null }),
    ],
  }))
  assert.deepEqual(m.held.map(c => c.symbol), ['BIG', 'SMALL'])
  assert.equal(m.held[0].dollarsText, '+$4,000')
}

// --- the futures / overseas row: levels with their own as-of, and a level-only root that keeps its price
{
  const m = movesModel(wire({
    macro: {
      headlines: [], futures: { status: 'available', quotes: [] },
      now: {
        status: 'available', as_of_text: 'Sun 6:45 PM ET',
        futures: [
          { symbol: '/ES', label: 'S&P 500 futures', level: 7398.75, change_pct: null, level_only: true, session: 'futures_open', session_label: 'futures open', printed_text: 'Sun 6:45 PM ET' },
          { symbol: '/YM', label: 'Dow futures', level: 51521, change_pct: 0.26, level_only: false, session: 'futures_open', session_label: 'futures open', printed_text: 'Sun 6:44 PM ET' },
        ],
        indices: [{ symbol: '$VIX', label: 'VIX', level: 17.1, change_pct: -2.1, level_only: false, session: 'overnight', session_label: 'overnight', printed_text: 'Sun 6:40 PM ET' }],
        missing: ['/NQ'],
        overseas: { status: 'no_feed', label: 'Overseas cash indices: no direct feed on this host.', rows: [] },
      },
    },
  }))
  assert.equal(m.levelsStatus, 'available')
  assert.equal(m.asOfText, 'Sun 6:45 PM ET')
  assert.deepEqual(m.levels.map(l => l.symbol), ['/ES', '/YM', '$VIX'])
  assert.equal(m.levels[0].levelOnly, true)
  assert.equal(m.levels[0].levelText, '$7,398.75')
  assert.equal(m.levels[1].pctText, '+0.3%')
  assert.equal(m.levels[1].arrow, '▲')
  assert.equal(m.levels[2].arrow, '▼')
  assert.equal(m.overseasText, 'Overseas cash indices: no direct feed on this host.')
  assert.deepEqual(m.overseas, [], 'a snapshot with no overseas rows draws none')
}

// --- overseas: the label and when it opens, never a percentage this host cannot compute
{
  const m = movesModel(wire({
    macro: {
      headlines: [], futures: { status: 'pending', quotes: [] },
      now: {
        status: 'pending', futures: [], indices: [],
        overseas: {
          status: 'no_feed', label: 'Overseas cash indices: no direct feed on this host.',
          rows: [{ label: 'Nikkei 225', status: 'no_feed', opens_text: 'opens Tue 7:00 PM ET' }],
        },
      },
    },
  }))
  assert.deepEqual(m.overseas, [{ label: 'Nikkei 225', text: 'opens Tue 7:00 PM ET' }])
  assert.equal(m.overseas[0].text.includes('%'), false, 'no invented move')
}

// --- no wire: nothing to draw, never a throw
{
  const m = movesModel(null)
  assert.deepEqual(m.held, [])
  assert.deepEqual(m.levels, [])
  assert.equal(m.levelsStatus, 'pending')
}

console.log('sinceCloseMoves LIVEFIX-LQ1282')
