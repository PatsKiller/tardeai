import { test, expect } from '@playwright/test'

/**
 * ActiveTrader tab: renders the permission queue + active trade card, is strictly read-only
 * (MANUAL_PAPER_TEST_ONLY — every order-shaped control disabled, no final submit), opens the
 * registry-driven strategy modal, and has no horizontal page overflow on a narrow viewport.
 */

async function openActiveTrader(page: import('@playwright/test').Page) {
  await page.goto('/v3/trading')
  await expect(page.getByRole('button', { name: 'ActiveTrader', exact: true })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'ActiveTrader', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'ActiveTrader', exact: true })).toBeVisible({ timeout: 20_000 })
}

test.describe('ActiveTrader tab', () => {
  test('renders read-only with no-live-routing posture and disabled order controls', async ({ page }) => {
    await openActiveTrader(page)
    await expect(page.getByText('NO LIVE ROUTING')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Permission queue' })).toBeVisible()
    // every order-shaped button in the trade card is disabled
    for (const label of ['Buy Bid', 'Sell Ask', 'Buy MKT', 'Flatten']) {
      await expect(page.getByRole('button', { name: label, exact: true })).toBeDisabled()
    }
  })

  test('prepare paper route opens allocation modal with NO enabled final submit', async ({ page }) => {
    await openActiveTrader(page)
    await page.getByRole('button', { name: 'Prepare paper route' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    await expect(dialog.getByRole('button', { name: 'Confirm paper order' })).toBeDisabled()
    // only paper account is selectable; disabled account checkboxes exist
    await expect(dialog.getByText(/Moomoo is represented as L2\/tape data-plane only/)).toBeVisible()
  })

  test('setups & strategy rules opens the registry-driven strategy modal', async ({ page }) => {
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
