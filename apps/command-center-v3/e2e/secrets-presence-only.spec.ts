import { test, expect, type Page } from '@playwright/test'
test.use({ hasTouch: true })

// Secrets are presence-only (page audit 2026-10-25): System → Admin showed the last four characters of every
// secret. The page shows "set" / "not set" (+ age when the server gives the operator one) and never a value,
// even if an old server still sends a masked hint. Synthetic fixture inputs only; every /api request is
// intercepted, non-GET requests are aborted and live :7777 traffic fails the test.
const recent = new Date(Date.now() - 3 * 86_400_000).toISOString()
const SECRETS = {
  secrets: [
    { key: 'FIXTURE_API_KEY', present: true, is_config: false, last_set_at: recent },
    { key: 'FIXTURE_DB_PASSWORD', present: true, is_config: false, masked: '••••QRST' },  // legacy field: must be ignored
    { key: 'FIXTURE_MISSING_TOKEN', present: false, is_config: false },
  ],
  detail: 'operator', note: 'fixture',
}

async function fixtures(page: Page) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') return route.abort()
    if (url.pathname === '/api/v2/admin/secrets') return route.fulfill({ status: 200, json: { ok: true, data: SECRETS } })
    return route.fulfill({ status: 200, json: {} })
  })
}

const size = (width: number) => ({ width, height: width === 412 ? 915 : width === 390 ? 844 : 1000 })

for (const width of [1440, 412, 390]) {
  test(`system admin: secrets show presence only ${width}`, async ({ page }) => {
    await page.setViewportSize(size(width))
    await fixtures(page)
    await page.goto('/v3/system?tab=Admin')
    const set = page.getByTestId('secret-presence-FIXTURE_API_KEY')
    await expect(set).toBeVisible()
    await expect(set).toHaveText('set · 3d ago')
    await expect(page.getByTestId('secret-presence-FIXTURE_DB_PASSWORD')).toHaveText('set')
    await expect(page.getByTestId('secret-presence-FIXTURE_MISSING_TOKEN')).toHaveText('not set')
    const text = await page.locator('body').innerText()
    expect(text).not.toContain('QRST')
    expect(text).not.toContain('••••')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
  })
}
