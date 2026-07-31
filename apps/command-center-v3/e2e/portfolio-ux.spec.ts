import { test, expect } from '@playwright/test'

/**
 * Portfolio hub UX smoke:
 * - Holdings is full-width (no allocation donut sidebar)
 * - Allocation is its own tab with sector + account breakdown
 * - Stop management is clearly labeled on holdings rows
 */
test.describe('Portfolio hub layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/v3/portfolio')
    // Hub title present even if APIs are slow / degraded
    await expect(page.getByText('Portfolio', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  })

  test('tabs include Holdings, Allocation, Stop Management', async ({ page }) => {
    for (const name of ['Holdings', 'Allocation', 'Stop Management']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeVisible()
    }
  })

  test('Holdings is full-width Bloomberg table with no inline allocation donut', async ({ page }) => {
    await page.getByRole('button', { name: 'Holdings', exact: true }).click()
    await expect(page.getByTestId('holdings-panel')).toBeVisible()
    await expect(page.getByTestId('holdings-table')).toBeVisible()
    await expect(page.getByTestId('holdings-table-legend')).toBeVisible()
    // Header columns present
    await expect(page.getByTestId('holdings-table-legend')).toContainText('Account')
    await expect(page.getByTestId('holdings-table-legend')).toContainText('P&L')
    await expect(page.getByTestId('holdings-table-legend')).toContainText('Stop')
    // Allocation panel should not be mounted on Holdings
    await expect(page.getByTestId('allocation-panel')).toHaveCount(0)
    // Chip navigates to Allocation tab
    await expect(page.getByTestId('holdings-open-allocation')).toBeVisible()
    await expect(page.getByTestId('holdings-open-stops')).toBeVisible()
  })

  test('Allocation tab shows sector mix and capital-by-account', async ({ page }) => {
    await page.getByRole('button', { name: 'Allocation', exact: true }).click()
    await expect(page.getByTestId('allocation-panel')).toBeVisible()
    await expect(page.getByText('Capital by account', { exact: true })).toBeVisible()
    await expect(page.getByText('Sector mix', { exact: true })).toBeVisible()
    await expect(page.getByTestId('allocation-go-holdings')).toBeVisible()
  })

  test('Stop Management tab is reachable from Holdings chip', async ({ page }) => {
    await page.getByRole('button', { name: 'Holdings', exact: true }).click()
    await page.getByTestId('holdings-open-stops').click()
    // Stop Management content — protocol header or table shell
    await expect(
      page.getByText(/Stop Management|stop monitoring|Yellow|Amber|Red|Audit/i).first(),
    ).toBeVisible({ timeout: 15_000 })
  })

  test('desk health strip is visible with build provenance', async ({ page }) => {
    await expect(page.getByTestId('portfolio-desk-health')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByTestId('desk-health-stops')).toBeVisible()
    await expect(page.getByTestId('desk-health-reload-ui')).toBeVisible()
  })

  test('deep-link ?symbol= focuses a holdings row when present', async ({ page }) => {
    // Land with a common symbol; if not in book, page still loads without crash
    await page.goto('/v3/portfolio?symbol=V&drawerTab=stops')
    await expect(page.getByText('Portfolio', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('portfolio-desk-health')).toBeVisible()
    // Drawer may open when V is held; soft-assert either drawer or holdings table
    const drawer = page.getByTestId('holdings-side-drawer')
    const table = page.getByTestId('holdings-table')
    await expect(table.or(drawer).first()).toBeVisible({ timeout: 15_000 })
  })

  test('row opens 75% ticker drawer with tabs', async ({ page }) => {
    await page.getByRole('button', { name: 'Holdings', exact: true }).click()
    await expect(page.getByTestId('holdings-table')).toBeVisible()
    // Click first data row (not header) — expand button
    const expand = page.locator('[id^="hold-"]').first()
    if (await expand.count()) {
      await expand.click()
      await expect(page.getByTestId('holdings-side-drawer')).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId('holding-drawer-tabs')).toBeVisible()
      await expect(page.getByTestId('holding-tab-overview')).toBeVisible()
      await expect(page.getByTestId('holding-tab-stops')).toBeVisible()
      await page.getByTestId('holding-tab-stops').click()
      await expect(page.getByTestId('holding-panel-stops')).toBeVisible()
      await page.getByTestId('holdings-drawer-close').click()
      await expect(page.getByTestId('holdings-side-drawer')).toHaveCount(0)
    }
  })
})
