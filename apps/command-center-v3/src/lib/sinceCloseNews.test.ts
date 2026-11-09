// LQ-20261107-1283 (mockup v3) — the news card model: the producer's rank decides the order, the ticker leads the
// card, the badge says why, the meta line names every feed that carried the story, the glow is the producer's urgency
// level, and only the top six are up front. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { newsModel } from './sinceCloseNews.ts'
import type { SinceCloseFeedItem, SinceCloseWire } from './sinceClose.ts'

const item = (o: Partial<SinceCloseFeedItem>): SinceCloseFeedItem => ({
  title: 'A story', source: 'yahoo_rss', published_at: '2026-11-09T21:00:00Z', kind: 'holding', exposure: 1000,
  so_what: 'You hold $1,000 here.', holdings: [{ symbol: 'AAA', held: true, market_value: 1000, change_pct: 2.5 }],
  ...o,
})
// the trailing semicolon is load-bearing: without it the next `{` block is parsed as a continuation of this
// expression and tsc reports a dozen bogus syntax errors (TS1003/TS1005) at the `status:` and `window_now:` lines.
const wire = (feed: SinceCloseFeedItem[], o: Partial<SinceCloseWire> = {}): SinceCloseWire => ({
  status: 'ok',
  window_now: { label: 'Since Fri 4:00 PM', close_tag: 'Fri close', session_date: '2026-11-06', session_open: false },
  feed,
  ...o,
});

// --- order is the producer's rank, not the arrival order
{
  const m = newsModel(wire([
    item({ title: 'third', rank: 3, score: 5, why: 'market-wide' }),
    item({ title: 'first', rank: 1, score: 60, why: '$8,524 moved · CIO: SPCX ADD_STOP', sources: ['yahoo_rss', 'google_news:Reuters'] }),
    item({ title: 'second', rank: 2, score: 30, why: 'watchlist AXON −18.2%' }),
  ]))
  assert.deepEqual(m.items.map(i => i.title), ['first', 'second', 'third'])
  assert.equal(m.top[0].badgeText, '#1')
  assert.equal(m.top[0].whyText, '$8,524 moved · CIO: SPCX ADD_STOP', 'the producer explains the rank, the card does not')
  assert.equal(m.top[0].sourcesText, 'yahoo_rss · google_news:Reuters', 'both feeds are named')
  assert.equal(m.top[0].dupText, '+1 more on AAA', 'a story three feeds carried says how many extra')
  assert.equal(m.top[1].dupText, '')
  assert.equal(m.top[1].leadArrow, '▲', 'v3 leads with the ticker and its own arrow')
  assert.equal(m.top[1].symbolsText, 'AAA ▲ +2.50%')
}

// --- v3: the ticker leads, its move is the precise one, and the basis names the close
{
  const m = newsModel(wire([item({ title: 'x', rank: 1 })]))
  const c = m.top[0]
  assert.equal(c.lead, 'AAA')
  assert.equal(c.leadText, '+2.50%')
  assert.equal(c.leadArrow, '▲')
  assert.equal(c.basisText, 'vs Fri close')
  assert.equal(c.glow, null, 'no urgency in the snapshot -> no glow, never a guessed one')
  assert.equal(c.glowText, null)
}

// --- v3: the glow is the producer's level, with the producer's reason
{
  const m = newsModel(wire([
    item({ title: 'good', rank: 1, urgency: 'green', urgency_why: 'held AAA +8.62% since the close' }),
    item({ title: 'bad', rank: 2, urgency: 'red', urgency_why: 'held BBB -4.4% since the close' }),
    item({ title: 'meh', rank: 3, urgency: 'amber', urgency_why: 'insider sale' }),
    item({ title: 'quiet', rank: 4, urgency: null }),
  ]))
  assert.deepEqual(m.items.map(i => i.glow), ['green', 'red', 'amber', null])
  assert.equal(m.top[0].glowText, 'big gain on a holding · held AAA +8.62% since the close')
  assert.equal(m.top[1].glowText, 'urgent risk · held BBB -4.4% since the close')
  assert.equal(m.top[2].glowText, 'watch closely · insider sale')
}

// --- v3: a market-wide story leads with "Market", and a watchlist story is flagged
{
  const m = newsModel(wire([
    item({ title: 'Futures slip', kind: 'macro', holdings: [], source: 'CNBC' }),
    item({ title: 'AXON cut', kind: 'watch', holdings: [{ symbol: 'AXON', held: false, market_value: null, change_pct: -18.18 }] }),
  ]))
  assert.equal(m.top[0].lead, 'Market')
  assert.equal(m.top[0].leadPct, null)
  assert.equal(m.top[0].basisText, 'Fri close', 'no percentage to compare -> the basis is just the close')
  assert.equal(m.top[1].isWatch, true)
  assert.equal(m.top[1].leadText, '-18.18%')
  assert.equal(m.top[1].leadArrow, '▼')
}

// --- the snapshot's glow rule travels with the feed, so the legend can explain itself
{
  const m = newsModel(wire([item({})], { feed_rule: { urgency: { red: 'a held name 3% or more down since the close' } } }))
  assert.equal(m.ruleText, 'a held name 3% or more down since the close')
  assert.equal(newsModel(wire([item({})])).ruleText, null, 'an older snapshot has no rule and the card shows no title')
}

// --- top six up front, the rest counted
{
  const feed = Array.from({ length: 9 }, (_, i) => item({ title: `s${i}`, rank: i + 1 }))
  const m = newsModel(wire(feed))
  assert.equal(m.total, 9)
  assert.equal(m.top.length, 6)
  assert.equal(m.hidden, 3)
}

// --- a snapshot from before the ranking: the order it was sent in, and NO badge (never an invented #1)
{
  const m = newsModel(wire([item({ title: 'a' }), item({ title: 'b' })]))
  assert.deepEqual(m.items.map(i => i.title), ['a', 'b'])
  assert.equal(m.items[0].badgeText, '')
}

// --- the move shown is the newest print's when there is one, and the close's when there is not
{
  const m = newsModel(wire([item({ title: 'x', holdings: [{ symbol: 'SPCX', held: true, market_value: 1, change_pct: 8.62, move_now_pct: -1.4 }] })]))
  assert.equal(m.top[0].symbolsText, 'SPCX ▼ -1.40%')
  assert.equal(m.top[0].leadPct, -1.4)
  assert.equal(m.top[0].leadArrow, '▼')
  const n = newsModel(wire([item({ title: 'y', holdings: [{ symbol: 'SPCX', held: true, market_value: 1, change_pct: 8.62, move_now_pct: null }] })]))
  assert.equal(n.top[0].symbolsText, 'SPCX ▲ +8.62%')
}

// --- a macro item has no symbol and still draws its meta line
{
  const m = newsModel(wire([item({ title: 'Futures slip', kind: 'macro', holdings: [], source: 'CNBC' })]))
  assert.equal(m.top[0].symbolsText, '')
  assert.equal(m.top[0].sourcesText, 'CNBC')
  assert.equal(m.top[0].soWhat, 'You hold $1,000 here.')
}

// --- no feed at all: an empty model, not a throw
{
  const m = newsModel(null)
  assert.equal(m.total, 0)
  assert.deepEqual(m.top, [])
}

console.log('sinceCloseNews LIVEFIX-LQ1283')
