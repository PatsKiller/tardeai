/** Phone header tap targets + no sideways scroll on DeskPage columns (page audit 2026-10-25): fixtures only.
 *
 * Audit rows: the compact metric strip buttons (PORT, TODAY, attention chips, ▾) were 40 px tall on phones because
 * the 44 px phone rule only covered .app-main; and once <main> stopped being an inner scroller (phone shell v2) a
 * DeskPage flex COLUMN forced to `flex-wrap: wrap` grew to its widest child's max-content and the page scrolled
 * sideways at 390 px.
 *
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/phone-header-taps.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

test.use({ hasTouch: true })

const NOW = '2026-10-25T18:00:00Z'

async function fixtures(page: Page) {
  const writes: string[] = []
  await page.route('**/api/**', route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${url.pathname}`); return route.abort() }
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/api/v2/desk-sources') return json({ ok: true, data: { observed_at: NOW, writers: [], scope: 'fixture' } })
    if (url.pathname === '/api/v2/governance/approvals') return json({ ok: true, data: { items: [], pending_count: 0, known_pending_count: 0, complete: true, gaps: [], as_of: NOW, recent: [], filtered_count: 0, offset: 0 } })
    return json({ ok: false, error: 'fixture: not stubbed' }, 404)
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test(`phone ${width}: every header button is at least 44x44 and the header stays one short line`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page)
    await page.goto('/v3/approvals')
    const strip = page.getByTestId('ms-compact')
    await expect(strip).toBeVisible()
    const buttons = strip.locator('button')
    const count = await buttons.count()
    expect(count).toBeGreaterThanOrEqual(3)
    for (let i = 0; i < count; i++) {
      const b = buttons.nth(i)
      if (!(await b.isVisible())) continue
      const box = (await b.boundingBox())!
      expect(box.height, `header button ${i} height`).toBeGreaterThanOrEqual(44)
      // PORT/TODAY cells shrink with their value (min-width 0 keeps the line on screen); chips and ▾ are 44 wide.
      const cls = (await b.getAttribute('class')) ?? ''
      if (/ms-compact__(chip|toggle)/.test(cls)) expect(box.width, `header button ${i} width`).toBeGreaterThanOrEqual(44)
    }
    // Still one line, and the chrome above the page stays a small share of the screen (≤15% rule).
    const stripBox = (await strip.boundingBox())!
    expect(stripBox.height).toBeLessThanOrEqual(height * 0.15)

    // A real tap on ▾ opens the full strip, a second tap closes it.
    const toggle = strip.locator('.ms-compact__toggle')
    await toggle.tap()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await toggle.tap()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // Nothing pinned: scrolled to the end, no fixed/sticky chrome covers more than 15% of the screen.
    await page.evaluate(() => window.scrollTo(0, document.scrollingElement!.scrollHeight))
    const pinned = await page.evaluate(() => Array.from(document.querySelectorAll('body *')).filter(el => {
      const cs = getComputedStyle(el)
      if (cs.position !== 'fixed' && cs.position !== 'sticky') return false
      if (cs.visibility === 'hidden' || cs.display === 'none') return false
      // Only pinned chrome actually on screen (the closed nav sheet waits off-canvas at x < 0).
      const r = el.getBoundingClientRect()
      return r.bottom > 0 && r.top < innerHeight && r.left < innerWidth && r.right > 0 && r.width > innerWidth * 0.5
    }).reduce((sum, el) => sum + Math.min(el.getBoundingClientRect().bottom, innerHeight) - Math.max(el.getBoundingClientRect().top, 0), 0))
    expect(pinned).toBeLessThanOrEqual(height * 0.15)

    expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
    expect(writes).toEqual([])
  })

  test(`phone ${width}: a DeskPage column never grows wider than the screen`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await fixtures(page)
    await page.goto('/v3/approvals')
    const clocks = page.getByRole('region', { name: 'Source clocks' })
    await expect(clocks).toBeVisible()
    const r = await clocks.evaluate(el => ({ wrap: getComputedStyle(el.parentElement!).flexWrap, right: el.getBoundingClientRect().right, vw: innerWidth }))
    expect(r.wrap).toBe('nowrap')
    expect(r.right).toBeLessThanOrEqual(r.vw + 1)
  })
}

test('desktop 1440: the compact phone header is not rendered and nothing scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const writes = await fixtures(page)
  await page.goto('/v3/approvals')
  await expect(page.getByRole('region', { name: 'Source clocks' })).toBeVisible()
  await expect(page.getByTestId('ms-compact')).toBeHidden()
  expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})
