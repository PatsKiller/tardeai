/** LQ-20261107-1282 + LQ-20261107-1283 (operator-approved mockup v3, 19:01 ET 2026-11-08) — the since-close card:
 *
 *  1. every held chip carries a green ▲ / red ▼ and a percentage for the close, AND a second value for what has
 *     printed since (overnight / pre-market / after-hours), or the grey "no print since Fri";
 *  2. a futures / overseas row replaces "futures feed pending", keeps a level-only root as a level, and says when each
 *     overseas exchange opens instead of inventing a number;
 *  3. the news grid is ONE column at 390 and 412 px and 2-3 on a desktop, six stories up front, the rest behind
 *     "Show all N";
 *  4. the ticker leads each news card with its arrow and %, the rank badge says why it is first, duplicate feeds are one
 *     story, and the red / amber / green glow is the producer's urgency level;
 *  5. nothing scrolls sideways at any of those widths.
 *
 *  Synthetic fixtures only (the repo is PUBLIC). The browser clock is pinned by `homeFixtures` to 2031-03-10. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

const PATH = '**/api/v2/home/since-close*'
const SHOTS = process.env.LQ1282_SHOTS ?? '/tmp/lq1282-shots'

const ext = (session: string, label: string, price: number, pct: number | null, printed: string, ref = '2031-03-07') => ({
  state: pct == null ? 'level_only' : 'print', session, session_label: label, price, change_pct: pct,
  printed_at: null, printed_text: printed, reference_close: pct == null ? null : price, reference_date: ref,
})

const holding = (symbol: string, pct: number, dollars: number, o: Record<string, unknown> = {}) => ({
  symbol, held: true, price: 10, change_pct: pct, week_pct: 1.2, dollar_impact: dollars, close_tag: 'Fri close',
  big_move: Math.abs(pct) >= 3, news: [], no_news: false, dollar_impact_now: dollars, move_now_pct: pct, ...o,
})

const item = (o: Record<string, unknown>) => ({
  title: 'A synthetic story', source: 'yahoo_rss', published_at: '2031-03-08T15:00:00Z', kind: 'holding', exposure: 1000,
  so_what: 'You hold $1,000 here.', holdings: [{ symbol: 'SPCX', held: true, market_value: 1000, change_pct: 8.62 }], ...o,
})

