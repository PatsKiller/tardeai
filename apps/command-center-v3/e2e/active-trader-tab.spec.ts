import { test, expect } from '@playwright/test'

/**
 * ActiveTrader tab (P2): honest data states (never fake-live), separated LANE/SETUP/DATA/SIZE/GATE chips,
 * scoped authority labels, disabled order controls, no preselected account, a11y modal, responsive.
 */

async function openActiveTrader(page: import('@playwright/test').Page) {
  await page.goto('/v3/trading')
  await expect(page.getByRole('button', { name: 'ActiveTrader', exact: true })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'ActiveTrader', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'ActiveTrader', exact: true })).toBeVisible({ timeout: 20_000 })
}

test.describe('ActiveTrader tab', () => {
  test('scoped authority + read-only, order controls disabled', async ({ page }) => {
    await openActiveTrader(page)
    await expect(page.getByText('ACTIVE TRADER ROUTES: OFF')).toBeVisible()
    await expect(page.getByText('ACTIVE TRADER SESSION: NOT AUTHORIZED')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Permission queue' })).toBeVisible()
    for (const label of [/Buy Bid/, /Buy MKT/, /Flatten/]) {
      await expect(page.getByRole('button', { name: label })).toBeDisabled()
    }
  })

  test('preview example shows REFERENCE SAMPLE · 0 ACTIONABLE and a preview route button', async ({ page }) => {
    await openActiveTrader(page)
    await page.getByRole('button', { name: 'Preview example' }).click()
    await expect(page.getByText('REFERENCE SAMPLE · 0 ACTIONABLE').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Preview allocation example' })).toBeVisible()
  })

  test('allocation modal: a11y, no preselected account, Confirm disabled', async ({ page }) => {
    await openActiveTrader(page)
    await page.getByRole('button', { name: 'Preview example' }).click()
    await page.getByRole('button', { name: 'Preview allocation example' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    await expect(dialog.getByText('No account is preselected.')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Confirm paper order' })).toBeDisabled()
    expect(await dialog.locator('input[type=checkbox]:checked').count()).toBe(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('separated chips: LANE, SETUP, DATA, SIZE TIER, GATE, SESSION are distinct', async ({ page }) => {
    await openActiveTrader(page)
    await page.getByRole('button', { name: 'Preview example' }).click()   // deterministic sample content
    for (const t of [/LANE:/, /SETUP:/, /DATA:/, /SIZE TIER:/, /GATE:/, /SESSION:/]) {
      await expect(page.getByText(t).first()).toBeVisible()
    }
    await expect(page.getByText('MULTI-SETUP').first()).toBeVisible()   // QTTB sample matches 2 setups
  })

  test('setups & strategy rules opens the registry modal', async ({ page }) => {
    await openActiveTrader(page)
    await page.getByRole('button', { name: /Setups & strategy rules/ }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('SETUPS & STRATEGY RULES')).toBeVisible()
  })

  test('narrow viewport: no horizontal page overflow', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openActiveTrader(page)
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
    expect(overflow).toBeFalsy()
  })
})
