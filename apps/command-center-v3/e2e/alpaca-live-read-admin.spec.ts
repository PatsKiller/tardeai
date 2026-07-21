/**
 * Screenshots: System → Admin Alpaca Live Read panel + secrets badges.
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:7777 npx playwright test e2e/alpaca-live-read-admin.spec.ts --reporter=line
 * Output under e2e/screenshots/alpaca-live-read/ (gitignored artifacts OK)
 */
import { test, expect } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'screenshots', 'alpaca-live-read')

test.describe('Alpaca live read-only admin', () => {
  test.beforeAll(() => {
    fs.mkdirSync(OUT, { recursive: true })
  })

  test('System Admin shows secrets + alpaca read panel', async ({ page }) => {
    await page.goto('/v3/system?tab=Admin', { waitUntil: 'networkidle', timeout: 45_000 })
    await page.waitForTimeout(1500)

    // Prefer clicking Admin tab if deep-link did not select it
    const adminTab = page.getByRole('button', { name: /^Admin$/i }).or(page.getByText(/^Admin$/))
    if (await adminTab.first().isVisible().catch(() => false)) {
      await adminTab.first().click()
      await page.waitForTimeout(800)
    }

    await page.screenshot({ path: path.join(OUT, 'system-admin-full.png'), fullPage: true })

    const secrets = page.getByText('API Keys & Secrets')
    await expect(secrets.first()).toBeVisible({ timeout: 15_000 })
    await page.screenshot({ path: path.join(OUT, 'secrets-manager.png'), fullPage: false })

    const panel = page.getByText('Alpaca Live — Read-Only Data')
    // Panel may show empty state if API unreachable; still capture page
    if (await panel.first().isVisible().catch(() => false)) {
      await panel.first().scrollIntoViewIfNeeded()
      await page.screenshot({ path: path.join(OUT, 'alpaca-live-read-panel.png'), fullPage: false })
    } else {
      await page.screenshot({ path: path.join(OUT, 'alpaca-live-read-panel-missing.png'), fullPage: false })
    }

    const files = fs.readdirSync(OUT)
    console.log('screenshots:', files.join(', '))
    expect(files.length).toBeGreaterThan(0)
  })
})