const wire = () => ({
  status: 'ok',
  window_now: { label: 'Since Fri 4:00 PM', close_tag: 'Fri close', session_date: '2031-03-07', session_open: false },
  generated_at: '2031-03-10T23:30:00Z',
  freshness: { age_seconds: 600, stale: false, window_current: true },
  summary: { source: 'deterministic', text: null, lines: ['Synthetic line.'] },
  moves: [
    holding('SPCX', 8.62, 8524, { extended: ext('overnight', 'overnight', 136.0, 1.2, 'Sun 10:00 PM ET'), move_now_pct: 1.2 }),
    holding('PFE', -1.64, -490),
    holding('RTX', -1.22, -1),
  ],
  macro: {
    headlines: [], futures: { status: 'available', quotes: [] },
    now: {
      status: 'available', as_of: '2031-03-10T22:45:00Z', as_of_text: 'Sun 6:45 PM ET',
      futures: [
        { symbol: '/ES', label: 'S&P 500 futures', level: 7398.75, change_pct: null, level_only: true, session: 'futures_open', session_label: 'futures open', printed_text: 'Sun 6:45 PM ET' },
        { symbol: '/YM', label: 'Dow futures', level: 51521, change_pct: 0.26, level_only: false, session: 'futures_open', session_label: 'futures open', printed_text: 'Sun 6:44 PM ET' },
      ],
      indices: [], missing: ['/NQ', '/RTY'],
      overseas: {
        status: 'no_feed', label: 'Overseas cash indices: no direct feed on this host — Asia/Europe moves appear as headlines below.',
        rows: [{ label: 'Nikkei 225', status: 'no_feed', opens_text: 'opens Sun 7:00 PM ET' },
          { label: 'Hang Seng', status: 'no_feed', opens_text: 'opens Sun 8:30 PM ET' }],
      },
    },
  },
  feed: [
    item({ title: 'SPCX soars on a tower deal', rank: 1, score: 60, why: '$8,524 moved · held SPCX +8.62%', urgency: 'green',
      urgency_why: 'held SPCX +8.62% since the close', sources: ['yahoo_rss', 'google_news:Reuters'],
      holdings: [{ symbol: 'SPCX', held: true, market_value: 1000, change_pct: 8.62, move_now_pct: 1.2 }] }),
    item({ title: 'PFE slides after a guidance cut', rank: 2, score: 30, why: '$490 at risk · held PFE -1.64%', urgency: 'red',
      urgency_why: 'held PFE -4.40% since the close', holdings: [{ symbol: 'PFE', held: true, market_value: 1000, change_pct: -1.64 }] }),
    item({ title: 'An insider sale at RTX', rank: 3, score: 12, why: 'held RTX insider sale', urgency: 'amber', urgency_why: 'insider sale',
      holdings: [{ symbol: 'RTX', held: true, market_value: 100, change_pct: -1.22 }] }),
    item({ title: 'A quiet story about nothing much', rank: 4, score: 2, why: 'held', urgency: null,
      holdings: [{ symbol: 'RTX', held: true, market_value: 100, change_pct: -1.22 }] }),
    item({ title: 'AXON downgraded by a desk', rank: 5, score: 1, why: 'watchlist AXON -18.2%', urgency: 'red', urgency_why: 'downgrade / cut',
      kind: 'watch', holdings: [{ symbol: 'AXON', held: false, market_value: null, change_pct: -18.18 }] }),
    item({ title: 'A sixth story', rank: 6, score: 1, why: 'held', urgency: null }),
    item({ title: 'A seventh story, behind the toggle', rank: 7, score: 1, why: 'held', urgency: null }),
  ],
  feed_rule: {
    score: 'min(60, $ moved on held names since the close) + 30 CIO brief action ...',
    urgency: { red: 'a held name 3% or more down since the close', amber: 'an insider sale, or a held name 5% or more down on the week',
      green: 'a held name 3% or more up since the close', none: 'no glow: read when you have time.' },
  },
  week_ahead: { events: [], fed_speakers: 'none' },
})

async function open(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 700 ? 915 : 1000 })
  await homeFixtures(page)
  // Registered AFTER homeFixtures, so it wins for this path (Playwright matches the newest route first).
  await page.route(PATH, r => r.fulfill({ json: { ok: true, data: wire() } }))
  await page.goto('/v3/')
  await expect(page.getByTestId('since-close-card')).toBeVisible()
  // the card is visible before the snapshot lands (it says "not built yet"); wait for a chip, so every measurement
  // below is taken against the rendered wire rather than the empty card.
  await expect(page.getByTestId('sc-chip-SPCX')).toBeVisible()
}

/** How many items of `sel` share the first row of a grid — 1 on a phone, 2+ on a desktop. */
const columnsIn = (page: Page, testid: string, sel: string): Promise<number> => page.evaluate(([id, s]) => {
  const root = document.querySelector(`[data-testid="${id}"]`)
  const cards = Array.from(root?.querySelectorAll(s) ?? []) as HTMLElement[]
  if (cards.length === 0) return 0
  const top = Math.round(cards[0].getBoundingClientRect().top)
  const xs = new Set(cards.filter(c => Math.abs(c.getBoundingClientRect().top - top) < 2)
    .map(c => Math.round(c.getBoundingClientRect().left)))
  return xs.size
}, [testid, sel] as const)

const noSideScroll = (page: Page): Promise<boolean> =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

