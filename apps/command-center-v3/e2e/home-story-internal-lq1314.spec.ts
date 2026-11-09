/** LQ-20261107-1314 — a Home news/feed card opens the INTERNAL view, never the publisher.
 *
 *  Operator, 20:12 ET: "I clicked on the SpaceX, and instead of taking me to the news or the CIO latest internally
 *  on the command center for SpaceX, it took me to this external link". So on both Home surfaces:
 *    - the card / headline row is a button, and tapping it opens the internal story view;
 *    - the view carries the CIO's latest line for that symbol and the story's own summary;
 *    - the publisher is one deliberate "Read source ↗" INSIDE that view (target=_blank);
 *    - closing returns to the same card — nothing is removed.
 *
 *  Synthetic wire/fixtures only. Phone (412) is a full-screen sheet; desktop (1440) is a centred dialog.
 */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

const SPCX_URL = 'https://www.reuters.com/markets/spcx-guidance'
const HEAD_URL = 'https://www.cnbc.com/2031/03/10/spcx-contract.html'

const win = { label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2026-11-09', session_open: false }
const spcx = { symbol: 'SPCX', held: true, market_value: 8524, change_pct: 8.62, move_now_pct: 8.62 }
const wire = {
  status: 'ok', window_now: win, generated_at: '2031-03-10T14:50:00Z',
  freshness: { age_seconds: 300, stale: false, window_current: true },
  moves: [{ ...spcx, price: 120, week_pct: 4.1, dollar_impact: 680, close_tag: 'Mon close', big_move: true, news: [], no_news: false }],
  macro: { headlines: [], futures: { status: 'pending', label: 'futures feed pending', quotes: [] } },
  summary: { source: 'llm', text: 'Synthetic summary. SPCX raised guidance after the close.', lines: [] },
  cio_brief: {
    status: 'available', risk_tier: 'moderate',
    summary: 'Trim into strength; keep the launch catalyst.',
    actions: [{ symbol: 'SPCX', action: 'HOLD', reason: 'crowded but not broken' }],
  },
  week_ahead: { events: [], fed_speakers: 'no feed — not listed' },
  feed: [{
    title: 'SPCX raises full-year guidance', title_url: SPCX_URL, url: SPCX_URL,
    source: 'reuters', sources: ['reuters', 'yahoo_rss'], published_at: '2031-03-10T12:00:00Z',
    kind: 'holding', rank: 1, urgency: 'green', urgency_why: 'held SPCX +8.62% since the close',
    so_what: 'Guidance up 12%; the position is 9.4% of the book.',
    why: '$8,524 moved · held SPCX +8.62%',
    holdings: [spcx],
  }],
}

async function openHome(page: Page, w: number, h: number) {
  await page.setViewportSize({ width: w, height: h })
  await homeFixtures(page)
  await page.route('**/api/v2/home/since-close*', r => r.fulfill({ json: { ok: true, data: wire } }))
  await page.goto('/v3/')
  await expect(page.getByTestId('since-close-feed')).toBeVisible()
}

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

// ── "What to read first" (SinceCloseNews) ───────────────────────────────────────────────────────────
for (const [w, h] of [[412, 915], [1440, 1000]] as const) {
  test(`${w}: the SPCX card opens the internal story, and the publisher link lives inside it`, async ({ page }) => {
    await openHome(page, w, h)
    const card = page.getByTestId('sc-news-1')
    await expect(card).toBeVisible()
    // the card itself must not be an external link any more
    expect(await card.locator(`a[href="${SPCX_URL}"]`).count()).toBe(0)
    expect(await card.locator('a[href]').count()).toBe(0)

    await card.click()

    const story = page.getByTestId('home-story')
    await expect(story).toBeVisible()
    // it is a dialog and the page under it did not navigate to the publisher
    expect(page.url()).not.toContain('reuters.com')
    expect(new URL(page.url()).pathname).toBe('/v3/')
    // CIO latest for THIS symbol
    await expect(page.getByTestId('home-story-sym')).toHaveText('SPCX')
    await expect(page.getByTestId('home-story-cio')).toContainText('CIO latest · SPCX')
    await expect(page.getByTestId('home-story-cio-action')).toContainText('HOLD — crowded but not broken')
    // the story's own summary
    await expect(page.getByTestId('home-story-title')).toContainText('SPCX raises full-year guidance')
    await expect(page.getByTestId('home-story-summary')).toContainText('the position is 9.4% of the book')
    // the internal pages for the symbol
    await expect(page.getByTestId('home-story-open-intel')).toHaveAttribute('href', '/v3/watch/intelligence/SPCX')
    // the publisher is here, and only here
    await expect(page.getByTestId('home-story-source')).toHaveAttribute('href', SPCX_URL)
    await expect(page.getByTestId('home-story-source')).toHaveAttribute('target', '_blank')
    await expect(page.getByTestId('home-story-source')).toContainText('Read source')

    if (w === 412) {
      // full-screen sheet: it covers the viewport, with the shared detail header
      const sheet = page.locator('.mobile-detail-sheet')
      const box = (await sheet.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(w - 2)
      expect(box.height).toBeGreaterThanOrEqual(h - 2)
      await expect(page.getByTestId('detail-header')).toHaveCount(1)
      expect(await sheet.getAttribute('aria-modal')).toBe('true')
    }
    expect(await noSideScroll(page)).toBeTruthy()

    // closing returns to the same card — nothing was removed
    if (w === 412) await page.getByTestId('detail-close').click()
    else await page.getByTestId('home-story-close').click()
    await expect(story).toHaveCount(0)
    await expect(card).toBeVisible()
  })
}

test('412: Escape and the desktop scrim both close the view; the card stays', async ({ page }) => {
  await openHome(page, 412, 915)
  await page.getByTestId('sc-news-1').click()
  await expect(page.getByTestId('home-story')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('home-story')).toHaveCount(0)
  await expect(page.getByTestId('sc-news-1')).toBeVisible()
})

test('1440: Escape closes the desktop dialog', async ({ page }) => {
  await openHome(page, 1440, 1000)
  await page.getByTestId('sc-news-1').click()
  await expect(page.getByTestId('home-story-dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('home-story-dialog')).toHaveCount(0)
})

test('412: a CIO brief with no line for the symbol says so instead of borrowing one', async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 })
  await homeFixtures(page)
  await page.route('**/api/v2/home/since-close*', r => r.fulfill({ json: { ok: true, data: {
    ...wire, cio_brief: { status: 'available', risk_tier: 'moderate', summary: 'Book-wide note.', actions: [] },
  } } }))
  await page.goto('/v3/')
  await page.getByTestId('sc-news-1').click()
  await expect(page.getByTestId('home-story-cio-none')).toContainText('carries no line for SPCX')
})

// ── Major News grid (MajorNewsGrid) — same rule for a guarded headline row ──────────────────────────
test('412: a Major News headline opens the internal view, not the publisher', async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 })
  await homeFixtures(page)
  await page.route('**/api/v2/home/since-close*', r => r.fulfill({ json: { ok: true, data: wire } }))
  await page.route('**/api/v2/portfolio/book-map*', r => r.fulfill({ json: { ok: true, data: {
    rows: [{ symbol: 'SPCX', day_change_pct: 3.4, day_change: 120, account_id: 'example_growth' }] } } }))
  await page.route('**/api/v2/news/headline-counts*', r => r.fulfill({ json: { ok: true, data: { counts: { SPCX: 1 } } } }))
  await page.route('**/api/v2/news/symbol-headlines*', r => r.fulfill({ json: { ok: true, data: {
    symbol: 'SPCX', guard_rejected: 0,
    headlines: [{ title: 'SPCX wins a launch contract', source: 'CNBC', url: HEAD_URL, published_at: '2031-03-10T13:00:00Z' }],
    ingest: { guarded_72h: 1, latest: '2031-03-10T13:00:00Z' },
  } } }))
  await page.goto('/v3/')

  const cell = page.locator('button[title^="SPCX · day"]')
  await expect(cell).toBeVisible()
  await cell.click()

  const row = page.getByTestId('major-news-headline').first()
  await expect(row).toBeVisible()
  expect(await row.evaluate(el => el.tagName)).toBe('BUTTON')
  expect(await row.locator(`a[href="${HEAD_URL}"]`).count()).toBe(0)

  await row.click()
  await expect(page.getByTestId('home-story')).toBeVisible()
  expect(page.url()).not.toContain('cnbc.com')
  await expect(page.getByTestId('home-story-sym')).toHaveText('SPCX')
  await expect(page.getByTestId('home-story-title')).toContainText('SPCX wins a launch contract')
  // the CIO line came from the one on-open read of the since-close wire
  await expect(page.getByTestId('home-story-cio-action')).toContainText('HOLD — crowded but not broken')
  await expect(page.getByTestId('home-story-source')).toHaveAttribute('href', HEAD_URL)

  await page.getByTestId('major-news-story-back').click()
  await expect(page.getByTestId('major-news-headline').first()).toBeVisible()
})
