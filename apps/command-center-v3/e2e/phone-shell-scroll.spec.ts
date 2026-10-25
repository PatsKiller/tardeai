/** Phone shell scrolls as one page (operator phone screenshots 2026-10-25): fixtures only, no production calls.
 *
 * Before: banners + metric strip + Ask the CIO bar sat outside the scrolling <main>, so on a phone that chrome never
 * left the screen and the first tab row scrolled under it. After: at <=820px the document scrolls, the chrome scrolls
 * away, and a page's tab row can be brought to the top of the screen and tapped. Desktop keeps the fixed shell.
 *
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/phone-shell-scroll.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

test.use({ hasTouch: true })

const NOW = '2026-10-25T18:00:00Z'
const items = Array.from({ length: 30 }, (_, i) => ({
  id: `design:DSN-fixture-${i}`, kind: i % 2 ? 'DESIGN' : 'ACTIVATE', title: `Fixture approval ${i}`, proposed_by: null,
  created_at: NOW, source: 'fixture', governed_href: null, decision_mode: 'RECORD', document_sha: 'b'.repeat(64), version: `v${i}`,
}))
const queue = { items, pending_count: items.length, known_pending_count: items.length, complete: true, gaps: [], as_of: NOW,
  recent: [], filtered_count: items.length, offset: 0 }

async function fixtures(page: Page) {
  const writes: string[] = []
  await page.route('**/api/**', route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${url.pathname}`); return route.abort() }
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/api/v2/governance/approvals') return json({ ok: true, data: queue })
    if (url.pathname === '/api/v2/desk-sources') return json({ ok: true, data: { observed_at: NOW, writers: [], scope: 'fixture' } })
    if (url.pathname === '/api/v2/cio/asks/tracked') return json({ ok: true, data: { tracked: [{ symbol: 'TSLA' }, { symbol: 'SPCX' }] } })
    return json({ ok: false, error: 'fixture: not stubbed' }, 404)
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test(`phone ${width}: chrome scrolls away and the first tab row is never clipped`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page)
    await page.goto('/v3/approvals')
    const tabs = page.getByRole('navigation', { name: 'Approvals Center views' })
    await expect(tabs).toBeVisible()
    await expect(page.getByText('Fixture approval 29')).toBeAttached()

    // The document is the scroller now; the shell is not pinned to the viewport height.
    const metrics = await page.evaluate(() => ({ doc: document.scrollingElement!.scrollHeight, vh: innerHeight,
      mainOverflow: getComputedStyle(document.querySelector('.app-main')!).overflowY }))
    expect(metrics.doc).toBeGreaterThan(metrics.vh)
    expect(metrics.mainOverflow).toBe('visible')

    // Bring the tab row to the top of the screen: nothing covers it, the Ask bar has scrolled off above.
    await tabs.evaluate(el => el.scrollIntoView({ block: 'start' }))
    const first = tabs.getByRole('button').first()
    const box = (await first.boundingBox())!
    expect(box.y).toBeGreaterThanOrEqual(0)
    const hit = await page.evaluate(([x, y]) => {
      const el = document.elementFromPoint(x, y)
      return el?.closest('nav')?.getAttribute('aria-label') ?? el?.tagName ?? null
    }, [box.x + box.width / 2, box.y + box.height / 2])
    expect(hit).toBe('Approvals Center views')
    const ask = (await page.getByTestId('ask-cio-bar').boundingBox())!
    expect(ask.y + ask.height).toBeLessThanOrEqual(box.y + 1)

    // A real tap on the second tab still switches the view.
    const second = tabs.getByRole('button').nth(1)
    await second.tap()
    await expect(second).toHaveAttribute('aria-pressed', 'true')

    // Scrolled to the end, the chrome is fully off-screen: the page has the whole viewport.
    await page.evaluate(() => window.scrollTo(0, document.scrollingElement!.scrollHeight))
    const askEnd = (await page.getByTestId('ask-cio-bar').boundingBox())!
    expect(askEnd.y + askEnd.height).toBeLessThanOrEqual(0)
    // The Ask bar is still there (nothing removed): back at the top it is fully visible.
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect(page.getByTestId('ask-cio-input')).toBeInViewport()

    const overflowX = await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
    expect(overflowX).toBeLessThanOrEqual(0)
    expect(writes).toEqual([])
  })
}

test('desktop 1440: fixed shell, main is the scroller', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const writes = await fixtures(page)
  await page.goto('/v3/approvals')
  await expect(page.getByText('Fixture approval 29')).toBeAttached()
  const m = await page.evaluate(() => ({ doc: document.scrollingElement!.scrollHeight, vh: innerHeight,
    mainOverflow: getComputedStyle(document.querySelector('.app-main')!).overflowY }))
  expect(m.mainOverflow).toBe('auto')
  expect(m.doc).toBeLessThanOrEqual(m.vh + 1)
  await expect(page.getByTestId('ask-cio-bar')).toBeInViewport()
  expect(writes).toEqual([])
})
