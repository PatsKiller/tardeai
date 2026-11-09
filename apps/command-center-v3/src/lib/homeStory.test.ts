// LQ-20261107-1314 — a Home news card must land on the internal view, and the internal view must not invent
// what the CIO brief or the story does not say.
//
// The operator tapped "SPCX ▲ +8.62%" in "What to read first" and left the Command Center entirely. The card
// now opens a story view; these checks pin the model that view is handed:
//
//   node apps/command-center-v3/src/lib/homeStory.test.ts
import { cioFor, relTime, sourceDomain, storyFromCard, storyFromHeadline } from './homeStory.ts'
import { cioFrom, type SinceCloseWire } from './sinceClose.ts'
import type { NewsCard } from './sinceCloseNews.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const brief = cioFrom({
  status: 'available',
  risk_tier: 'moderate',
  summary: 'Trim into strength; do not add to the AI complex.',
  actions: [
    { symbol: 'SPCX', action: 'HOLD', reason: 'crowded but not broken' },
    { symbol: 'AAA', action: 'TRIM', reason: 'position is 14% of the book' },
  ],
})

console.log('homeStory: the internal view of a Home news card')

// ── the CIO line is per symbol, and absent is said, not borrowed ────────────────────────────────────
check('the symbol line is found case-insensitively', cioFor(brief, 'spcx').action === 'HOLD — crowded but not broken')
check('a symbol with no line is not pending', cioFor(brief, 'ZZZ').pending === false)
check('a symbol with no line has no action', cioFor(brief, 'ZZZ').action === null)
check('the brief keeps its tier and summary', cioFor(brief, 'SPCX').tier === 'moderate' && cioFor(brief, 'SPCX').summary !== null)
check('a market-wide story borrows no symbol line', cioFor(brief, null).action === null)
check('a market-wide story still shows the brief', cioFor(brief, null).pending === false)
check('an unbuilt brief is pending with its own label', cioFor(cioFrom({ status: 'pending', label: 'CIO brief pending' }), 'SPCX').pending === true)
check('a missing brief is pending, not empty', cioFor(null, 'SPCX').pending === true)

// ── the ranked card carries everything the view draws ──────────────────────────────────────────────
const card: NewsCard = {
  key: 'SPCX raises guidance|0', rank: 1, badgeText: '#1', whyText: '$8,524 moved · held SPCX +8.6%',
  glow: 'green', glowText: 'big gain on a holding', lead: 'SPCX', leadPct: 8.62, leadText: '+8.62%', leadArrow: '▲',
  basisText: 'vs Fri close', kind: 'holding', isWatch: false,
  title: 'SPCX raises full-year guidance', url: 'https://www.reuters.com/markets/spcx-guidance',
  sourcesText: 'yahoo_rss · reuters', timeText: 'Mon 7:12 AM ET', symbolsText: 'SPCX ▲ +8.62%',
  dupText: '+1 more on SPCX', soWhat: 'Guidance up 12%; the position is 9.4% of the book.',
}
const wire = { cio_brief: {
  status: 'available', risk_tier: 'moderate', summary: 'Trim into strength.', actions: [{ symbol: 'SPCX', action: 'HOLD', reason: 'not broken' }],
} } as unknown as SinceCloseWire
const story = storyFromCard(card, wire)
check('the story leads with the card’s own symbol', story.sym === 'SPCX' && story.macro === false)
check('the move is the card’s move', story.moveText === '▲ +8.62%' && story.movePct === 8.62)
check('the story keeps the publisher URL for Read source', story.url === card.url)
check('the publisher domain is shown as a badge', story.sourceDomain === 'reuters.com')
check('the summary is the producer’s so_what', story.summary === card.soWhat)
check('the CIO line reaches the view', story.cio.action === 'HOLD — not broken')
check('a card with no URL still opens (nothing is invented)', storyFromCard({ ...card, url: null }, null).url === null)
check('a macro card has no symbol', storyFromCard({ ...card, kind: 'macro', lead: 'Market', leadPct: null }, null).sym === null)

// ── one guarded headline from the Major News grid ──────────────────────────────────────────────────
const head = storyFromHeadline('SPCX', { title: 'SPCX wins a launch contract', source: 'CNBC',
  url: 'https://www.cnbc.com/2031/03/10/spcx-contract.html', published_at: '2031-03-10T12:00:00Z' },
{ cio: brief, movePct: 3.4, basisText: 'today' })
check('the headline’s symbol is the grid cell’s symbol', head.sym === 'SPCX')
check('the headline carries no invented body summary', head.summary === '')
check('the headline keeps its publisher URL', head.sourceDomain === 'cnbc.com')
check('the headline shows the day move', head.moveText === '+3.40%' && head.basisText === 'today')
check('the headline gets the CIO line for its symbol', head.cio.action === 'HOLD — crowded but not broken')

// ── small helpers ──────────────────────────────────────────────────────────────────────────────────
check('an unparseable URL has no domain', sourceDomain('not a url') === null)
check('www is stripped from the domain', sourceDomain('https://www.example.com/a') === 'example.com')
check('relative time is hours', relTime('2031-03-10T12:00:00Z', Date.parse('2031-03-10T15:00:00Z')) === '3h ago')
check('relative time under an hour is minutes', relTime('2031-03-10T14:30:00Z', Date.parse('2031-03-10T15:00:00Z')) === '30m ago')
check('no time is empty, not "0m ago"', relTime(null) === '')

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
