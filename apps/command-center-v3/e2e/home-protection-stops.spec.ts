/** Protection correctness retained inside the operator-restored Do-now layout. Synthetic fixture only. */
import { test, expect } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

for (const width of [1440, 412, 390]) {
  test(`Home stop provenance and categories ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 915 })
    const writes = await homeFixtures(page, { stale: true })
    await page.goto('/v3/')
    await expect(page.getByTestId('home-stops-as-of')).toContainText('Mar 10')
    await expect(page.getByRole('status').filter({ hasText: 'Synthetic broker read is old' })).toBeVisible()
    await expect(page.getByTestId('home-filled-awaiting-sync')).toContainText('DEMOC: stop filled · awaiting holdings sync')
    await page.getByTestId('do-now-show-all').click()
    await expect(page.getByTestId('do-now-item').filter({ hasText: 'DEMOB' })).toContainText('pending activation')
    await expect(page.getByTestId('do-now-item').filter({ hasText: 'DEMOC' })).toContainText('filled · awaiting holdings sync')
    await expect(page.getByTestId('do-now')).not.toContainText('DEMOD is below')
    const action = page.getByTestId('do-now-item').filter({ hasText: 'DEMOB' }).getByTestId('do-now-action')
    await expect(action).toHaveAttribute('href', /detail=position%3Aexample_growth%3ADEMOB/)
    expect(writes).toEqual([])
  })
}

// 2026-10-31 (V stopped and re-bought): Home shows the server's dated note, never a stale bare "awaiting sync".
for (const width of [1440, 390]) {
  test(`Home filled stop shows the dated server note ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 915 })
    const note = 'stop filled Tue Mar 4 10:21 ET · waiting for the holdings sync (holdings last updated Mon Mar 3 20:00 ET)'
    const writes = await homeFixtures(page, { filledReason: note })
    await page.goto('/v3/')
    const line = page.getByTestId('home-filled-awaiting-sync')
    await expect(line).toContainText(`DEMOC: ${note}`)
    await expect(line).not.toContainText('awaiting holdings sync')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
    expect(writes).toEqual([])
  })
}
