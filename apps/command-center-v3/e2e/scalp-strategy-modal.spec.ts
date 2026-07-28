import { test, expect } from '@playwright/test'

/**
 * Scalp setup taxonomy UI: the SETUPS & STRATEGY RULES modal is registry-driven, keyboard-accessible,
 * responsive (desktop + narrow), and strictly read-only (no order/submit/approve/2FA/broker control).
 * The panel + button render on the Trading hub Scalp tab.
 */

async function openScalpTab(page: import('@playwright/test').Page) {
  await page.goto('/v3/trading')
  await expect(page.getByRole('button', { name: 'Scalp', exact: true })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Scalp', exact: true }).click()
  await expect(page.getByRole('button', { name: /SETUPS & STRATEGY RULES/ })).toBeVisible({ timeout: 20_000 })
}

test.describe('Scalp strategy modal', () => {
  test('button opens a read-only registry-driven dialog with the named setups', async ({ page }) => {
    await openScalpTab(page)
    await page.getByRole('button', { name: /SETUPS & STRATEGY RULES/ }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    // registry-derived setups present
    for (const label of ['L2 MOMENTUM', 'VWAP PULLBACK', 'VWAP REVERSION', '15M ORB', 'MICRO PULLBACK']) {
      await expect(dialog.getByText(label, { exact: true }).first()).toBeVisible()
    }
    // read-only: no action controls
    await expect(dialog.getByRole('button', { name: /buy|submit|approve|2fa|order|place/i })).toHaveCount(0)
    await expect(dialog.getByText(/MANUAL PAPER ONLY/).first()).toBeVisible()
  })

  test('Escape closes and focus returns to the opener', async ({ page }) => {
    await openScalpTab(page)
    const opener = page.getByRole('button', { name: /SETUPS & STRATEGY RULES/ })
    await opener.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(opener).toBeFocused()
  })

  test('filters and compare view work', async ({ page }) => {
    await openScalpTab(page)
    await page.getByRole('button', { name: /SETUPS & STRATEGY RULES/ }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'PREMARKET', exact: true }).click()
    await expect(dialog.getByText('PREMARKET MOMENTUM', { exact: true }).first()).toBeVisible()
    await dialog.getByRole('button', { name: /Compare setups/ }).click()
    await expect(dialog.getByText('Invalidation', { exact: true }).first()).toBeVisible()
  })

  test('narrow viewport: no horizontal page overflow', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openScalpTab(page)
    await page.getByRole('button', { name: /SETUPS & STRATEGY RULES/ }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
    expect(overflow).toBeFalsy()
  })
})
