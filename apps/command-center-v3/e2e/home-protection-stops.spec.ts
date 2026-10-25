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
