/** LQ-20261107-1253: the Home "Since last close" card — top of Home, 412 and 1440, no side scroll; one line while the
 *  session is open; pending states never blank. Synthetic wire only. LQ1253_PNG_DIR writes element screenshots. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

const PNG = process.env.LQ1253_PNG_DIR || ''
const win = (open: boolean) => ({ label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2026-11-09', session_open: open })
const mv = (symbol: string, held: boolean, pct: number, o: object = {}) => ({ symbol, held, price: 10, change_pct: pct, week_pct: 2.1, dollar_impact: held ? pct * 100 : null, close_tag: 'Mon close', big_move: Math.abs(pct) >= 3, news: [], no_news: false, ...o })
const wire = (open: boolean, extra: object = {}) => ({
  status: 'ok', window_now: win(open), generated_at: '2026-11-10T10:50:00Z',
  freshness: { age_seconds: 300, stale: false, window_current: true },
  moves: [mv('AAA', true, 8.6), mv('BBB', true, -4.4, { no_news: true }), mv('WWW', false, -18.2)],
  macro: { headlines: [], futures: { status: 'pending', label: 'futures feed pending', quotes: [] } },
  summary: { source: 'llm', text: 'Synthetic summary. AAA rose after a founder-sale headline. BBB fell with no news. The watchlist name WWW dropped sharply. Futures are pending. Look at BBB first.', lines: [] },
  cio_brief: { status: 'pending', label: 'CIO brief pending' },
  week_ahead: { events: [{ date: '2026-11-10', kind: 'macro', label: 'Consumer Price Index', time_et: '08:30', symbols: [] }, { date: '2026-11-12', kind: 'earnings', label: 'AAA earnings', time_et: null, symbols: ['AAA'] }], fed_speakers: 'no feed — not listed' },
  feed: [
    { title: 'Synthetic: AAA founder plans to sell 260k shares', source: 'yahoo_rss', published_at: '2026-11-10T01:00:00Z', kind: 'holding', exposure: 1086, so_what: 'You hold $1,086 here; AAA is +8.6% since Mon close.', holdings: [{ symbol: 'AAA', held: true, market_value: 1086, change_pct: 8.6 }] },
    { title: 'Synthetic: markets swoon amid AI fears', source: 'CNBC', published_at: '2026-11-09T23:00:00Z', kind: 'macro', exposure: 0, so_what: 'Market backdrop for the whole book ($9,000 held).', holdings: [] },
  ], ...extra,
})

async function open(page: Page, w: number, h: number, body: object) {
  await page.setViewportSize({ width: w, height: h })
  await homeFixtures(page)
  await page.route('**/api/v2/home/since-close*', r => r.fulfill({ json: { ok: true, data: body } }))
  await page.goto('/v3/')
}
const shot = async (page: Page, name: string) => { if (PNG) await page.getByTestId('since-close-card').screenshot({ path: `${PNG}/${name}.png` }) }
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

for (const [w, h] of [[1440, 1000], [412, 915]] as const) {
  test(`${w}: overnight card is full, first on the page, readable, no side scroll`, async ({ page }) => {
    await open(page, w, h, wire(false))
    const card = page.getByTestId('since-close-card')
    await expect(card).toHaveAttribute('data-state', 'full')
    await expect(card).toContainText('Since Mon 4:00 PM')
    await expect(page.getByTestId('since-close-cio')).toContainText('CIO brief pending')
    await expect(page.getByTestId('since-close-futures')).toContainText('futures feed pending')
    await expect(page.getByTestId('since-close-feed')).toContainText('You hold $1,086 here')
    await expect(page.getByTestId('since-close-week')).toContainText('Consumer Price Index')
    const c = (await card.boundingBox())!, n = (await page.getByTestId('needs-you-card').or(page.getByTestId('home-do-now-page').locator('section,div').nth(1)).first().boundingBox())
    if (n) expect(c.y).toBeLessThanOrEqual(n.y)
    expect(c.x + c.width).toBeLessThanOrEqual(w + 1)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `after-${w}`)
  })
}

test('412: session open collapses to one line that expands', async ({ page }) => {
  await open(page, 412, 915, wire(true))
  const card = page.getByTestId('since-close-card')
  await expect(card).toHaveAttribute('data-state', 'collapsed')
  expect((await card.boundingBox())!.height).toBeLessThan(70)
  await page.getByTestId('since-close-expand').click()
  await expect(page.getByTestId('since-close-feed')).toBeVisible()
})

test('412: no snapshot yet is a visible card, not blank', async ({ page }) => {
  await open(page, 412, 915, { status: 'no_snapshot', window: win(false) })
  await expect(page.getByTestId('since-close-none')).toBeVisible()
  await shot(page, 'after-none-412')
})