test('412: one column of news, every chip carries its close move and its "now" value, no sideways scroll', async ({ page }) => {
  await open(page, 412)

  // 1. the chip: close arrow + %, and a SECOND value for the overnight print
  const spcx = page.getByTestId('sc-chip-SPCX')
  await expect(spcx).toContainText('▲')
  await expect(spcx).toContainText('+8.6%')
  const now = page.getByTestId('sc-chip-SPCX-now')
  await expect(now).toContainText('now (overnight)')
  await expect(now).toContainText('+1.2%')
  await expect(now).toContainText('vs Fri close')
  // a name with no print since the close says exactly that
  await expect(page.getByTestId('sc-chip-PFE-none')).toContainText('no print since Fri')
  // red for a loss, green for a gain
  await expect(page.getByTestId('sc-chip-PFE').locator('[data-tone="down"]')).toHaveCount(1)
  await expect(page.getByTestId('sc-chip-SPCX').locator('[data-tone="up"]')).toHaveCount(1)

  // 2. futures / overseas: a real level with an arrow, a level-only root with no invented %, and the exchange opens
  const futs = page.getByTestId('since-close-futures')
  await expect(futs).toHaveAttribute('data-status', 'available')
  await expect(page.getByTestId('sc-level-/YM')).toContainText('▲')
  await expect(page.getByTestId('sc-level-/ES')).toHaveAttribute('data-level-only', '1')
  await expect(page.getByTestId('sc-level-/ES')).toContainText('$7,398.75')
  await expect(page.getByTestId('sc-overseas-Nikkei 225')).toContainText('opens Sun 7:00 PM ET')
  await expect(futs).not.toContainText('futures feed pending')

  // 3. one column at 412, six stories up front, the seventh behind the toggle
  const feed = page.getByTestId('since-close-feed')
  await expect(feed).toHaveAttribute('data-shown', '6')
  await expect(feed).toHaveAttribute('data-total', '7')
  expect(await columnsIn(page, 'since-close-feed', 'article')).toBe(1)
  await page.getByTestId('since-close-feed-more').click()
  await expect(feed).toHaveAttribute('data-shown', '7')

  // 4. the ticker leads, the badge explains, the glow is the producer's, duplicates are one story
  const first = page.getByTestId('sc-news-1')
  await expect(first).toContainText('SPCX')
  // the number is the move SINCE the close (the overnight print), and the producer's reason carries the close move
  await expect(first).toContainText('▲ +1.20%')
  await expect(first).toContainText('vs Fri close')
  await expect(first).toContainText('$8,524 moved · held SPCX +8.62%')
  await expect(first).toHaveAttribute('data-glow', 'green')
  await expect(page.getByTestId('sc-news-rank').first()).toContainText('#1')
  await expect(first.getByTestId('sc-news-dup')).toContainText('+1 more on SPCX')
  await expect(page.getByTestId('sc-news-2')).toHaveAttribute('data-glow', 'red')
  await expect(page.getByTestId('sc-news-3')).toHaveAttribute('data-glow', 'amber')
  await expect(page.getByTestId('sc-news-4')).toHaveAttribute('data-glow', 'none')

  expect(await noSideScroll(page)).toBeTruthy()
  await page.screenshot({ path: `${SHOTS}/since-close-v3-412.png`, fullPage: true })
})

test('390: still one column, still no sideways scroll', async ({ page }) => {
  await open(page, 390)
  expect(await columnsIn(page, 'since-close-feed', 'article')).toBe(1)
  await expect(page.getByTestId('since-close-feed')).toHaveAttribute('data-shown', '6')
  expect(await noSideScroll(page)).toBeTruthy()
  await page.screenshot({ path: `${SHOTS}/since-close-v3-390.png`, fullPage: true })
})

test('1280: the news is a multi-column grid and the holdings stay a grid too', async ({ page }) => {
  await open(page, 1280)
  expect(await columnsIn(page, 'since-close-feed', 'article')).toBeGreaterThanOrEqual(2)
  expect(await columnsIn(page, 'since-close-moves', '[data-testid^="sc-chip-"]')).toBeGreaterThanOrEqual(2)
  expect(await noSideScroll(page)).toBeTruthy()
  await page.screenshot({ path: `${SHOTS}/since-close-v3-1280.png`, fullPage: true })
})
