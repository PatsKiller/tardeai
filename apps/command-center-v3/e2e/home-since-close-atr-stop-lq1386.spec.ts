/** LQ-20261107-1386 — the since-close feed's "at its stop" label is a measurement, not a row count.
 *
 *  On 2026-11-08 ~23:00 ET the Home card said "SKYD at its stop", "V at its stop" and "PFE at its stop" on rows the
 *  CIO brief had answered HOLD — those names sat 1.8x, 1.6x and 3.6x their daily ATR above the stop. Only ANET
 *  (0.62x ATR) really was at its stop. The producer now labels a name only inside the house band (room to a working
 *  stop < 1 x ATR) and otherwise keeps its since-close move text.
 *
 *  This spec pins the text the producer emits for those five names (the strings below are the producer's own, see
 *  tests/test_since_close_card_atr_stop_band_lq1386_20261108.py) as it reaches the phone: exactly ONE "at its stop"
 *  on the card at 412 px, the other four names carrying their move text, and no sideways scroll at 412 or 390.
 *
 *  Synthetic fixtures only (the repo is PUBLIC). The browser clock is pinned by `homeFixtures` to 2031-03-10. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

const PATH = '**/api/v2/home/since-close*'
const SHOTS = process.env.LQ1386_SHOTS ?? '/tmp/lq1386-shots'

const position = (symbol: string, pct: number, dollars: number) => ({
  symbol, held: true, price: 10, change_pct: pct, week_pct: 1.0, dollar_impact: dollars, close_tag: 'Fri close',
  big_move: Math.abs(pct) >= 3, news: [], no_news: false, dollar_impact_now: dollars, move_now_pct: pct,
})

const story = (symbol: string, rank: number, why: string) => ({
  title: `${symbol} makes a real announcement`, source: 'wire', published_at: '2031-03-08T15:00:00Z', kind: 'holding',
  exposure: 1000, so_what: `You hold $1,000 here; ${symbol} is flat since Fri close.`, urgency: null, urgency_why: null,
  sources: ['wire'], rank, score: 60, why,
  holdings: [{ symbol, held: true, market_value: 1000, change_pct: 1.0 }],
})

const wire = () => ({
  status: 'ok',
  window_now: { label: 'Since Fri 4:00 PM', close_tag: 'Fri close', session_date: '2031-03-07', session_open: false },
  generated_at: '2031-03-10T23:30:00Z',
  freshness: { age_seconds: 600, stale: false, window_current: true },
  summary: { source: 'deterministic', text: null, lines: ['Synthetic line.'] },
  moves: [
    position('ANET', 0.13, 45), position('SKYD', 3.20, 259), position('V', -0.40, 173),
    position('PFE', -1.00, 295), position('MU', 2.00, 202),
  ],
  macro: {
    headlines: [], futures: { status: 'pending', quotes: [] },
    now: { status: 'pending', label: 'Futures feed pending', futures: [], indices: [], missing: [], overseas: { status: 'no_feed', rows: [], label: '' } },
  },
  feed: [
    story('ANET', 1, '$45 moved · ANET at its stop'),
    story('PFE', 2, '$295 moved · PFE -1.0% since the close'),
    story('SKYD', 3, '$259 moved · SKYD +3.2% since the close'),
    story('V', 4, '$173 moved · V -0.4% since the close'),
    story('MU', 5, '$202 moved · MU +2.0% since the close'),
  ],
  feed_rule: {
    score: 'min(60, $ moved on held names since the close) + 30 CIO brief action + 15 held name within 1 ATR of its stop ...',
    urgency: { red: 'a held name 3% or more down since the close', amber: 'an insider sale, or a held name 5% or more down on the week',
      green: 'a held name 3% or more up since the close', none: 'no glow: read when you have time.' },
  },
  week_ahead: { events: [], fed_speakers: 'none' },
})

async function open(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 700 ? 915 : 1000 })
  await homeFixtures(page)
  await page.route(PATH, r => r.fulfill({ json: { ok: true, data: wire() } }))
  await page.goto('/v3/')
  await expect(page.getByTestId('since-close-card')).toBeVisible()
  await expect(page.getByTestId('sc-chip-ANET')).toBeVisible()
  await expect(page.getByTestId('sc-news-1')).toBeVisible()
}

const noSideScroll = (page: Page): Promise<boolean> =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

const countAtStop = (page: Page): Promise<number> =>
  page.getByTestId('since-close-feed').evaluate(el => ((el.textContent ?? '').match(/at its stop/g) ?? []).length)

test('412: only the name inside the band is "at its stop"; the other four keep their move text', async ({ page }) => {
  await open(page, 412)
  const feed = page.getByTestId('since-close-feed')
  await expect(page.getByTestId('sc-news-1')).toContainText('$45 moved · ANET at its stop')
  await expect(feed).toContainText('PFE -1.0% since the close')
  await expect(feed).toContainText('SKYD +3.2% since the close')
  await expect(feed).toContainText('V -0.4% since the close')
  await expect(feed).toContainText('MU +2.0% since the close')
  expect(await countAtStop(page), 'one measured name, one label').toBe(1)
  await expect(page.getByTestId('sc-news-1')).not.toContainText('since the close')
  expect(await noSideScroll(page)).toBeTruthy()
  await page.screenshot({ path: `${SHOTS}/atr-stop-412.png`, fullPage: true })
})

test('390: the corrected text still fits, with no sideways scroll', async ({ page }) => {
  await open(page, 390)
  expect(await countAtStop(page)).toBe(1)
  expect(await noSideScroll(page)).toBeTruthy()
  await page.screenshot({ path: `${SHOTS}/atr-stop-390.png`, fullPage: true })
})
