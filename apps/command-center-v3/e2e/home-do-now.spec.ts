/** Restored pre-Board-14 Home. Synthetic symbols, amounts and names; fixture GETs only. */
import { test, expect } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'
declare const process: { env: Record<string, string | undefined> }

// locator.tap requires a touch-enabled browser context, including when only the viewport is resized.
test.use({ hasTouch: true })

for (const width of [1440, 412, 390]) {
  test(`restored Home layout and source correctness ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 2000 : 915 })
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
    const writes = await homeFixtures(page)
    await page.goto('/v3/')
    await expect(page.getByTestId('home-do-now-page')).toBeVisible()
    for (const id of ['home-portfolio', 'home-today', 'home-ytd', 'home-market', 'home-accounts', 'home-movers', 'home-numbers', 'home-opportunities', 'home-market-card', 'home-pulse']) await expect(page.getByTestId(id)).toBeVisible()
    await expect(page.getByTestId('home-portfolio')).toContainText('$20,000')
    await expect(page.getByTestId('home-ytd')).toContainText('+$300')
    await expect(page.getByTestId('num-unprotected')).toContainText('1')
    await expect(page.getByTestId('home-do-now-page')).not.toContainText('below its stop')
    await expect(page.getByTestId('home-do-now-page')).not.toContainText('99 positions')
    await expect(page.getByTestId('do-now-item')).toHaveCount(7)
    await expect(page.getByRole('link', { name: /Deploy hold/ })).toHaveAttribute('href', '/v3/system/releases')
    await expect(page.getByTestId('home-pulse').getByRole('link').last()).toHaveAttribute('href', '/v3/system/releases')
    await expect(page.getByTestId('home-do-now-page')).toContainText('Do-now as of Mar 10')
    await expect(page.getByTestId('home-do-now-page')).not.toContainText('2031-03-10T')
    for (const id of ['briefing', 'release', 'agents', 'news']) await expect(page.getByTestId(`home-drawer-${id}`).getByRole('button', { expanded: false }).first()).toBeVisible()
    await expect(page.getByTestId('home-major-news')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    expect(overflow).toBeLessThanOrEqual(1)
    // Desktop scrolls inside .app-main; fullPage alone cannot capture content clipped by that scroller.
    if (width === 1440) {
      await expect(page.getByTestId('home-drawer-news')).toBeInViewport()
      const clipped = await page.locator('.app-main').evaluate(el => el.scrollHeight - el.clientHeight)
      expect(clipped).toBeLessThanOrEqual(1)
    }
    if (process.env.HOME_REVERT_PROOF_DIR) await page.screenshot({ path: `${process.env.HOME_REVERT_PROOF_DIR}/impl-home-${width}.png`, fullPage: true })
    const q = page.getByTestId('do-now')
    await q.getByTestId('do-now-show-all').click()
    await expect(q.getByTestId('do-now-item')).toHaveCount(13)
    await expect(q).toContainText('2 approvals waiting')
    await expect(q.getByTestId('do-now-accounts').getByTestId('account-chip').first()).toHaveText('Example Income')
    expect(writes).toEqual([]); expect(errors).toEqual([])
  })
}

test('412: every queue row, filter, Show all and four drawers responds to taps', async ({ page }) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 412, height: 915 })
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  const writes = await homeFixtures(page)
  await page.goto('/v3/')
  const q = page.getByTestId('do-now')
  for (const [tab, expected] of [['protect', 3], ['decide', 3], ['fix', 7], ['all', 7]] as const) {
    await q.getByTestId(`do-now-tab-${tab}`).tap()
    await expect(q.getByTestId(`do-now-tab-${tab}`)).toHaveAttribute('aria-pressed', 'true')
    await expect(q.getByTestId('do-now-item')).toHaveCount(expected)
    if (tab !== 'all') for (const row of await q.getByTestId('do-now-item').all()) await expect(row).toHaveAttribute('data-category', tab)
    expect((await q.getByTestId(`do-now-tab-${tab}`).boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  await q.getByTestId('do-now-show-all').tap()
  const rows = q.getByTestId('do-now-item')
  await expect(rows).toHaveCount(13)
  const count = await rows.count()
  for (let i = 0; i < count; i++) {
    const row = rows.nth(i)
    await row.getByRole('button', { name: /^Details:/ }).tap()
    const sheet = page.getByRole('dialog'); await expect(sheet).toBeVisible()
    const bounds = await sheet.boundingBox(); expect(bounds!.width).toBeGreaterThanOrEqual(411); expect(bounds!.y).toBeLessThanOrEqual(1)
    expect(bounds!.height).toBeGreaterThanOrEqual(914)
    if (process.env.HOME_REVERT_PROOF_DIR) await page.screenshot({ path: `${process.env.HOME_REVERT_PROOF_DIR}/impl-home-row-${i + 1}-412.png` })
    const actionHref = await row.getByTestId('do-now-action').getAttribute('href')
    expect(actionHref).not.toBeNull()
    await expect(sheet.getByRole('link')).toHaveAttribute('href', actionHref!)
    await sheet.getByRole('button', { name: '← Back' }).tap()
    await expect(sheet).toHaveCount(0)
    expect((await row.getByTestId('do-now-action').boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  await q.getByTestId('do-now-show-all').tap(); await expect(rows).toHaveCount(7)
  for (const [id, title] of [['briefing', 'AI briefing'], ['release', 'Deploy on main'], ['agents', 'Agents and Hermes'], ['news', 'Market movers']]) {
    await page.getByTestId(`home-drawer-${id}`).getByRole('button', { expanded: false }).first().tap()
    const sheet = page.getByRole('dialog', { name: title }); await expect(sheet).toBeVisible()
    if (process.env.HOME_REVERT_PROOF_DIR) await page.screenshot({ path: `${process.env.HOME_REVERT_PROOF_DIR}/impl-home-drawer-${id}-412.png` })
    await sheet.getByRole('button', { name: '← Back' }).tap(); await expect(sheet).toHaveCount(0)
  }
  expect(writes).toEqual([]); expect(errors).toEqual([])
})

for (const [path, message] of [
  ['/api/v2/home/do-now', 'queue refresh failed'],
  ['/api/v2/cio/pages', 'Current positions refresh failed'],
  ['/api/v2/overview', 'Approval count refresh failed'],
] as const) {
  test(`retained 503 source is visibly stale: ${path}`, async ({ page }) => {
    const writes = await homeFixtures(page); await page.goto('/v3/')
    await expect(page.getByTestId('do-now-sources')).toHaveText('3/3 sources answered')
    await expect(page.getByTestId('do-now-item')).toHaveCount(7)
    await expect(page.getByTestId('num-unprotected')).toContainText('1')
    await page.route('**/api/**', route => route.request().method() === 'GET' && new URL(route.request().url()).pathname === path
      ? route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }) : route.fallback())
    await page.clock.fastForward(60_001)
    await expect(page.getByTestId('do-now-stale')).toContainText(message)
    await expect(page.getByTestId('do-now-clear')).toHaveCount(0)
    await expect(page.getByTestId('home-do-now-page')).not.toContainText('2031-03-10T')
    expect(writes).toEqual([])
  })
}

test('missing current sources is never an all-clear or a zero unprotected count', async ({ page }) => {
  await homeFixtures(page, { unavailable: true }); await page.goto('/v3/')
  await expect(page.getByTestId('do-now-clear')).toHaveCount(0)
  await expect(page.getByTestId('num-unprotected')).toContainText('—')
})

test('Classic view stays reachable', async ({ page }) => {
  await homeFixtures(page); await page.goto('/v3/')
  await page.getByTestId('classic-view-link').click(); await expect(page).toHaveURL(/view=classic/)
  await expect(page.getByTestId('needs-action-card')).toBeVisible()
})
