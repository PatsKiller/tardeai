/**
 * Capture operator decision cards for acceptance review.
 *
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:7777 npx playwright test e2e/operator-cards-screenshots.spec.ts --reporter=line
 *
 * Output: e2e/screenshots/operator-cards/{SYM}-collapsed.png, {SYM}-details.png
 * Advisory only — no orders, no 2FA.
 */
import { test, expect, type Page, type Locator } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const SYMBOLS = ['CECO', 'FATN', 'DXCM', 'MRLN', 'NUAI', 'SMCI', 'BETA', 'SWBI'] as const
const OUT = path.join(__dirname, 'screenshots', 'operator-cards')

async function findCardRoot(page: Page, sym: string): Promise<Locator> {
  // Ticker is rendered large in the header; climb to a card-sized ancestor.
  const tick = page.locator('span, div').filter({ hasText: new RegExp(`^${sym}$`) }).first()
  await expect(tick).toBeVisible({ timeout: 25_000 })
  // Prefer ancestor that contains the operator state band
  const withState = tick.locator(
    'xpath=ancestor::div[.//text()[contains(.,"READY") or contains(.,"WAIT") or contains(.,"REFRESH") or contains(.,"BLOCKED") or contains(.,"NO TRADE") or contains(.,"MANAGE POSITION")]][1]',
  )
  if (await withState.count()) return withState
  return tick.locator('xpath=ancestor::div[4]')
}

test.describe('operator decision cards — screenshots', () => {
  test.setTimeout(240_000)

  test('collapsed + details for eight symbols', async ({ page }) => {
    fs.mkdirSync(OUT, { recursive: true })
    page.setDefaultTimeout(30_000)

    await page.goto('/v3/watch', { waitUntil: 'networkidle', timeout: 90_000 }).catch(async () => {
      await page.goto('/v3/watch', { waitUntil: 'domcontentloaded', timeout: 60_000 })
    })
    // Let watchlist API settle
    await page.waitForTimeout(5000)

    const search = page.getByPlaceholder(/symbol/i)
    await expect(search).toBeVisible({ timeout: 30_000 })

    for (const sym of SYMBOLS) {
      await search.fill('')
      await search.fill(sym)
      // Allow server-side symbol lookup
      await page.waitForTimeout(2500)

      // Clear "not found" soft-fail by waiting for ticker
      const missing = page.getByText(new RegExp(`${sym} is not on the watchlist|is not in the watchlist`, 'i'))
      if (await missing.isVisible().catch(() => false)) {
        // Still capture the empty state for the report
        await page.screenshot({ path: path.join(OUT, `${sym}-collapsed.png`), fullPage: false })
        await page.screenshot({ path: path.join(OUT, `${sym}-details.png`), fullPage: false })
        continue
      }

      const root = await findCardRoot(page, sym)
      await root.scrollIntoViewIfNeeded()
      await page.waitForTimeout(300)

      await root.screenshot({ path: path.join(OUT, `${sym}-collapsed.png`) })

      const details = root.getByRole('button', { name: /^Details$/i })
      if (await details.count()) {
        await details.click()
        await page.waitForTimeout(600)
        await root.screenshot({ path: path.join(OUT, `${sym}-details.png`) })
        const hide = root.getByRole('button', { name: /Hide details/i })
        if (await hide.count()) await hide.click()
      } else {
        fs.copyFileSync(path.join(OUT, `${sym}-collapsed.png`), path.join(OUT, `${sym}-details.png`))
      }
    }

    // Clear search and take a short overview
    await search.fill('')
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(OUT, `_watch-overview.png`), fullPage: true })

    const files = fs.readdirSync(OUT).filter(f => f.endsWith('.png'))
    console.log('screenshots:', files.join(', '))
    expect(files.filter(f => f.endsWith('-collapsed.png')).length).toBe(SYMBOLS.length)
  })
})
